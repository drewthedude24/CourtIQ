import json
from pathlib import Path

import cv2 as cv

from yolo_detector import YoloDetector
from pose_detector import PoseDetector
from predictive_ball_tracker import PredictiveBallTracker
from shot_detector import ShotDetector
from shot_result_detector import ShotResultDetector
import debug_overlay


OFFLINE_INFERENCE_SIZE = (1280, 720)
OFFLINE_YOLO_IMAGE_SIZE = 960
OFFLINE_FOCUS_IMAGE_SIZE = 640
OFFLINE_FULL_FRAME_INTERVAL = 1
OFFLINE_CONFIDENCE_THRESHOLD = 0.12
OFFLINE_VIDEO_CODEC = "mp4v"

yolo_detector = YoloDetector(
    confidence_threshold=OFFLINE_CONFIDENCE_THRESHOLD,
    image_size=OFFLINE_YOLO_IMAGE_SIZE,
    focus_image_size=OFFLINE_FOCUS_IMAGE_SIZE,
)
pose_detector = PoseDetector()

# because my history of the ball tracking is deque structure, needs to be converted to list first
def serialize(tracked_ball):
    """Convert tracker data into values that JSON can write to disk."""
    center = tracked_ball["center"]
    velocity_x, velocity_y = tracked_ball["velocity"]

    serialized = {
        "detected": tracked_ball["detected"],
        "center": list(center) if center is not None else None,
        "velocity": [velocity_x, velocity_y],
        "history": [list(point) for point in tracked_ball["history"]],
        "missing_frames": tracked_ball["missing_frames"],
    }
    for key in (
        "tracking_status",
        "predicted_center",
        "measurement_center",
        "selected_confidence",
        "selected_source",
        "candidate_count",
        "association_distance",
        "gate_distance",
        "prediction_uncertainty",
        "kalman_acceleration",
    ):
        value = tracked_ball.get(key)
        if (
            key.endswith("center") or key == "kalman_acceleration"
        ) and value is not None:
            value = list(value)
        serialized[key] = value
    return serialized

# write each record into jsonl file for future sql implementation
def write_json_line(json_file, frame_record):
    json.dump(frame_record, json_file)
    json_file.write("\n")


def get_inference_size(source_width, source_height):
    """Fit the source into the configured bounds without stretching it."""
    max_width, max_height = OFFLINE_INFERENCE_SIZE
    source_is_portrait = source_height > source_width
    bounds_are_portrait = max_height > max_width
    if source_is_portrait != bounds_are_portrait:
        max_width, max_height = max_height, max_width

    scale = min(max_width / source_width, max_height / source_height)
    inference_width = max(2, int(round(source_width * scale / 2.0)) * 2)
    inference_height = max(2, int(round(source_height * scale / 2.0)) * 2)
    return inference_width, inference_height


def scale_point(point, scale_x, scale_y):
    if point is None:
        return None
    return int(round(point[0] * scale_x)), int(round(point[1] * scale_y))


def scale_bbox(bbox, scale_x, scale_y):
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 * scale_x)),
        int(round(y1 * scale_y)),
        int(round(x2 * scale_x)),
        int(round(y2 * scale_y)),
    )


def scale_tracked_ball(tracked_ball, scale_x, scale_y):
    """Copy tracker output into source-video coordinates for drawing only."""
    scaled = dict(tracked_ball)
    for key in ("center", "predicted_center", "measurement_center"):
        scaled[key] = scale_point(tracked_ball.get(key), scale_x, scale_y)
    scaled["history"] = [
        scale_point(point, scale_x, scale_y) for point in tracked_ball["history"]
    ]
    velocity_x, velocity_y = tracked_ball["velocity"]
    scaled["velocity"] = velocity_x * scale_x, velocity_y * scale_y
    acceleration_x, acceleration_y = tracked_ball.get(
        "kalman_acceleration",
        (0.0, 0.0),
    )
    scaled["kalman_acceleration"] = (
        acceleration_x * scale_x,
        acceleration_y * scale_y,
    )
    uncertainty = tracked_ball.get("prediction_uncertainty")
    if uncertainty is not None:
        scaled["prediction_uncertainty"] = uncertainty * (
            (scale_x + scale_y) / 2.0
        )
    return scaled


