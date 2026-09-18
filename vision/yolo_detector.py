from ultralytics import YOLO
import time
import cv2


class YoloDetector():
    # model is type of yolo model "yolo26n.pt", conf_thres is detection min needed
    # device is what core to run yolo with, mps is gpu, cpu, cuda, amd, tpu ...
    # will need to not hardcode the model directory for best.pt 
    def __init__(
        self,
        model="runs3/basketball_yolo3/weights/best.pt",
        confidence_threshold=0.6,
        device="mps",
        image_size=512,
        focus_image_size=640,
        focus_skip_confidence=0.45,
    ):
        self.model = YOLO(model)
        self.conf = confidence_threshold
        self.device = device
        self.image_size = image_size
        self.focus_image_size = focus_image_size
        self.focus_skip_confidence = focus_skip_confidence
        self.last_focus_regions = []
        self.last_full_frame_run = True
    """     
    # returns the updated inferenced frame given from opencv, # WILL KEEP FOR NOW, INCASE WE DONT WANT FPS TEXT
    def detect_frame(self, frame):
        results = self.model.predict(frame, imgsz = 320, verbose = False, conf = self.conf, device = self.device)
        annotated_frame = results[0].plot()
        return annotated_frame
    """

    # returns annotated frame + YOLO inference FPS
    def detect_frame_with_fps(
        self,
        frame,
        focus_regions=None,
        run_full_frame=True,
    ):
        start_time = time.perf_counter()
        normalized_regions = self._normalize_focus_regions(
            focus_regions or [],
            frame.shape,
        )
        run_full_frame = run_full_frame or not normalized_regions
        self.last_full_frame_run = run_full_frame

        if run_full_frame:
            full_results = self.model.predict(
                frame,
                imgsz=self.image_size,
                verbose=False,
                conf=self.conf,
                device=self.device,
                classes=[0, 1],
            )
            detections = self._extract_detections(
                full_results[0],
                source="full",
            )
            annotated_frame = full_results[0].plot()
        else:
            detections = []
            annotated_frame = frame.copy()

        self.last_focus_regions = []
        for region in normalized_regions:
            if self._region_has_strong_ball(
                detections,
                region,
                self.focus_skip_confidence,
            ):
                continue

            x1, y1, x2, y2 = region
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            crop_results = self.model.predict(
                crop,
                imgsz=self.focus_image_size,
                verbose=False,
                conf=self.conf,
                device=self.device,
                classes=[0, 1],
            )
            detections.extend(
                self._extract_detections(
                    crop_results[0],
                    offset=(x1, y1),
                    source="focus",
                )
            )
            self.last_focus_regions.append(region)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (255, 0, 255), 1)

        detections = self._deduplicate_detections(detections)
        self._draw_focus_detections(annotated_frame, detections)
        end_time = time.perf_counter()
        inference_fps = 1.0 / (end_time - start_time) if end_time > start_time else 0.0

        return annotated_frame, detections, round(inference_fps)

    @staticmethod
    def _extract_detections(result, offset=(0, 0), source="full"):
        detections = []
        if result.boxes is None:
            return detections
        offset_x, offset_y = offset
        for box in result.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
            x1 += offset_x
            x2 += offset_x
            y1 += offset_y
            y2 += offset_y
            detections.append(
                {
                    "class_id": class_id,
                    "confidence": confidence,
                    "bbox": (x1, y1, x2, y2),
                    "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                    "source": source,
                }
            )
        return detections

    @classmethod
    def _normalize_focus_regions(cls, regions, frame_shape):
        frame_height, frame_width = frame_shape[:2]
        normalized = []
        for region in regions:
            if region is None:
                continue
            x1, y1, x2, y2 = map(int, region)
            x1 = max(0, min(frame_width, x1))
            x2 = max(0, min(frame_width, x2))
            y1 = max(0, min(frame_height, y1))
            y2 = max(0, min(frame_height, y2))
            if x2 - x1 < 64 or y2 - y1 < 64:
                continue

            candidate = (x1, y1, x2, y2)
            merged = False
            for index, existing in enumerate(normalized):
                if cls._intersection_over_union(candidate, existing) >= 0.65:
                    normalized[index] = (
                        min(candidate[0], existing[0]),
                        min(candidate[1], existing[1]),
                        max(candidate[2], existing[2]),
                        max(candidate[3], existing[3]),
                    )
                    merged = True
                    break
            if not merged:
                normalized.append(candidate)
        return normalized[:2]

    @classmethod
    def _deduplicate_detections(cls, detections):
        selected = []
        for detection in sorted(
            detections,
            key=lambda item: item["confidence"],
            reverse=True,
        ):
            if any(
                detection["class_id"] == existing["class_id"]
                and cls._same_object(detection, existing)
                for existing in selected
            ):
                continue
            selected.append(detection)
        return selected

    @staticmethod
    def _region_has_strong_ball(detections, region, confidence_threshold):
        x1, y1, x2, y2 = region
        return any(
            detection["class_id"] == 0
            and detection["confidence"] >= confidence_threshold
            and x1 <= detection["center"][0] <= x2
            and y1 <= detection["center"][1] <= y2
            for detection in detections
        )

    @classmethod
    def _same_object(cls, first, second):
        if cls._intersection_over_union(first["bbox"], second["bbox"]) >= 0.35:
            return True
        if first["class_id"] != 0:
            return False

        first_width = first["bbox"][2] - first["bbox"][0]
        first_height = first["bbox"][3] - first["bbox"][1]
        second_width = second["bbox"][2] - second["bbox"][0]
        second_height = second["bbox"][3] - second["bbox"][1]
        duplicate_distance = max(
            18.0,
            0.75 * max(first_width, first_height, second_width, second_height),
        )
        center_distance = (
            (first["center"][0] - second["center"][0]) ** 2
            + (first["center"][1] - second["center"][1]) ** 2
        ) ** 0.5
        return center_distance <= duplicate_distance

    @staticmethod
    def _intersection_over_union(first_bbox, second_bbox):
        first_x1, first_y1, first_x2, first_y2 = first_bbox
        second_x1, second_y1, second_x2, second_y2 = second_bbox
        intersection_width = max(0, min(first_x2, second_x2) - max(first_x1, second_x1))
        intersection_height = max(0, min(first_y2, second_y2) - max(first_y1, second_y1))
        intersection_area = intersection_width * intersection_height
        first_area = max(1, (first_x2 - first_x1) * (first_y2 - first_y1))
        second_area = max(1, (second_x2 - second_x1) * (second_y2 - second_y1))
        union_area = first_area + second_area - intersection_area
        return intersection_area / max(1, union_area)

    @staticmethod
    def _draw_focus_detections(annotated_frame, detections):
        for detection in detections:
            if detection.get("source") != "focus":
                continue
            x1, y1, x2, y2 = detection["bbox"]
            label = "basketball" if detection["class_id"] == 0 else "hoop"
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
            cv2.putText(
                annotated_frame,
                f"focus {label} {detection['confidence']:.2f}",
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 0, 255),
                2,
                cv2.LINE_AA,
            )
    # need to not just return rectangles around detections, must add detections of coordinates for shot logic 
    # will update later, rn is testing if it works with main.py pipeline
    # slightly updated currently for that
