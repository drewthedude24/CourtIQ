from collections import deque
import math

import numpy as np


class PredictiveBallTracker:
    """Associate ball detections over time and bridge short detection gaps."""

    def __init__(
        self,
        history_size=90,
        low_confidence_threshold=0.12,
        high_confidence_threshold=0.40,
        max_prediction_frames=10,
        max_missing_frames=18,
        base_gate_distance=75.0,
        gate_growth_per_missing_frame=18.0,
        speed_gate_factor=1.0,
        max_speed=120.0,
        max_acceleration=12.0,
        process_noise=4.0,
        measurement_noise=8.0,
        mahalanobis_gate=4.5,
        uncertainty_gate_factor=1.5,
        reacquire_after_missing_frames=None,
        reacquire_confidence_threshold=0.55,
    ):
        self.history_pos = deque(maxlen=history_size)
        self.low_confidence_threshold = low_confidence_threshold
        self.high_confidence_threshold = high_confidence_threshold
        self.max_prediction_frames = max_prediction_frames
        self.max_missing_frames = max_missing_frames
        self.base_gate_distance = base_gate_distance
        self.gate_growth_per_missing_frame = gate_growth_per_missing_frame
        self.speed_gate_factor = speed_gate_factor
        self.max_speed = max_speed
        self.max_acceleration = max_acceleration
        self.measurement_noise = measurement_noise
        self.mahalanobis_gate = mahalanobis_gate
        self.uncertainty_gate_factor = uncertainty_gate_factor
        self.reacquire_after_missing_frames = reacquire_after_missing_frames
        self.reacquire_confidence_threshold = reacquire_confidence_threshold

        # State: x, y, velocity_x, velocity_y. Acceleration is represented as
        # process uncertainty, which is more stable through short occlusions.
        self.transition = np.array(
            [
                [1.0, 0.0, 1.0, 0.0],
                [0.0, 1.0, 0.0, 1.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self.measurement_matrix = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
            ],
            dtype=np.float64,
        )
        acceleration_x = np.array([0.5, 0.0, 1.0, 0.0])
        acceleration_y = np.array([0.0, 0.5, 0.0, 1.0])
        self.process_covariance = process_noise * (
            np.outer(acceleration_x, acceleration_x)
            + np.outer(acceleration_y, acceleration_y)
        )
        self.identity = np.eye(4, dtype=np.float64)

        self.position = None
        self.velocity = (0.0, 0.0)
        self.acceleration = (0.0, 0.0)
        self.state_vector = None
        self.state_covariance = None
        self.prediction_uncertainty = None
        self.last_area = None
        self.missing_frames = 0

    def update(self, detections):
        candidates = [
            detection
            for detection in detections
            if detection["class_id"] == 0
            and detection["confidence"] >= self.low_confidence_threshold
        ]

        if self.position is None:
            return self._start_or_report_lost(candidates)

        predicted_center, predicted_velocity = self._predict()
        gate_distance = self._calculate_gate_distance()
        selected, association_distance = self._choose_candidate(
            candidates,
            predicted_center,
            gate_distance,
        )

        if selected is None:
            reacquired = self._choose_reacquisition_candidate(candidates)
            if reacquired is not None:
                return self._restart_from_detection(
                    reacquired,
                    predicted_center,
                    len(candidates),
                    gate_distance,
                )
            return self._handle_missing_detection(
                predicted_center,
                predicted_velocity,
                len(candidates),
                gate_distance,
            )

        return self._correct_with_detection(
            selected,
            predicted_center,
            predicted_velocity,
            association_distance,
            len(candidates),
            gate_distance,
        )

    def reset(self):
        self.history_pos.clear()
        self.position = None
        self.velocity = (0.0, 0.0)
        self.acceleration = (0.0, 0.0)
        self.state_vector = None
        self.state_covariance = None
        self.prediction_uncertainty = None
        self.last_area = None
        self.missing_frames = 0

    def get_focus_region(self, frame_shape, base_size=360):
        """Return a next-frame crop without advancing the Kalman filter."""
        if self.state_vector is None:
            return None

        projected_state = self.transition @ self.state_vector
        projected_covariance = (
            self.transition @ self.state_covariance @ self.transition.T
            + self.process_covariance
        )
        center_x, center_y = projected_state[:2]
        uncertainty = self._position_uncertainty(projected_covariance)
        speed = math.hypot(projected_state[2], projected_state[3])
        expansion = min(
            320.0,
            uncertainty * 3.0 + speed * 1.5 + self.missing_frames * 24.0,
        )
        crop_size = int(round(base_size + expansion))

        frame_height, frame_width = frame_shape[:2]
        half_size = crop_size / 2.0
        x1 = max(0, int(round(center_x - half_size)))
        y1 = max(0, int(round(center_y - half_size)))
        x2 = min(frame_width, int(round(center_x + half_size)))
        y2 = min(frame_height, int(round(center_y + half_size)))
        if x2 - x1 < 64 or y2 - y1 < 64:
            return None
        return x1, y1, x2, y2

    def _start_or_report_lost(self, candidates):
        strong_candidates = [
            candidate
            for candidate in candidates
            if candidate["confidence"] >= self.high_confidence_threshold
        ]
        if not strong_candidates:
            self.missing_frames += 1
            return self._build_result(
                tracking_status="LOST",
                detected=False,
                center=None,
                predicted_center=None,
                measurement_center=None,
                selected_confidence=None,
                selected_source=None,
                candidate_count=len(candidates),
                association_distance=None,
                gate_distance=None,
            )

        selected = max(strong_candidates, key=lambda candidate: candidate["confidence"])
        measurement = self._as_float_point(selected["center"])
        self._initialize_filter(measurement)
        self.last_area = self._bbox_area(selected)
        self.missing_frames = 0
        self.history_pos.append(self._as_int_point(self.position))

        return self._build_result(
            tracking_status="DETECTED",
            detected=True,
            center=self.position,
            predicted_center=self.position,
            measurement_center=measurement,
            selected_confidence=selected["confidence"],
            selected_source=selected.get("source", "full"),
            candidate_count=len(candidates),
            association_distance=0.0,
            gate_distance=self.base_gate_distance,
        )

    def _predict(self):
        self.acceleration = (
            self.acceleration[0] * 0.8,
            self.acceleration[1] * 0.8,
        )
        self.state_vector = self.transition @ self.state_vector
        self.state_covariance = (
            self.transition @ self.state_covariance @ self.transition.T
            + self.process_covariance
        )
        self._limit_motion_state()
        self._sync_motion_from_filter()
        self.prediction_uncertainty = self._position_uncertainty(
            self.state_covariance
        )
        predicted_center = self.position
        return predicted_center, self.velocity

    def _calculate_gate_distance(self):
        speed = math.hypot(*self.velocity)
        return min(
            240.0,
            self.base_gate_distance
            + speed * self.speed_gate_factor
            + (self.prediction_uncertainty or 0.0) * self.uncertainty_gate_factor
            + self.missing_frames * self.gate_growth_per_missing_frame,
        )

    def _choose_candidate(self, candidates, predicted_center, gate_distance):
        best_candidate = None
        best_distance = None
        best_cost = math.inf

        for candidate in candidates:
            candidate_center = self._as_float_point(candidate["center"])
            distance = self._distance(predicted_center, candidate_center)
            confidence = candidate["confidence"]
            mahalanobis_distance = self._mahalanobis_distance(
                candidate_center,
                confidence,
            )

            if distance > gate_distance:
                continue

            # A release accelerates much faster than the constant-velocity
            # model expects. Trust a strong detection inside the physical gate
            # even when the statistical gate is temporarily overconfident.
            strong_spatial_match = (
                confidence >= self.high_confidence_threshold
                and distance <= gate_distance
            )
            if (
                mahalanobis_distance > self.mahalanobis_gate
                and not strong_spatial_match
            ):
                continue

            if (
                self.missing_frames > self.max_prediction_frames
                and confidence < self.high_confidence_threshold
            ):
                continue

            # Weak detections are useful only when they closely follow the track.
            if (
                confidence < self.high_confidence_threshold
                and distance > gate_distance * 0.45
            ):
                continue

            distance_cost = mahalanobis_distance / self.mahalanobis_gate
            confidence_cost = (1.0 - confidence) * 0.45
            size_cost = self._size_change_cost(candidate) * 0.12
            total_cost = distance_cost + confidence_cost + size_cost

            if total_cost < best_cost:
                best_candidate = candidate
                best_distance = distance
                best_cost = total_cost

        return best_candidate, best_distance

    def _choose_reacquisition_candidate(self, candidates):
        """Recover from a bad prediction using a strong full-frame detection."""
        if (
            self.reacquire_after_missing_frames is None
            or self.missing_frames < self.reacquire_after_missing_frames
        ):
            return None

        strong_full_frame_candidates = [
            candidate
            for candidate in candidates
            if candidate["confidence"] >= self.reacquire_confidence_threshold
            and candidate.get("source", "full") == "full"
        ]
        if not strong_full_frame_candidates:
            return None
        return max(
            strong_full_frame_candidates,
            key=lambda candidate: candidate["confidence"],
        )

    def _restart_from_detection(
        self,
        selected,
        predicted_center,
        candidate_count,
        gate_distance,
    ):
        measurement = self._as_float_point(selected["center"])
        association_distance = self._distance(predicted_center, measurement)
        self.history_pos.clear()
        self._initialize_filter(measurement)
        self.last_area = self._bbox_area(selected)
        self.missing_frames = 0
        self.history_pos.append(self._as_int_point(self.position))

        return self._build_result(
            tracking_status="DETECTED",
            detected=True,
            center=self.position,
            predicted_center=predicted_center,
            measurement_center=measurement,
            selected_confidence=selected["confidence"],
            selected_source=selected.get("source", "full"),
            candidate_count=candidate_count,
            association_distance=association_distance,
            gate_distance=gate_distance,
        )

    def _correct_with_detection(
        self,
        selected,
        predicted_center,
        predicted_velocity,
        association_distance,
        candidate_count,
        gate_distance,
    ):
        measurement = self._as_float_point(selected["center"])
        confidence = selected["confidence"]
        self._correct_filter(measurement, confidence)
        self.last_area = self._bbox_area(selected)
        self.missing_frames = 0
        self.history_pos.append(self._as_int_point(self.position))

        return self._build_result(
            tracking_status="DETECTED",
            detected=True,
            center=self.position,
            predicted_center=predicted_center,
            measurement_center=measurement,
            selected_confidence=confidence,
            selected_source=selected.get("source", "full"),
            candidate_count=candidate_count,
            association_distance=association_distance,
            gate_distance=gate_distance,
        )

    def _handle_missing_detection(
        self,
        predicted_center,
        predicted_velocity,
        candidate_count,
        gate_distance,
    ):
        self.missing_frames += 1

        if self.missing_frames <= self.max_prediction_frames:
            self.position = predicted_center
            self.history_pos.append(self._as_int_point(self.position))
            return self._build_result(
                tracking_status="PREDICTED",
                detected=False,
                center=self.position,
                predicted_center=predicted_center,
                measurement_center=None,
                selected_confidence=None,
                selected_source=None,
                candidate_count=candidate_count,
                association_distance=None,
                gate_distance=gate_distance,
            )

        if self.missing_frames == self.max_prediction_frames + 1:
            self.history_pos.clear()

        if self.missing_frames > self.max_missing_frames:
            self.reset()

        return self._build_result(
            tracking_status="LOST",
            detected=False,
            center=None,
            predicted_center=predicted_center,
            measurement_center=None,
            selected_confidence=None,
            selected_source=None,
            candidate_count=candidate_count,
            association_distance=None,
            gate_distance=gate_distance,
        )

    def _size_change_cost(self, candidate):
        candidate_area = self._bbox_area(candidate)
        if self.last_area is None or candidate_area <= 0:
            return 0.0
        return min(2.0, abs(math.log(candidate_area / self.last_area)))

    @staticmethod
    def _bbox_area(detection):
        x1, y1, x2, y2 = detection["bbox"]
        return max(1.0, float((x2 - x1) * (y2 - y1)))

    @staticmethod
    def _distance(point1, point2):
        return math.hypot(point2[0] - point1[0], point2[1] - point1[1])

    @staticmethod
    def _as_float_point(point):
        return float(point[0]), float(point[1])

    @staticmethod
    def _as_int_point(point):
        return int(round(point[0])), int(round(point[1]))

    @staticmethod
    def _limit_vector(vector, maximum_length):
        length = math.hypot(*vector)
        if length <= maximum_length or length == 0:
            return vector
        scale = maximum_length / length
        return vector[0] * scale, vector[1] * scale

    def _initialize_filter(self, measurement):
        self.state_vector = np.array(
            [measurement[0], measurement[1], 0.0, 0.0],
            dtype=np.float64,
        )
        self.state_covariance = np.diag(
            [25.0, 25.0, 144.0, 144.0]
        )
        self.prediction_uncertainty = self._position_uncertainty(
            self.state_covariance
        )
        self._sync_motion_from_filter()

    def _correct_filter(self, measurement, confidence):
        predicted_velocity = tuple(self.state_vector[2:4])
        measurement_vector = np.asarray(measurement, dtype=np.float64)
        measurement_covariance = self._measurement_covariance(confidence)
        innovation = measurement_vector - self.measurement_matrix @ self.state_vector
        innovation_covariance = (
            self.measurement_matrix
            @ self.state_covariance
            @ self.measurement_matrix.T
            + measurement_covariance
        )
        kalman_gain = (
            self.state_covariance
            @ self.measurement_matrix.T
            @ np.linalg.inv(innovation_covariance)
        )
        self.state_vector = self.state_vector + kalman_gain @ innovation

        covariance_factor = self.identity - kalman_gain @ self.measurement_matrix
        self.state_covariance = (
            covariance_factor @ self.state_covariance @ covariance_factor.T
            + kalman_gain @ measurement_covariance @ kalman_gain.T
        )
        self._limit_motion_state()
        self._sync_motion_from_filter()
        self.acceleration = self._limit_vector(
            (
                self.velocity[0] - predicted_velocity[0],
                self.velocity[1] - predicted_velocity[1],
            ),
            self.max_acceleration,
        )
        self.prediction_uncertainty = self._position_uncertainty(
            self.state_covariance
        )

    def _mahalanobis_distance(self, candidate_center, confidence):
        measurement_vector = np.asarray(candidate_center, dtype=np.float64)
        innovation = measurement_vector - self.measurement_matrix @ self.state_vector
        innovation_covariance = (
            self.measurement_matrix
            @ self.state_covariance
            @ self.measurement_matrix.T
            + self._measurement_covariance(confidence)
        )
        squared_distance = float(
            innovation.T @ np.linalg.inv(innovation_covariance) @ innovation
        )
        return math.sqrt(max(0.0, squared_distance))

    def _measurement_covariance(self, confidence):
        variance = self.measurement_noise + 40.0 * (1.0 - confidence) ** 2
        return np.eye(2, dtype=np.float64) * variance

    def _limit_motion_state(self):
        velocity = self._limit_vector(
            (self.state_vector[2], self.state_vector[3]),
            self.max_speed,
        )
        self.state_vector[2:4] = velocity

    def _sync_motion_from_filter(self):
        self.position = tuple(float(value) for value in self.state_vector[:2])
        self.velocity = tuple(float(value) for value in self.state_vector[2:4])

    @staticmethod
    def _position_uncertainty(covariance):
        return math.sqrt(max(0.0, float(covariance[0, 0] + covariance[1, 1])))

    def _build_result(
        self,
        tracking_status,
        detected,
        center,
        predicted_center,
        measurement_center,
        selected_confidence,
        selected_source,
        candidate_count,
        association_distance,
        gate_distance,
    ):
        return {
            "detected": detected,
            "center": self._as_int_point(center) if center is not None else None,
            "velocity": self.velocity,
            "history": self.history_pos,
            "missing_frames": self.missing_frames,
            "tracking_status": tracking_status,
            "predicted_center": (
                self._as_int_point(predicted_center)
                if predicted_center is not None
                else None
            ),
            "measurement_center": (
                self._as_int_point(measurement_center)
                if measurement_center is not None
                else None
            ),
            "selected_confidence": selected_confidence,
            "selected_source": selected_source,
            "candidate_count": candidate_count,
            "association_distance": association_distance,
            "gate_distance": gate_distance,
            "prediction_uncertainty": self.prediction_uncertainty,
            "kalman_acceleration": self.acceleration,
        }
