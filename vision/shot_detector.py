class ShotDetector():
    def __init__(self):
        self.active_shooter_id = None
        self.state = "idle"
        self.ball_near_wrist = False

    def update(tracked_ball, people, hoop_detection):
        