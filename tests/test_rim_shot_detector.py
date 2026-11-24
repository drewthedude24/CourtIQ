from vision.rim_shot_detector import RimShotDetector

FPS = 30
# A 60x60 hoop box: its top edge (the rim line) is y=400 and its centre is x=330.
HOOP_BOX = (300, 400, 360, 460)
# Ball positions for a shot dropping in from the upper left, ending at rim level.
ARC_TO_RIM = [(240, 300), (270, 330), (300, 360), (330, 390)]
THROUGH_NET = [(330, 425), (330, 445), (330, 520)]
# Two seconds with no ball in sight: longer than the detector watches the rim after a shot.
NO_BALL = [None] * (2 * FPS)


def hoop(shift=0):
    x1, y1, x2, y2 = HOOP_BOX
    return {"class_id": 1, "confidence": 0.9, "bbox": (x1 + shift, y1, x2 + shift, y2)}


def ball(x, y, radius=18):
    return {
        "class_id": 0,
        "confidence": 0.8,
        "bbox": (x - radius, y - radius, x + radius, y + radius),
        "center": (x, y),
    }


def play(detector, ball_path, start_s=0.0):
    """Feed one frame per ball position (None = ball not seen). Returns the shot events."""
    events = []
    for i, position in enumerate(ball_path):
        detections = [hoop()] + ([ball(*position)] if position else [])
        result = detector.update(detections, start_s + i / FPS)
        if result["event"]:
            events.append(result)
    return events


def test_ball_dropping_through_the_net_is_a_make():
    events = play(RimShotDetector(), ARC_TO_RIM + THROUGH_NET)

    assert [event["result"] for event in events] == ["MAKE"]
    # The shot time is when the ball reached the rim, not when the result was decided.
    assert events[0]["shot_time_s"] == 3 / FPS
    assert events[0]["shot_id"] == 1


def test_ball_bouncing_off_the_rim_is_a_miss():
    bounce_away = [(300, 350), (260, 340), (220, 380), (180, 460), (150, 560)]

    events = play(RimShotDetector(), ARC_TO_RIM + bounce_away + NO_BALL)

    assert [event["result"] for event in events] == ["MISS"]


def test_airball_just_beside_the_rim_is_a_miss():
    # Passes rim level one hoop-width left of the hoop's centre and keeps falling.
    airball = [(180, 300), (210, 330), (240, 360), (270, 390), (280, 440), (290, 500)]

    events = play(RimShotDetector(), airball + NO_BALL)

    assert [event["result"] for event in events] == ["MISS"]


def test_ball_lost_after_hitting_the_rim_is_still_a_shot():
    events = play(RimShotDetector(), ARC_TO_RIM + NO_BALL)

    assert [event["result"] for event in events] == ["MISS"]


def test_one_stray_sighting_in_the_net_is_not_a_make():
    events = play(RimShotDetector(), ARC_TO_RIM + [(330, 430)] + NO_BALL)

    assert [event["result"] for event in events] == ["MISS"]


def test_rim_bounce_counts_as_one_shot():
    # A high bounce: 0.9 s up, 0.9 s back down onto the rim, after the first result is in.
    up_and_down_again = [(320, 390 - 6 * i) for i in range(1, 27)] + [(320, 234 + 6 * i) for i in range(1, 27)]

    events = play(RimShotDetector(), ARC_TO_RIM + up_and_down_again + NO_BALL)

    assert len(events) == 1


def test_ball_held_below_the_rim_is_not_a_shot():
    dribble = [(330, 520 + 40 * (i % 2)) for i in range(3 * FPS)]

    assert play(RimShotDetector(), dribble) == []


def test_two_shots_are_counted_separately():
    detector = RimShotDetector()

    first = play(detector, ARC_TO_RIM + THROUGH_NET)
    second = play(detector, ARC_TO_RIM + NO_BALL, start_s=5.0)

    assert [event["result"] for event in first + second] == ["MAKE", "MISS"]
    assert [event["shot_id"] for event in first + second] == [1, 2]


def test_follows_a_hoop_that_drifts_with_the_camera():
    detector = RimShotDetector()
    events = []
    # The whole picture slides right 15 px a second, as if the phone is slowly panning.
    for i, (x, y) in enumerate([(330, 390)] * 40 + ARC_TO_RIM + THROUGH_NET):
        shift = i // 2
        result = detector.update([hoop(shift), ball(x + shift, y)], i / FPS)
        if result["event"]:
            events.append(result["result"])

    # The still ball at the rim for the first 40 frames never came from above, so only
    # the real shot counts.
    assert events == ["MAKE"]


def test_no_hoop_means_no_shots():
    detector = RimShotDetector()

    results = [detector.update([ball(x, y)], i / FPS) for i, (x, y) in enumerate(ARC_TO_RIM)]

    assert not any(result["event"] for result in results)
    assert results[-1]["hoop_bbox"] is None


def test_rim_crop_is_only_requested_while_a_shot_is_arriving():
    detector = RimShotDetector()
    frame_shape = (1280, 720, 3)

    detector.update([hoop(), ball(330, 560)], 0.0)
    assert detector.get_focus_region(frame_shape) is None

    detector.update([hoop(), ball(240, 300)], 1 / FPS)
    x1, y1, x2, y2 = detector.get_focus_region(frame_shape)
    # The crop covers the hoop box with room around it.
    assert x1 < 300 and x2 > 360 and y1 < 400 and y2 > 460


def test_ball_at_the_rim_long_after_being_high_is_not_a_shot():
    # High in the air, out of sight for 2 seconds, then at rim level (a rebound being carried).
    path = [(240, 300)] + NO_BALL + [(330, 390), (330, 430), (330, 445)]

    assert play(RimShotDetector(), path) == []


def test_ball_high_on_the_far_side_of_the_picture_does_not_start_a_shot():
    # 6 hoop-widths to the left: too far away to be this hoop's shot one frame later.
    path = [(-30, 300), (330, 390), (330, 430), (330, 445)]

    assert play(RimShotDetector(), path) == []


def test_stray_ball_far_below_the_hoop_does_not_start_a_shot():
    detector = RimShotDetector()
    # The real ball is high in the air while YOLO also reports a "ball" on the ground under the hoop.
    results = [detector.update([hoop(), ball(240, 300), ball(330, 700)], i / FPS) for i in range(3)]
    results += [detector.update([hoop()], (3 + i) / FPS) for i in range(2 * FPS)]

    assert not any(result["event"] for result in results)


def test_ball_hidden_by_the_net_then_dropping_out_below_is_a_make():
    out_under_the_net = [None, None, (330, 470), (330, 500)]

    events = play(RimShotDetector(), ARC_TO_RIM + out_under_the_net)

    assert [event["result"] for event in events] == ["MAKE"]


def test_shot_still_being_watched_when_the_video_ends_is_reported():
    detector = RimShotDetector()
    assert detector.finish() is None

    assert play(detector, ARC_TO_RIM) == []
    final = detector.finish()

    assert final["event"] and final["result"] == "MISS"
    assert final["shot_time_s"] == 3 / FPS
