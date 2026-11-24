from eval.score import match_shots


def test_pairs_nearby_shots_and_counts_missed_and_false():
    labels = [(10.0, "MAKE"), (30.0, "MISS")]
    detections = [(10.8, "MAKE"), (50.0, "MISS")]

    pairs, missed, false = match_shots(labels, detections)

    assert pairs == [((10.0, "MAKE"), (10.8, "MAKE"))]
    assert missed == [(30.0, "MISS")]
    assert false == [(50.0, "MISS")]


def test_each_detection_is_used_once_and_closest_wins():
    labels = [(10.0, "MAKE"), (11.0, "MISS")]
    detections = [(10.9, "MISS")]

    pairs, missed, false = match_shots(labels, detections)

    # The detection is closer to the 11.0 shot, so the 10.0 shot counts as missed.
    assert pairs == [((11.0, "MISS"), (10.9, "MISS"))]
    assert missed == [(10.0, "MAKE")]
    assert false == []
