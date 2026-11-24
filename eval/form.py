"""Compare ways of measuring shot form on the labeled clips, before any of them goes in the app.

Run from the project root:  python -m eval.form
Needs the detections a full `python -m eval.score` run saved in eval/output/. For each labeled
shot it runs two pose models on the 2.5 seconds before the ball reaches the rim, saves their
keypoints next to those detections, and prints how steady each form number is.

python -m eval.form --replay  skips the video and the pose models: it recomputes the numbers
from the saved keypoints in seconds, for trying changes to vision/shot_form.py.
"""
import csv
import json
import sys
from itertools import combinations
from pathlib import Path
from statistics import correlation, mean, median, stdev

import cv2 as cv

from eval.score import LABELS_PATH, OUTPUT_DIR, PROJECT_ROOT, VIDEO_DIR, match_shots, replay
from vision.shot_form import NUMBERS, SEEN, measure

WINDOW_S = 2.5
SOURCES = ("yolo", "mediapipe")
YOLO_MODEL = PROJECT_ROOT / "yolo26n-pose.pt"
MEDIAPIPE_MODEL = OUTPUT_DIR / "pose_landmarker_heavy.task"
# Both models number their joints in this order: left then right, shoulder down to ankle.
JOINTS = [
    f"{side}_{part}"
    for part in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")
    for side in ("left", "right")
]
YOLO_INDEXES = range(5, 17)
MEDIAPIPE_INDEXES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
# The bar a number must clear to be kept, set before looking at any results.
MIN_COVERAGE = 0.9
MAX_WIGGLE_OF_SPREAD = 0.5
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


def saved_detections(clip):
    """One entry per video frame: its time, the balls seen and the rim line, from the saved run."""
    frames = []
    with (OUTPUT_DIR / Path(clip).stem / "frames.jsonl").open() as f:
        for line in f:
            record = json.loads(line)
            balls = [d for d in record["detections"] if d["class_id"] == 0]
            hoops = [d for d in record["detections"] if d["class_id"] == 1]
            hoop = max(hoops, key=lambda d: d["confidence"]) if hoops else None
            frames.append({
                "t": record["timestamp_s"],
                "balls": [(*d["center"], d["bbox"][2] - d["bbox"][0]) for d in balls],
                # The top edge of the hoop box is the rim line.
                "hoop": (hoop["center"][0], hoop["bbox"][1]) if hoop else None,
            })
    return frames


def yolo_pose():
    from ultralytics import YOLO

    model = YOLO(str(YOLO_MODEL))

    def keypoints(frame, _time_ms):
        result = model.predict(frame, imgsz=640, verbose=False)[0]
        if result.boxes is None or len(result.boxes) == 0:
            return {}, None
        # The clips have one person. With more, the biggest is the one nearest the camera.
        boxes = result.boxes.xyxy
        biggest = int(((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])).argmax())
        xy = result.keypoints.xy[biggest].tolist()
        confidence = result.keypoints.conf[biggest].tolist()
        return {name: [*xy[i], confidence[i]] for name, i in zip(JOINTS, YOLO_INDEXES)}, None

    return keypoints


def mediapipe_pose():
    import mediapipe as mp
    from mediapipe.tasks import python as tasks
    from mediapipe.tasks.python import vision

    landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=tasks.BaseOptions(model_asset_path=str(MEDIAPIPE_MODEL)),
        running_mode=vision.RunningMode.VIDEO,
    ))

    def keypoints(frame, time_ms):
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv.cvtColor(frame, cv.COLOR_BGR2RGB))
        result = landmarker.detect_for_video(image, time_ms)
        if not result.pose_landmarks:
            return {}, None
        height, width = frame.shape[:2]
        flat, world = result.pose_landmarks[0], result.pose_world_landmarks[0]
        points = {
            name: [flat[i].x * width, flat[i].y * height, flat[i].visibility]
            for name, i in zip(JOINTS, MEDIAPIPE_INDEXES)
        }
        return points, {name: [world[i].x, world[i].y, world[i].z] for name, i in zip(JOINTS, MEDIAPIPE_INDEXES)}

    return keypoints


def clip_frames(clip, wanted):
    """Yield (frame index, picture at the detector's size) for the wanted frames of a clip."""
    folder = OUTPUT_DIR / Path(clip).stem
    size = tuple(json.loads((folder / "configuration.json").read_text())["inference_resolution"])
    cap = cv.VideoCapture(str(VIDEO_DIR / clip))
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index in wanted:
            yield index, cv.resize(frame, size, interpolation=cv.INTER_AREA)
        index += 1
    cap.release()


def run_pose(clip, shots, detections):
    """Save both pose models' keypoints for the frames before each shot of one clip."""
    wanted = {
        index: number
        for number, (rim_time_s, _) in enumerate(shots)
        for index, frame in enumerate(detections)
        if rim_time_s - WINDOW_S <= frame["t"] <= rim_time_s
    }
    folder = OUTPUT_DIR / Path(clip).stem
    # A fresh MediaPipe model per clip: it follows the person from frame to frame.
    models = {"yolo": yolo_pose(), "mediapipe": mediapipe_pose()}
    files = {source: (folder / f"pose_{source}.jsonl").open("w") for source in SOURCES}
    for index, frame in clip_frames(clip, wanted):
        for source in SOURCES:
            points, world = models[source](frame, int(detections[index]["t"] * 1000))
            record = {"shot": wanted[index], "frame": index, "points": points, "world": world}
            files[source].write(json.dumps(record) + "\n")
    for file in files.values():
        file.close()


