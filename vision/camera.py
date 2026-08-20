import cv2 as cv 

# defining a class so later in main.py its easier to pipeline
class Camera:
    # initializing, cap is either 0, 1, 2, 3, -1 (0 is webcam)
    # height/width is the webcam source (1280/720 leads to 30 FPS yolo)
    def __init__(self, source = 0, width = 1280, height= 720):
        self.width = width
        self.height = height

        self.cap = cv.VideoCapture(source)
        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, height)

        # checks if the camera can open
        if not self.cap.isOpened():
            raise RuntimeError("Camera cannot open")
            
    # gets a frame and sends it to while loop in main.py
    def read_frame(self):
        ret,frame = self.cap.read()

        if not ret:
            print("No Frame to recieve, exiting...")
            return None
        
        return frame
    
    # returns a text with the FPS currently
    def get_fps(self):
        fps = str(self.cap.get(cv.CAP_PROP_FPS))
        return fps

    # releases and turns off the camera when asked too
    def release(self):
        self.cap.release()
        # might have to remove the next line, and put in MAIN.PY file only, cause you dont want to shut whole window
        cv.destroyAllWindows()

    
