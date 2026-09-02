import cv2 as cv
import time
import json

from yolo_detector import YoloDetector
from pose_detector import PoseDetector
from ball_tracker import BallTracker
from shot_detector import ShotDetector
import debug_overlay

yolo_detector = YoloDetector()
pose_detector = PoseDetector()
ball_tracker = BallTracker()
shot_detector = ShotDetector()
session_start_time = time.perf_counter()

# input_path = "video/test_clips/clip_01.mp4"


clips = [
    "video/make_pass.mov",
    "video/miss_dribble.mov",
    "video/miss_self.mov",
]


def process_vid(input_path, output_folder):
    # create both objects to use in loop
    cap = cv.VideoCapture(input_path)

    fps = cap.get(cv.CAP_PROP_FPS)
    width = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv.VideoWriter_fourcc(*"mp4v")

    writer = cv.VideoWriter(output_folder, fourcc, fps, (width, height))

    frame_ind = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_s = frame_ind / fps

        # help with frame rate consistency at 30+ FPS by resizing after testing
        frame = cv.resize(frame, (640, 360))
        # call and get the annotated frame with its FPS
        yolo_frame, detections, yolo_fps = yolo_detector.detect_frame_with_fps(frame)
        people = pose_detector.detect(yolo_frame)
        tracked_ball = ball_tracker.update(detections)
        
        shot_state = shot_detector.update(tracked_ball, people)

        timestamp_s = time.perf_counter() - session_start_time
        debug_overlay.draw_debug_overlay(yolo_frame, tracked_ball, shot_state, timestamp_s)

        writer.write(yolo_frame)

        frame_ind += 1

    cap.release()
    writer.release()


def write_json_line(json_file, frame_record):
    json.dump(frame_record, json_file)
    json_file.write("\n")


for input_path in clips:
    process_vid(input_path, "output.mp4")
