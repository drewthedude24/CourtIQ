"""Measure a shooter's form on one shot, from body keypoints and ball positions.

The five numbers (docs/form-results.md shows why these and how steady each one is):
  knee_bend_deg   the deepest knee bend before the release. 180 is a straight leg.
  elbow_bend_deg  the tightest the shooting elbow gets before the push. Empty when the arm was hidden.
  arm_angle_deg   how steeply the arm points up as the ball leaves. 90 is straight up.
  jump            how far the feet rise, in standing shoulder-heights.
  flight_time_s   from the ball leaving the hand to it reaching the rim.

The clips are filmed from behind, where a bent knee points away from the camera and looks almost
straight in the picture. So the knee and arm are worked out from up-and-down distances, which look
the same from any side, and the elbow from the pose model's 3D points.

A frame is {"t": seconds, "points": {"left_knee": (x, y, confidence), ...},
            "world": {"left_knee": (x, y, z), ...},
            "balls": [(x, y, width), ...], "hoop": (centre x, y of the rim line) or None,
            "rim": the same point from the shot detector, or None}.
"hoop" is this frame's own hoop box, so it moves with the camera straight away, but now and then
the box is on the wrong object. "rim" is steadied over a second and stays on the real hoop.

Numbers are read at extremes (deepest bend, highest reach), not on one chosen frame, so being a
frame early or late barely changes them. Lengths are compared within the same shot, never in pixels.
"""
import math
from statistics import median

# How long before the ball reaches the rim to watch the shooter. Covers the dip and the release.
FORM_WINDOW_S = 2.5
# A joint counts as seen at this confidence or higher. Below it, the number that needs it stays empty.
SEEN = 0.5
# The ball is in a hand when its centre is within this many ball-widths of that wrist.
# A hand is about 0.8 ball-widths long, so a held ball sits about 0.9 from the wrist.
HAND_REACH = 1.3
# The shot detector only starts a shot within a second of seeing the ball high above the rim
# (FALL_TIME_S in rim_shot_detector.py), so its shot time is never more than a second late.
ARRIVAL_WINDOW_S = 1.0
# If the ball is lost for longer than this on the way back to the hand, the release is unknown.
RELEASE_GAP_S = 0.15
# A shot ball moves under 1 ball-width per frame at 30 fps, so under 30 widths a second.
# A "ball" further away than this allows is something else.
BALL_SPEED = 45
# How far back from the release to look for the deepest knee bend and the tightest elbow.
KNEE_WINDOW_S = 1.0
ELBOW_WINDOW_S = 0.6
# The elbow is only reported when the arm was seen in this share of those frames.
ELBOW_SEEN = 0.8
# The legs are straight as the ball leaves. Their length then is the ruler for the knee bend.
STRAIGHT_WINDOW_S = 0.15
# The feet are on the ground this close to the deepest bend.
GROUND_WINDOW_S = 0.1
# The arm keeps rising for a moment after the ball leaves.
REACH_WINDOW_S = 0.3
# A number needs at least this many frames in its window.
MIN_FRAMES = 3
# Shoulder-to-wrist is about 0.68 of hip-to-ankle on an average body (Winter's body-segment tables).
ARM_PER_LEG = 0.68

SIDES = ("left", "right")
NUMBERS = ("knee_bend_deg", "elbow_bend_deg", "arm_angle_deg", "jump", "flight_time_s")


def angle(a, b, c):
    """The angle at b in degrees between the lines b-a and b-c. 180 is a straight limb."""
    to_a = [p - q for p, q in zip(a, b)]
    to_c = [p - q for p, q in zip(c, b)]
    lengths = math.hypot(*to_a) * math.hypot(*to_c)
    if lengths == 0:
        return None
    cosine = sum(p * q for p, q in zip(to_a, to_c)) / lengths
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def joints(frame, names, world=False):
    """The position of each named joint, or None if any of them was not clearly seen.
    In the picture (x, y) by default, or the pose model's 3D points with world=True."""
    points = [frame["points"].get(name) for name in names]
    if any(point is None or point[2] < SEEN for point in points):
        return None
    if world:
        return [frame["world"][name] for name in names]
    return [point[:2] for point in points]


def both_sides(value):
    """Average value("left") and value("right"), skipping a side that could not be measured."""
    values = [v for v in map(value, SIDES) if v is not None]
    return sum(values) / len(values) if values else None


