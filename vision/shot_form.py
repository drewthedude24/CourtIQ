"""Measure a shooter's form on one shot, from body keypoints and ball positions.

Stage A version: each number is measured several ways so eval/form.py can compare them.
  flat      the angle as drawn in the picture. Wrong when the limb points at or away from the camera.
  vertical  worked out from up-and-down distances only, which look the same from any side.
  3d        from a pose model's 3D points.

A frame is {"t": seconds, "points": {"left_knee": (x, y, confidence), ...},
            "world": {"left_knee": (x, y, z), ...}  (only from a 3D pose model),
            "balls": [(x, y, width), ...], "hoop": (centre x, y of the rim line) or None}.

Numbers are read at extremes (deepest bend, highest reach), not on one chosen frame, so being a
frame early or late barely changes them. Lengths are compared within the same shot, never in pixels.
"""
import math
from statistics import median

# A joint counts as seen at this confidence or higher. Below it, the number that needs it stays empty.
SEEN = 0.5
# The ball is in a hand when its centre is within this many ball-widths of that wrist.
# A hand is about 0.8 ball-widths long, so a held ball sits about 0.9 from the wrist.
HAND_REACH = 1.3
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
# The push starts when the legs are this much of the way from their deepest bend back to straight.
PUSH_START = 0.25
# The arm keeps rising for a moment after the ball leaves.
REACH_WINDOW_S = 0.3
# A number needs at least this many frames in its window.
MIN_FRAMES = 3
# Shoulder-to-wrist is about 0.68 of hip-to-ankle on an average body (Winter's body-segment tables).
ARM_PER_LEG = 0.68

SIDES = ("left", "right")
NUMBERS = (
    "knee_flat", "knee_vertical", "knee_3d",
    "elbow_flat", "elbow_3d",
    "arm_flat", "arm_vertical", "arm_3d",
    "release_height", "jump", "release_time_s", "flight_time_s",
)


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
    """The position of each named joint, or None if any of them was not clearly seen."""
    points = [frame["points"].get(name) for name in names]
    if any(point is None or point[2] < SEEN for point in points):
        return None
    if world:
        return [frame["world"][name] for name in names] if "world" in frame else None
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


def knee_angle(frame, world=False):
    def one_side(side):
        found = joints(frame, [f"{side}_hip", f"{side}_knee", f"{side}_ankle"], world)
        return found and angle(*found)
    return both_sides(one_side)


def elbow_angle(frame, arm, world=False):
    found = joints(frame, [f"{arm}_shoulder", f"{arm}_elbow", f"{arm}_wrist"], world)
    return found and angle(*found)


def arm_rise(frame, arm):
    """How far the wrist is above the shoulder, in pixels."""
    found = joints(frame, [f"{arm}_shoulder", f"{arm}_wrist"])
    return found and found[0][1] - found[1][1]


def arm_lift(frame, arm, world=False):
    """How steeply the shoulder-to-wrist line points up, in degrees. 0 is level, 90 straight up."""
    found = joints(frame, [f"{arm}_shoulder", f"{arm}_wrist"], world)
    if not found or found[0] == found[1]:
        return None
    shoulder, wrist = found
    # y grows downward in pictures and in the pose model's 3D points.
    return math.degrees(math.asin((shoulder[1] - wrist[1]) / math.dist(shoulder, wrist)))


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


def nearest_hand(frame, ball):
    """(distance in ball-widths, "left" or "right") for the seen wrist closest to the ball."""
    x, y, width = ball
    reaches = []
    for side in SIDES:
        wrist = joints(frame, [f"{side}_wrist"])
        if wrist and width > 0:
            reaches.append((math.dist(wrist[0], (x, y)) / width, side))
    return min(reaches, default=(None, None))


def find_release(frames, rim_time_s):
    """When the ball left the hand, and which arm shot it.

    Follows the ball backward in time, from the rim to the hand. The release is the earliest
    frame of that flight where the ball is out of the hands. Following one ball matters: the
    detector sometimes marks a hand or a second ball as a ball.
    Returns (None, None) when the ball is lost on the way.
    """
    later = ball = None  # the frame and ball the flight was last followed to
    for frame in reversed([f for f in frames if f["t"] <= rim_time_s]):
        if later is None:
            if not frame["balls"] or frame["hoop"] is None:
                continue
            found = min(frame["balls"], key=lambda b: math.dist(b[:2], frame["hoop"]))
        else:
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
        if later is not None and reach is not None and reach <= HAND_REACH:
            # The hand that pushed the ball is the one still closest to it a frame later.
            return later["t"], nearest_hand(later, ball)[1] or hand
        later, ball = frame, found
    return None, None


