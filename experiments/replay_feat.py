# got the replay feat to work for now, will make it stronger in the future
# use deque to store as a queue and store previous frames and lower qual
import cv2 as cv 
import time 
from collections import deque

buffer = deque(maxlen = 150)


cap = cv.VideoCapture(0)
cap.set(cv.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv.CAP_PROP_FRAME_HEIGHT, 720)


# check if camera opens 
if not cap.isOpened():
    print("Error: Camera cannot open")
    exit()

# Read if it does open, shows true:
while True:
    ret, frame = cap.read()
    # if no frame to read, broken, then cancel while loop
    if not ret:
        print("No frame to recieve, exiting...")
        break

    small_frame = cv.resize(frame, (640, 360))
    buffer.append(small_frame)

    if cv.waitKey(1) & 0xFF == ord('r'):
        print("yes")
        fourcc = cv.VideoWriter_fourcc(*"mp4v")

        writer = cv.VideoWriter(
            "/Users/johnmeng_1/Desktop/courtIQ/video/shot.mp4",
            fourcc,
            30,
            (640, 360)
        )

        for frame in buffer:
           writer.write(frame)
        writer.release()
    # display fps in the frame
    fps = str(cap.get(cv.CAP_PROP_FPS))
    text = "FPS: " + fps
    cv.putText(frame, text, (50,50), cv.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2, cv.LINE_AA)
    cv.imshow("Camera", frame)

    # can leave with button
    if cv.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv.destroyAllWindows()
    
