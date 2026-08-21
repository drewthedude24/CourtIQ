from ultralytics import YOLO
import time
import cv2 
class YoloDetector():
    # model is type of yolo model "yolo26n.pt", conf_thres is detection min needed
    # device is what core to run yolo with, mps is gpu, cpu, cuda, amd, tpu ...
    # will need to not hardcode the model directory for best.pt 
    def __init__(self, model = "/Users/andrewmeng/Desktop/courtIQ/runs3/basketball_yolo3/weights/best.pt", confidence_threshold = 0.6, device = "mps"):
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
        results = self.model.predict(frame, imgsz = 512, verbose = False, conf = self.conf, device = self.device,
                                     classes = [0,1])
        end_time = time.perf_counter()

        # gets each detection box and its details where we loop through each one
        boxes = results[0].boxes
        for box in boxes:
            class_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1,y1,x2,y2 = map(int, box.xyxy[0].cpu().numpy())
            center_x = (x2 + x1) // 2
            center_y = (y2 + y1) // 2
            # information about each detection box in a frame
            """
            print(f"Class ID: {class_id}")
            print(f"Confidence Score: {conf}")
            print(f"({x1} {y1}) ({x2} {y2})")
            print("_________________________")
            """
        
        annotated_frame = results[0].plot()
        inference_fps = 1.0 / (end_time - start_time) if end_time > start_time else 0.0

        return annotated_frame, round(inference_fps)
    # need to not just return rectangles around detections, must add detections of coordinates for shot logic 
    # will update later, rn is testing if it works with main.py pipeline
    # slightly updated currently for that