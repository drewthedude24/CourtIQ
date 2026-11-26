"""Check how steady the shot form numbers are on the labeled clips.

Run from the project root, after a full `python -m eval.score` run:  python -m eval.form
That run saves, for each clip in eval/output/, the detections (frames.jsonl) and the pose
keypoints from the frames before each shot (pose.jsonl). This script recomputes the form
numbers from those files, so a change to vision/shot_form.py can be tried in seconds.

It prints, for each number: on how many shots it was measured, its average, how much it changes
from shot to shot inside one clip (spread), and how much it changes when only the even or only
the odd frames are used (wiggle). It also writes eval/output/<clip>/form_sheet.jpg: each shot's
deepest-bend frame and release frame with the skeleton drawn, for checking by eye.

The first version of this script compared two pose models and several ways of measuring each
number. That comparison is in docs/form-results.md and can be rerun from commit 1822971.
"""
import csv
import json
from pathlib import Path
from statistics import mean, median, stdev

import cv2 as cv

from eval.score import LABELS_PATH, OUTPUT_DIR, VIDEO_DIR, match_shots, replay
from vision.shot_form import FORM_WINDOW_S, NUMBERS, SEEN, measure

BONES = [("shoulder", "elbow"), ("elbow", "wrist"), ("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle")]


def labeled_shots():
    """{clip: [(time the ball reached the rim, true result), ...]} for every labeled shot found."""
    labels = {}
    with LABELS_PATH.open() as f:
        for row in csv.DictReader(f):
            labels.setdefault(row["clip"], []).append((float(row["time_s"]), row["result"].upper()))
    shots = {}
    for clip, clip_labels in labels.items():
        detections = [(event["timestamp_s"], event["result"]) for event in replay(clip)]
        pairs, _, _ = match_shots(clip_labels, detections)
        shots[clip] = [(rim_time_s, result) for (_, result), (rim_time_s, _) in pairs]
    return shots


def pose_frames(clip):
    """The frames the form pass looked at before each shot, ready for measure(), in time order."""
    folder = OUTPUT_DIR / Path(clip).stem
    with (folder / "frames.jsonl").open() as f:
        records = [json.loads(line) for line in f]
    frames = []
    with (folder / "pose.jsonl").open() as f:
        for line in f:
            pose = json.loads(line)
            record = records[pose["frame_index"]]
            frames.append({
                "t": record["timestamp_s"], "balls": pose["balls"], "hoop": pose["hoop"],
                "rim": record["shot_result"]["rim_center"],
                "index": pose["frame_index"], "points": pose["points"], "world": pose["world"],
            })
    return frames


def write_sheet(clip, picks):
    """picks is a list of (frame, lines of text to print on it) in the order they should appear."""
    folder = OUTPUT_DIR / Path(clip).stem
    size = tuple(json.loads((folder / "configuration.json").read_text())["inference_resolution"])
    by_index = {frame["index"]: (frame, label) for frame, label in picks}
    cap = cv.VideoCapture(str(VIDEO_DIR / clip))
    tiles = []
    for index in range(max(by_index) + 1):
        ok, picture = cap.read()
        if not ok:
            break
        if index not in by_index:
            continue
        frame, label = by_index[index]
        picture = cv.resize(picture, size, interpolation=cv.INTER_AREA)
        points = {name: point for name, point in frame["points"].items() if point[2] >= SEEN}
        for side, colour in (("left", (255, 160, 0)), ("right", (0, 220, 255))):
            for start, end in BONES:
                if f"{side}_{start}" in points and f"{side}_{end}" in points:
                    a, b = points[f"{side}_{start}"], points[f"{side}_{end}"]
                    cv.line(picture, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), colour, 4)
        for x, y, width in frame["balls"]:
            cv.circle(picture, (int(x), int(y)), int(width / 2), (0, 255, 0), 2)
        for row, text in enumerate(label):
            cv.putText(picture, text, (12, 40 + 38 * row), cv.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 5)
            cv.putText(picture, text, (12, 40 + 38 * row), cv.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        tiles.append(cv.resize(picture, (360, 640)))
    cap.release()
    blank = tiles[0] * 0
    per_row = 8  # four shots a row, two pictures each
    rows = [tiles[i:i + per_row] for i in range(0, len(tiles), per_row)]
    sheet = cv.vconcat([cv.hconcat(row + [blank] * (per_row - len(row))) for row in rows])
    cv.imwrite(str(folder / "form_sheet.jpg"), sheet)


def report(rows):
    """rows: one per shot, with its clip, true result, and numbers from all, even and odd frames."""
    print(f"\n{len(rows)} shots.\n")
    print("| Number | Shots measured | Average | Spread | Wiggle | Makes | Misses |")
    print("|---|---|---|---|---|---|---|")
    for number in NUMBERS:
        measured = [row for row in rows if row["all"][number] is not None]
        by_clip = {}
        for row in measured:
            by_clip.setdefault(row["clip"], []).append(row["all"][number])
        spread = mean(stdev(values) for values in by_clip.values() if len(values) > 1)
        wiggle = median(
            abs(row["even"][number] - row["odd"][number])
            for row in rows
            if None not in (row["even"][number], row["odd"][number])
        )
        makes, misses = (
            mean(row["all"][number] for row in measured if row["result"] == result)
            for result in ("MAKE", "MISS")
        )
        average = mean(row["all"][number] for row in measured)
        print(f"| {number} | {len(measured)} of {len(rows)} | {average:.2f} | {spread:.2f} "
              f"| {wiggle:.2f} | {makes:.2f} | {misses:.2f} |")


def main():
    rows = []
    for clip, shots in labeled_shots().items():
        frames = pose_frames(clip)
        picks = []
        for rim_time_s, result in shots:
            mine = [frame for frame in frames if rim_time_s - FORM_WINDOW_S <= frame["t"] <= rim_time_s]
            numbers = measure(mine, rim_time_s)
            rows.append({
                "clip": clip, "result": result, "all": numbers,
                "even": measure(mine[0::2], rim_time_s),
                "odd": measure(mine[1::2], rim_time_s),
            })
            if numbers["bend_s"] is not None:
                at = {frame["t"]: frame for frame in mine}
                knee = f"knee {numbers['knee_bend_deg']:.0f}"
                picks.append((at[numbers["bend_s"]], [f"{rim_time_s:.1f}s {result}", "deepest bend", knee]))
                picks.append((at[numbers["release_s"]], ["release", f"{numbers['arm']} arm"]))
        if picks:
            write_sheet(clip, picks)
    report(rows)


if __name__ == "__main__":
    main()
