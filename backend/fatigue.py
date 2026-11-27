"""A small model of how a shooter's jump changes through a session.

Jump is the one form number that falls as a session goes on (docs/fatigue-results.md). The model:

    jump on a shot = that session's starting jump + per_shot * (shots taken before it)

Every session gets its own starting jump, because people jump a little higher on some days.
All sessions share one per_shot, the number the model learns. It is fitted again from all of a
user's shots every time the page asks, so a new session updates it and nothing is stored.
"""
from math import sqrt
from statistics import fmean

# A session needs this many shots with a measured jump to say anything about a trend.
MIN_SHOTS = 5
# A session's first and last jumps are averaged over this many shots, since one jump is noisy.
EDGE = 3
# With fewer sessions than this there is nothing to check the trend against.
MIN_SESSIONS = 3


def slope(sessions):
    """The change in jump per shot that fits these sessions best (least squares).
    Each session is a list of (shots taken before, jump). Both are measured from the session's
    own average, so a session that is lower overall does not look like a drop."""
    up, down = 0.0, 0.0
    for points in sessions:
        before, jump = fmean(x for x, _ in points), fmean(y for _, y in points)
        up += sum((x - before) * (y - jump) for x, y in points)
        down += sum((x - before) ** 2 for x, _ in points)
    return up / down


def miss(points, per_shot):
    """How far off each jump of one session is when it is guessed as the session's average
    plus a trend of per_shot. With per_shot 0 the guess is just the average."""
    before, jump = fmean(x for x, _ in points), fmean(y for _, y in points)
    return [abs(y - (jump + per_shot * (x - before))) for x, y in points]


def check(sessions):
    """Leave-one-session-out cross-validation: learn the trend from the other sessions, then
    see how far off it is on the session it never saw. "without" is the same guess with no
    trend. If with_trend is not smaller, the trend does not carry over to new sessions."""
    with_trend, without = [], []
    for held_out in range(len(sessions)):
        others = sessions[:held_out] + sessions[held_out + 1:]
        with_trend += miss(sessions[held_out], slope(others))
        without += miss(sessions[held_out], 0)
    return {"with_trend": fmean(with_trend), "without": fmean(without)}


def early_and_late(sessions):
    """Makes in the first and the second half of every session, added up."""
    halves = {"early": {"makes": 0, "shots": 0}, "late": {"makes": 0, "shots": 0}}
    for rows in sessions:
        for row in rows:
            half = halves["early" if 2 * (row["shot_number"] - 1) < len(rows) - 1 else "late"]
            half["shots"] += 1
            half["makes"] += row["result"] == "MAKE"
    early, late = (half["makes"] / half["shots"] for half in halves.values())
    # The gap is clear when it is more than twice its standard error, which is how much a gap
    # like this moves by luck alone with this many shots.
    luck = sqrt(sum(p * (1 - p) / half["shots"] for p, half in zip((early, late), halves.values())))
    return {**halves, "clear": abs(early - late) > 2 * luck}


def fatigue_report(rows):
    """rows: one per shot (database.get_jump_shots), oldest session first, in shot order."""
    by_session = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)
    # Only sessions with enough measured jumps are used, here and on the page.
    kept = [shots for shots in by_session.values()
            if sum(shot["jump"] is not None for shot in shots) >= MIN_SHOTS]
    if not kept:
        return {"model": None, "sessions": [], "makes": None}

    points = [[(shot["shot_number"] - 1, shot["jump"]) for shot in shots if shot["jump"] is not None]
              for shots in kept]
    enough = len(kept) >= MIN_SESSIONS
    per_shot = slope(points) if enough else None

    sessions = []
    for shots, session_points in zip(kept, points):
        jumps = [y for _, y in session_points]
        before, jump = fmean(x for x, _ in session_points), fmean(jumps)
        # The model's line for this session, from its first shot to its last.
        start = jump - per_shot * before if enough else None
        sessions.append({
            "id": shots[0]["session_id"],
            "original_filename": shots[0]["original_filename"],
            "created_at": shots[0]["created_at"],
            "start": start,
            "end": start + per_shot * (len(shots) - 1) if enough else None,
            # What was measured: the average of the first and of the last three jumps.
            "first": fmean(jumps[:EDGE]),
            "last": fmean(jumps[-EDGE:]),
            "shots": [{"shot_number": shot["shot_number"], "jump": shot["jump"], "result": shot["result"]}
                      for shot in shots if shot["jump"] is not None],
        })

    model = None
    if enough:
        typical_shots = round(fmean(len(shots) for shots in kept))
        start = fmean(session["start"] for session in sessions)
        model = {
            "per_shot": per_shot,
            "sessions": len(kept),
            # In how many sessions the measured jump ended lower than it started.
            "dropped": sum(session["last"] < session["first"] for session in sessions),
            "typical_shots": typical_shots,
            "start": start,
            # How much lower the last jump of a typical session is than the first, in percent.
            "drop_pct": 100 * per_shot * (typical_shots - 1) / start,
            "check": check(points),
        }
    return {"model": model, "sessions": sessions, "makes": early_and_late(kept)}