def shot_frames(clip, source, detections):
    """{shot number: frames ready for measure()} from the keypoints saved for one pose model."""
    by_shot = {}
    with (OUTPUT_DIR / Path(clip).stem / f"pose_{source}.jsonl").open() as f:
        for line in f:
            record = json.loads(line)
            frame = dict(detections[record["frame"]], index=record["frame"], points=record["points"])
            if record["world"]:
                frame["world"] = record["world"]
            by_shot.setdefault(record["shot"], []).append(frame)
    return by_shot


def write_sheet(clip, picks):
    """One picture per clip: each shot's deepest-bend frame and release frame with the skeleton.

    picks is a list of (frame, label) in the order they should appear.
    """
    pictures = dict(clip_frames(clip, {frame["index"] for frame, _ in picks}))
    tiles = []
    for frame, label in picks:
        picture = pictures[frame["index"]]
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
    blank = tiles[0] * 0
    per_row = 8  # four shots a row, two pictures each
    rows = [tiles[i:i + per_row] for i in range(0, len(tiles), per_row)]
    sheet = cv.vconcat([cv.hconcat(row + [blank] * (per_row - len(row))) for row in rows])
    cv.imwrite(str(OUTPUT_DIR / Path(clip).stem / "form_sheet.jpg"), sheet)


def report(rows):
    """rows: one per shot and pose model, with the numbers from all, even and odd frames."""
    shots = len(rows) // len(SOURCES)
    passing = []
    print(f"\n{shots} shots. Spread = how much a number changes shot to shot inside one clip.")
    print("Wiggle = how much it changes when only the even or only the odd frames are used.\n")
    print("| Number | Pose model | Shots measured | Average | Spread | Wiggle | Kept |")
    print("|---|---|---|---|---|---|---|")
    for number in NUMBERS:
        for source in SOURCES:
            mine = [row for row in rows if row["source"] == source]
            values = [row["all"][number] for row in mine if row["all"][number] is not None]
            if not values:
                continue
            by_clip = {}
            for row in mine:
                if row["all"][number] is not None:
                    by_clip.setdefault(row["clip"], []).append(row["all"][number])
            spread = mean(stdev(v) for v in by_clip.values() if len(v) > 1)
            wiggles = [
                abs(row["even"][number] - row["odd"][number])
                for row in mine
                if None not in (row["even"][number], row["odd"][number])
            ]
            wiggle = median(wiggles) if wiggles else float("inf")
            kept = len(values) >= MIN_COVERAGE * shots and wiggle < MAX_WIGGLE_OF_SPREAD * spread
            if kept:
                passing.append((number, source))
            print(f"| {number} | {source} | {len(values)} of {shots} | {mean(values):.2f} "
                  f"| {spread:.2f} | {wiggle:.2f} | {'yes' if kept else 'no'} |")

    def column(number, source):
        return {(row["clip"], row["shot"]): row["all"][number] for row in rows if row["source"] == source}

    print("\nAgreement: do two ways of measuring the same thing rise and fall together? (1.0 = perfectly)\n")
    for part in ("knee", "elbow", "arm", "release_height", "jump", "release_time_s", "flight_time_s"):
        columns = [(n, s) for n in NUMBERS if n.startswith(part) for s in SOURCES]
        for first, second in combinations(columns, 2):
            a, b = column(*first), column(*second)
            both = [key for key in a if a[key] is not None and b[key] is not None]
            if len(both) >= 10:
                r = correlation([a[key] for key in both], [b[key] for key in both])
                print(f"- {first[0]} ({first[1]}) vs {second[0]} ({second[1]}): {r:+.2f} on {len(both)} shots")

    print("\nMakes vs misses, for the numbers that were kept. Small sample: a hint, not a finding.\n")
    print("| Number | Pose model | Makes | Misses |")
    print("|---|---|---|---|")
    for number, source in passing:
        averages = []
        for result in ("MAKE", "MISS"):
            values = [
                row["all"][number] for row in rows
                if row["source"] == source and row["result"] == result and row["all"][number] is not None
            ]
            averages.append(f"{mean(values):.2f} ({len(values)} shots)")
        print(f"| {number} | {source} | {averages[0]} | {averages[1]} |")


def main():
    replaying = "--replay" in sys.argv
    rows = []
    for clip, shots in labeled_shots().items():
        detections = saved_detections(clip)
        if not replaying:
            print(f"Running the pose models on {clip}...")
            run_pose(clip, shots, detections)
        picks = []
        for source in SOURCES:
            by_shot = shot_frames(clip, source, detections)
            for number, (rim_time_s, result) in enumerate(shots):
                frames = by_shot[number]
                numbers = measure(frames, rim_time_s)
                rows.append({
                    "clip": clip, "shot": number, "source": source, "result": result,
                    "all": numbers,
                    "even": measure(frames[0::2], rim_time_s),
                    "odd": measure(frames[1::2], rim_time_s),
                })
                if source == "yolo" and numbers["bend_s"] is not None:
                    at = {frame["t"]: frame for frame in frames}
                    knee = f"knee {numbers['knee_vertical']:.0f}"
                    picks.append((at[numbers["bend_s"]], [f"{rim_time_s:.1f}s {result}", "deepest bend", knee]))
                    picks.append((at[numbers["release_s"]], ["release", f"{numbers['arm']} arm"]))
        if not replaying and picks:
            write_sheet(clip, picks)
    report(rows)


if __name__ == "__main__":
    main()
