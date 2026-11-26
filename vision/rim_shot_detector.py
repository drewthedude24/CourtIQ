"""Find shots by watching the ball at the rim.

A shot is the ball coming down from above the rim to rim level, close to the hoop.
A make is the ball then being seen straight below the rim: in the net or dropping out of it.

Distances are measured in hoop boxes and times in seconds, so the same numbers work for any
video size, camera distance or frame rate. The hoop box is YOLO's box around the rim and
net: its top edge is the rim line.
"""
from collections import deque
from statistics import median

# A shot drops in from above: the ball must first be seen this many hoop-heights over the rim line,
HIGH_ABOVE_RIM = 1.0
# and no further than this many hoop-widths to the side, so a ball elsewhere in the picture is ignored.
HIGH_SIDE_LIMIT = 4.0
# A ball takes under a second to fall from the top of its arc to the rim.
FALL_TIME_S = 1.0
# The ball counts as reaching the rim within this many hoop-widths of the hoop's centre.
# Wider than the rim itself so airballs that just miss are still shots.
RIM_SIDE_LIMIT = 1.5
# After the ball reaches the rim, look for it below the rim for this long. A ball can roll
# around the rim for most of a second before it drops.
WATCH_S = 1.5
# The net often hides the ball, so it also counts while dropping out, up to this many
# hoop-heights under the hoop box.
UNDER_NET = 1.0
# One sighting below the rim can be a stray detection. Two is a make.
MAKE_SIGHTINGS = 2
# A whole ball is about half a hoop-width wide. A narrower box is only a slice of a ball, such as
# one leaving the edge of the picture, so it doesn't count as the ball below the rim.
MIN_BALL_WIDTH = 0.3
# A ball's box is about as tall as it is wide. One under half as tall is something else. At the edge
# of the zoomed-in crop the model called flat strips of the rim and of a roof a ball, and at rim
# height that started shots early.
MIN_BALL_HEIGHT = 0.5
# A ball rolling on the rim has its centre about one ball radius (0.25 hoop-heights) above the rim line.
# Higher than this after reaching the rim, it bounced. The camera can't tell if a bounced ball then
# drops through the net or behind it, and in the test clips those drops were all misses.
BOUNCE_ABOVE_RIM = 0.3
# A rim bounce can drop the ball onto the rim again, so wait before counting a new shot.
COOLDOWN_S = 2.0
# How long MAKE or MISS stays on the video.
RESULT_DISPLAY_S = 4.0
# The rim line is steadied with the median of this many hoop boxes: a second of video while a shot
# is arriving, and up to four seconds while the detector is skipping frames.
HOOP_HISTORY = 30
REASONS = {
    "MAKE": "ball seen below the rim",
    "MISS": "ball not seen below the rim",
    "BOUNCE": "ball bounced up off the rim",
}


