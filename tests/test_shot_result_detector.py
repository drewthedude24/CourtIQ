import unittest

from vision.shot_detector import ShotDetector
from vision.shot_result_detector import ShotResultDetector


def hoop_detection(bbox=(800, 240, 920, 290)):
    x1, y1, x2, y2 = bbox
    return {
        "class_id": 1,
        "confidence": 0.9,
        "bbox": bbox,
        "center": ((x1 + x2) // 2, (y1 + y2) // 2),
    }


def tracked_ball(center, status="DETECTED"):
    return {
        "detected": status == "DETECTED",
        "center": center,
        "velocity": (0.0, 5.0),
        "history": [],
        "missing_frames": 0 if status == "DETECTED" else 1,
        "tracking_status": status,
    }


class ShotResultDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detections = [hoop_detection()]

    def test_confirms_make_when_ball_is_observed_below_rim(self):
        detector = ShotResultDetector()

        detector.update(
            self.detections, tracked_ball((840, 220)), "RELEASED", 10
        )
        detector.update(
            self.detections, tracked_ball((842, 255), "PREDICTED"), "RELEASED", 11
        )
        result = detector.update(
            self.detections, tracked_ball((844, 280)), "RELEASED", 12
        )

        self.assertTrue(result["event"])
        self.assertEqual(result["result"], "MAKE")
        self.assertEqual(result["status"], "MAKE")

    def test_rebound_outside_rim_changes_provisional_crossing_to_miss(self):
        detector = ShotResultDetector(predicted_confirmation_frames=45)

        detector.update(
            self.detections, tracked_ball((840, 220)), "RELEASED", 10
        )
        crossing = detector.update(
            self.detections, tracked_ball((850, 270), "PREDICTED"), "RELEASED", 11
        )
        result = detector.update(
            self.detections, tracked_ball((700, 350)), "RELEASED", 30
        )

        self.assertTrue(crossing["provisional_make"])
        self.assertTrue(result["event"])
        self.assertEqual(result["result"], "MISS")

    def test_upward_bounce_after_rim_contact_is_miss(self):
        detector = ShotResultDetector()

        detector.update(
            self.detections, tracked_ball((840, 220)), "RELEASED", 10
        )
        detector.update(
            self.detections, tracked_ball((845, 250)), "RELEASED", 11
        )
        result = detector.update(
            self.detections, tracked_ball((844, 195)), "RELEASED", 25
        )

        self.assertTrue(result["event"])
        self.assertEqual(result["result"], "MISS")
        self.assertEqual(result["reason"], "ball bounced upward from rim")

    def test_uncontradicted_predicted_crossing_becomes_make(self):
        detector = ShotResultDetector(predicted_confirmation_frames=3)

        detector.update(
            self.detections, tracked_ball((840, 220)), "RELEASED", 10
        )
        detector.update(
            self.detections, tracked_ball((850, 270), "PREDICTED"), "RELEASED", 11
        )
        detector.update(self.detections, tracked_ball(None, "LOST"), "RELEASED", 12)
        detector.update(self.detections, tracked_ball(None, "LOST"), "RELEASED", 13)
        result = detector.update(
            self.detections, tracked_ball(None, "LOST"), "RELEASED", 14
        )

        self.assertTrue(result["event"])
        self.assertEqual(result["result"], "MAKE")
        self.assertEqual(result["reason"], "predicted crossing held")


class ShotDetectorLifecycleTests(unittest.TestCase):
    @staticmethod
    def person(person_id=1):
        return {
            "person_id": person_id,
            "keypoints": {
                "left_wrist": {"position": (280, 255)},
                "right_wrist": {"position": (285, 250)},
                "right_ear": {"position": (300, 225)},
            },
        }

    def test_released_state_survives_long_detection_gap(self):
        detector = ShotDetector()
        detector.state = "RELEASED"
        lost_ball = {
            "detected": False,
            "center": None,
            "velocity": (0.0, 0.0),
            "missing_frames": 100,
        }

        state = detector.update(lost_ball, [])

        self.assertEqual(state, "RELEASED")

    def test_complete_shot_returns_detector_to_idle(self):
        detector = ShotDetector()
        detector.state = "RELEASED"

        detector.complete_shot()

        self.assertEqual(detector.state, "IDLE")

    def test_complete_shot_ignores_immediate_rebound_handling(self):
        detector = ShotDetector(result_cooldown_frames=2)
        detector.state = "RELEASED"
        ball = {
            "detected": True,
            "center": (285, 252),
            "velocity": (0.0, -10.0),
            "missing_frames": 0,
        }

        detector.complete_shot()
        first = detector.update(ball, [self.person()])
        second = detector.update(ball, [self.person()])

        self.assertEqual(first, "IDLE")
        self.assertEqual(second, "IDLE")
        self.assertEqual(detector.cooldown_frames_remaining, 0)

    def test_fast_upward_separation_from_possession_is_release(self):
        detector = ShotDetector()
        detector.state = "POSSESSION"
        detector.current_possessor_id = 1
        ball = {
            "detected": True,
            "center": (400, 190),
            "velocity": (14.0, -12.0),
            "missing_frames": 0,
        }

        state = detector.update(ball, [self.person()])

        self.assertEqual(state, "RELEASED")
        self.assertEqual(detector.active_shooter_id, 1)


if __name__ == "__main__":
    unittest.main()
