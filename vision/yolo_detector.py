from ultralytics import YOLO
import time

class YoloDetector():
    # model is type of yolo model "yolo26n.pt", conf_thres is detection min needed
    # device is what core to run yolo with, mps is gpu, cpu, cuda, amd, tpu ...
    def __init__(self, model = "yolo26n.pt", confidence_threshold = 0.6, device = "mps"):
        self.model = YOLO(model)
        self.conf = confidence_threshold
        self.device = device

    # returns the updated inferenced frame given from opencv, # WILL KEEP FOR NOW, INCASE WE DONT WANT FPS TEXT
    def detect_frame(self, frame):
        results = self.model.predict(frame, imgsz = 320, verbose = False, conf = self.conf, device = self.device)
        annotated_frame = results[0].plot()
        return annotated_frame

    # returns annotated frame + YOLO inference FPS
    def detect_frame_with_fps(self, frame):
        start_time = time.perf_counter()
        results = self.model.predict(frame, imgsz = 320, verbose = False, conf = self.conf, device = self.device)
        end_time = time.perf_counter()

        annotated_frame = results[0].plot()
        inference_fps = 1.0 / (end_time - start_time) if end_time > start_time else 0.0

        return annotated_frame, round(inference_fps)
    # need to not just return rectangles around detections, must add detections of coordinates for shot logic 
    # will update later, rn is testing if it works with main.py pipeline