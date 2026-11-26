import json
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2 as cv
import torch

from yolo_detector import YoloDetector
from ball_path import LAG, BallPath
from rim_shot_detector import WATCH_S, RimShotDetector
from pose_model import PoseModel
from shot_form import FORM_WINDOW_S, IN_THE_AIR_S, ball_and_hoop, ball_in_hand, measure
from form_pictures import save_pictures
from video_reader import VideoReader
from video_writer import start_video_writer
import overlay


OFFLINE_INFERENCE_SIZE = (1280, 720)
# The annotated video is saved smaller than the detector's picture: it encodes faster and
# still fills a phone screen.
OFFLINE_VIDEO_SIZE = (960, 540)
OFFLINE_YOLO_IMAGE_SIZE = 640
OFFLINE_FOCUS_IMAGE_SIZE = 448
OFFLINE_CONFIDENCE_THRESHOLD = 0.12
# While no shot is on its way, the detector only looks at every 4th frame. ball_path.py
# works out where the ball was on the frames in between.
DETECT_EVERY = 4
OFFLINE_VIDEO_CODEC = "h264"

yolo_detector = YoloDetector(
    confidence_threshold=OFFLINE_CONFIDENCE_THRESHOLD,
    image_size=OFFLINE_YOLO_IMAGE_SIZE,
    focus_image_size=OFFLINE_FOCUS_IMAGE_SIZE,
)

# write each record into jsonl file for future sql implementation
def write_json_line(json_file, frame_record):
    json.dump(frame_record, json_file)
    json_file.write("\n")


def lap(timings, stage, start):
    """Add the seconds since `start` to `stage` and return the current time."""
    now = time.perf_counter()
    timings[stage] += now - start
    return now


def get_inference_size(source_width, source_height, bounds=None):
    """Fit the source into the bounds (the detector's size if none are given) without stretching it."""
    max_width, max_height = bounds or OFFLINE_INFERENCE_SIZE
    source_is_portrait = source_height > source_width
    bounds_are_portrait = max_height > max_width
    if source_is_portrait != bounds_are_portrait:
        max_width, max_height = max_height, max_width

    scale = min(max_width / source_width, max_height / source_height)
    inference_width = max(2, int(round(source_width * scale / 2.0)) * 2)
    inference_height = max(2, int(round(source_height * scale / 2.0)) * 2)
    return inference_width, inference_height


class FormPass:
    """Measure the shooter's form on each shot, in a second thread, while the detector keeps going.

    A shot is only known once the ball reaches the rim, about a second after the release. So the
    main loop keeps the last few seconds of frames in memory, and when a shot is found it hands
    over the frames before it. The pose model runs on just those.
    The one thread takes the shots in turn, so the pose model sees the frames in time order
    (it follows the person from frame to frame).
    frame_notes holds each frame's time, balls and hoop. The detector adds to it as it goes.

    The form numbers need the ball on every frame up to the release, so this pass also runs
    the ball detector on the frames the main loop skipped. Once the ball is in the air the
    shooter's part is over, and the rest of the frames are not looked at.
    """

    def __init__(self, video, frame_notes, output_path):
        self.video = video     # only used to turn a kept frame into a picture
        self.frame_notes = frame_notes
        self.output_path = output_path
        self.thread = ThreadPoolExecutor(max_workers=1)
        self.shots = []        # one entry per shot handed to the thread
        self.pose_model = None
        self.next_index = 0    # frames before this one were already looked at for an earlier shot
        self.pose_frames = []  # the frames before each shot, with their joints
        self.seconds = 0.0

    def add(self, event, recent_frames):
        """Hand a shot to the thread, with the frames before it. recent_frames is the main
        loop's memory: (frame index, frame as read from the video), oldest first."""
        # A waiting shot holds its frames in memory (about 100 MB), so at most one may wait.
        if len(self.shots) >= 2:
            self.shots[-2].result()
        first_s, last_s = event["timestamp_s"] - FORM_WINDOW_S, event["timestamp_s"]
        frames = [
            (index, yuv) for index, yuv in recent_frames
            if first_s <= self.frame_notes[index]["t"] <= last_s
        ]
        shot_number = len(self.shots) + 1
        self.shots.append(self.thread.submit(self.measure_shot, event, shot_number, frames))

    def measure_shot(self, event, shot_number, frames):
        start = time.perf_counter()
        if self.pose_model is None:
            self.pose_model = PoseModel()
            self.pose_file = (self.output_path / "pose.jsonl").open("w", encoding="utf-8")
        first_s, last_s = event["timestamp_s"] - FORM_WINDOW_S, event["timestamp_s"]
        last_held_s, in_the_air = first_s, False
        for index, yuv in frames:
            if index < self.next_index:
                continue
            self.next_index = index + 1
            note = self.frame_notes[index]
            points, world = {}, {}
            if not in_the_air:
                frame = self.video.picture(yuv)
                if not note["detected"]:
                    note.update(ball_and_hoop(yolo_detector.detect_full_frame(frame)))
                points, world = self.pose_model.keypoints(frame, note["t"])
            self.pose_frames.append(dict(note, index=index, points=points, world=world))
            # The balls and hoop are saved too: on a frame the main loop skipped they are only known here.
            write_json_line(self.pose_file, {
                "frame_index": index, "points": points, "world": world,
                "balls": note["balls"], "hoop": note["hoop"],
            })
            if ball_in_hand(self.pose_frames[-1]):
                last_held_s = note["t"]
            # The ball is above the rim line and has been out of the hands for a moment.
            in_the_air = in_the_air or (
                note["t"] - last_held_s > IN_THE_AIR_S
                and note["rim"] is not None
                and any(y < note["rim"][1] for _, y, _ in note["balls"])
            )
        measured = [frame for frame in self.pose_frames if first_s <= frame["t"] <= last_s]
        event["form"] = measure(measured, last_s)
        # The pictures of where each number was read, drawn from the frames still in memory.
        read_at = set(event["form"].get("seen_at", {}).values())
        images = {
            index: self.video.picture(yuv) for index, yuv in frames
            if self.frame_notes[index]["t"] in read_at
        }
        save_pictures(shot_number, event["form"], measured, images, self.output_path / "form")
        self.seconds += time.perf_counter() - start

    def finish(self, on_progress):
        """Wait for every shot."""
        for done, shot in enumerate(self.shots, start=1):
            shot.result()  # Also raises here anything that went wrong in the thread.
            on_progress("form", done, len(self.shots))
        self.thread.shutdown()
        if self.pose_model is not None:
            self.pose_file.close()
            self.pose_model.close()