def measure(frames, rim_time_s):
    """All the form numbers for one shot. A number that could not be measured is None."""
    numbers = dict.fromkeys(NUMBERS + ("release_s", "bend_s", "arm"))
    release_s, arm = find_release(frames, rim_time_s)
    if release_s is None:
        return numbers
    numbers.update(release_s=release_s, arm=arm, flight_time_s=rim_time_s - release_s)
    knee_from, reach_to = release_s - KNEE_WINDOW_S, release_s + REACH_WINDOW_S

    # Knee: the deepest bend before the release.
    legs = series(frames, leg_length)
    _, straight = extreme(legs, release_s - STRAIGHT_WINDOW_S, release_s + STRAIGHT_WINDOW_S, max)
    bend_s, shortest = extreme(legs, knee_from, release_s, min)
    if straight and bend_s is not None:
        # Thigh and shank are about the same length, so the hip, knee and ankle make a triangle
        # with two equal sides: hip-to-ankle = 2 x thigh x sin(half the knee angle).
        numbers["knee_vertical"] = 2 * math.degrees(math.asin(min(1.0, shortest / straight)))
        # The bottom of a dip is flat, so its exact moment is fuzzy. The push is timed from when
        # the legs are clearly on their way up instead, which happens on a steep part of the curve.
        rising = shortest + PUSH_START * (straight - shortest)
        push_s = max(t for t, length in legs if bend_s <= t <= release_s and length <= rising)
        numbers.update(bend_s=bend_s, release_time_s=release_s - push_s)
    _, numbers["knee_flat"] = extreme(series(frames, knee_angle), knee_from, release_s, min)
    _, numbers["knee_3d"] = extreme(
        series(frames, lambda f: knee_angle(f, world=True)), knee_from, release_s, min)

    # Elbow: the tightest it gets before the push.
    def tightest_elbow(world):
        wind_up = [f for f in frames if release_s - ELBOW_WINDOW_S <= f["t"] <= release_s]
        angles = series(wind_up, lambda f: elbow_angle(f, arm, world))
        # With gaps, the tightest moment may be in a frame that is missing, and the number
        # comes out too wide. From behind the arm is hidden like this on about a third of shots.
        if len(angles) < ELBOW_SEEN * len(wind_up):
            return None
        return extreme(angles, release_s - ELBOW_WINDOW_S, release_s, min)[1]

    numbers["elbow_flat"], numbers["elbow_3d"] = tightest_elbow(False), tightest_elbow(True)

    # Arm: the steepest it points as the ball leaves.
    _, numbers["arm_flat"] = extreme(
        series(frames, lambda f: arm_lift(f, arm)), release_s, reach_to, max)
    _, numbers["arm_3d"] = extreme(
        series(frames, lambda f: arm_lift(f, arm, world=True)), release_s, reach_to, max)
    _, highest_rise = extreme(series(frames, lambda f: arm_rise(f, arm)), release_s, reach_to, max)
    if straight and highest_rise is not None:
        # Same idea as the knee: the wrist's height over the shoulder against the arm's real
        # length, with the straight leg as the ruler for how long this shooter's arm is.
        lift = highest_rise / (ARM_PER_LEG * straight)
        numbers["arm_vertical"] = math.degrees(math.asin(max(-1.0, min(1.0, lift))))

    # Heights, in units of this shooter's standing shoulder height (ankle to shoulder).
    def body_length(frame):
        ankle_y, shoulder_y = height_of(frame, "ankle"), height_of(frame, "shoulder")
        return ankle_y - shoulder_y if None not in (ankle_y, shoulder_y) else None

    def hand_over_feet(frame):
        ankle_y, wrist = height_of(frame, "ankle"), joints(frame, [f"{arm}_wrist"])
        return ankle_y - wrist[0][1] if ankle_y is not None and wrist else None

    def feet_below_rim(frame):
        # Measured from the rim line, so the camera tilting up or down doesn't look like a jump.
        ankle_y = height_of(frame, "ankle")
        return ankle_y - frame["hoop"][1] if None not in (ankle_y, frame["hoop"]) else None

    _, body = extreme(
        series(frames, body_length),
        release_s - STRAIGHT_WINDOW_S, release_s + STRAIGHT_WINDOW_S, max)
    if body:
        _, reach = extreme(series(frames, hand_over_feet), release_s, reach_to, max)
        if reach is not None:
            numbers["release_height"] = reach / body
        feet = series(frames, feet_below_rim)
        # The feet are on the ground at the deepest bend. Taking them from that moment, not from
        # earlier, keeps a step toward the hoop from being counted as jump.
        on_ground = at_peak = None
        if numbers["bend_s"] is not None:
            _, on_ground = extreme(feet, numbers["bend_s"] - 0.1, numbers["bend_s"] + 0.1, max)
            _, at_peak = extreme(feet, release_s - STRAIGHT_WINDOW_S, reach_to, min)
        if None not in (on_ground, at_peak):
            numbers["jump"] = (on_ground - at_peak) / body
    return numbers
