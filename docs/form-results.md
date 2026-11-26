# Shot form: which numbers can be measured from behind

Measured 2026-11-24 on the 6 labeled clips (63 shots), all filmed by hand from behind the
shooter at 30 fps.

- The comparison below (two pose models, several ways to measure each number) was made with
  the first version of `eval/form.py`. To rerun it, check out commit `1822971` and run
  `python -m eval.form`.
- The five kept numbers now come from the real pipeline. Their current figures are in
  [In the real pipeline](#in-the-real-pipeline) at the end.

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
- **One pose model, not two.** Since the elbow needs MediaPipe anyway, the pipeline uses
  MediaPipe's keypoints for all five numbers (Andrew's call). They also pass the bar for
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
  struggles with) and the jump on `s3` at 80.5 s (the clip ends).
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

## In the real pipeline

`process_vid` now measures form itself. Each time a shot is found, a second thread goes
back over the video and runs MediaPipe on only the 2.5 s before that shot (`FormPass` in
`vision/offline_runner.py`), then adds a `form` block to the shot event. The detector
keeps going meanwhile. The keypoints are saved to `pose.jsonl` next to `frames.jsonl`.

Reproduce: a full run in Docker, then the form table from what that run saved.

    docker compose up -d --wait db
    docker compose run --rm -v ./eval:/app/eval -v ./video:/app/video api python -m eval.score
    python -m eval.form

