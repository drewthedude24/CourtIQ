import math

import pytest

from vision.shot_form import angle, ball_and_hoop, ball_in_hand, find_arrival, find_release, measure

FPS = 30
SIDES = ("left", "right")
RIM_TIME_S = 2.3
# The made-up shot: stand, dip to a 110 degree knee at 1.1 s, straighten, let go at 1.4 s.
DIP_START_S, DEEPEST_S, RELEASE_S = 0.8, 1.1, 1.4
DEEPEST_KNEE = 110
SEGMENT = 200  # thigh and shank length in pixels
HALF_ARM = 136  # upper arm and forearm: the whole arm is 0.68 of the straight leg
HOOP = (700, 300)  # centre x and rim line y


def knee_at(t):
    if t <= DIP_START_S or t >= RELEASE_S:
        return 180
    # A smooth dip that slows down at the bottom, like a real one.
    progress = (t - DIP_START_S) / (RELEASE_S - DIP_START_S)
    return 180 - (180 - DEEPEST_KNEE) * (1 - math.cos(2 * math.pi * progress)) / 2


def stick_figure(t, from_behind=False, reach_deg=90, hidden=()):
    """One frame of a shooter facing right: feet at y=1000, hips straight above the ankles.

    The 3D points are always the true side-on shape. from_behind squashes only the picture.
    """
    half_knee = math.radians(knee_at(t) / 2)
    hip_y = 1000 - 2 * SEGMENT * math.sin(half_knee)
    shoulder_y = hip_y - 250
    released = t >= RELEASE_S
    reach = math.radians(reach_deg)
    # Before the release the forearm is folded back (elbow at 90 degrees). After it the arm is
    # straight and points reach_deg above level.
    folded_wrist = (100 + HALF_ARM, shoulder_y - HALF_ARM)
    straight_wrist = (100 + 2 * HALF_ARM * math.cos(reach), shoulder_y - 2 * HALF_ARM * math.sin(reach))
    spots = {
        "ankle": (100, 1000),
        "knee": (100 + SEGMENT * math.cos(half_knee), (1000 + hip_y) / 2),
        "hip": (100, hip_y),
        "shoulder": (100, shoulder_y),
        "elbow": (100, shoulder_y - HALF_ARM),
        "wrist": straight_wrist if released else folded_wrist,
    }
    world = {f"{side}_{name}": (x, y, 0) for name, (x, y) in spots.items() for side in SIDES}
    if from_behind:
        # Seen from behind, forward and back are invisible: every joint lines up.
        spots = {name: (100, y) for name, (_, y) in spots.items()}
        folded_wrist = (100, folded_wrist[1])
    points = {
        f"{side}_{name}": (x, y, 0.2 if name in hidden else 0.9)
        for name, (x, y) in spots.items()
        for side in SIDES
    }

    # The ball sits just above the folded-back hand until the release, then flies to the hoop.
    held = (folded_wrist[0], folded_wrist[1] - 40)
    flown = (t - RELEASE_S + 1 / FPS) / (RIM_TIME_S - RELEASE_S + 1 / FPS) if released else 0
    ball = (held[0] + (HOOP[0] - held[0]) * flown, held[1] + (HOOP[1] - held[1]) * flown, 60)
    return {"t": t, "points": points, "world": world, "balls": [ball], "hoop": HOOP, "rim": HOOP}


def shot(**figure_options):
    return [stick_figure(i / FPS, **figure_options) for i in range(int(RIM_TIME_S * FPS))]


def test_angle_of_a_straight_line_and_a_corner():
    assert angle((0, 0), (1, 0), (2, 0)) == pytest.approx(180)
    assert angle((0, 1), (0, 0), (1, 0)) == pytest.approx(90)
    assert angle((0, 0, 1), (0, 0, 0), (1, 0, 0)) == pytest.approx(90)


def test_detections_become_balls_and_the_rim_line():
    detections = [
        {"class_id": 0, "confidence": 0.8, "bbox": (90, 190, 130, 230), "center": (110, 210)},
        {"class_id": 1, "confidence": 0.4, "bbox": (0, 0, 10, 10), "center": (5, 5)},
        {"class_id": 1, "confidence": 0.9, "bbox": (300, 400, 360, 460), "center": (330, 430)},
    ]

    assert ball_and_hoop(detections) == {"balls": [(110, 210, 40)], "hoop": (330, 400)}
    assert ball_and_hoop([]) == {"balls": [], "hoop": None}


def test_release_is_the_first_frame_the_ball_is_out_of_the_hand():
    frames = shot()
    release_s, arm = find_release(frames, *find_arrival(frames, RIM_TIME_S))

    assert release_s == pytest.approx(RELEASE_S, abs=1 / FPS)
    assert arm in SIDES


def test_a_false_ball_on_the_hand_after_the_shot_does_not_move_the_release():
    frames = shot()
    for frame in frames:
        if frame["t"] >= 2.0:
            x, y, _ = frame["points"]["right_wrist"]
            frame["balls"].append((x, y, 40))

    release_s, _ = find_release(frames, *find_arrival(frames, RIM_TIME_S))

    assert release_s == pytest.approx(RELEASE_S, abs=1 / FPS)


def test_no_release_when_the_ball_is_lost_for_too_long_after_leaving_the_hand():
    frames = shot()
    for frame in frames:
        if RELEASE_S - 0.01 <= frame["t"] <= RELEASE_S + 0.3:
            frame["balls"] = []

    assert find_release(frames, *find_arrival(frames, RIM_TIME_S)) == (None, None)
    assert measure(frames, RIM_TIME_S)["knee_bend_deg"] is None


