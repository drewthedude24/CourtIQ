import numpy as np

from vision.form_pictures import HEIGHT, picture

# A shooter standing in the middle of a 720 x 1280 frame, every joint clearly seen.
SPOTS = {"shoulder": 500, "elbow": 420, "wrist": 340, "hip": 750, "knee": 900, "ankle": 1050}
FRAME = {
    "points": {f"{side}_{name}": (360 + dx, y, 0.9) for name, y in SPOTS.items()
               for side, dx in (("left", -40), ("right", 40))},
    "balls": [(400, 300, 50)],
}


def test_a_picture_is_a_small_crop_around_the_shooter_with_the_joints_drawn():
    image = picture(np.zeros((1280, 720, 3), np.uint8), FRAME, "elbow_bend_deg", "right")

    assert image.shape[0] == HEIGHT
    # Cropped to the body, so narrower than the frame squeezed to the same height.
    assert image.shape[1] < HEIGHT * 720 / 1280
    blue, green, red = image[..., 0], image[..., 1], image[..., 2]
    assert ((green > 150) & (red < 100) & (blue < 100)).any()  # the measured arm, in green


def test_a_joint_that_was_not_seen_is_not_drawn():
    hidden = {"points": {name: (x, y, 0.1) for name, (x, y, _) in FRAME["points"].items()}, "balls": []}

    assert picture(np.zeros((1280, 720, 3), np.uint8), hidden, "knee_bend_deg", "right") is None
