import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2 as cv
import torch

from yolo_detector import YoloDetector
from predictive_ball_tracker import PredictiveBallTracker
from rim_shot_detector import RimShotDetector
from pose_model import PoseModel
from shot_form import FORM_WINDOW_S, ball_and_hoop, measure
from form_pictures import save_pictures
from video_writer import start_video_writer
import debug_overlay


OFFLINE_INFERENCE_SIZE = (1280, 720)
OFFLINE_YOLO_IMAGE_SIZE = 640
OFFLINE_FOCUS_IMAGE_SIZE = 448
OFFLINE_FULL_FRAME_INTERVAL = 1
OFFLINE_CONFIDENCE_THRESHOLD = 0.12
OFFLINE_VIDEO_CODEC = "h264"

yolo_detector = YoloDetector(
    confidence_threshold=OFFLINE_CONFIDENCE_THRESHOLD,
    image_size=OFFLINE_YOLO_IMAGE_SIZE,
    focus_image_size=OFFLINE_FOCUS_IMAGE_SIZE,
)

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


def lap(timings, stage, start):
    """Add the seconds since `start` to `stage` and return the current time."""
    now = time.perf_counter()
    timings[stage] += now - start
    return now


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

class FormPass:
    """Measure the shooter's form on each shot, in a second thread, while the detector keeps going.

    A shot is only known once the ball reaches the rim, about a second after the release. So the
    video is opened a second time and the pose model runs on just the frames before each shot.
    The one thread takes the shots in turn, so the pose model sees the same frames in the same
    order as if it ran after the detector (it follows the person from frame to frame).
    frame_notes holds each frame's time, balls and hoop. The detector adds to it as it goes.
    """

    def __init__(self, input_path, inference_size, frame_notes, output_path):
        self.input_path = input_path
        self.inference_size = inference_size
        self.frame_notes = frame_notes
        self.output_path = output_path
        self.thread = ThreadPoolExecutor(max_workers=1)
        self.shots = []        # one entry per shot handed to the thread
        self.pose_model = None
        self.next_index = 0    # the next frame the second read of the video will give
        self.pose_frames = []  # the frames pose was run on, with their joints
        self.seconds = 0.0

    def add(self, event):
        """Hand a shot to the thread and return straight away."""
        self.shots.append(self.thread.submit(self.measure_shot, event))

    def measure_shot(self, event):
        start = time.perf_counter()
        if self.pose_model is None:
            self.pose_model = PoseModel()
            self.cap = cv.VideoCapture(self.input_path)
            self.pose_file = (self.output_path / "pose.jsonl").open("w", encoding="utf-8")
        first_s, last_s = event["timestamp_s"] - FORM_WINDOW_S, event["timestamp_s"]
        # Walk forward to the shot. Frames an earlier shot already covered are not read again.
        while self.next_index < len(self.frame_notes):
            index, note = self.next_index, self.frame_notes[self.next_index]
            # grab() skips a frame without turning it into a picture, which is much faster.
            if note["t"] > last_s or not self.cap.grab():
                break
            self.next_index += 1
            if note["t"] < first_s:
                continue
            _, frame = self.cap.retrieve()
            frame = cv.resize(frame, self.inference_size, interpolation=cv.INTER_AREA)
            points, world = self.pose_model.keypoints(frame, note["t"])
            write_json_line(self.pose_file, {"frame_index": index, "points": points, "world": world})
            self.pose_frames.append(dict(note, index=index, points=points, world=world))
        frames = [frame for frame in self.pose_frames if first_s <= frame["t"] <= last_s]
        event["form"] = measure(frames, last_s)
        self.seconds += time.perf_counter() - start

    def finish(self):
        """Wait for every shot. Returns the frames pose was run on, for drawing the form pictures."""
        for shot in self.shots:
            shot.result()  # Also raises here anything that went wrong in the thread.
        self.thread.shutdown()
        if self.pose_model is not None:
            self.cap.release()
            self.pose_file.close()
            self.pose_model.close()
        return self.pose_frames


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

    writer = start_video_writer(output_path / "annotated.mp4", fps, source_width, source_height)

    # Each clip needs fresh state so a previous clip cannot affect the next one.
    ball_tracker = PredictiveBallTracker()
    shot_detector = RimShotDetector()
    frame_index = 0
    shot_events = []
    frame_notes = []  # each frame's time, balls and hoop, kept for the form pass
    form_pass = FormPass(input_path, inference_size, frame_notes, output_path)
    previous_tracking_status = "LOST"
    make_count = 0
    miss_count = 0

    def shot_event(shot_result):
        return {
            "shot_id": shot_result["shot_id"],
            "frame_index": frame_index,
            # When the ball reached the rim, not when the result was decided.
            "timestamp_s": shot_result["shot_time_s"],
            "result": shot_result["result"],
            "reason": shot_result["reason"],
            "rim_center": shot_result["rim_center"],
            "makes": make_count,
            "misses": miss_count,
        }

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

    # Seconds spent in each part of the loop, summed over all frames (saved to timings.json).
    timings = dict.fromkeys(
        ["read_resize", "ball_detector", "tracking_and_shots",
         "drawing", "video_write", "json_write", "form", "form_pictures"],
        0.0,
    )
    job_start = time.perf_counter()

    try:
        with (output_path / "frames.jsonl").open("w", encoding="utf-8") as json_file:
            while True:
                # Ultralytics lowers PyTorch to min(8, cores - 1) threads the first time a
                # model runs. In Docker that was the slowest setting: all cores ran both
                # models 2 to 4x faster. Set every frame, since that first run happens mid-loop.
                # Not on a Mac with a GPU, where all cores made the pose model slower.
                if not torch.backends.mps.is_available():
                    torch.set_num_threads(os.cpu_count())
                t = time.perf_counter()
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
                t = lap(timings, "read_resize", t)

                focus_regions = []
                ball_focus_region = ball_tracker.get_focus_region(
                    inference_frame.shape
                )
                if ball_focus_region is not None:
                    focus_regions.append(ball_focus_region)

                rim_focus_region = shot_detector.get_focus_region(inference_frame.shape)
                if rim_focus_region is not None:
                    focus_regions.append(rim_focus_region)

                run_full_frame = (
                    previous_tracking_status == "LOST"
                    or frame_index % OFFLINE_FULL_FRAME_INTERVAL == 0
                )

                t = lap(timings, "tracking_and_shots", t)  # picking the focus crops

                _, detections, yolo_fps = yolo_detector.detect_frame_with_fps(
                    inference_frame,
                    focus_regions=focus_regions,
                    run_full_frame=run_full_frame,
                )
                t = lap(timings, "ball_detector", t)
                tracked_ball = ball_tracker.update(detections)
                shot_result = shot_detector.update(detections, timestamp_s)
                frame_notes.append(
                    {"t": timestamp_s, **ball_and_hoop(detections), "rim": shot_result["rim_center"]}
                )

                if shot_result["event"]:
                    if shot_result["result"] == "MAKE":
                        make_count += 1
                    elif shot_result["result"] == "MISS":
                        miss_count += 1
                t = lap(timings, "tracking_and_shots", t)

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
                    shot_result["status"],
                    timestamp_s,
                    scale_shot_result(shot_result, scale_x, scale_y),
                )
                debug_overlay.draw_shot_counter(
                    output_frame,
                    make_count,
                    miss_count,
                )
                t = lap(timings, "drawing", t)
                writer.stdin.write(output_frame.data)
                t = lap(timings, "video_write", t)

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
                        "shot_result": shot_result,
                        "score": {
                            "makes": make_count,
                            "misses": miss_count,
                        },
                    },
                )

                if shot_result["event"]:
                    shot_events.append(shot_event(shot_result))
                    form_pass.add(shot_events[-1])
                lap(timings, "json_write", t)

                previous_tracking_status = tracked_ball["tracking_status"]
                frame_index += 1

            # The video can end while a shot is still being watched.
            last_result = shot_detector.finish()
            if last_result:
                make_count += last_result["result"] == "MAKE"
                miss_count += last_result["result"] == "MISS"
                shot_events.append(shot_event(last_result))
                form_pass.add(shot_events[-1])
    finally:
        # Closing its input tells ffmpeg there are no more frames. Then wait for it to finish the file.
        t = time.perf_counter()
        writer.stdin.close()
        video_written = writer.wait() == 0
        lap(timings, "video_write", t)
        cap.release()
    if not video_written:
        raise RuntimeError("ffmpeg could not write annotated.mp4")

    pose_frames = form_pass.finish()
    # The form pass ran next to the detector, so the stages now add up to more than the total.
    timings["form"] = form_pass.seconds
    t = time.perf_counter()
    save_pictures(input_path, inference_size, shot_events, pose_frames, output_path / "form")
    lap(timings, "form_pictures", t)
    with (output_path / "shot_events.jsonl").open("w", encoding="utf-8") as event_file:
        for event in shot_events:
            write_json_line(event_file, event)

    timings = {stage: round(seconds, 2) for stage, seconds in timings.items()}
    timings["total"] = round(time.perf_counter() - job_start, 2)
    timings["frames"] = frame_index
    (output_path / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")

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
