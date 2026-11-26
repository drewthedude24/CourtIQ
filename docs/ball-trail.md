# The ring and the trail on the ball

How the annotated video decides where the ball is on every frame (`vision/ball_path.py`),
and how that was measured.

## The problem

The detector only looks at every 4th frame (see `docs/speed-plan.md`, round 2). On the 3
frames in between, the old tracker guessed forward: "the ball keeps moving the way it was".
A dribbled ball turns around at the floor and at the hand, so the guess overshot, and the
next real detection pulled the ring back. That is what made the trail zigzag.

## What changed

- **The video is drawn 8 frames behind the detector.** By then the detections on both sides
  of a skipped frame are known, so the ball is placed on a smooth curve between them
  (a cubic Hermite spline) in place of a guess. Nobody sees the delay: the video is made
  offline.
- **The trail keeps the whole shot.** It is normally two thirds of a second long. While the
  ball is above the rim line, and until the make or miss is decided, it is not shortened,
  so it runs from the release to the rim (2.5 seconds at most). After that it shrinks back.
- **A spare ball lying on the court is ignored.** A ball seen in the same spot 3 times in
  about a second is lying still. The path does not start on it or hop over to it.
- **An unsure detection only counts close to the ball's last place.** Further away it was a
  hand or an elbow.
- The Kalman-filter tracker (`predictive_ball_tracker.py`, 562 lines) is gone. Nothing but
  the drawing used it. Shot detection reads the detector's boxes directly and is untouched.

## Measured

"Truth" here is a second run with the detector looking at every frame. A ring counts as
off the ball when its centre is more than 20 pixels from the detection (a ball is about 40
pixels wide in these clips). Docker on an Apple M5 Pro laptop.

| Clip | Ring off the ball, before | After | Frames with a ring, before | After |
|---|---|---|---|---|
| `longvid.mov` (dribbles and 6 shots) | 16% | 3% | 990 of 1431 | 1091 |
| `miss_dribble.mov` | 8% | 1% | 396 of 468 | 426 |
| `make_pass.mov` (60 fps, two players) | 2% | 1% | 529 of 750 | 538 |
| `miss_self.mov` | 3% | 1% | 292 of 381 | 283 |

`s1.mov` has a spare ball on the grass, and the every-frame run itself hops between the two
balls, so it cannot be used as truth. Checked by eye in place of a number: before, the ring
sat on the spare ball whenever the shooter hid the real one. Now it does not.

Speed, `longvid.mov` in Docker, old and new back to back:

| | Before | After |
|---|---|---|
| 2 CPUs | 34.6 and 34.4 s | 34.8 and 34.0 s |
| 1 CPU | 57.0 s | 56.9 s |

Not timed on the EC2 server. The change adds no detector or pose work, only a little
arithmetic per frame, and 8 small frames held in memory (about 12 MB).

`shot_events.jsonl` and `pose.jsonl` on the six eval clips are byte for byte the same as
before: the same 62 shots, results and form numbers.

## Still not right

- **The floor touch of a dribble is rounded off.** With a look every 4th frame the lowest
  point is usually between two looks, so the trail turns a little above the floor. Looking
  at every 2nd frame fixes it (ring off the ball on under 1% of frames) but that is about
  twice the detector work.
- **A ball hidden behind the body for a moment** is drawn on a straight line between where
  it went in and where it came out.
