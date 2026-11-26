"""Pictures of where each form number was read: the frame it came from, cropped to the shooter,
with the joints that number uses drawn on top. The page shows them when a shot is clicked.

Only the joints are drawn, not the angle. The knee and arm numbers come from up-and-down
distances (see shot_form.py), so from behind an angle drawn on the picture would not match them.
"""
import cv2 as cv

# Same as SEEN in shot_form.py: a joint seen less surely than this is not drawn.
SEEN = 0.5
# Saved this many pixels tall: small enough to load fast and sit five in a row on the page.
HEIGHT = 320
# Room around the joints, as a share of the body's height: the head is above the shoulders.
MARGIN = 0.25
GREY, GREEN, ORANGE = (200, 200, 200), (0, 255, 0), (0, 140, 255)  # OpenCV colours are BGR

SIDES = ("left", "right")
# The whole body, drawn thin and grey so the measured part stands out.
BODY = [
    (f"{side}_{a}", f"{side}_{b}")
    for side in SIDES
    for a, b in (("shoulder", "elbow"), ("elbow", "wrist"), ("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle"))
] + [("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")]


def legs(arm):
    return [(f"{side}_{a}", f"{side}_{b}") for side in SIDES for a, b in (("hip", "knee"), ("knee", "ankle"))]


def shooting_arm(arm):
    return [(f"{arm}_shoulder", f"{arm}_elbow"), (f"{arm}_elbow", f"{arm}_wrist")]


# The bones each number is read from, drawn thick and green. `arm` is the shooting arm.
MEASURED = {
    "knee_bend_deg": legs,
    "elbow_bend_deg": shooting_arm,
    "arm_angle_deg": lambda arm: [(f"{arm}_shoulder", f"{arm}_wrist")],
    "jump": legs,
    "flight_time_s": shooting_arm,
}


def picture(image, frame, name, arm):
    """The frame cropped around the shooter, with the bones `name` is read from drawn on it.
    None when none of those bones were clearly seen."""
    points = {joint: (int(x), int(y)) for joint, (x, y, sure) in frame["points"].items() if sure >= SEEN}
    measured = [(a, b) for a, b in MEASURED[name](arm) if a in points and b in points]
    if not measured:
        return None

    image = image.copy()
    for a, b in BODY:
        if a in points and b in points:
            cv.line(image, points[a], points[b], GREY, 2, cv.LINE_AA)
    for a, b in measured:
        cv.line(image, points[a], points[b], GREEN, 4, cv.LINE_AA)
        for joint in (a, b):
            cv.circle(image, points[joint], 7, GREEN, -1, cv.LINE_AA)
    # Flight time starts when the ball leaves the hand, so circle the ball by the hand.
    wrist = points.get(f"{arm}_wrist")
    if name == "flight_time_s" and wrist and frame["balls"]:
        x, y, width = min(frame["balls"], key=lambda ball: (ball[0] - wrist[0]) ** 2 + (ball[1] - wrist[1]) ** 2)
        cv.circle(image, (int(x), int(y)), int(width / 2), ORANGE, 3, cv.LINE_AA)

    xs, ys = zip(*points.values())
    pad = MARGIN * (max(ys) - min(ys))
    height, width = image.shape[:2]
    crop = image[max(0, int(min(ys) - pad)):min(height, int(max(ys) + pad)),
                 max(0, int(min(xs) - pad)):min(width, int(max(xs) + pad))]
    return cv.resize(crop, (round(crop.shape[1] * HEIGHT / crop.shape[0]), HEIGHT), interpolation=cv.INTER_AREA)


def save_pictures(shot_number, form, pose_frames, images, folder):
    """One picture per measured number of one shot, saved as <folder>/<shot number>_<number>.jpg.
    pose_frames are the frames the form was measured on, with their joints and frame index.
    images holds the picture of every frame a number was read on, by frame index."""
    by_time = {frame["t"]: frame for frame in pose_frames}
    folder.mkdir(exist_ok=True)
    for name, t in form.get("seen_at", {}).items():
        frame = by_time[t]
        drawn = picture(images[frame["index"]], frame, name, form["arm"])
        if drawn is not None:
            cv.imwrite(str(folder / f"{shot_number}_{name}.jpg"), drawn, [cv.IMWRITE_JPEG_QUALITY, 85])
