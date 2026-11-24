"""Process all test clips into one cumulative full-resolution debug video."""

import json
from pathlib import Path

import cv2 as cv

import debug_overlay
from offline_runner import (
    draw_source_detections,
    pose_detector,
    scale_shot_result,
    scale_tracked_ball,
    serialize,
    write_json_line,
)
from predictive_ball_tracker import PredictiveBallTracker
from shot_detector import ShotDetector
from shot_result_detector import ShotResultDetector
from yolo_detector import YoloDetector


STITCHED_INFERENCE_SIZE = (1280, 720)
STITCHED_FULL_IMAGE_SIZE = 960
STITCHED_FOCUS_IMAGE_SIZE = 640
STITCHED_FULL_FRAME_INTERVAL = 3
STITCHED_CONFIDENCE_THRESHOLD = 0.12

stitched_yolo_detector = YoloDetector(
    confidence_threshold=STITCHED_CONFIDENCE_THRESHOLD,
    image_size=STITCHED_FULL_IMAGE_SIZE,
    focus_image_size=STITCHED_FOCUS_IMAGE_SIZE,
)


def read_video_metadata(path):
    cap = cv.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    metadata = {
        "width": int(cap.get(cv.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv.CAP_PROP_FPS),
        "frames": int(cap.get(cv.CAP_PROP_FRAME_COUNT)),
    }
    cap.release()
    if metadata["width"] <= 0 or metadata["height"] <= 0 or metadata["fps"] <= 0:
        raise RuntimeError(f"Video has invalid metadata: {path}")
    return metadata


def process_stitched_videos(input_paths, output_folder):
    if not input_paths:
        raise ValueError("At least one input video is required")

    input_paths = [Path(path) for path in input_paths]
    metadata = [read_video_metadata(path) for path in input_paths]
    output_width = metadata[0]["width"]
    output_height = metadata[0]["height"]
    output_fps = metadata[0]["fps"]
    if any(
        item["width"] != output_width or item["height"] != output_height
        for item in metadata
    ):
        raise RuntimeError("All stitched clips must have the same resolution")

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    writer = cv.VideoWriter(
        str(output_path / "annotated.mp4"),
        cv.VideoWriter_fourcc(*"mp4v"),
        output_fps,
        (output_width, output_height),
    )
    if not writer.isOpened():
        raise RuntimeError("Could not create stitched annotated.mp4")

    (output_path / "configuration.json").write_text(
        json.dumps(
            {
                "render_mode": "stitched-debug",
                "clips": [path.name for path in input_paths],
                "clip_metadata": metadata,
                "inference_resolution": list(STITCHED_INFERENCE_SIZE),
                "output_resolution": [output_width, output_height],
                "frame_coordinates": "inference_resolution",
                "full_frame_imgsz": STITCHED_FULL_IMAGE_SIZE,
                "focus_crop_imgsz": STITCHED_FOCUS_IMAGE_SIZE,
                "full_frame_interval": STITCHED_FULL_FRAME_INTERVAL,
                "confidence_threshold": STITCHED_CONFIDENCE_THRESHOLD,
                "tracker": "constant-velocity Kalman filter with acceleration process noise",
                "resets_tracking_between_clips": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    global_frame_index = 0
    global_shot_id = 0
    make_count = 0
    miss_count = 0
    shot_events = []

    try:
        with (
            (output_path / "frames.jsonl").open("w", encoding="utf-8") as json_file,
            (output_path / "shot_events.jsonl").open(
                "w", encoding="utf-8"
            ) as event_file,
        ):
            for clip_path in input_paths:
                cap = cv.VideoCapture(str(clip_path))
                if not cap.isOpened():
                    raise RuntimeError(f"Could not open video: {clip_path}")

                # Reset motion state at a hard edit while preserving session totals.
                ball_tracker = PredictiveBallTracker()
                shot_detector = ShotDetector()
                shot_result_detector = ShotResultDetector()
                previous_shot_state = "IDLE"
                previous_tracking_status = "LOST"
                clip_frame_index = 0

                try:
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break

                        timestamp_s = global_frame_index / output_fps
                        inference_frame = cv.resize(
                            frame,
                            STITCHED_INFERENCE_SIZE,
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
                            or clip_frame_index % STITCHED_FULL_FRAME_INTERVAL == 0
                        )
                        _, detections, yolo_fps = (
                            stitched_yolo_detector.detect_frame_with_fps(
                                inference_frame,
                                focus_regions=focus_regions,
                                run_full_frame=run_full_frame,
                            )
                        )
                        people = pose_detector.detect(inference_frame)
                        tracked_ball = ball_tracker.update(detections)
                        shot_state = shot_detector.update(tracked_ball, people)
                        shot_result = shot_result_detector.update(
                            detections,
                            tracked_ball,
                            shot_state,
                            global_frame_index,
                        )

                        if shot_result["event"]:
                            global_shot_id += 1
                            if shot_result["result"] == "MAKE":
                                make_count += 1
                            elif shot_result["result"] == "MISS":
                                miss_count += 1

                        scale_x = frame.shape[1] / STITCHED_INFERENCE_SIZE[0]
                        scale_y = frame.shape[0] / STITCHED_INFERENCE_SIZE[1]
                        output_frame = frame.copy()
                        draw_source_detections(
                            output_frame,
                            detections,
                            stitched_yolo_detector.last_focus_regions,
                            scale_x,
                            scale_y,
                        )
                        debug_overlay.draw_debug_overlay(
                            output_frame,
                            scale_tracked_ball(tracked_ball, scale_x, scale_y),
                            shot_state,
                            timestamp_s,
                            scale_shot_result(shot_result, scale_x, scale_y),
                        )
                        debug_overlay.draw_shot_counter(
                            output_frame,
                            make_count,
                            miss_count,
                        )
                        writer.write(output_frame)

                        write_json_line(
                            json_file,
                            {
                                "frame_index": global_frame_index,
                                "clip": clip_path.name,
                                "clip_frame_index": clip_frame_index,
                                "timestamp_s": timestamp_s,
                                "yolo_fps": yolo_fps,
                                "full_frame_run": stitched_yolo_detector.last_full_frame_run,
                                "requested_focus_regions": [
                                    list(region) for region in focus_regions
                                ],
                                "focus_regions": [
                                    list(region)
                                    for region in stitched_yolo_detector.last_focus_regions
                                ],
                                "detections": detections,
                                "ball": serialize(tracked_ball),
                                "shot_state": shot_state,
                                "shot_result": shot_result,
                                "score": {
                                    "makes": make_count,
                                    "misses": miss_count,
                                },
                            },
                        )

                        if shot_result["event"]:
                            event_record = {
                                "shot_id": global_shot_id,
                                "clip": clip_path.name,
                                "frame_index": global_frame_index,
                                "clip_frame_index": clip_frame_index,
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
                        global_frame_index += 1
                        clip_frame_index += 1
                finally:
                    cap.release()
    finally:
        writer.release()

    return shot_events


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    clips = sorted((project_root / "video").glob("*.mov"))
    if not clips:
        print(f"No .mov videos found in {project_root / 'video'}")
    else:
        output_folder = project_root / "outputunique2"
        print(f"Stitching {len(clips)} clips -> {output_folder}")
        events = process_stitched_videos(clips, output_folder)
        for event in events:
            print(
                f"  Shot {event['shot_id']}: {event['result']} "
                f"in {event['clip']} at {event['timestamp_s']:.2f}s"
            )
