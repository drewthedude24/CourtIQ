import pytest

from vision.ball_path import BallPath

FPS = 30


def ball(x, y, confidence=0.8, radius=20):
    return {
        "class_id": 0,
        "confidence": confidence,
        "bbox": (x - radius, y - radius, x + radius, y + radius),
        "center": (x, y),
    }


def test_skipped_frames_lie_between_the_detections_around_them():
    path = BallPath(FPS)
    for frame in (0, 4, 8, 12):
        path.add(frame, [ball(100 + 10 * frame, 500)])

    assert path.ball(4) == (140, 500, 40)
    x, y, width = path.ball(6)
    assert (x, y, width) == pytest.approx((160, 500, 40))


def test_curve_bends_through_an_arc():
    path = BallPath(FPS)
    # A ball on the arc y = (frame - 8)^2, seen on every 4th frame.
    for frame in (0, 4, 8, 12, 16):
        path.add(frame, [ball(100 + 10 * frame, 300 + (frame - 8) ** 2)])

    # A straight line from frame 4 to frame 8 would put frame 6 at y = 308. The arc is at 304.
    assert path.ball(6)[1] == pytest.approx(304, abs=1.5)


def test_no_ball_before_the_first_detection_or_across_a_long_gap():
    path = BallPath(FPS)
    path.add(4, [ball(100, 500)])
    path.add(40, [ball(140, 500)])

    assert path.ball(2) is None
    assert path.ball(20) is None
    assert path.ball(40) == (140, 500, 40)


def test_a_weak_detection_cannot_start_a_path_but_can_continue_one():
    path = BallPath(FPS)
    path.add(0, [ball(100, 500, confidence=0.2)])
    assert path.ball(0) is None

    path.add(4, [ball(100, 500)])
    path.add(8, [ball(130, 480, confidence=0.2)])
    assert path.ball(8) == (130, 480, 40)


def test_a_ball_far_away_starts_a_new_path_that_is_not_joined_to_the_old_one():
    path = BallPath(FPS)
    path.add(0, [ball(100, 500)])
    path.add(4, [ball(600, 100)])

    assert path.ball(4) == (600, 100, 40)
    assert path.ball(2) is None


def test_a_spare_ball_lying_still_is_ignored():
    path = BallPath(FPS)
    spare = ball(300, 800)
    for frame in range(0, 40, 4):
        path.add(frame, [spare])
    # The ball in play shows up, then goes out of sight behind the player.
    path.add(40, [spare, ball(500, 400)])
    path.add(44, [spare, ball(520, 380)])
    path.add(48, [spare])

    assert path.ball(40)[:2] == (500, 400)
    assert path.ball(44)[:2] == (520, 380)
    assert path.ball(48) is None


def test_trail_grows_while_a_shot_is_in_the_air_and_shrinks_back_after():
    path = BallPath(FPS)
    short = round(0.67 * FPS)

    def step(frame, in_flight):
        return path.trail(frame, (frame, 500, 40), in_flight)

    for frame in range(40):
        trail = step(frame, in_flight=False)
    assert len(trail) == short
    assert trail[-1] == (38, 500)

    for frame in range(40, 70):
        trail = step(frame, in_flight=True)
    assert len(trail) == short + 30

    lengths = [len(step(frame, in_flight=False)) for frame in range(70, 100)]
    assert lengths[0] == short + 30 - 2
    assert lengths[-1] == short
