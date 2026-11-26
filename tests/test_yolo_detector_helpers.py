import unittest

from vision.yolo_detector import YoloDetector


def detection(center, bbox, confidence, source="full", class_id=0):
    return {
        "class_id": class_id,
        "confidence": confidence,
        "bbox": bbox,
        "center": center,
        "source": source,
    }


class YoloDetectorHelperTests(unittest.TestCase):
    def test_focus_detection_replaces_weaker_duplicate(self):
        detections = [
            detection((100, 100), (88, 88, 112, 112), 0.4),
            detection((102, 101), (90, 89, 114, 113), 0.8, source="focus"),
        ]

        merged = YoloDetector._deduplicate_detections(detections)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "focus")
        self.assertEqual(merged[0]["confidence"], 0.8)

    def test_distinct_focus_regions_stay_separate_and_are_clipped(self):
        regions = [(-20, -10, 300, 300), (200, 100, 500, 350)]

        normalized = YoloDetector._normalize_focus_regions(
            regions,
            (360, 640, 3),
        )

        self.assertEqual(normalized, [(0, 0, 300, 300), (200, 100, 500, 350)])

    def test_nearly_identical_focus_regions_are_merged(self):
        regions = [(100, 100, 500, 400), (110, 105, 510, 405)]

        normalized = YoloDetector._normalize_focus_regions(
            regions,
            (720, 1280, 3),
        )

        self.assertEqual(normalized, [(100, 100, 510, 405)])

    def test_strong_full_detection_skips_redundant_focus_crop(self):
        detections = [
            detection((200, 180), (188, 168, 212, 192), 0.7),
        ]

        should_skip = YoloDetector._region_has_strong_ball(
            detections,
            (100, 100, 300, 300),
            0.45,
        )

        self.assertTrue(should_skip)

    def test_weak_full_detection_still_requests_focus_crop(self):
        detections = [
            detection((200, 180), (188, 168, 212, 192), 0.2),
        ]

        should_skip = YoloDetector._region_has_strong_ball(
            detections,
            (100, 100, 300, 300),
            0.45,
        )

        self.assertFalse(should_skip)


if __name__ == "__main__":
    unittest.main()