def height_of(frame, joint):
    """The y of a joint, averaged over the left and right ones that are seen."""
    def one_side(side):
        found = joints(frame, [f"{side}_{joint}"])
        return found and found[0][1]
    return both_sides(one_side)


def leg_length(frame):
    def one_side(side):
        found = joints(frame, [f"{side}_hip", f"{side}_ankle"])
        return found and math.dist(*found)
    return both_sides(one_side)


def elbow_angle(frame, arm):
    found = joints(frame, [f"{arm}_shoulder", f"{arm}_elbow", f"{arm}_wrist"], world=True)
    return found and angle(*found)


def arm_rise(frame, arm):
    """How far the wrist is above the shoulder, in pixels."""
    found = joints(frame, [f"{arm}_shoulder", f"{arm}_wrist"])
    return found and found[0][1] - found[1][1]


def body_length(frame):
    """Ankles to shoulders, in pixels."""
    ankle_y, shoulder_y = height_of(frame, "ankle"), height_of(frame, "shoulder")
    return ankle_y - shoulder_y if None not in (ankle_y, shoulder_y) else None


def feet_below_rim(frame):
    """Measured from the rim line, so the camera tilting up or down doesn't look like a jump."""
    ankle_y = height_of(frame, "ankle")
    return ankle_y - frame["hoop"][1] if None not in (ankle_y, frame["hoop"]) else None


def series(frames, value):
    """(time, value) for each frame where value(frame) could be measured.
    Each value is replaced by the median of itself and its two neighbours, so one bad frame can't
    become the deepest bend."""
    raw = [(frame["t"], value(frame)) for frame in frames]
    raw = [(t, v) for t, v in raw if v is not None]
    return [
        (t, median(v for _, v in raw[max(0, i - 1):i + 2]))
        for i, (t, _) in enumerate(raw)
    ]


def extreme(points, start_s, end_s, pick):
    """(time, value) of the smallest (pick=min) or largest (pick=max) value between two times."""
    inside = [(v, t) for t, v in points if start_s <= t <= end_s]
    if len(inside) < MIN_FRAMES:
        return None, None
    value, t = pick(inside)
    return t, value


def ball_and_hoop(detections):
    """One frame's YOLO detections as the "balls" and "hoop" parts of a frame."""
    balls = [d for d in detections if d["class_id"] == 0]
    hoops = [d for d in detections if d["class_id"] == 1]
    hoop = max(hoops, key=lambda d: d["confidence"]) if hoops else None
    return {
        "balls": [(*d["center"], d["bbox"][2] - d["bbox"][0]) for d in balls],
        # The top edge of the hoop box is the rim line.
        "hoop": (hoop["center"][0], hoop["bbox"][1]) if hoop else None,
    }


def nearest_hand(frame, ball):
    """(distance in ball-widths, "left" or "right") for the seen wrist closest to the ball."""
    x, y, width = ball
    reaches = []
    for side in SIDES:
        wrist = joints(frame, [f"{side}_wrist"])
        if wrist and width > 0:
            reaches.append((math.dist(wrist[0], (x, y)) / width, side))
    return min(reaches, default=(None, None))


def find_arrival(frames, shot_time_s):
    """(frame, ball) where the ball reached the rim: the sighting closest to the rim in the
    second before the detector's shot time. None when no ball was seen in that second.

    Usually that is the frame at the shot time. But the net can hide the ball on its way in, and
    then the shot time is when the ball dropped out under the net, which is too late to start from.
    """
    sightings = [
        (frame, ball)
        for frame in frames
        if shot_time_s - ARRIVAL_WINDOW_S <= frame["t"] <= shot_time_s and frame["rim"]
        for ball in frame["balls"]
    ]
    return min(sightings, key=lambda sighting: math.dist(sighting[1][:2], sighting[0]["rim"]), default=None)


def find_release(frames, later, ball):
    """When the ball left the hand, and which arm shot it.

    Follows the ball backward in time to the hand, starting from the frame and ball where it
    reached the rim. The release is the earliest frame of that flight where the ball is out of
    the hands. Following one ball matters: the detector sometimes marks a hand or a second ball
    as a ball.
    Returns (None, None) when the ball is lost on the way.
    """
    for frame in reversed([f for f in frames if f["t"] < later["t"]]):
        gap_s = later["t"] - frame["t"]
        if gap_s > RELEASE_GAP_S:
            return None, None
        reachable = [
            b for b in frame["balls"]
            if math.dist(b[:2], ball[:2]) <= BALL_SPEED * gap_s * ball[2]
        ]
        if not reachable:
            continue
        found = min(reachable, key=lambda b: math.dist(b[:2], ball[:2]))
        reach, hand = nearest_hand(frame, found)
        if reach is not None and reach <= HAND_REACH:
            # The hand that pushed the ball is the one still closest to it a frame later.
            return later["t"], nearest_hand(later, ball)[1] or hand
        later, ball = frame, found
    return None, None


