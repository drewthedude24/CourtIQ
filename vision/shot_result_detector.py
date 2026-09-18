from collections import deque
from statistics import median


class ShotResultDetector:
    """Classify a released shot by how its trajectory interacts with the rim."""

    def __init__(
        self,
        hoop_history_size=30,
        predicted_confirmation_frames=45,
        max_shot_frames=180,
        result_display_frames=120,
    ):
        self.hoop_boxes = deque(maxlen=hoop_history_size)
        self.predicted_confirmation_frames = predicted_confirmation_frames
        self.max_shot_frames = max_shot_frames
        self.result_display_frames = result_display_frames

        self.previous_shot_state = "IDLE"
        self.shot_id = 0
        self.active = False
        self.release_frame = None
        self.frames_since_release = 0
        self.approached_rim = False
        self.entered_top_corridor = False
        self.provisional_make_frame = None
        self.provisional_crossing_x = None
        self.previous_point = None
        self.last_observed_point = None

        self.last_result = None
        self.result_frame = None
        self.result_reason = None
        self.result_display_remaining = 0
        self.event_result = None

    def update(self, detections, tracked_ball, shot_state, frame_index):
        self.event_result = None
        self._update_hoop(detections)

        if not self.active and self.result_display_remaining > 0:
            self.result_display_remaining -= 1

        release_started = (
            shot_state == "RELEASED" and self.previous_shot_state != "RELEASED"
        )
        if release_started:
            self._start_shot(frame_index)

        if self.active:
            self.frames_since_release = frame_index - self.release_frame
            self._update_active_shot(tracked_ball, frame_index)

            if self.active and self.provisional_make_frame is not None:
                confirmation_age = frame_index - self.provisional_make_frame
                if confirmation_age >= self.predicted_confirmation_frames:
                    self._finish("MAKE", frame_index, "predicted crossing held")

            if self.active and self.frames_since_release >= self.max_shot_frames:
                self._finish("MISS", frame_index, "shot timed out without a rim crossing")

        self.previous_shot_state = shot_state
        return self._build_result()

    def get_focus_region(self, frame_shape):
        """Return a high-resolution crop around the rim and its approach area."""
        geometry = self._rim_geometry()
        if geometry is None:
            return None

        rim_x, rim_y = geometry["rim_center"]
        crop_width = max(440.0, geometry["hoop_width"] * 3.8)
        crop_height = max(360.0, geometry["hoop_height"] * 7.5)
        crop_center_y = rim_y - 0.8 * geometry["hoop_height"]
        frame_height, frame_width = frame_shape[:2]

        x1 = max(0, int(round(rim_x - crop_width / 2.0)))
        y1 = max(0, int(round(crop_center_y - crop_height / 2.0)))
        x2 = min(frame_width, int(round(rim_x + crop_width / 2.0)))
        y2 = min(frame_height, int(round(crop_center_y + crop_height / 2.0)))
        if x2 - x1 < 64 or y2 - y1 < 64:
            return None
        return x1, y1, x2, y2

    def _start_shot(self, frame_index):
        self.shot_id += 1
        self.active = True
        self.release_frame = frame_index
        self.frames_since_release = 0
        self.approached_rim = False
        self.entered_top_corridor = False
        self.provisional_make_frame = None
        self.provisional_crossing_x = None
        self.previous_point = None
        self.last_observed_point = None

        self.last_result = None
        self.result_frame = None
        self.result_reason = None
        self.result_display_remaining = 0

    def _update_active_shot(self, tracked_ball, frame_index):
        geometry = self._rim_geometry()
        point = tracked_ball.get("center")
        tracking_status = tracked_ball.get("tracking_status")

        if geometry is None or point is None or tracking_status == "LOST":
            return

        point = (float(point[0]), float(point[1]))
        observed = tracking_status == "DETECTED"
        rim_x, rim_y = geometry["rim_center"]
        hoop_width = geometry["hoop_width"]
        hoop_height = geometry["hoop_height"]
        scoring_left, scoring_right = geometry["scoring_window"]

        if observed and self._is_upward_rim_bounce(
            point,
            frame_index,
            geometry,
        ):
            self._finish("MISS", frame_index, "ball bounced upward from rim")
            self.previous_point = None
            self.last_observed_point = None
            return

        if (
            geometry["approach_left"] <= point[0] <= geometry["approach_right"]
            and rim_y - 3.0 * hoop_height
            <= point[1]
            <= rim_y + 2.5 * hoop_height
        ):
            self.approached_rim = True

        if (
            scoring_left <= point[0] <= scoring_right
            and rim_y - 2.0 * hoop_height <= point[1] <= rim_y
        ):
            self.entered_top_corridor = True

        crossing_x = self._downward_crossing_x(self.previous_point, point, rim_y)
        if crossing_x is not None and scoring_left <= crossing_x <= scoring_right:
            if self.provisional_make_frame is None:
                self.provisional_make_frame = frame_index
                self.provisional_crossing_x = crossing_x

        # A real detection below the rim is stronger evidence than prediction alone.
        if (
            observed
            and self.entered_top_corridor
            and scoring_left <= point[0] <= scoring_right
            and rim_y + 0.15 * hoop_height
            <= point[1]
            <= rim_y + 2.2 * hoop_height
        ):
            self._finish("MAKE", frame_index, "ball observed below rim corridor")
            self.previous_point = None
            return

        outer_left = rim_x - 0.48 * hoop_width
        outer_right = rim_x + 0.48 * hoop_width
        near_rim_height = point[1] >= rim_y - 0.65 * hoop_height
        if (
            observed
            and self.approached_rim
            and near_rim_height
            and not outer_left <= point[0] <= outer_right
        ):
            self._finish("MISS", frame_index, "ball deflected outside rim corridor")
            self.previous_point = None
            return

        if observed:
            self.last_observed_point = {
                "frame_index": frame_index,
                "point": point,
            }

        self.previous_point = {
            "frame_index": frame_index,
            "point": point,
            "observed": observed,
        }

    def _is_upward_rim_bounce(self, point, frame_index, geometry):
        """Reject a make when an observed ball rebounds sharply above the rim."""
        previous = self.last_observed_point
        if previous is None or not self.approached_rim:
            return False

        frame_gap = frame_index - previous["frame_index"]
        if frame_gap <= 0 or frame_gap > 30:
            return False

        previous_x, previous_y = previous["point"]
        rim_x, rim_y = geometry["rim_center"]
        hoop_width = geometry["hoop_width"]
        hoop_height = geometry["hoop_height"]
        near_rim_before_gap = (
            abs(previous_x - rim_x) <= 0.8 * hoop_width
            and rim_y - hoop_height <= previous_y <= rim_y + 1.5 * hoop_height
        )
        still_near_rim_horizontally = abs(point[0] - rim_x) <= hoop_width
        upward_distance = previous_y - point[1]
        minimum_rebound = max(12.0, 0.6 * hoop_height)
        return (
            near_rim_before_gap
            and still_near_rim_horizontally
            and upward_distance >= minimum_rebound
        )

    @staticmethod
    def _downward_crossing_x(previous_point, current_point, rim_y):
        if previous_point is None:
            return None

        previous_x, previous_y = previous_point["point"]
        current_x, current_y = current_point
        if previous_y > rim_y or current_y < rim_y or current_y <= previous_y:
            return None

        vertical_distance = current_y - previous_y
        if vertical_distance == 0:
            return None

        crossing_fraction = (rim_y - previous_y) / vertical_distance
        return previous_x + crossing_fraction * (current_x - previous_x)

    def _finish(self, result, frame_index, reason):
        self.active = False
        self.last_result = result
        self.result_frame = frame_index
        self.result_reason = reason
        self.result_display_remaining = self.result_display_frames
        self.event_result = result

    def _update_hoop(self, detections):
        candidates = [
            detection for detection in detections if detection.get("class_id") == 1
        ]
        if not candidates:
            return

        current_bbox = self._stable_hoop_bbox()
        if current_bbox is None:
            selected = max(candidates, key=lambda detection: detection["confidence"])
        else:
            reference_center = self._bbox_center(current_bbox)
            selected = min(
                candidates,
                key=lambda detection: self._distance(
                    self._bbox_center(detection["bbox"]), reference_center
                ),
            )

        self.hoop_boxes.append(tuple(float(value) for value in selected["bbox"]))

    def _stable_hoop_bbox(self):
        if not self.hoop_boxes:
            return None
        return tuple(median(values) for values in zip(*self.hoop_boxes))

    def _rim_geometry(self):
        bbox = self._stable_hoop_bbox()
        if bbox is None:
            return None

        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)

        # This model's hoop box covers the rim plus net. The rim occupies the
        # upper-left portion of that box in the current fixed-camera clips.
        rim_x = x1 + 0.35 * width
        rim_y = y1 + 0.43 * height
        scoring_left = x1 + 0.04 * width
        scoring_right = x1 + 0.90 * width

        return {
            "hoop_bbox": bbox,
            "hoop_width": width,
            "hoop_height": height,
            "rim_center": (rim_x, rim_y),
            "scoring_window": (scoring_left, scoring_right),
            "approach_left": x1 - 0.5 * width,
            "approach_right": x1 + 1.2 * width,
        }

    def _build_result(self):
        geometry = self._rim_geometry()
        if self.active:
            status = "TRACKING"
        elif self.result_display_remaining > 0 and self.last_result is not None:
            status = self.last_result
        else:
            status = "WAITING"

        result = {
            "status": status,
            "event": self.event_result is not None,
            "result": self.event_result,
            "shot_id": self.shot_id if self.shot_id else None,
            "active": self.active,
            "release_frame": self.release_frame,
            "frames_since_release": self.frames_since_release,
            "result_frame": self.result_frame,
            "reason": self.result_reason,
            "approached_rim": self.approached_rim,
            "provisional_make": self.provisional_make_frame is not None,
            "provisional_make_frame": self.provisional_make_frame,
            "provisional_crossing_x": self.provisional_crossing_x,
            "hoop_bbox": None,
            "rim_center": None,
            "scoring_window": None,
        }
        if geometry is not None:
            result["hoop_bbox"] = [round(value, 2) for value in geometry["hoop_bbox"]]
            result["rim_center"] = [
                round(value, 2) for value in geometry["rim_center"]
            ]
            result["scoring_window"] = [
                round(value, 2) for value in geometry["scoring_window"]
            ]
        return result

    @staticmethod
    def _bbox_center(bbox):
        x1, y1, x2, y2 = bbox
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    @staticmethod
    def _distance(point1, point2):
        x_distance = point2[0] - point1[0]
        y_distance = point2[1] - point1[1]
        return (x_distance**2 + y_distance**2) ** 0.5
