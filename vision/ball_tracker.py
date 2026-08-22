from collections import deque
import math
# max_jump_distance = 150, direction_window=5
class BallTracker():
    def __init__(self, max_missing_frames = 5):
        # store all frames of ball
        self.history_pos = deque(maxlen = 60)
        self.missing_frames = 0
        self.max_missing_frames = max_missing_frames
        #self.max_jump_distance = 150
        #self.direction_window = direction_window

    def calculate_dist(self, point1, point2):
        x1, y1 = point1
        x2,y2 = point2
        return math.sqrt((x2-x1) ** 2 + (y2-y1) ** 2)
    """"
    def choose_ball(self,detections):
        ball_candidates = []
        for detection in detections:
            if detection["class_id"] == 0:
                ball_candidates.append(detection)
        # no basketball detections occured
        if len(ball_candidates) == 0:
            return None

        # if no history yet, use highest confidence method
        if len(self.history_pos) == 0:
            return max(ball_candidates, key=lambda detection : detection["confidence"])

        previous_pos = self.history_pos[-1]
        best_ball = None
        smallest_dist = float("inf")

        for candidate in ball_candidates:
            distance = self.calculate_dist(previous_pos, candidate["center"])
            if distance < smallest_dist:
                smallest_dist = distance
                best_ball = candidate

        if smallest_dist > self.max_jump_distance:
            return None
        
        return best_ball
    """

    def update(self, detections):
        tracked_ball = {"detected" : False, 
                        "center" : None,
                         "velocity" : (0,0) ,
                         "history": self.history_pos,
                         "missing_frames" : self.missing_frames}
        
        # if there are two basketball in one frame randomly, must choose the best one 
        best_ball = None 

        for detection in detections:
            if detection["class_id"] != 0:
                continue
            # choosing best ball, eventually will need to update this: 
            # must choose based on if ball is closer to previous frame
            if best_ball is None or detection["confidence"] > best_ball["confidence"]:
                best_ball = detection

        if best_ball is None:
            self.missing_frames += 1
            tracked_ball["missing_frames"] = self.missing_frames
            # if ball gone for too long
            if self.missing_frames > self.max_missing_frames:
                self.history_pos.clear()
            return tracked_ball
        
        # if there is a ball, reset and update normally
        self.missing_frames = 0
       
        self.history_pos.append(best_ball["center"])

        tracked_ball["detected"] = True
        tracked_ball["center"] = best_ball["center"]
        tracked_ball['history'] = self.history_pos
        tracked_ball["missing_frames"] = 0

        velocityX = 0
        velocityY = 0

        if len(self.history_pos) >= 2:
            previous_x,previous_y = self.history_pos[-2]
            current_x,current_y = self.history_pos[-1]
            # later for velocity might have to switch to real time, instead of just pixel per frame
            velocityX = current_x - previous_x
            velocityY = current_y - previous_y

        tracked_ball["velocity"] = (velocityX, velocityY)
        
        return tracked_ball
            

    

        