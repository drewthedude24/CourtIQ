import unittest

from vision.predictive_ball_tracker import PredictiveBallTracker


def ball_detection(center, confidence=0.8, size=24):
    x, y = center
    half_size = size // 2
    return {
        "class_id": 0,
        "confidence": confidence,
        "center": center,
        "bbox": (
            x - half_size,
            y - half_size,
            x + half_size,
            y + half_size,
        ),
    }


class PredictiveBallTrackerTests(unittest.TestCase):
    def test_requires_strong_detection_to_start_track(self):
        tracker = PredictiveBallTracker()

        result = tracker.update([ball_detection((100, 100), confidence=0.12)])

        self.assertEqual(result["tracking_status"], "LOST")
        self.assertFalse(result["detected"])

    def test_accepts_low_confidence_detection_near_prediction(self):
        tracker = PredictiveBallTracker()
        tracker.update([ball_detection((100, 100))])
        tracker.update([ball_detection((110, 95))])

        result = tracker.update([ball_detection((119, 90), confidence=0.12)])

        self.assertEqual(result["tracking_status"], "DETECTED")
        self.assertEqual(result["selected_confidence"], 0.12)

    def test_predicts_through_short_detection_gap(self):
        tracker = PredictiveBallTracker()
        tracker.update([ball_detection((100, 100))])
        tracker.update([ball_detection((112, 94))])

        result = tracker.update([])

        self.assertEqual(result["tracking_status"], "PREDICTED")
        self.assertFalse(result["detected"])
        self.assertIsNotNone(result["center"])
        self.assertEqual(result["missing_frames"], 1)

    def test_rejects_implausible_jump(self):
        tracker = PredictiveBallTracker(base_gate_distance=60.0)
        tracker.update([ball_detection((100, 100))])
        tracker.update([ball_detection((108, 96))])

        result = tracker.update([ball_detection((900, 600), confidence=0.95)])

        self.assertEqual(result["tracking_status"], "PREDICTED")
        self.assertFalse(result["detected"])

    def test_accepts_strong_release_acceleration_inside_physical_gate(self):
        tracker = PredictiveBallTracker(base_gate_distance=90.0)
        tracker.update([ball_detection((100, 300))])
        tracker.update([ball_detection((102, 298))])

        result = tracker.update([ball_detection((110, 225), confidence=0.9)])

        self.assertEqual(result["tracking_status"], "DETECTED")
        self.assertEqual(result["selected_confidence"], 0.9)

    def test_live_reacquisition_restarts_bad_prediction(self):
        tracker = PredictiveBallTracker(
            max_prediction_frames=3,
            reacquire_after_missing_frames=2,
            reacquire_confidence_threshold=0.55,
        )
        tracker.update([ball_detection((100, 100))])
        tracker.update([])
        tracker.update([])

        reacquired = ball_detection((500, 300), confidence=0.8)
        reacquired["source"] = "full"
        result = tracker.update([reacquired])

        self.assertEqual(result["tracking_status"], "DETECTED")
        self.assertEqual(result["center"], (500, 300))
        self.assertEqual(result["missing_frames"], 0)
        self.assertEqual(list(result["history"]), [(500, 300)])

    def test_live_reacquisition_rejects_weak_false_detection(self):
        tracker = PredictiveBallTracker(
            reacquire_after_missing_frames=1,
            reacquire_confidence_threshold=0.55,
        )
        tracker.update([ball_detection((100, 100))])
        tracker.update([])

        weak_detection = ball_detection((500, 300), confidence=0.4)
        weak_detection["source"] = "full"
        result = tracker.update([weak_detection])

        self.assertEqual(result["tracking_status"], "PREDICTED")
        self.assertFalse(result["detected"])

    def test_resets_after_long_detection_gap(self):
        tracker = PredictiveBallTracker(
            max_prediction_frames=2,
            max_missing_frames=3,
        )
        tracker.update([ball_detection((100, 100))])

        tracker.update([])
        tracker.update([])
        tracker.update([])
        result = tracker.update([])

        self.assertEqual(result["tracking_status"], "LOST")
        self.assertIsNone(result["center"])
        self.assertEqual(result["missing_frames"], 0)

    def test_kalman_uncertainty_grows_during_detection_gap(self):
        tracker = PredictiveBallTracker()
        tracker.update([ball_detection((100, 100))])
        tracker.update([ball_detection((112, 94))])
        detected = tracker.update([ball_detection((124, 90))])

        predicted = tracker.update([])

        self.assertEqual(predicted["tracking_status"], "PREDICTED")
        self.assertGreater(predicted["center"][0], detected["center"][0])
        self.assertGreater(
            predicted["prediction_uncertainty"],
            detected["prediction_uncertainty"],
        )

    def test_focus_region_uses_next_kalman_prediction_and_stays_in_frame(self):
        tracker = PredictiveBallTracker()
        tracker.update([ball_detection((20, 20))])
        tracker.update([ball_detection((30, 24))])

        region = tracker.get_focus_region((360, 640, 3), base_size=200)

        self.assertIsNotNone(region)
        x1, y1, x2, y2 = region
        self.assertGreaterEqual(x1, 0)
        self.assertGreaterEqual(y1, 0)
        self.assertLessEqual(x2, 640)
        self.assertLessEqual(y2, 360)


if __name__ == "__main__":
    unittest.main()
