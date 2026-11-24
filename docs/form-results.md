# Shot form: which numbers can be measured from behind

Measured 2026-11-24 on the 6 labeled clips (63 shots), all filmed by hand from behind the
shooter at 30 fps. Reproduce with `python -m eval.form` (about 3.5 minutes on the Mac), or
`python -m eval.form --replay` to recompute from the saved keypoints in seconds.

## What was tested

For each shot, two pose models looked at the 2.5 seconds before the ball reached the rim:
YOLO pose (`yolo26n-pose.pt`, already in the repo) and MediaPipe (Google's model, which also
guesses 3D positions). Each form number was then worked out up to three ways:

- **flat**: the angle as drawn in the picture.
- **vertical**: from up-and-down distances only. For the knee, how much the hip-to-ankle
  distance shortens compared with the same legs when straight.
- **3d**: from MediaPipe's 3D points.

There is no answer key (no side-view recording), so this shows which numbers are
**repeatable**. It does not show that any of them is accurate to some number of degrees.

## The bar, set before looking

A number is kept if it is measured on at least 90% of shots, and the wiggle test moves it by
less than half of its own shot-to-shot spread.

- **Spread**: how much the number changes from shot to shot inside one clip.
- **Wiggle**: how much it changes when it is recomputed from only the even frames, then only
  the odd frames. A number that depends on catching one exact frame fails this.

## Results

| Number | Pose model | Shots measured | Average | Spread | Wiggle | Passes the bar |
|---|---|---|---|---|---|---|
| Knee, flat (°) | YOLO | 62 of 63 | 152.6 | 8.6 | 0.6 | yes |
| Knee, flat (°) | MediaPipe | 62 of 63 | 152.2 | 8.4 | 0.7 | yes |
| **Knee, vertical (°)** | **YOLO** | **62 of 63** | **101.6** | **5.7** | **2.1** | **yes** |
| Knee, vertical (°) | MediaPipe | 62 of 63 | 99.0 | 5.6 | 1.9 | yes |
| Knee, 3D (°) | MediaPipe | 62 of 63 | 151.9 | 7.1 | 0.8 | yes |
| Elbow, flat (°) | YOLO | 61 of 63 | 20.1 | 8.1 | 11.0 | no |
| Elbow, flat (°) | MediaPipe | 41 of 63 | 24.4 | 7.3 | 5.6 | no |
| **Elbow, 3D (°)** | **MediaPipe** | **41 of 63** | **63.3** | **4.5** | **2.0** | **no (coverage)** |
| Arm at release, flat (°) | YOLO | 61 of 63 | 86.8 | 1.5 | 1.2 | no |
| Arm at release, flat (°) | MediaPipe | 61 of 63 | 85.9 | 1.4 | 1.8 | no |
| **Arm at release, vertical (°)** | **YOLO** | **61 of 63** | **47.2** | **3.9** | **1.2** | **yes** |
| Arm at release, vertical (°) | MediaPipe | 61 of 63 | 46.8 | 2.5 | 1.25 | no |
| Arm at release, 3D (°) | MediaPipe | 61 of 63 | 81.0 | 3.5 | 2.4 | no |
| Release height (shoulder-heights) | YOLO | 61 of 63 | 1.28 | 0.02 | 0.01 | no |
| Release height (shoulder-heights) | MediaPipe | 61 of 63 | 1.29 | 0.02 | 0.01 | no |
| **Jump (shoulder-heights)** | **YOLO** | **61 of 63** | **0.25** | **0.03** | **0.01** | **yes** |
| Jump (shoulder-heights) | MediaPipe | 61 of 63 | 0.25 | 0.02 | 0.01 | yes |
| Release time (s) | YOLO | 62 of 63 | 0.27 | 0.03 | 0.07 | no |
| Release time (s) | MediaPipe | 62 of 63 | 0.26 | 0.02 | 0.07 | no |
| **Flight time (s)** | **YOLO** | **62 of 63** | **1.07** | **0.08** | **0.03** | **yes** |
| Flight time (s) | MediaPipe | 62 of 63 | 1.06 | 0.08 | 0.03 | yes |

Do two pose models agree when they measure the same thing? (1.0 is perfect agreement.)

| Number | YOLO vs MediaPipe |
|---|---|
| Knee, vertical | 0.94 |
| Knee, flat | 0.94 |
| Arm at release, vertical | 0.84 |
| Jump | 0.82 |
| Release time | 0.06 |
| Elbow, flat | 0.17 |

## Decision

**Keep five numbers:**

| Number | What it is | How |
|---|---|---|
| Knee bend (°) | The deepest bend before the release. 180 is a straight leg. | Leg shortening |
| Arm angle at release (°) | How steeply the arm points up as the ball leaves. | Wrist height over the shoulder against arm length |
| Jump | How far the feet rise, in standing shoulder-heights. | Feet against the rim line |
| Flight time (s) | Ball leaving the hand to reaching the rim. | Ball track |
| Elbow bend (°) | The tightest the shooting elbow gets before the push. | MediaPipe 3D, only when the arm was seen |

