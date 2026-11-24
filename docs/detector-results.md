# Shot detector results

How well the detector finds shots and calls make or miss, measured against hand labels.
One row is added each time the detector changes.

| Version | Found | Make/miss right | False detections | Fully correct | Run time | What changed |
|---|---|---|---|---|---|---|
| Baseline (release-based) | 21 of 63 (33%) | 18 of 21 (86%) | 1 | 18 of 63 (29%) | 623 s | |

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
