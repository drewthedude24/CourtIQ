"""Find a person's joints in a video frame with MediaPipe's pose model.

MediaPipe gives each joint twice: where it is in the picture, and a guess of where it is in 3D
(metres, measured from the hips). The 3D guess is what makes the elbow readable from behind.
"""
from pathlib import Path

import cv2 as cv
import mediapipe as mp
from mediapipe.tasks import python as tasks
from mediapipe.tasks.python import vision

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "pose_landmarker_heavy.task"
# The joints the form numbers use, and MediaPipe's number for each.
JOINTS = {
    "left_shoulder": 11, "right_shoulder": 12, "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16, "left_hip": 23, "right_hip": 24,
    "left_knee": 25, "right_knee": 26, "left_ankle": 27, "right_ankle": 28,
}


class PoseModel:
    """Make a new one for each video: it follows the person from frame to frame."""

    def __init__(self):
        self.landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
        ))

    def keypoints(self, frame, timestamp_s):
        """(points, world) for the most obvious person in the frame. Frames must come in time order.

        points: {"left_knee": [x, y, how sure it is seen from 0 to 1], ...} in pixels.
        world:  {"left_knee": [x, y, z], ...} in metres. Both are empty when nobody is found.
        """
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv.cvtColor(frame, cv.COLOR_BGR2RGB))
        result = self.landmarker.detect_for_video(image, int(timestamp_s * 1000))
        if not result.pose_landmarks:
            return {}, {}
        height, width = frame.shape[:2]
        flat, world = result.pose_landmarks[0], result.pose_world_landmarks[0]
        points = {
            name: [flat[i].x * width, flat[i].y * height, flat[i].visibility]
            for name, i in JOINTS.items()
        }
        return points, {name: [world[i].x, world[i].y, world[i].z] for name, i in JOINTS.items()}

    def close(self):
        self.landmarker.close()
