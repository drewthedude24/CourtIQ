import pytest

from backend.fatigue import fatigue_report


def session(name, jumps, results=None):
    """The rows the database gives for one session: one per shot, in order.
    A jump of None is a shot where the jump could not be measured."""
    results = results or ["MAKE"] * len(jumps)
    return [
        {"session_id": name, "original_filename": f"{name}.mov", "created_at": f"2026-11-0{name[-1]}",
         "shot_number": number, "jump": jump, "result": result}
        for number, (jump, result) in enumerate(zip(jumps, results), start=1)
    ]


def dropping(level, shots=6, per_shot=-0.01):
    """Jumps that start at `level` and change by `per_shot` on every shot."""
    return [level + per_shot * shot for shot in range(shots)]


def test_finds_the_drop_per_shot_shared_by_every_session():
    rows = session("s1", dropping(0.30)) + session("s2", dropping(0.25)) + session("s3", dropping(0.28))

    model = fatigue_report(rows)["model"]

    assert model["per_shot"] == pytest.approx(-0.01)
    assert (model["sessions"], model["dropped"]) == (3, 3)


def test_each_session_keeps_its_own_starting_level():
    rows = session("s1", dropping(0.30)) + session("s2", dropping(0.25)) + session("s3", dropping(0.28))

    sessions = fatigue_report(rows)["sessions"]

    assert [s["id"] for s in sessions] == ["s1", "s2", "s3"]
    assert [s["start"] for s in sessions] == pytest.approx([0.30, 0.25, 0.28])
    assert [s["end"] for s in sessions] == pytest.approx([0.25, 0.20, 0.23])
    # What was measured, next to the model's line: the average of the first and last three jumps.
    assert [(s["first"], s["last"]) for s in sessions] == [
        pytest.approx((0.29, 0.26)), pytest.approx((0.24, 0.21)), pytest.approx((0.27, 0.24)),
    ]
    assert sessions[0]["shots"][1] == {"shot_number": 2, "jump": pytest.approx(0.29), "result": "MAKE"}


def test_a_lower_jumping_long_session_is_not_mistaken_for_a_drop():
    # Nothing changes inside any session. One line through all the shots together would slope
    # down, because only the low session has shots 7 to 12.
    rows = (session("s1", [0.30] * 6) + session("s2", [0.30] * 6) + session("s3", [0.20] * 12))

    model = fatigue_report(rows)["model"]

    assert model["per_shot"] == pytest.approx(0)
    assert model["dropped"] == 0


def test_typical_drop_is_a_share_of_the_starting_jump():
    rows = session("s1", dropping(0.25, shots=11)) + session("s2", dropping(0.25, shots=11)) + session("s3", dropping(0.25, shots=11))

    model = fatigue_report(rows)["model"]

    # 10 steps of -0.01 from a start of 0.25 is 0.10 lower, which is 40%.
    assert (model["typical_shots"], model["start"]) == (11, pytest.approx(0.25))
    assert model["drop_pct"] == pytest.approx(-40)


def test_no_model_until_three_sessions():
    rows = session("s1", dropping(0.30)) + session("s2", dropping(0.25))

    report = fatigue_report(rows)

    assert report["model"] is None
    # The shots are still listed for the chart, but no trend line is claimed.
    assert [(s["id"], len(s["shots"]), s["start"], s["end"]) for s in report["sessions"]] == [
        ("s1", 6, None, None), ("s2", 6, None, None),
    ]


def test_a_session_with_too_few_measured_jumps_is_left_out():
    rows = (session("s1", dropping(0.30)) + session("s2", dropping(0.25)) + session("s3", dropping(0.28))
            + session("s4", [0.9, 0.1, None, None, None, None]))

    report = fatigue_report(rows)

    assert [s["id"] for s in report["sessions"]] == ["s1", "s2", "s3"]
    assert report["model"]["per_shot"] == pytest.approx(-0.01)


def test_an_unmeasured_shot_is_skipped_but_keeps_its_place():
    jumps = dropping(0.30, shots=8)
    jumps[2] = None
    rows = session("s1", jumps) + session("s2", dropping(0.25)) + session("s3", dropping(0.28))

    report = fatigue_report(rows)

    assert report["model"]["per_shot"] == pytest.approx(-0.01)
    assert [shot["shot_number"] for shot in report["sessions"][0]["shots"]] == [1, 2, 4, 5, 6, 7, 8]


def test_check_scores_the_trend_on_sessions_it_did_not_learn_from():
    rows = session("s1", dropping(0.30)) + session("s2", dropping(0.25)) + session("s3", dropping(0.28))

    check = fatigue_report(rows)["model"]["check"]

    # Every session drops the same way, so the trend learned from the other two is exact.
    assert check["with_trend"] == pytest.approx(0)
    # Guessing the session's average for every shot is off by 0.015 on average here.
    assert check["without"] == pytest.approx(0.015)


def test_check_says_when_the_trend_does_not_carry_over():
    # Two sessions drop and one rises just as much, so a trend learned from two is wrong for the third.
    rows = (session("s1", dropping(0.30)) + session("s2", dropping(0.25))
            + session("s3", dropping(0.28, per_shot=0.01)))

    check = fatigue_report(rows)["model"]["check"]

    assert check["with_trend"] > check["without"]


def test_makes_are_counted_for_the_first_and_second_half_of_each_session():
    results = ["MAKE", "MAKE", "MISS", "MAKE", "MISS", "MISS"]
    rows = (session("s1", dropping(0.30), results) + session("s2", dropping(0.25), results)
            + session("s3", dropping(0.28), results))

    makes = fatigue_report(rows)["makes"]

    assert makes["early"] == {"makes": 6, "shots": 9}
    assert makes["late"] == {"makes": 3, "shots": 9}
    # 67% against 33% on 9 shots each is still inside what luck does.
    assert makes["clear"] is False


def test_a_big_gap_on_many_shots_is_called_clear():
    results = ["MAKE"] * 10 + ["MISS"] * 10
    rows = (session("s1", dropping(0.30, shots=20), results) + session("s2", dropping(0.25, shots=20), results)
            + session("s3", dropping(0.28, shots=20), results))

    assert fatigue_report(rows)["makes"]["clear"] is True


def test_no_shots_gives_an_empty_report():
    assert fatigue_report([]) == {"model": None, "sessions": [], "makes": None}
