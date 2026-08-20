import cv2 as cv 
import time 

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
    
