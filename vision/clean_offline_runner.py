"""Create user-facing full-resolution videos with only results and shot counts."""

import json
from pathlib import Path

import cv2 as cv

import debug_overlay
from offline_runner import (
    OFFLINE_CONFIDENCE_THRESHOLD,
    OFFLINE_FOCUS_IMAGE_SIZE,
    OFFLINE_FULL_FRAME_INTERVAL,
    OFFLINE_VIDEO_CODEC,
    OFFLINE_YOLO_IMAGE_SIZE,
    get_inference_size,
    pose_detector,
    serialize,
    write_json_line,
    yolo_detector,
)
from predictive_ball_tracker import PredictiveBallTracker
from shot_detector import ShotDetector
from shot_result_detector import ShotResultDetector


def process_clean_video(input_path, output_folder):
    cap = cv.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = cap.get(cv.CAP_PROP_FPS)
    source_width = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
    source_height = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or source_width <= 0 or source_height <= 0:
        cap.release()
        raise RuntimeError(f"Video has invalid metadata: {input_path}")
    inference_size = get_inference_size(source_width, source_height)

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    writer = cv.VideoWriter(
        str(output_path / "annotated.mp4"),
        cv.VideoWriter_fourcc(*OFFLINE_VIDEO_CODEC),
        fps,
        (source_width, source_height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not create annotated.mp4")

    ball_tracker = PredictiveBallTracker()
    shot_detector = ShotDetector()
    shot_result_detector = ShotResultDetector()
    frame_index = 0
    previous_shot_state = "IDLE"
    previous_tracking_status = "LOST"
    make_count = 0
    miss_count = 0
    shot_events = []

    (output_path / "configuration.json").write_text(
        json.dumps(
            {
                "render_mode": "clean-results-only",
                "inference_resolution": list(inference_size),
                "output_resolution": [source_width, source_height],
                "frame_coordinates": "inference_resolution",
                "full_frame_imgsz": OFFLINE_YOLO_IMAGE_SIZE,
                "focus_crop_imgsz": OFFLINE_FOCUS_IMAGE_SIZE,
                "full_frame_interval": OFFLINE_FULL_FRAME_INTERVAL,
                "confidence_threshold": OFFLINE_CONFIDENCE_THRESHOLD,
                "video_codec": OFFLINE_VIDEO_CODEC,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        with (
            (output_path / "frames.jsonl").open("w", encoding="utf-8") as json_file,
            (output_path / "shot_events.jsonl").open(
                "w", encoding="utf-8"
            ) as event_file,
        ):
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_s = frame_index / fps
                inference_frame = cv.resize(
                    frame,
                    inference_size,
                    interpolation=cv.INTER_AREA,
                )

                focus_regions = []
                ball_focus_region = ball_tracker.get_focus_region(
                    inference_frame.shape
                )
                if ball_focus_region is not None:
                    focus_regions.append(ball_focus_region)

                if previous_shot_state in {"POSSIBLE_SHOT", "RELEASED"}:
                    rim_focus_region = shot_result_detector.get_focus_region(
                        inference_frame.shape
                    )
                    if rim_focus_region is not None:
                        focus_regions.append(rim_focus_region)

                run_full_frame = (
                    previous_tracking_status == "LOST"
                    or frame_index % OFFLINE_FULL_FRAME_INTERVAL == 0
                )
                _, detections, yolo_fps = yolo_detector.detect_frame_with_fps(
                    inference_frame,
                    focus_regions=focus_regions,
                    run_full_frame=run_full_frame,
                )
                people = pose_detector.detect(inference_frame)
                tracked_ball = ball_tracker.update(detections)
                shot_state = shot_detector.update(tracked_ball, people)
                shot_result = shot_result_detector.update(
                    detections,
                    tracked_ball,
                    shot_state,
                    frame_index,
                )

                if shot_result["event"]:
                    if shot_result["result"] == "MAKE":
                        make_count += 1
                    elif shot_result["result"] == "MISS":
                        miss_count += 1

                output_frame = frame.copy()
                debug_overlay.draw_clean_result_overlay(
                    output_frame,
                    shot_result,
                    make_count,
                    miss_count,
                )
                writer.write(output_frame)

                write_json_line(
                    json_file,
                    {
                        "frame_index": frame_index,
                        "timestamp_s": timestamp_s,
                        "yolo_fps": yolo_fps,
                        "full_frame_run": yolo_detector.last_full_frame_run,
                        "requested_focus_regions": [
                            list(region) for region in focus_regions
                        ],
                        "focus_regions": [
                            list(region) for region in yolo_detector.last_focus_regions
                        ],
                        "detections": detections,
                        "ball": serialize(tracked_ball),
                        "shot_state": shot_state,
                        "shot_result": shot_result,
                        "score": {"makes": make_count, "misses": miss_count},
                    },
                )

                if shot_result["event"]:
                    event_record = {
                        "shot_id": shot_result["shot_id"],
                        "frame_index": frame_index,
                        "timestamp_s": timestamp_s,
                        "result": shot_result["result"],
                        "release_frame": shot_result["release_frame"],
                        "reason": shot_result["reason"],
                        "rim_center": shot_result["rim_center"],
                        "provisional_crossing_x": shot_result[
                            "provisional_crossing_x"
                        ],
                        "makes": make_count,
                        "misses": miss_count,
                    }
                    write_json_line(event_file, event_record)
                    shot_events.append(event_record)
                    shot_detector.complete_shot()

                previous_shot_state = shot_state
                previous_tracking_status = tracked_ball["tracking_status"]
                frame_index += 1
    finally:
        writer.release()
        cap.release()

    return shot_events


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    clips = sorted((project_root / "video").glob("*.mov"))
    if not clips:
        print(f"No .mov videos found in {project_root / 'video'}")
    else:
        for clip in clips:
            output_folder = project_root / "output10" / clip.stem
            print(f"Processing {clip} -> {output_folder}")
            events = process_clean_video(str(clip), str(output_folder))
            if events:
                for event in events:
                    print(
                        f"  Shot {event['shot_id']}: {event['result']} "
                        f"at {event['timestamp_s']:.2f}s"
                    )
            else:
                print("  No completed shot was detected")
