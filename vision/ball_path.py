"""Where the ball is on every frame, for the ring and the dotted trail on the annotated video.

The detector only looks at some frames (DETECT_EVERY in offline_runner.py). On the frames in
between, the ball is placed on a smooth curve through the detections before and after it.
That needs detections from after the frame, so the video is drawn LAG frames behind the detector.
"""
import math
from collections import deque

# How many frames the drawing runs behind the detector: two detector steps, so the curve
# through a frame knows the next two detections.
LAG = 8
# Two detections further apart than this many frames are not joined: the ball was out of sight.
MAX_GAP = 8
# A detection this sure can start a path, or move it to a ball somewhere else in the picture.
STRONG = 0.4
# A ball is lying still when a ball was within STILL pixels of the same spot on SAME_SPOT of
# the detector's last LOOKS looks (about a second). A dribbled ball passes a spot once or twice.
STILL, SAME_SPOT, LOOKS = 6, 3, 8
# The ball is looked for near where it was last seen: within this many ball-widths, plus
# this many more for every frame since. A fast pass covers about one ball-width a frame.
REACH, REACH_PER_FRAME = 1.5, 1.2
# The trail covers this many seconds. While a shot is in the air it is not shortened, so it
# runs from the release to the rim, up to the longer limit.
TRAIL_S, FLIGHT_TRAIL_S = 0.67, 2.5


class BallPath:
    def __init__(self, fps):
        self.fps = fps
        # The detections chosen as the ball: (frame, x, y, width, joined to the one before).
        self.seen = deque(maxlen=4 * LAG)
        self.drawn = deque(maxlen=round(FLIGHT_TRAIL_S * fps))  # (frame, x, y) already drawn
        self.trail_start = 0
        self.last_spots = deque(maxlen=LOOKS)  # where the detector saw balls on its last looks

    def add(self, frame_index, detections):
        """Take the detections of a frame the detector looked at and pick the ball."""
        balls = [d for d in detections if d["class_id"] == 0]
        # A ball in a spot where one keeps being seen is lying still: a spare ball on the floor,
        # or the ball in play being held. Only a ball that moved can start a path.
        resting = [
            d for d in balls
            if sum(any(math.dist(d["center"], spot) <= STILL for spot in look) for look in self.last_spots) >= SAME_SPOT
        ]
        self.last_spots.append([d["center"] for d in balls])
        moving = [d for d in balls if d["confidence"] >= STRONG and d not in resting]
        last = self.seen[-1] if self.seen else None
        chosen, joined = None, False
        if last and frame_index - last[0] <= MAX_GAP:
            def distance(d):
                return math.dist(d["center"], last[1:3])
            reach = last[3] * (REACH + REACH_PER_FRAME * (frame_index - last[0]))
            # A resting ball only counts if it is the followed ball itself, come to rest.
            # An unsure detection only counts close by: further off it is more often a hand or a shoe.
            near = [
                d for d in balls
                if distance(d) <= (STILL if d in resting else reach if d["confidence"] >= STRONG else reach / 3)
            ]
            if near:
                chosen, joined = min(near, key=distance), True
                # With two balls in the picture, the one in play is the one that moves.
                if chosen in resting and moving:
                    chosen, joined = None, False
        if chosen is None and moving:
            chosen = max(moving, key=lambda d: d["confidence"])
        if chosen:
            left, top, right, bottom = chosen["bbox"]
            width = math.sqrt((right - left) * (bottom - top))
            self.seen.append((frame_index, *chosen["center"], width, joined))

    def ball(self, frame_index):
        """(x, y, width) of the ball on a frame at least LAG frames back, or None."""
        seen = list(self.seen)
        for n, (a, b) in enumerate(zip(seen, seen[1:] + [None])):
            if a[0] == frame_index:
                return a[1:4]
            if b and a[0] < frame_index < b[0] and b[4]:
                before = seen[n - 1] if n > 0 and a[4] else a
                after = seen[n + 2] if n + 2 < len(seen) and seen[n + 2][4] else b
                step = b[0] - a[0]
                t = (frame_index - a[0]) / step
                x, y = (
                    curve(a[k], b[k], t,
                          step * (b[k] - before[k]) / (b[0] - before[0]),
                          step * (after[k] - a[k]) / (after[0] - a[0]))
                    for k in (1, 2)
                )
                return x, y, a[3] + (b[3] - a[3]) * t
        return None

    def trail(self, frame_index, ball, in_flight):
        """The ball's positions before this frame, oldest first. Call once a frame, in order."""
        if in_flight:
            self.trail_start = max(self.trail_start, frame_index - FLIGHT_TRAIL_S * self.fps)
        else:
            # After a shot the long trail shrinks back three frames at a time, not all at once.
            self.trail_start = min(self.trail_start + 3, frame_index - TRAIL_S * self.fps)
        trail = [point[1:] for point in self.drawn if point[0] >= self.trail_start]
        if ball:
            self.drawn.append((frame_index, *ball[:2]))
        return trail


def curve(start, end, t, start_slope, end_slope):
    """A point on the smooth curve (a cubic Hermite spline) from `start` to `end`. `t` runs from
    0 to 1, and the slopes say which way the curve is heading at each end."""
    return (
        (2 * t**3 - 3 * t**2 + 1) * start + (t**3 - 2 * t**2 + t) * start_slope
        + (3 * t**2 - 2 * t**3) * end + (t**3 - t**2) * end_slope
    )
