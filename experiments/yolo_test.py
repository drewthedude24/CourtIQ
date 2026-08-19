import cv2
import time
from ultralytics import YOLO


model = YOLO("yolo26n.pt")

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
  raise RuntimeError("Could not open webcam")

display_count = 0
display_start = time.time()
display_fps = 0.0

try:
  while True:
    ok, frame = cap.read()
    if not ok:
      break

    frame = cv2.resize(frame, (640, 360))

    results = model.predict(frame, imgsz=320, verbose=False)
    output = results[0].plot()

    display_count += 1
    now = time.time()
    if now - display_start >= 1.0:
      display_fps = display_count / (now - display_start)
      display_count = 0
      display_start = now

    cv2.putText(
      output,
      f"Display FPS: {display_fps:.1f}",
      (20, 40),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.8,
      (0, 255, 0),
      2,
      cv2.LINE_AA,
    )
    cv2.putText(
      output,
      f"Camera FPS: {cap.get(cv2.CAP_PROP_FPS):.1f}",
      (20, 75),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.8,
      (255, 255, 255),
      2,
      cv2.LINE_AA,
    )

    cv2.imshow("YOLO Webcam", output)

    if cv2.waitKey(1) & 0xFF == ord("q"):
      break
finally:
  cap.release()
  cv2.destroyAllWindows()