class RimShotDetector:
    def __init__(self):
        self.hoop_boxes = deque(maxlen=HOOP_HISTORY)
        self.last_high_s = None   # when the ball was last seen high above the rim
        self.shot_time_s = None   # when the ball reached the rim on the latest shot
        self.watching = False     # True from reaching the rim until the result is decided
        self.sightings_below_rim = 0
        self.shot_id = 0
        self.result = None
        self.rim_crop_wanted = False

    def update(self, detections, timestamp_s):
        """Take one frame's YOLO detections. Returns the shot status for that frame."""
        self._update_hoop(detections)
        hoop = self._hoop_box()
        event = reason = None
        if hoop is not None:
            below_rim, bounced = self._read_balls(detections, hoop, timestamp_s)
            if self.watching:
                self.sightings_below_rim += below_rim
                if bounced:
                    event, reason = "MISS", REASONS["BOUNCE"]
                elif self.sightings_below_rim >= MAKE_SIGHTINGS:
                    event = "MAKE"
                elif timestamp_s - self.shot_time_s >= WATCH_S:
                    event = "MISS"
                if event:
                    self.watching = False
                    self.result = event

        ball_was_high = self.last_high_s is not None and timestamp_s - self.last_high_s <= FALL_TIME_S
        self.rim_crop_wanted = self.watching or ball_was_high

        if self.watching:
            status = "TRACKING"
        elif self.result and timestamp_s - self.shot_time_s <= RESULT_DISPLAY_S:
            status = self.result
        else:
            status = "WAITING"
        return {
            "status": status,
            "event": event is not None,
            "result": event,
            "shot_id": self.shot_id or None,
            "shot_time_s": self.shot_time_s,
            "reason": event and (reason or REASONS[event]),
            "hoop_bbox": hoop and [round(value, 2) for value in hoop],
            # The overlay draws the rim line from these two.
            "rim_center": hoop and [round((hoop[0] + hoop[2]) / 2, 2), round(hoop[1], 2)],
            "scoring_window": hoop and [round(hoop[0], 2), round(hoop[2], 2)],
        }

    def finish(self):
        """Call when the video ends. A shot still being watched is decided on what was seen."""
        if not self.watching:
            return None
        return self.update([], self.shot_time_s + WATCH_S)

    def _read_balls(self, detections, hoop, timestamp_s):
        """Note balls high above the rim and start a shot when one reaches the rim.
        Returns (a ball is straight below the rim, the ball bounced up off the rim)."""
        left, top, right, bottom = hoop
        width, height = right - left, bottom - top
        centre_x = (left + right) / 2
        below_rim = bounced = False
        for detection in detections:
            if detection["class_id"] != 0:
                continue
            ball_x, ball_y = detection["center"]
            ball_left, ball_top, ball_right, ball_bottom = detection["bbox"]
            if ball_bottom - ball_top < MIN_BALL_HEIGHT * (ball_right - ball_left):
                continue
            side = abs(ball_x - centre_x) / width

            # Checked before a shot can start, so the frame the ball arrives on never counts as a bounce.
            if self.watching and ball_y <= top - BOUNCE_ABOVE_RIM * height and side <= RIM_SIDE_LIMIT:
                bounced = True

            if ball_y <= top - HIGH_ABOVE_RIM * height and side <= HIGH_SIDE_LIMIT:
                self.last_high_s = timestamp_s
            elif (
                # Level with the hoop box: its bottom edge is past the rim line and it is not under the net.
                ball_bottom >= top and ball_y <= bottom
                and side <= RIM_SIDE_LIMIT
                and self._shot_can_start(timestamp_s)
            ):
                self.shot_id += 1
                self.shot_time_s = timestamp_s
                self.watching = True
                self.sightings_below_rim = 0
                self.result = None
                self.last_high_s = None

            # Straight below the rim: centre within the hoop box's width, the whole ball under the rim line.
            if (
                left <= ball_x <= right and ball_top >= top and ball_y <= bottom + UNDER_NET * height
                and ball_right - ball_left >= MIN_BALL_WIDTH * width
            ):
                below_rim = True
        return below_rim, bounced

    def _shot_can_start(self, timestamp_s):
        came_from_above = self.last_high_s is not None and timestamp_s - self.last_high_s <= FALL_TIME_S
        cooled_down = self.shot_time_s is None or timestamp_s - self.shot_time_s >= COOLDOWN_S
        return came_from_above and cooled_down and not self.watching

    def get_focus_region(self, frame_shape):
        """A box around the rim for YOLO to look at in more detail, only while a shot is arriving."""
        hoop = self._hoop_box()
        if hoop is None or not self.rim_crop_wanted:
            return None
        left, top, right, bottom = hoop
        width, height = right - left, bottom - top
        frame_height, frame_width = frame_shape[:2]
        # Room for the ball to arrive from above or the side, and to drop out under the net.
        return (
            max(0, int(left - 2 * width)),
            max(0, int(top - 3 * height)),
            min(frame_width, int(right + 2 * width)),
            min(frame_height, int(bottom + 2 * height)),
        )

    def _update_hoop(self, detections):
        hoops = [detection for detection in detections if detection["class_id"] == 1]
        if not hoops:
            return
        current = self._hoop_box()
        if current is None:
            chosen = max(hoops, key=lambda hoop: hoop["confidence"])
        else:
            # With two hoops in view, stay on the one already being followed.
            chosen = min(
                hoops,
                key=lambda hoop: abs(hoop["bbox"][0] - current[0]) + abs(hoop["bbox"][1] - current[1]),
            )
        self.hoop_boxes.append(chosen["bbox"])

    def _hoop_box(self):
        if not self.hoop_boxes:
            return None
        return tuple(median(values) for values in zip(*self.hoop_boxes))