def scale_shot_result(shot_result, scale_x, scale_y):
    """Copy rim geometry into source-video coordinates for drawing only."""
    scaled = dict(shot_result)
    scaled["rim_center"] = scale_point(
        shot_result.get("rim_center"),
        scale_x,
        scale_y,
    )
    scoring_window = shot_result.get("scoring_window")
    if scoring_window is not None:
        scaled["scoring_window"] = [
            int(round(scoring_window[0] * scale_x)),
            int(round(scoring_window[1] * scale_x)),
        ]
    hoop_bbox = shot_result.get("hoop_bbox")
    if hoop_bbox is not None:
        scaled["hoop_bbox"] = scale_bbox(hoop_bbox, scale_x, scale_y)
    return scaled


def draw_source_detections(frame, detections, focus_regions, scale_x, scale_y):
    """Draw inference-space detections on the original-resolution frame."""
    for region in focus_regions:
        x1, y1, x2, y2 = scale_bbox(region, scale_x, scale_y)
        cv.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)

    for detection in detections:
        x1, y1, x2, y2 = scale_bbox(
            detection["bbox"],
            scale_x,
            scale_y,
        )
        source = detection.get("source", "full")
        color = (255, 0, 255) if source == "focus" else (255, 200, 0)
        label = "basketball" if detection["class_id"] == 0 else "hoop"
        cv.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        cv.putText(
            frame,
            f"{source} {label} {detection['confidence']:.2f}",
            (x1, max(25, y1 - 10)),
            cv.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv.LINE_AA,
        )

# main loop for each clip
def process_vid(input_path, output_folder):
    cap = cv.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = cap.get(cv.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise RuntimeError(f"Video has no valid FPS value: {input_path}")

    source_width = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
    source_height = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))
    if source_width <= 0 or source_height <= 0:
        cap.release()
        raise RuntimeError(f"Video has no valid frame size: {input_path}")
    inference_size = get_inference_size(source_width, source_height)

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    fourcc = cv.VideoWriter_fourcc(*OFFLINE_VIDEO_CODEC)
    writer = cv.VideoWriter(
        str(output_path / "annotated.mp4"),
        fourcc,
        fps,
        (source_width, source_height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not create annotated.mp4")

    # Each clip needs fresh state so a previous clip cannot affect the next one.
    ball_tracker = PredictiveBallTracker()
    shot_detector = ShotDetector()
    shot_result_detector = ShotResultDetector()
    frame_index = 0
    shot_events = []
    previous_shot_state = "IDLE"
    previous_tracking_status = "LOST"
    make_count = 0
    miss_count = 0

    (output_path / "configuration.json").write_text(
        json.dumps(
            {
                "inference_resolution": list(inference_size),
                "output_resolution": [source_width, source_height],
                "frame_coordinates": "inference_resolution",
                "full_frame_imgsz": OFFLINE_YOLO_IMAGE_SIZE,
                "focus_crop_imgsz": OFFLINE_FOCUS_IMAGE_SIZE,
                "full_frame_interval": OFFLINE_FULL_FRAME_INTERVAL,
                "confidence_threshold": OFFLINE_CONFIDENCE_THRESHOLD,
                "video_codec": OFFLINE_VIDEO_CODEC,
                "tracker": "constant-velocity Kalman filter with acceleration process noise",
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

                # This is source-video time, not how long processing takes.
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

                scale_x = frame.shape[1] / inference_size[0]
                scale_y = frame.shape[0] / inference_size[1]
                output_frame = frame.copy()
                draw_source_detections(
                    output_frame,
                    detections,
                    yolo_detector.last_focus_regions,
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
                        "score": {
                            "makes": make_count,
                            "misses": miss_count,
                        },
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
    # project root is two levels up from this file: /<repo>/vision/offline_runner.py -> repo root
    project_root = Path(__file__).resolve().parents[1]
    video_dir = project_root / "video"

    clips = sorted(video_dir.glob("*.mov"))
    if not clips:
        print(f"No .mov videos found in {video_dir}")
    else:
        for clip in clips:
            out_folder = project_root / "output9" / clip.stem
            print(f"Processing {clip} -> {out_folder}")
            events = process_vid(str(clip), str(out_folder))
            if events:
                for event in events:
                    print(
                        f"  Shot {event['shot_id']}: {event['result']} "
                        f"at {event['timestamp_s']:.2f}s ({event['reason']})"
                    )
            else:
                print("  No completed shot was detected")
