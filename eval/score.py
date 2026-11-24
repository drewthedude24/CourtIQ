"""Score the shot detector against hand labels.

Run from the project root:  python -m eval.score
Reads eval/labels.csv (clip,time_s,result), runs the detector on each clip in video/
with the same settings as the website, and prints a results table.
"""
import csv
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = PROJECT_ROOT / "eval" / "labels.csv"
VIDEO_DIR = PROJECT_ROOT / "video"
OUTPUT_DIR = PROJECT_ROOT / "eval" / "output"
# A detection counts as the same shot if it is this close in time to the label.
MATCH_WINDOW_S = 2.0


def match_shots(labels, detections):
    """Pair labeled shots with detections, closest times first, each used once.

    labels and detections are lists of (time_s, result).
    Returns (pairs, missed labels, false detections).
    """
    close = sorted(
        (abs(detection_time - label_time), i, j)
        for i, (label_time, _) in enumerate(labels)
        for j, (detection_time, _) in enumerate(detections)
        if abs(detection_time - label_time) <= MATCH_WINDOW_S
    )
    used_labels, used_detections, pairs = set(), set(), []
    for _, i, j in close:
        if i not in used_labels and j not in used_detections:
            used_labels.add(i)
            used_detections.add(j)
            pairs.append((labels[i], detections[j]))
    pairs.sort()
    missed = [label for i, label in enumerate(labels) if i not in used_labels]
    false = [detection for j, detection in enumerate(detections) if j not in used_detections]
    return pairs, missed, false


def main():
    # Imported here so the tests can use match_shots without a database or models.
    from backend.app import load_vision_processor

    labels = {}
    with LABELS_PATH.open() as f:
        for row in csv.DictReader(f):
            labels.setdefault(row["clip"], []).append((float(row["time_s"]), row["result"].upper()))

    process_vid = load_vision_processor()
    start = time.perf_counter()
    rows = []
    for clip, clip_labels in labels.items():
        print(f"Running the detector on {clip}...")
        events = process_vid(str(VIDEO_DIR / clip), str(OUTPUT_DIR / Path(clip).stem))
        detections = [(event["timestamp_s"], event["result"]) for event in events]
        pairs, missed, false = match_shots(clip_labels, detections)

        right = 0
        for (label_time, label_result), (detection_time, detection_result) in pairs:
            if label_result == detection_result:
                right += 1
            else:
                print(f"  wrong call at {label_time:.1f} s: was {label_result}, detector said {detection_result}")
        for label_time, label_result in missed:
            print(f"  missed shot at {label_time:.1f} s ({label_result})")
        for detection_time, detection_result in false:
            print(f"  false detection at {detection_time:.1f} s ({detection_result})")
        rows.append((clip, len(clip_labels), len(pairs), right, len(missed), len(false)))

    totals = ("Total",) + tuple(sum(row[k] for row in rows) for k in range(1, 6))
    print()
    print("| Clip | Real shots | Found | Make/miss right | Missed | False detections |")
    print("|---|---|---|---|---|---|")
    for row in rows + [totals]:
        print("| " + " | ".join(str(value) for value in row) + " |")
    _, shots, found, right, _, false = totals
    print()
    # max(..., 1) keeps a run with no shots from dividing by zero.
    print(f"Found {found} of {shots} shots ({found / max(shots, 1):.0%}).")
    print(f"Called make/miss right on {right} of {found} found shots ({right / max(found, 1):.0%}).")
    print(f"False detections: {false}.")
    print(f"Fully correct (found and called right): {right} of {shots} ({right / max(shots, 1):.0%}).")
    print(f"Run time: {time.perf_counter() - start:.0f} s.")


if __name__ == "__main__":
    main()