Full Docker run, 6 clips, 2026-11-24. The form numbers were worked out again from that run's
saved files after the fix in [Two shots the ball rule got wrong](#two-shots-the-ball-rule-got-wrong):

| Number | Shots measured | Average | Spread | Wiggle | Makes | Misses |
|---|---|---|---|---|---|---|
| Knee bend (°) | 62 of 63 | 98.7 | 4.7 | 2.0 | 96.2 | 101.5 |
| Elbow bend (°) | 43 of 63 | 63.2 | 3.7 | 3.0 | 63.2 | 63.1 |
| Arm angle at release (°) | 62 of 63 | 46.9 | 2.5 | 1.27 | 46.1 | 47.8 |
| Jump (shoulder-heights) | 61 of 63 | 0.25 | 0.02 | 0.01 | 0.26 | 0.24 |
| Flight time (s) | 62 of 63 | 1.07 | 0.05 | 0.03 | 1.10 | 1.05 |

- **Close to the comparison.** The MediaPipe rows above gave knee 99.0, arm 46.8, jump 0.25,
  flight 1.06 and elbow 63.3 on 41 shots. The small differences are MediaPipe on Linux
  against MediaPipe on the Mac, and the one shot fixed below.
- **The detector is unchanged:** 63 of 63 found, 61 fully correct, 0 false.
- **The elbow's wiggle (3.0°) is close to its spread (3.7°).** Its average is steady, but a
  difference of a few degrees between two shots means nothing.

- **After the second speed round (2026-11-25)** the form pass stops running pose once the ball
  has been out of the hands for 0.35 s, and the frames are read a faster way that makes the
  picture a little darker. The numbers move by about 1° (knee, arm) and 2° (elbow) per shot,
  and their averages stay where they were. The table is in `docs/speed-plan.md`, round 2.

### What it costs

| | Before | With form |
|---|---|---|
| Docker run, 6 clips (7.9 minutes of video) | about 380 s | 608 s |
| Docker image | 2.8 GB | 3.04 GB |

- The form pass took 228 s of the 608 s: 4,719 pose frames at about 48 ms each. The same
  model takes about 12 ms a frame on the Mac outside Docker.
- "Before" is this same run minus its form pass. The 440 s in `docs/detector-results.md` is an
  older single run, and run times here swing a lot with what else the laptop is doing.
- On `longvid.mov` on the Mac: 7 s of a 37 s run.

### Faster options that were tried

Decision (2026-11-24): keep the heavy model on every frame in a second pass. Each faster option
loses the elbow.

Each option was run on the same frames and compared shot by shot with the heavy model, on 69
shots (the 63 labeled plus `longvid.mov`'s 6). Pose time is from a 150-frame timing test in
Docker. The run times are estimates from that test, not full runs.

| Option | Pose time per frame in Docker | Six-clip run | Shots measured | What changes |
|---|---|---|---|---|
| Heavy model, every frame (kept) | 43 ms | 608 s (measured) | 68 of 69 | |
| Full model | 11 ms | about 454 s | 67 of 69 | Knee, arm, jump and flight follow the heavy model (r 0.85 to 0.99). The elbow does not: 89° against 62°, r 0.19. |
| Lite model | 7 ms | about 440 s | 38 of 69 | Fails: the wrists are seen too rarely to find the release. |
| Heavy model, every other frame | 43 ms on half the frames | about 505 s | 66 of 69 | Knee reads 3° shallower. The elbow stops following the every-frame value (r 0.39). |

- **Why Docker is slower than the Mac.** Not a Docker setting: the image runs natively on arm64
  with all 15 cores and the same MediaPipe version, and reading the video is fast. The model
  uses one CPU core in both places. The Mac's chip has matrix instructions (SME2) that the Linux
  machine inside Docker does not get, which is the likely cause but is not proven. A server will
  not have them either, so the Docker speed is the realistic one.
- **No second pass.** A shot is only known about a second after the release, so pose in the first
  pass means pose on every frame: 2,308 frames on `s1` against 750. That is about 100 s with the
  heavy model against 36 s now. YOLO's pose model on every frame takes about 34 s on `s1` (15 ms a
  frame) and cannot give the elbow. Keeping recent frames in memory and running pose when a shot
  fires would save about 4 s a clip and need about 330 MB of memory.

### Two shots the ball rule got wrong

The first pipeline run left one `longvid.mov` shot empty and gave one labeled shot wrong numbers.
Both came from where the walk back to the hand started.

- **The net hid the ball** (`longvid.mov`, the make at 19.3 s). The ball was last seen just
  above the rim and next seen under the net 0.56 s later, which is when the detector says the
  shot happened. The walk started there and gave up, because the ball was missing for more
  than 0.15 s.
- **The hoop box was on the wrong object** (`r1` at 63.1 s). The walk started from the ball
  nearest that frame's hoop box. In about 7% of frames the box is not on the hoop, and here that
  picked the shooter's hand. The shot was saved with a 0.0 s flight time and a 142° knee bend.

Now the walk starts from the ball sighting closest to the rim in the second before the detector's
shot time (`find_arrival` in `vision/shot_form.py`), using the detector's steadied rim, which stays
on the real hoop. If that sighting is more than 0.15 s before the shot time, the shot time is
late and the flight time ends at the sighting.

- `longvid.mov`: 6 of 6 shots measured, was 5 of 6.
- `r1` at 63.1 s: flight 0.83 s, knee 113°, and its elbow and arm are now measured.
- The other 62 labeled shots: no number changed.
- The one-second look-back is not tuned: any value from 0.75 to 2.0 s gives the same numbers on
  all 69 shots. Below 0.56 s the `longvid.mov` shot goes empty again.
- Both cases were found on these clips, so this is a fix checked on the clips that showed the
  problem, not on new ones.
- The jump still reads each frame's own hoop box, to follow the camera as it tilts.

### A clip the rules never saw

`longvid.mov` was not used to choose the five numbers or how they are measured. Uploaded through
the API in Docker, all 6 of its shots got all five numbers: knee 93 to 105°, elbow 41 to 59°,
arm 48 to 53°, jump 0.21 to 0.23, flight 1.07 to 1.17 s. The Mac gives the same within 3°. That
upload took 60 s, 22 s of it the form pass. The first run measured 5 of the 6. The sixth needed
the fix above, so that one shot is no longer unseen.