def measure(frames, shot_time_s):
    """The form numbers for one shot. A number that could not be measured is None.
    Also gives the release time, the deepest-bend time and the shooting arm, and in "seen_at"
    the time of the frame each measured number was read on, for drawing it.
    shot_time_s is the shot detector's time for the ball reaching the rim."""
    numbers = dict.fromkeys(NUMBERS + ("release_s", "bend_s", "arm"))
    seen_at = numbers["seen_at"] = {}
    arrival = find_arrival(frames, shot_time_s)
    release_s, arm = find_release(frames, *arrival) if arrival else (None, None)
    if release_s is None:
        return numbers
    # A ball out of sight for that long before the shot time was hidden by the net, and the shot
    # time is late. The flight then ends where the ball was last seen.
    last_seen_s = arrival[0]["t"]
    rim_time_s = shot_time_s if shot_time_s - last_seen_s <= RELEASE_GAP_S else last_seen_s
    numbers.update(release_s=release_s, arm=arm, flight_time_s=rim_time_s - release_s)
    seen_at["flight_time_s"] = release_s
    near_release = (release_s - STRAIGHT_WINDOW_S, release_s + STRAIGHT_WINDOW_S)
    reach_to = release_s + REACH_WINDOW_S

    # Elbow: the tightest it gets before the push.
    wind_up = [f for f in frames if release_s - ELBOW_WINDOW_S <= f["t"] <= release_s]
    elbows = series(wind_up, lambda f: elbow_angle(f, arm))
    # With gaps, the tightest moment may be in a frame that is missing, and the number comes out
    # too wide. From behind the arm is hidden like this on about a third of shots.
    if len(elbows) >= ELBOW_SEEN * len(wind_up):
        elbow_s, numbers["elbow_bend_deg"] = extreme(elbows, release_s - ELBOW_WINDOW_S, release_s, min)
        if elbow_s is not None:
            seen_at["elbow_bend_deg"] = elbow_s

    # Knee: the deepest bend before the release, from how much the legs shorten.
    legs = series(frames, leg_length)
    _, straight = extreme(legs, *near_release, max)
    bend_s, shortest = extreme(legs, release_s - KNEE_WINDOW_S, release_s, min)
    if not straight or bend_s is None:
        return numbers
    # Thigh and shank are about the same length, so the hip, knee and ankle make a triangle
    # with two equal sides: hip-to-ankle = 2 x thigh x sin(half the knee angle).
    numbers["knee_bend_deg"] = 2 * math.degrees(math.asin(min(1.0, shortest / straight)))
    numbers["bend_s"] = seen_at["knee_bend_deg"] = bend_s

    # Arm: the steepest it points as the ball leaves. Same idea as the knee: the wrist's height
    # over the shoulder against the arm's real length, with the straight leg as the ruler for
    # how long this shooter's arm is.
    reach_s, highest_rise = extreme(series(frames, lambda f: arm_rise(f, arm)), release_s, reach_to, max)
    if highest_rise is not None:
        seen_at["arm_angle_deg"] = reach_s
        lift = highest_rise / (ARM_PER_LEG * straight)
        numbers["arm_angle_deg"] = math.degrees(math.asin(max(-1.0, min(1.0, lift))))

    # Jump: how far the feet rise from the deepest bend to the top. Taking the ground from the
    # bend, not from earlier, keeps a step toward the hoop from being counted as jump.
    _, body = extreme(series(frames, body_length), *near_release, max)
    feet = series(frames, feet_below_rim)
    _, on_ground = extreme(feet, bend_s - GROUND_WINDOW_S, bend_s + GROUND_WINDOW_S, max)
    peak_s, at_peak = extreme(feet, release_s - STRAIGHT_WINDOW_S, reach_to, min)
    if body and None not in (on_ground, at_peak):
        numbers["jump"] = (on_ground - at_peak) / body
        seen_at["jump"] = peak_s
    return numbers
