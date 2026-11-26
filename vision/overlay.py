"""What the annotated video shows on top of the footage: a ring and a dotted trail on the ball,
a line on the rim, and a small score card in the corner that says Make or Miss after a shot.

The colours and the font are the website's (see DESIGN.md).
"""
from functools import lru_cache
from pathlib import Path

import cv2 as cv
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = str(Path(__file__).with_name("BarlowCondensed-Bold.ttf"))
# Red, green, blue. OpenCV wants them the other way round, hence the [::-1] below.
COURT, ASPHALT, PAINT, MUTED = (19, 49, 85), (34, 39, 44), (242, 240, 234), (184, 198, 212)
BALL, MAKE, MISS = (248, 132, 45), (83, 222, 115), (255, 103, 101)
# How many of the ball's last positions are dotted behind it (two thirds of a second at 30 fps).
TRAIL = 20
# The detector skips frames (DETECT_EVERY in offline_runner.py). The ring stays on the ball's
# predicted position for this many frames without a detection, so it does not blink.
RING_COAST = 4


def draw(frame, tracked_ball, shot_result, makes, misses, scale):
    """Draw on `frame`. `scale` turns the detector's coordinates into this frame's pixels."""
    def at(x, y):
        return round(x * scale), round(y * scale)

    # All sizes are in units of 1/720 of the frame's short side, so a 4K clip looks the same.
    unit = min(frame.shape[:2]) / 720
    status = shot_result["status"]

    def painted(centre, radius, thickness):
        """A white circle with a thin dark edge, so it shows on a bright wall and on a dark one.
        A thickness of -1 fills the circle, which is how the trail's dots are drawn."""
        edge = round(2 * unit)
        if thickness == -1:
            cv.circle(frame, centre, radius + edge // 2, ASPHALT[::-1], -1, cv.LINE_AA)
        else:
            cv.circle(frame, centre, radius, ASPHALT[::-1], thickness + edge, cv.LINE_AA)
        cv.circle(frame, centre, radius, PAINT[::-1], thickness, cv.LINE_AA)

    # The ball's path: a dot on each of its last positions, smaller the older it is.
    # The newest two are skipped because they sit under the ball itself.
    trail = list(tracked_ball["history"])[-TRAIL:-2]
    for age, point in enumerate(reversed(trail)):
        painted(at(*point), round((4 - age / 6) * unit), -1)

    # A ring on the ball the tracker is following: on the detection when there is one, and on
    # the tracker's prediction for a few frames when there is not.
    centre = tracked_ball["measurement_center"] or tracked_ball["center"]
    if centre and tracked_ball["missing_frames"] < RING_COAST:
        radius = round(tracked_ball["width"] / 2 * scale + 5 * unit)
        painted(at(*centre), radius, round(2 * unit))

    # The rim line: orange, or green or red for a few seconds after a shot.
    if shot_result["scoring_window"]:
        left, right = shot_result["scoring_window"]
        rim_y = shot_result["rim_center"][1]
        colour = {"MAKE": MAKE, "MISS": MISS}.get(status, BALL)
        cv.line(frame, at(left, rim_y), at(right, rim_y), colour[::-1], round(4 * unit), cv.LINE_AA)

    card = score_card(makes, misses, status, unit)
    margin = round(24 * unit)
    frame[margin:margin + card.shape[0], margin:margin + card.shape[1]] = card


@lru_cache(maxsize=8)
def score_card(makes, misses, status, unit):
    """The score card as a picture, ready to paste on a frame. It only changes when the score
    or the status does, so the last few are remembered instead of drawn again every frame.

    OpenCV can't load a font file, so the card is drawn with Pillow. It is drawn 3 times too
    big and shrunk, which smooths the edges of the circles.
    """
    u = unit * 3
    numbers = ImageFont.truetype(FONT, round(40 * u))
    words = ImageFont.truetype(FONT, round(24 * u))
    width, row, pad = round(172 * u), round(44 * u), round(14 * u)
    result = status if status in ("MAKE", "MISS") else None
    height = pad * 2 + row * (3 if result else 2)

    card = Image.new("RGB", (width, height), COURT)
    pen = ImageDraw.Draw(card)
    pen.rectangle((0, 0, width - 1, height - 1), outline=PAINT, width=round(2 * u))

    def mark(y, colour, filled, ground):
        """The website's shot marks: a filled dot for a make, a ring for a miss."""
        r = round(8 * u)
        box = (pad, y - r, pad + 2 * r, y + r)
        pen.ellipse(box, fill=colour if filled else ground, outline=colour, width=round(3 * u))

    for line, (word, count, colour) in enumerate((("Makes", makes, MAKE), ("Misses", misses, MISS))):
        y = pad + row * line + row // 2
        mark(y, colour, colour == MAKE, COURT)
        pen.text((pad + round(26 * u), y), word, MUTED, words, anchor="lm")
        pen.text((width - pad, y), str(count), PAINT, numbers, anchor="rm")

    if result:
        # The last shot's result: a painted block in its colour with the word on it.
        colour = MAKE if result == "MAKE" else MISS
        top = pad + row * 2 + round(6 * u)
        pen.rectangle((round(2 * u), top, width - round(2 * u) - 1, height - round(2 * u) - 1), fill=colour)
        y = (top + height) // 2
        mark(y, ASPHALT, result == "MAKE", colour)
        pen.text((pad + round(26 * u), y), result.capitalize(), ASPHALT, numbers, anchor="lm")

    card = card.resize((width // 3, height // 3), Image.LANCZOS)
    return cv.cvtColor(np.array(card), cv.COLOR_RGB2BGR)
