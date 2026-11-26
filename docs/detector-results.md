# Shot detector results

How well the detector finds shots and calls make or miss, measured against hand labels.
One row is added each time the detector changes.

| Version | Found | Make/miss right | False detections | Fully correct | Run time | What changed |
|---|---|---|---|---|---|---|
| Baseline (release-based) | 21 of 63 (33%) | 18 of 21 (86%) | 1 | 18 of 63 (29%) | 623 s | |
| Rim-based shots | 63 of 63 (100%) | 57 of 63 (90%) | 0 | 57 of 63 (90%) | 530 s | Shots are found at the rim instead of at the release. Pose model no longer runs. |
| Bounce and width rules | 63 of 63 (100%) | 61 of 63 (97%) | 0 | 61 of 63 (97%) | not timed | A ball that bounces up off the rim is a miss. A sliver of a ball under the rim does not count. Scored by replay, not a full run. |
| Smaller YOLO images | 63 of 63 (100%) | 61 of 63 (97%) | 0 | 61 of 63 (97%) | 440 s | Full frame 960 to 640, zoomed-in crops 640 to 448. Full Docker run with both changes. |
| Speed changes | 63 of 63 (100%) | 61 of 63 (97%) | 0 | 61 of 63 (97%) | 747 s on 2 CPUs (903 s before) | No detector change. One video encode instead of two, and the form pass and the full-frame detector run in their own threads. Every saved number is identical to the run before. See `docs/speed-plan.md`. |
| Frame skipping | 62 of 63 (98%) | 60 of 62 (97%) | 0 | 60 of 63 (95%) | 418 s on 2 CPUs (757 s before) | The detector looks at every 4th frame, and at every frame while a shot is on its way. Frames are read through ffmpeg, the ball crop is gone and a flat box no longer counts as a ball. The lost shot is an airball in `s4.mov` that leaves the picture at rim height. See `docs/speed-plan.md`, round 2. |
| Server speed round | 62 of 63 (98%) | 60 of 62 (97%) | 0 | 60 of 63 (95%) | 480 s on the EC2 server (779 s before) | No rule change. The video is read once and shrunk by ffmpeg, the annotated video is 540p, and the detector runs in 16-bit floats on the server. Same shots right and wrong as the row above. See `docs/speed-plan.md`, round 3. |

- **Found:** real shots the detector reported, within 2 seconds of the labeled time.
- **Make/miss right:** found shots where the make or miss call matches the label.
- **False detections:** shots the detector reported that did not happen.
- **Fully correct:** shots that were found and called right, out of all real shots.
- **Run time:** seconds the detector took for all 6 clips (472 seconds of video). The rows
  down to "Smaller YOLO images" were run with all 15 laptop CPUs and before the form pass
  existed. The "Speed changes" row is with the container pinned to 2 CPUs, like the server,
  and includes the form pass. Its "before" run was made the same hour on the same 2 CPUs.
  Before, the H.264 conversion came on top of this number. Now it is inside it.
  The "Server speed round" row is the first one timed on the EC2 server itself (one real
  core), so its seconds cannot be compared with the laptop rows above it.

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

## Bounce and width rules, smaller YOLO images

Two changes, measured together in one full Docker run (63 found, 61 fully correct, 0 false
detections, 440 s):

- **Bounce rule:** after the ball reaches the rim, if its centre goes more than 0.3
  hoop-heights back above the rim line, the shot is a miss. This fixed the three r1 shots
  that fell behind the rim. The cost is that a shot which bounces on the rim and then drops
  in would also be called a miss. None of the 63 shots does that, so this score does not
  show it.
- **Width rule:** a ball box narrower than 0.3 hoop-widths does not count as the ball under
  the rim. This fixed s4 at 28.2 s. It rests on that one shot.
- **Smaller images:** the full frame runs at 640 instead of 960 and the zoomed-in crops at
  448 instead of 640. The crops are about 300 by 430 pixels, so scaling them up to 640
  cost more than the full frame.

Run time went from 623 s (baseline) to 530 s (rim-based shots) to 440 s. Run times vary
between runs, so treat these as rough.

Still wrong: r1 at 8.6 and 71.3 s, both misses called makes. The ball is seen twice at the
edge of the area under the rim on its way out, which looks the same as some real makes.

On the Mac, the smaller images lost one shot (s4 at 8.8 s) that is only found when the
ball's bottom edge lands exactly on the rim line. The Docker run found it.

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
