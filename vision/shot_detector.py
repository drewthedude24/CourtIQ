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
        self.release_distance_threshold = 80
        self.release_upward_velocity_threshold = -4
        self.possessor_missing_frames = 0
# will add hoop detection later !!!
    def update(self,tracked_ball, people, allowed_missing_frames = 10):
        # A release belongs to the current shot until the result detector calls
        # complete_shot(). Detector gaps near the rim must not erase it.
        if self.state == "RELEASED":
            return self.state

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

        # Find whose wrist is closer to the ball. Checking both wrists prevents
        # pose jitter or a left-handed gather from breaking possession.
        for person in people:
            wrist_dist = self.closest_wrist_distance(ball_center, person)
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

            wrist_dist = self.closest_wrist_distance(ball_center, current_possessor)
            ear_y = current_possessor['keypoints']['right_ear']['position'][1]

            # Fast releases can move from gather to airborne in one frame. Test
            # release before dropping possession when the wrist keypoint jitters.
            if self.looks_like_release(ball_center, veloY, wrist_dist, ear_y):
                self.active_shooter_id = self.current_possessor_id
                self.state = "RELEASED"
            elif wrist_dist < self.possession_distance_threshold:
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

            wrist_dist = self.closest_wrist_distance(ball_center, current_possessor)

            ear_y = current_possessor['keypoints']['right_ear']['position'][1]
            if self.looks_like_release(ball_center, veloY, wrist_dist, ear_y):
                self.active_shooter_id = self.current_possessor_id
                self.state = "RELEASED"
            elif veloY > 0 and wrist_dist < self.possession_distance_threshold:
                self.state = "POSSESSION"

        return self.state
    
    def calculate_dist(self, point1, point2):
        x1, y1 = point1
        x2, y2 = point2
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    def closest_wrist_distance(self, ball_center, person):
        wrist_positions = [
            person["keypoints"]["left_wrist"]["position"],
            person["keypoints"]["right_wrist"]["position"],
        ]
        return min(
            self.calculate_dist(ball_center, wrist_position)
            for wrist_position in wrist_positions
        )

    def looks_like_release(self, ball_center, velocity_y, wrist_distance, ear_y):
        return (
            wrist_distance > self.release_distance_threshold
            and ball_center[1] <= ear_y
            and velocity_y <= self.release_upward_velocity_threshold
        )

    def reset(self):
        self.state = "IDLE"
        self.active_shooter_id = None
        self.current_possessor_id = None
        self.possessor_missing_frames = 0

    def complete_shot(self):
        """Allow a new possession only after make/miss has been decided."""
        self.reset()