def test_a_ball_hidden_by_the_net_still_gets_its_numbers():
    # The ball is last seen just above the rim and next seen under the net half a second after
    # reaching it. That is when the detector says the shot happened. In between, the hand is
    # marked as a ball.
    last_seen_s, shot_time_s = 2.2, RIM_TIME_S + 0.5
    frames = [stick_figure(i / FPS) for i in range(round(shot_time_s * FPS) + 1)]
    for frame in frames:
        if frame["t"] > last_seen_s + 0.01:
            frame["balls"] = []
    x, y, _ = frames[75]["points"]["right_wrist"]
    frames[75]["balls"] = [(x, y, 40)]
    frames[-1]["balls"] = [(HOOP[0], HOOP[1] + 80, 60)]

    numbers = measure(frames, shot_time_s)

    assert numbers["release_s"] == pytest.approx(RELEASE_S, abs=1 / FPS)
    assert numbers["flight_time_s"] == pytest.approx(last_seen_s - RELEASE_S, abs=1 / FPS)
    assert numbers["knee_bend_deg"] == pytest.approx(DEEPEST_KNEE, abs=3)


def test_a_wrong_hoop_box_does_not_move_the_release():
    # In the last frame the hoop box is on something beside the shooter, and the hand next to
    # it is marked as a ball. The steadied rim is still on the real hoop.
    frames = shot()
    x, y, _ = frames[-1]["points"]["right_wrist"]
    frames[-1]["hoop"] = (x, y + 100)
    frames[-1]["balls"].append((x, y, 40))

    numbers = measure(frames, RIM_TIME_S)

    assert numbers["release_s"] == pytest.approx(RELEASE_S, abs=1 / FPS)


def test_numbers_for_a_shot_seen_from_the_side():
    numbers = measure(shot(), RIM_TIME_S)

    assert numbers["knee_bend_deg"] == pytest.approx(DEEPEST_KNEE, abs=3)
    assert numbers["elbow_bend_deg"] == pytest.approx(90, abs=3)
    assert numbers["arm_angle_deg"] == pytest.approx(90, abs=3)
    assert numbers["jump"] == pytest.approx(0, abs=0.02)
    assert numbers["flight_time_s"] == pytest.approx(RIM_TIME_S - RELEASE_S, abs=2 / FPS)
    assert numbers["bend_s"] == pytest.approx(DEEPEST_S, abs=2 / FPS)


def test_each_number_remembers_the_frame_it_was_read_on():
    seen_at = measure(shot(), RIM_TIME_S)["seen_at"]

    assert seen_at["knee_bend_deg"] == pytest.approx(DEEPEST_S, abs=2 / FPS)
    assert RELEASE_S - 0.6 <= seen_at["elbow_bend_deg"] <= RELEASE_S
    assert RELEASE_S <= seen_at["arm_angle_deg"] <= RELEASE_S + 0.3
    assert RELEASE_S - 0.15 <= seen_at["jump"] <= RELEASE_S + 0.3
    assert seen_at["flight_time_s"] == pytest.approx(RELEASE_S, abs=1 / FPS)


def test_the_same_numbers_come_out_when_the_shot_is_seen_from_behind():
    numbers = measure(shot(from_behind=True, reach_deg=50), RIM_TIME_S)

    # In the picture the knee looks straight and the arm looks straight up. Up-and-down distances
    # and the 3D elbow still give the real angles.
    assert numbers["knee_bend_deg"] == pytest.approx(DEEPEST_KNEE, abs=3)
    assert numbers["arm_angle_deg"] == pytest.approx(50, abs=3)
    assert numbers["elbow_bend_deg"] == pytest.approx(90, abs=3)


def test_a_joint_that_was_not_clearly_seen_leaves_its_number_empty():
    numbers = measure(shot(hidden=("elbow",)), RIM_TIME_S)

    assert numbers["elbow_bend_deg"] is None
    assert numbers["knee_bend_deg"] == pytest.approx(DEEPEST_KNEE, abs=3)


def test_an_arm_hidden_for_part_of_the_wind_up_leaves_the_elbow_empty():
    frames = shot()
    for frame in frames:
        if RELEASE_S - 0.3 <= frame["t"] <= RELEASE_S - 0.1:
            x, y, _ = frame["points"]["right_elbow"]
            frame["points"]["right_elbow"] = frame["points"]["left_elbow"] = (x, y, 0.2)

    numbers = measure(frames, RIM_TIME_S)

    assert numbers["elbow_bend_deg"] is None
    assert numbers["knee_bend_deg"] == pytest.approx(DEEPEST_KNEE, abs=3)


def test_half_the_frames_give_nearly_the_same_knee_bend():
    every_frame = measure(shot(), RIM_TIME_S)["knee_bend_deg"]
    every_other = measure(shot()[::2], RIM_TIME_S)["knee_bend_deg"]

    assert every_other == pytest.approx(every_frame, abs=5)


def test_the_ball_is_in_the_hand_until_the_release():
    assert ball_in_hand(stick_figure(RELEASE_S - 0.2))
    assert not ball_in_hand(stick_figure(RELEASE_S + 0.2))


def test_a_hidden_ball_or_hidden_wrists_count_as_still_in_the_hand():
    in_flight = stick_figure(RELEASE_S + 0.2)
    assert ball_in_hand(dict(in_flight, balls=[]))
    assert ball_in_hand(stick_figure(RELEASE_S + 0.2, hidden=("wrist",)))
