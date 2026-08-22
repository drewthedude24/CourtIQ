import math

class ShotDetector():

    def __init__(self):
        self.current_possessor_id = None
        self.active_shooter_id = None
        self.state = "IDLE"
        # self.ball_near_wrist = False
        # later will implement pose deque, that stores the last 60 frames
        # when a shot is detected at the top of shot, go back in frames to see
        # key details like knee bend and stuff like that 
        # pose_history = deque(maxlen = 60)

        self.possession_distance_threshold = 90
        self.release_distance_threshold = 120
        self.possessor_missing_frames = 0
# will add hoop detection later !!!
    def update(self,tracked_ball, people, allowed_missing_frames = 10):
        # determines what happens when ball is not detected in a frame
        if not tracked_ball["detected"]:
            # if within a limit, keep state the same
            if tracked_ball["missing_frames"] <= allowed_missing_frames:
                return self.state
            # if not found for awhile, reset completley
            else:
                self.reset()
                return self.state

        ball_center = tracked_ball["center"]
        veloX, veloY = tracked_ball["velocity"]

        closest_person_id = None
        closest_wrist_distance = math.inf

        # find whos wrist is closer to the ball 
        for person in people:
            right_wrist = person["keypoints"]["right_wrist"]["position"]
            wrist_dist = self.calculate_dist(ball_center, right_wrist)
            if wrist_dist < closest_wrist_distance:
                closest_wrist_distance = wrist_dist
                closest_person_id = person["person_id"]

        if self.state == "IDLE":
            # for the possession threshold value, LATER we will NORMALIZE IT!!!
            if closest_person_id is not None and closest_wrist_distance < self.possession_distance_threshold:
                self.current_possessor_id = closest_person_id
                self.state = "POSSESSION"

        elif self.state == "POSSESSION":
            current_possessor = None

            for person in people:
                if person["person_id"] == self.current_possessor_id:
                    current_possessor = person 
                    break

            if current_possessor is None:
                self.possessor_missing_frames += 1
                if self.possessor_missing_frames <= 5:
                    return self.state
                # should reset after more than 5 frames, make sure to check
                self.reset()
                return self.state

            self.possessor_missing_frames = 0

            right_wrist = current_possessor["keypoints"]["right_wrist"]["position"]

            wrist_dist = self.calculate_dist(
            tracked_ball["center"],
            right_wrist
            )

            if wrist_dist < self.possession_distance_threshold:
                if veloY < 0:
                    self.state = "POSSIBLE_SHOT"
            else:
                self.current_possessor_id = None
                self.state = "IDLE"

        elif self.state == "POSSIBLE_SHOT":
            current_possessor = None
            
            for person in people:
                if person["person_id"] == self.current_possessor_id:
                    current_possessor = person 
                    break
            
            if current_possessor is None:
                self.possessor_missing_frames += 1
                if self.possessor_missing_frames <= 5:
                    return self.state
                # should reset after more than 5 frames, make sure to check
                self.reset()
                return self.state

            self.possessor_missing_frames = 0

            right_wrist = current_possessor["keypoints"]["right_wrist"]["position"]
            
            wrist_dist = self.calculate_dist(
                tracked_ball["center"],
                right_wrist
            )

            ear_y = current_possessor['keypoints']['right_ear']['position'][1]
            if wrist_dist > self.release_distance_threshold and ball_center[1] <= ear_y and veloY < 0:
                self.active_shooter_id = self.current_possessor_id
                self.state = "RELEASED"
            elif veloY > 0 and wrist_dist < self.possession_distance_threshold:
                self.state = "POSSESSION"
        return self.state
    
    def calculate_dist(self, point1, point2):
        x1, y1 = point1
        x2, y2 = point2
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    def reset(self):
        self.state = "IDLE"
        self.active_shooter_id = None
        self.current_possessor_id = None
        self.possessor_missing_frames = 0
