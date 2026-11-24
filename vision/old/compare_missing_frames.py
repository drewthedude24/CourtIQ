import json
from pathlib import Path

import cv2 as cv

import debug_overlay
from offline_runner import (
    OFFLINE_INFERENCE_SIZE,
    pose_detector,
    serialize,
    write_json_line,
    yolo_detector,
)
from predictive_ball_tracker import PredictiveBallTracker
from shot_detector import ShotDetector


TRACKER_CONFIGS = {
    "prediction6_missing18": {
        "max_prediction_frames": 6,
        "max_missing_frames": 18,
    },
    "prediction10_missing18": {
        "max_prediction_frames": 10,
        "max_missing_frames": 18,
    },
    "prediction6_missing30": {
        "max_prediction_frames": 6,
        "max_missing_frames": 30,
    },
    "prediction10_missing30": {
        "max_prediction_frames": 10,
        "max_missing_frames": 30,
    },
}


def process_comparison(input_path, output_root):
    cap = cv.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = cap.get(cv.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise RuntimeError(f"Video has no valid FPS value: {input_path}")

    clip_name = Path(input_path).stem
    output_root = Path(output_root)
    trackers = {
        name: PredictiveBallTracker(**settings)
        for name, settings in TRACKER_CONFIGS.items()
    }
    shot_detectors = {name: ShotDetector() for name in TRACKER_CONFIGS}
    writers = {}
    json_files = {}
    fourcc = cv.VideoWriter_fourcc(*"mp4v")

    try:
        for name, settings in TRACKER_CONFIGS.items():
            clip_output = output_root / name / clip_name
            clip_output.mkdir(parents=True, exist_ok=True)
            (clip_output / "configuration.json").write_text(
                json.dumps(settings, indent=2),
                encoding="utf-8",
            )

            writer = cv.VideoWriter(
                str(clip_output / "annotated.mp4"),
                fourcc,
                fps,
                OFFLINE_INFERENCE_SIZE,
            )
            if not writer.isOpened():
                raise RuntimeError(f"Could not create video for {name}/{clip_name}")
            writers[name] = writer
            json_files[name] = (clip_output / "frames.jsonl").open(
                "w",
                encoding="utf-8",
            )

        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_s = frame_index / fps
            inference_frame = cv.resize(
                frame,
                OFFLINE_INFERENCE_SIZE,
                interpolation=cv.INTER_AREA,
            )
            yolo_frame, detections, yolo_fps = yolo_detector.detect_frame_with_fps(
                inference_frame
            )
            people = pose_detector.detect(inference_frame)

            for name in TRACKER_CONFIGS:
                tracked_ball = trackers[name].update(detections)
                shot_state = shot_detectors[name].update(tracked_ball, people)
                comparison_frame = yolo_frame.copy()
                debug_overlay.draw_debug_overlay(
                    comparison_frame,
                    tracked_ball,
                    shot_state,
                    timestamp_s,
                )
                cv.putText(
                    comparison_frame,
                    name,
                    (20, 220),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 255),
                    2,
                    cv.LINE_AA,
                )
                writers[name].write(comparison_frame)
                write_json_line(
                    json_files[name],
                    {
                        "frame_index": frame_index,
                        "timestamp_s": timestamp_s,
                        "yolo_fps": yolo_fps,
                        "detections": detections,
                        "ball": serialize(tracked_ball),
                        "shot_state": shot_state,
                    },
                )

            frame_index += 1
    finally:
        cap.release()
        for writer in writers.values():
            writer.release()
        for json_file in json_files.values():
            json_file.close()


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    video_dir = project_root / "video"
    output_root = project_root / "output3"
    clips = sorted(video_dir.glob("*.mov"))

    if not clips:
        print(f"No .mov videos found in {video_dir}")
    else:
        for clip in clips:
            print(f"Comparing tracker settings on {clip.name}")
            process_comparison(str(clip), output_root)
