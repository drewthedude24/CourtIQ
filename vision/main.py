from collections import deque
import time

import cv2 as cv

from camera import Camera
from yolo_detector import YoloDetector
from pose_detector import PoseDetector
from predictive_ball_tracker import PredictiveBallTracker
from shot_detector import ShotDetector
from shot_result_detector import ShotResultDetector
import debug_overlay


LIVE_FRAME_SIZE = (960, 540)
LIVE_FULL_IMAGE_SIZE = 640
LIVE_FOCUS_IMAGE_SIZE = 640
LIVE_FULL_FRAME_INTERVAL = 3
LIVE_CONFIDENCE_THRESHOLD = 0.12
CAMERA_SOURCE = 0


def draw_performance_overlay(frame, yolo_fps, pipeline_fps, full_frame_run):
    """Show detector and complete-pipeline speed without covering shot details."""
    mode = "full + focus" if full_frame_run else "focus only"
    height = frame.shape[0]
    cv.putText(
        frame,
        f"YOLO: {yolo_fps} FPS | Pipeline: {pipeline_fps:.1f} FPS",
        (20, height - 55),
        cv.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv.LINE_AA,
    )
    cv.putText(
        frame,
        f"Inference: {mode}",
        (20, height - 20),
        cv.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 0, 255),
        2,
        cv.LINE_AA,
    )


def main():
    camera = Camera(source=CAMERA_SOURCE, width=1280, height=720)
    yolo_detector = YoloDetector(
        confidence_threshold=LIVE_CONFIDENCE_THRESHOLD,
        image_size=LIVE_FULL_IMAGE_SIZE,
        focus_image_size=LIVE_FOCUS_IMAGE_SIZE,
    )
    pose_detector = PoseDetector()
    ball_tracker = PredictiveBallTracker(
        history_size=30,
        max_prediction_frames=3,
        max_missing_frames=6,
        reacquire_after_missing_frames=2,
        reacquire_confidence_threshold=0.55,
    )
    shot_detector = ShotDetector()
    shot_result_detector = ShotResultDetector()

    frame_index = 0
    previous_shot_state = "IDLE"
    previous_tracking_status = "LOST"
    session_start_time = time.perf_counter()
    recent_pipeline_times = deque(maxlen=30)

    try:
        while True:
            frame_start_time = time.perf_counter()
            frame = camera.read_frame()
            if frame is None:
                break

            inference_frame = cv.resize(
                frame,
                LIVE_FRAME_SIZE,
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
                or frame_index % LIVE_FULL_FRAME_INTERVAL == 0
            )

            yolo_frame, detections, yolo_fps = yolo_detector.detect_frame_with_fps(
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

            timestamp_s = time.perf_counter() - session_start_time
            debug_overlay.draw_debug_overlay(
                yolo_frame,
                tracked_ball,
                shot_state,
                timestamp_s,
                shot_result,
            )

            frame_processing_time = time.perf_counter() - frame_start_time
            recent_pipeline_times.append(frame_processing_time)
            average_processing_time = sum(recent_pipeline_times) / len(
                recent_pipeline_times
            )
            pipeline_fps = (
                1.0 / average_processing_time if average_processing_time > 0 else 0.0
            )
            draw_performance_overlay(
                yolo_frame,
                yolo_fps,
                pipeline_fps,
                yolo_detector.last_full_frame_run,
            )

            if shot_result["event"]:
                print(
                    f"Shot {shot_result['shot_id']}: {shot_result['result']} "
                    f"at {timestamp_s:.2f}s ({shot_result['reason']})"
                )
                shot_detector.complete_shot()

            cv.imshow("CourtIQ Live", yolo_frame)
            previous_shot_state = shot_state
            previous_tracking_status = tracked_ball["tracking_status"]
            frame_index += 1

            if cv.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv.destroyAllWindows()


if __name__ == "__main__":
    main()
