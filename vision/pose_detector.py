from ultralytics import YOLO
import time
import cv2 

class PoseDetector():
    def __init__(self, model = "yolo26n-pose.pt", conf = 0.7, device = "cpu"):
        self.model = YOLO(model)
        self.conf = conf
        self.device = device

    # we will see if imgsz being diff than basketball detection matters
    def detect(self, frame):
        results = self.model.track(frame,persist = True, tracker = "bytetrack.yaml",
         imgsz = 384, verbose = False, conf = self.conf, device = self.device)
        
        people = []
        result = results[0]

        # if no one is detected
        if result.boxes is None:
            return people

        # tracker has not assigned IDs yet
        if result.boxes.id is None:
            return people

        boxes = result.boxes
        kpts = result.keypoints

        for i in range(len(boxes)):
            person_id = int(boxes.id[i])
            x1,y1,x2,y2 = map(int, boxes.xyxy[i].cpu().numpy())
            conf = float(boxes.conf[i])
            person_height = y2-y1
            person_keypoints = kpts.xy[i].cpu().numpy()
            keypoint_conf = kpts.conf[i].cpu().numpy()

            # gets each persons information and its keypoints x,y,conf
            person = {
                "person_id": person_id,
                "confidence" : conf,
                "bbox": (x1,y1,x2,y2),
                "height" : person_height,
                "keypoints": {
                    "left_shoulder": {
                        "position": tuple(person_keypoints[5]),
                        "confidence": float(keypoint_conf[5])
                    },

                    "right_shoulder": {
                        "position": tuple(person_keypoints[6]),
                        "confidence": float(keypoint_conf[6])
                    },

                    "left_elbow": {
                        "position": tuple(person_keypoints[7]),
                        "confidence": float(keypoint_conf[7])
                    },

                    "right_elbow": {
                        "position": tuple(person_keypoints[8]),
                        "confidence": float(keypoint_conf[8])
                    },

                    "left_wrist": {
                        "position": tuple(person_keypoints[9]),
                        "confidence": float(keypoint_conf[9])
                    },

                    "right_wrist": {
                        "position": tuple(person_keypoints[10]),
                        "confidence": float(keypoint_conf[10])
                    },

                    "left_hip": {
                        "position": tuple(person_keypoints[11]),
                        "confidence": float(keypoint_conf[11])
                    },

                    "right_hip": {
                        "position": tuple(person_keypoints[12]),
                        "confidence": float(keypoint_conf[12])
                    },

                    "left_knee": {
                        "position": tuple(person_keypoints[13]),
                        "confidence": float(keypoint_conf[13])
                    },

                    "right_knee": {
                        "position": tuple(person_keypoints[14]),
                        "confidence": float(keypoint_conf[14])
                    }
                }
            }
            people.append(person)
            return people