# Shot detector results

How well the detector finds shots and calls make or miss, measured against hand labels.
One row is added each time the detector changes.

| Version | Found | Make/miss right | False detections | Fully correct | Run time | What changed |
|---|---|---|---|---|---|---|
| Baseline (release-based) | 21 of 63 (33%) | 18 of 21 (86%) | 1 | 18 of 63 (29%) | 623 s | |
| Rim-based shots | 63 of 63 (100%) | 57 of 63 (90%) | 0 | 57 of 63 (90%) | 530 s | Shots are found at the rim instead of at the release. Pose model no longer runs. |

- **Found:** real shots the detector reported, within 2 seconds of the labeled time.
- **Make/miss right:** found shots where the make or miss call matches the label.
- **False detections:** shots the detector reported that did not happen.
- **Fully correct:** shots that were found and called right, out of all real shots.
- **Run time:** seconds the detector took for all 6 clips (472 seconds of video).

## Setup

- 6 self-recorded clips, 63 shots (32 makes, 31 misses), portrait 720x1280 at 30 fps,
  filmed handheld. The clips are not in git. The labels are in `eval/labels.csv`.
- The time in a label is when the ball first reaches the rim.
- Run in Docker on an Apple M5 Pro laptop, with the same settings the website uses:

  ```
  docker compose up -d --wait db
  docker compose run --rm -v ./eval:/app/eval -v ./video:/app/video api python -m eval.score
  ```

- Accuracy is the same on every run. Run time is not: a second baseline run with other
  apps open took 1293 s. Speed is only compared between runs made with other apps closed.

## Rim-based shots

The baseline only counted a shot after the pose model saw a release (ball leaving the
wrist above the head). That release was missed for most shots, so the rim was never
checked, even though YOLO saw the ball in about 90% of the frames around each shot.

`vision/rim_shot_detector.py` drops the release step. A shot is the ball coming down from
above the rim to rim level near the hoop. A make is the ball then seen at least twice
straight below the rim, in the net or dropping out of it.

| Clip | Real shots | Found | Make/miss right | Missed | False detections |
|---|---|---|---|---|---|
| r1.mov | 13 | 13 | 8 | 0 | 0 |
| s1.mov | 10 | 10 | 10 | 0 | 0 |
| s2.mov | 9 | 9 | 9 | 0 | 0 |
| s3.mov | 11 | 11 | 11 | 0 | 0 |
| s4.mov | 10 | 10 | 9 | 0 | 0 |
| s5.mov | 10 | 10 | 10 | 0 | 0 |
| Total | 63 | 63 | 57 | 0 | 0 |

The rules were worked out on these same 6 clips, so this score is optimistic. The number
to trust will come from clips recorded afterwards.

What worked:

- Finding shots at the rim. Every threshold is in hoop-widths, hoop-heights or seconds.
  Moving each of the 7 thresholds 25% up and down gave the same score all 14 times.
- Counting the ball just under the net as well as inside it. The net often hides the ball
  until it drops out.
- Watching the rim for 1.5 seconds. Two makes took more than 0.8 seconds to show up below
  the rim.
- Deciding a shot that is still in progress when the video ends. Two clips end less than
  a second after the last shot.

What did not work:

- Counting any ball below rim level as "reached the rim". A second ball lying on the
  ground under the hoop started a false shot.
- Telling makes from misses by how fast the ball drops. It was worse than counting
  sightings on these clips.

Still wrong (6 shots, all misses called makes):

- r1 at 15.7, 57.5 and 63.2 s: the ball bounces and falls behind the rim, and from that
  camera angle it is seen through the net.
- r1 at 8.6 and 71.3 s and s4 at 28.2 s: the ball is seen twice at the edge of the area
  under the rim on its way out sideways. Makes are seen there 3 to 18 times, so
  needing 3 sightings would fix these 3, but two makes are seen exactly 3 times, which
  leaves no margin.

## Baseline by clip

| Clip | Real shots | Found | Make/miss right | Missed | False detections |
|---|---|---|---|---|---|
| r1.mov | 13 | 4 | 3 | 9 | 1 |
| s1.mov | 10 | 5 | 3 | 5 | 0 |
| s2.mov | 9 | 2 | 2 | 7 | 0 |
| s3.mov | 11 | 2 | 2 | 9 | 0 |
| s4.mov | 10 | 2 | 2 | 8 | 0 |
| s5.mov | 10 | 6 | 6 | 4 | 0 |
| Total | 63 | 21 | 18 | 42 | 1 |
