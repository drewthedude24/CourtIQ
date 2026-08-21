# this will be connecting camera & yolo_detector file together in while loop
import cv2 as cv 
import time 
from camera import Camera
from yolo_detector import YoloDetector

# create both objects to use in loop
camera = Camera()
yolo_detector = YoloDetector()

# run while loop until we close or error
while True:
    # call to get frame
    frame = camera.read_frame()
    # break if not there
    if frame is None:
        print("No frame available...")
        break

    # help with frame rate consistency at 30+ FPS by resizing after testing
    frame = cv.resize(frame, (640, 360))
    # call and get the annotated frame with its FPS 
    yolo_frame, yolo_fps = yolo_detector.detect_frame_with_fps(frame)

    text = "YOLO FPS: " + str(yolo_fps)
    cv.putText(yolo_frame, text, (50,50), cv.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2, cv.LINE_AA)
    cv.imshow("Detection: ", yolo_frame)
    
    # can close with button
    if cv.waitKey(1) & 0xFF == ord('q'):
            break

camera.release()
cv.destroyAllWindows()