# main loop for each clip
def process_vid(input_path, output_folder, on_progress=lambda stage, done, total: None):
    """Find the shots in a video. on_progress(stage, done, total) is called as the work moves
    along: stage "detect" counts video frames, then stage "form" counts shots. The form pass
    runs next to the detector, so by then most shots are already measured."""
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
    frame_count = int(cap.get(cv.CAP_PROP_FRAME_COUNT))
    video_size = get_inference_size(source_width, source_height, OFFLINE_VIDEO_SIZE)
    # OpenCV was only asked about the video. The frames come from ffmpeg, which is faster,
    # already shrunk to the detector's size.
    cap.release()
    video = VideoReader(input_path, *inference_size)

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    writer = start_video_writer(output_path / "annotated.mp4", fps, *video_size)

    # Each clip needs fresh state so a previous clip cannot affect the next one.
    ball_path = BallPath(fps)
    shot_detector = RimShotDetector()
    frame_index = 0
    shot_events = []
    frame_notes = []  # each frame's time, balls and hoop, kept for the form pass
    form_pass = FormPass(video, frame_notes, output_path)
    # The newest frames, kept as ffmpeg handed them over, for the form pass. A shot is decided
    # at most WATCH_S after the ball reaches the rim, and its form is read on the FORM_WINDOW_S before.
    recent_frames = deque(maxlen=round(fps * (FORM_WINDOW_S + WATCH_S + 0.5)))
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
                "output_resolution": list(video_size),
                "frame_coordinates": "inference_resolution",
                "full_frame_imgsz": OFFLINE_YOLO_IMAGE_SIZE,
                "focus_crop_imgsz": OFFLINE_FOCUS_IMAGE_SIZE,
                "detect_every": DETECT_EVERY,
                "confidence_threshold": OFFLINE_CONFIDENCE_THRESHOLD,
                "video_codec": OFFLINE_VIDEO_CODEC,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Seconds spent in each part of the loop, summed over all frames (saved to timings.json).
    timings = dict.fromkeys(
        ["read_resize", "ball_detector", "tracking_and_shots",
         "drawing", "video_write", "json_write", "form"],
        0.0,
    )
    job_start = time.perf_counter()

    # A helper thread works one frame ahead of the loop below: it reads the next frame and,
    # when asked to, runs the full-frame ball detector on it. Neither needs anything from the
    # frame before. The zoomed-in rim crop does (it follows the rim), so it stays in the loop.
    ahead_timings = {"read_resize": 0.0, "ball_detector": 0.0}

    def read_frame(detect):
        """The next frame and its full-frame detections (None when `detect` is False).
        None at the end of the video."""
        t = time.perf_counter()
        yuv = video.read()
        if yuv is None:
            return None
        frame = video.picture(yuv)
        t = lap(ahead_timings, "read_resize", t)
        full_detections = yolo_detector.detect_full_frame(frame) if detect else None
        lap(ahead_timings, "ball_detector", t)
        return yuv, frame, full_detections

    # Frames wait here for LAG frames before they are drawn on, so the ball's place on a
    # frame the detector skipped can be worked out from the detections on both sides of it.
    waiting = deque()

    def finish_frame(output_frame, record):
        """Draw on a frame, send it to the video and save its line of frames.jsonl."""
        t = time.perf_counter()
        shot_result = record["shot_result"]
        ball = ball_path.ball(record["frame_index"])
        rim = shot_result["rim_center"]
        # A shot is in the air while the ball is above the rim line, and until its result is in.
        in_flight = shot_result["status"] == "TRACKING" or bool(ball and rim and ball[1] < rim[1])
        overlay.draw(
            output_frame, ball, ball_path.trail(record["frame_index"], ball, in_flight),
            shot_result, record["score"]["makes"], record["score"]["misses"],
            scale=video_size[0] / inference_size[0],
        )
        t = lap(timings, "drawing", t)
        writer.stdin.write(output_frame.data)
        t = lap(timings, "video_write", t)
        write_json_line(json_file, {**record, "ball": ball and [round(value, 1) for value in ball]})
        lap(timings, "json_write", t)

    reader = ThreadPoolExecutor(max_workers=1)
    next_frames = reader.submit(read_frame, True)

    try:
        with (output_path / "frames.jsonl").open("w", encoding="utf-8") as json_file:
            while True:
                # Ultralytics lowers PyTorch to min(8, cores - 1) threads the first time a
                # model runs. In Docker that was the slowest setting: all cores ran both
                # models 2 to 4x faster. Set every frame, since that first run happens mid-loop.
                # Not on a Mac with a GPU, where all cores made the pose model slower.
                if not torch.backends.mps.is_available():
                    torch.set_num_threads(os.cpu_count())
                frames = next_frames.result()
                if frames is None:
                    break
                # The detector looks at every DETECT_EVERY-th frame, and at every frame while a
                # shot is on its way to the rim. The helper has to be told one frame early.
                next_frames = reader.submit(
                    read_frame,
                    (frame_index + 1) % DETECT_EVERY == 0 or shot_detector.rim_crop_wanted,
                )
                yuv, frame, full_detections = frames
                recent_frames.append((frame_index, yuv))

                # This is source-video time, not how long processing takes.
                timestamp_s = frame_index / fps
                t = time.perf_counter()

                # On a frame the detector skipped there are no detections: the shot detector
                # only keeps time, and ball_path.py fills in the ball later.
                detected = full_detections is not None
                detections, yolo_fps = [], 0
                if detected:
                    _, detections, yolo_fps = yolo_detector.detect_frame_with_fps(
                        frame,
                        focus_regions=[shot_detector.get_focus_region(frame.shape)],
                        full_detections=full_detections,
                    )
                t = lap(timings, "ball_detector", t)
                if detected:
                    ball_path.add(frame_index, detections)
                shot_result = shot_detector.update(detections, timestamp_s)
                frame_notes.append({
                    "t": timestamp_s, **ball_and_hoop(detections),
                    "rim": shot_result["rim_center"], "detected": detected,
                })

                if shot_result["event"]:
                    if shot_result["result"] == "MAKE":
                        make_count += 1
                    elif shot_result["result"] == "MISS":
                        miss_count += 1
                t = lap(timings, "tracking_and_shots", t)

                output_frame = cv.resize(frame, video_size, interpolation=cv.INTER_LINEAR)
                lap(timings, "drawing", t)
                waiting.append((output_frame, {
                    "frame_index": frame_index,
                    "timestamp_s": timestamp_s,
                    "yolo_fps": yolo_fps,
                    "detector_ran": detected,
                    "detections": detections,
                    "shot_result": shot_result,
                    "score": {"makes": make_count, "misses": miss_count},
                }))
                if len(waiting) > LAG:
                    finish_frame(*waiting.popleft())

                if shot_result["event"]:
                    shot_events.append(shot_event(shot_result))
                    form_pass.add(shot_events[-1], recent_frames)

                frame_index += 1
                on_progress("detect", frame_index, frame_count)

            # The video can end while a shot is still being watched.
            last_result = shot_detector.finish()
            if last_result:
                make_count += last_result["result"] == "MAKE"
                miss_count += last_result["result"] == "MISS"
                shot_events.append(shot_event(last_result))
                form_pass.add(shot_events[-1], recent_frames)
            while waiting:
                finish_frame(*waiting.popleft())
    finally:
        # Closing its input tells ffmpeg there are no more frames. Then wait for it to finish the file.
        t = time.perf_counter()
        writer.stdin.close()
        video_written = writer.wait() == 0
        lap(timings, "video_write", t)
        reader.shutdown()  # Waits for a frame that is still being read, so the video can be closed.
        video.release()
    if not video_written:
        raise RuntimeError("ffmpeg could not write annotated.mp4")

    form_pass.finish(on_progress)
    # The helper thread and the form pass ran next to the loop, so the stages add up to more than the total.
    for stage, seconds in ahead_timings.items():
        timings[stage] += seconds
    timings["form"] = form_pass.seconds
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