The first four pass the bar. **The elbow does not: it is kept at Andrew's request**, and it
is empty on about a third of shots (measured on 41 of 63).

### How the elbow was made usable

Measured on every shot, the 3D elbow swung 18° from shot to shot inside one clip, which is
too much to be real. Frame by frame it is a sensible curve: about 160° with the ball low,
folding to about 65 to 70° and holding there, then opening as the ball leaves. The swing
came from shots where the arm was hidden behind the body for part of that hold, so the
tightest moment fell in a missing frame.

The rule now: the elbow is reported only when the arm was seen in at least 80% of the
0.6 s before the release (`ELBOW_SEEN` in `vision/shot_form.py`). With that rule it reads
63.3° with a 4.5° spread and a 2.0° wiggle, next to the 59 to 65° that side-view studies
report. Without it: 74.4° and an 18° spread. The result barely moves with the settings:
windows of 0.3 to 0.6 s and thresholds of 80 to 100% all give 39 to 42 shots at about 63°.

The elbow rows above were recomputed with `--replay` from the same run's saved keypoints.

**Dropped:**

- **Release time.** Its real shot-to-shot change (0.03 s, one frame) is smaller than what
  30 fps can resolve (wiggle 0.07 s), and the two models do not agree (0.06).
- **Release height.** It came out the same on every shot (spread 0.02). It only restates the
  shooter's arm length and the arm angle, so it adds nothing.

### What MediaPipe did and did not add

- **The elbow needs it.** Only its 3D points give a usable elbow from behind.
- **It did not fix the knee or the arm.** Its 3D knee (152°) is almost the same as its own
  flat knee (agreement 0.89), and its 3D arm (81°) is close to the flat arm (86°).
- **Open for Stage B: one pose model or two.** MediaPipe's keypoints also pass the bar for
  knee, jump and flight time. For the arm they miss it by a hair (wiggle 1.25 against a
  limit of 1.245), and only because that version is steadier shot to shot (spread 2.5
  against YOLO's 3.9). On this Mac, MediaPipe takes about 12 ms a frame and YOLO pose 18 ms.

## What this shows about "repeatable is not accurate"

The flat knee and the 3D knee both pass the bar, and both read about 152°, which is a
nearly straight leg. The picture sheets show an obvious crouch on every shot. So those two
are steady and wrong. Passing the bar is necessary, not enough. The vertical knee reads
about 100°, close to the 104 to 110° that side-view studies report for jump shots.

## Checked by eye

`eval/output/<clip>/form_sheet.jpg` shows, for every shot, the frame picked as the deepest
bend and the frame picked as the release, with the skeleton drawn. On the first rows of
`r1` and `s1` the bend frame is the crouch with the ball at the waist, the release frame
has the ball one to two ball-widths off the hand, and the shooting arm is the right one.

## Limits

- **No answer key.** The knee number could be off by a steady amount. Two known pulls: the
  hips move back toward the camera in a crouch (reads deeper), and the shooter drifts toward
  the hoop during the jump (reads shallower).
- **Arm angle** uses an average body's arm-to-leg ratio (0.68). For one person that makes it
  steady, but its absolute value can be off by a few degrees.
- **Jump** includes any drift toward the hoop, which lifts the feet in the picture.
- **Elbow** is empty on about a third of shots, and it is one model's 3D guess with nothing
  independent to check it against.
- **The release** is about one frame late: the hand follows the ball for a moment.
- **Not measured:** `s4` at 8.8 s (the ball track is lost, the same shot the detector
  struggles with), the arm on `r1` at 63.1 s, the jump on `s3` at 80.5 s (the clip ends).
- All 63 shots are one camera style and at most two shooters.

## Makes vs misses (a hint, not a finding)

| Number | Makes (32) | Misses (30) |
|---|---|---|
| Knee bend (°) | 97.8 | 105.6 |
| Arm angle at release (°) | 45.8 | 48.6 |
| Jump | 0.25 | 0.25 |
| Flight time (s) | 1.10 | 1.03 |
| Elbow bend (°), 41 shots | 63.2 | 63.3 |

Most of the knee gap comes from one clip: `r1` has a shallower bend (about 120°) and 10 of
its 13 shots are misses. Inside single clips the gap is 0 to 5°. Flight time is a little
longer on makes in 5 of 6 clips.

## A bug the first run caught

The first table gave a 0.3 s flight time and an arm pointing down at the release. The ball
detector sometimes marks the shooter's lowered hand or shoe as a ball after the shot, and
the first release rule took that as the ball being held again. The rule now follows the one
real ball backward from the rim to the hand (`find_release` in `vision/shot_form.py`).
