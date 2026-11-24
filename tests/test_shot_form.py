import math

import pytest

from vision.shot_form import angle, find_release, measure

FPS = 30
SIDES = ("left", "right")
RIM_TIME_S = 2.3
# The made-up shot: stand, dip to a 110 degree knee at 1.1 s, straighten, let go at 1.4 s.
DIP_START_S, DEEPEST_S, RELEASE_S = 0.8, 1.1, 1.4
DEEPEST_KNEE = 110
SEGMENT = 200  # thigh and shank length in pixels
HOOP = (700, 300)  # centre x and rim line y


def knee_at(t):
    if t <= DIP_START_S or t >= RELEASE_S:
        return 180
    # A smooth dip that slows down at the bottom, like a real one.
    progress = (t - DIP_START_S) / (RELEASE_S - DIP_START_S)
    return 180 - (180 - DEEPEST_KNEE) * (1 - math.cos(2 * math.pi * progress)) / 2


def stick_figure(t, from_behind=False, hidden=()):
    """One frame of a shooter drawn from the side: feet at y=1000, hips straight above the ankles."""
    half_knee = math.radians(knee_at(t) / 2)
    hip_y = 1000 - 2 * SEGMENT * math.sin(half_knee)
    shoulder_y = hip_y - 250
    released = t >= RELEASE_S
    # Before the release the forearm is folded back (elbow at 90 degrees). After it the arm is straight up.
    elbow = (100, shoulder_y - 150)
    wrist = (100, shoulder_y - 300) if released else (250, shoulder_y - 150)
    spots = {
        "ankle": (100, 1000),
        "knee": (100 + SEGMENT * math.cos(half_knee), (1000 + hip_y) / 2),
        "hip": (100, hip_y),
        "shoulder": (100, shoulder_y),
        "elbow": elbow,
        "wrist": wrist,
    }
    if from_behind:
        # Seen from behind, forward and back are invisible: every joint lines up.
        spots = {name: (100, y) for name, (_, y) in spots.items()}
    points = {
        f"{side}_{name}": (x, y, 0.2 if name in hidden else 0.9)
        for name, (x, y) in spots.items()
        for side in SIDES
    }

    # The ball sits just above the folded-back hand until the release, then flies to the hoop.
    held = (100 if from_behind else 250, shoulder_y - 190)
    flown = (t - RELEASE_S + 1 / FPS) / (RIM_TIME_S - RELEASE_S + 1 / FPS) if released else 0
    ball = (held[0] + (HOOP[0] - held[0]) * flown, held[1] + (HOOP[1] - held[1]) * flown, 60)
    return {"t": t, "points": points, "balls": [ball], "hoop": HOOP}


def shot(**figure_options):
    return [stick_figure(i / FPS, **figure_options) for i in range(int(RIM_TIME_S * FPS))]


def test_angle_of_a_straight_line_and_a_corner():
    assert angle((0, 0), (1, 0), (2, 0)) == pytest.approx(180)
    assert angle((0, 1), (0, 0), (1, 0)) == pytest.approx(90)
    assert angle((0, 0, 1), (0, 0, 0), (1, 0, 0)) == pytest.approx(90)


def test_release_is_the_first_frame_the_ball_is_out_of_the_hand():
    release_s, arm = find_release(shot(), RIM_TIME_S)

    assert release_s == pytest.approx(RELEASE_S, abs=1 / FPS)
    assert arm in SIDES


def test_a_false_ball_on_the_hand_after_the_shot_does_not_move_the_release():
    frames = shot()
    for frame in frames:
        if frame["t"] >= 2.0:
            x, y, _ = frame["points"]["right_wrist"]
            frame["balls"].append((x, y, 40))

    release_s, _ = find_release(frames, RIM_TIME_S)

    assert release_s == pytest.approx(RELEASE_S, abs=1 / FPS)


def test_no_release_when_the_ball_is_lost_for_too_long_after_leaving_the_hand():
    frames = shot()
    for frame in frames:
        if RELEASE_S - 0.01 <= frame["t"] <= RELEASE_S + 0.3:
            frame["balls"] = []

    assert find_release(frames, RIM_TIME_S) == (None, None)
    assert measure(frames, RIM_TIME_S)["knee_vertical"] is None


def test_numbers_for_a_shot_seen_from_the_side():
    numbers = measure(shot(), RIM_TIME_S)

    assert numbers["knee_vertical"] == pytest.approx(DEEPEST_KNEE, abs=3)
    assert numbers["knee_flat"] == pytest.approx(DEEPEST_KNEE, abs=3)
    assert numbers["elbow_flat"] == pytest.approx(90, abs=3)
    assert numbers["arm_flat"] == pytest.approx(90, abs=3)
    assert numbers["release_time_s"] == pytest.approx(RELEASE_S - DEEPEST_S, abs=2 / FPS)
    assert numbers["flight_time_s"] == pytest.approx(RIM_TIME_S - RELEASE_S, abs=2 / FPS)
    # Hand straight up over the head: the feet-to-hand height is the body plus the whole arm.
    assert numbers["release_height"] == pytest.approx((650 + 300) / 650, abs=0.03)
    # No 3D points were given, so the 3D versions stay empty.
    assert numbers["knee_3d"] is None


def test_leg_shortening_still_reads_the_knee_from_behind_where_the_flat_angle_cannot():
    numbers = measure(shot(from_behind=True), RIM_TIME_S)

    assert numbers["knee_vertical"] == pytest.approx(DEEPEST_KNEE, abs=3)
    assert numbers["knee_flat"] == pytest.approx(180, abs=3)


def test_a_joint_that_was_not_clearly_seen_leaves_its_number_empty():
    numbers = measure(shot(hidden=("elbow",)), RIM_TIME_S)

    assert numbers["elbow_flat"] is None
    assert numbers["knee_vertical"] == pytest.approx(DEEPEST_KNEE, abs=3)


def test_an_arm_hidden_for_part_of_the_wind_up_leaves_the_elbow_empty():
    frames = shot()
    for frame in frames:
        if RELEASE_S - 0.3 <= frame["t"] <= RELEASE_S - 0.1:
            x, y, _ = frame["points"]["right_elbow"]
            frame["points"]["right_elbow"] = frame["points"]["left_elbow"] = (x, y, 0.2)

    numbers = measure(frames, RIM_TIME_S)

    assert numbers["elbow_flat"] is None
    assert numbers["knee_vertical"] == pytest.approx(DEEPEST_KNEE, abs=3)


def test_half_the_frames_give_nearly_the_same_knee_bend():
    every_frame = measure(shot(), RIM_TIME_S)["knee_vertical"]
    every_other = measure(shot()[::2], RIM_TIME_S)["knee_vertical"]

    assert every_other == pytest.approx(every_frame, abs=5)
