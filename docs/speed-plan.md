# Speed plan: faster video processing on the server

The goal was to make one uploaded video finish as fast as possible on the real server
(Docker on a 2 vCPU, 4 GB Intel EC2 `c7i-flex.large`) without changing what the detector
finds or what the form numbers say.

## Result in one table

`longvid.mov` (47 s of video, 6 shots), upload to finished, same code path as the website.

| | Before | After | Change |
|---|---|---|---|
| Container pinned to 2 CPUs | 109 s | 76 s | 30% less time (1.44x faster) |
| Container pinned to 1 CPU | 165 s | 135 s | 18% less time (1.23x faster) |
| Peak memory | 877 MB | 969 MB | +92 MB |
| Annotated video file | 15.4 MB | 10.9 MB | smaller |
| Shots, form numbers, form pictures | | | identical, on all 7 clips |

- Machine: Docker on an Apple M5 Pro laptop. **Not measured on the EC2 server yet.**
- The six-clip accuracy check is unchanged: 63 found, 61 fully correct, 0 false.
- Each number is the average of two back-to-back runs (109.1 and 109.4 s before, 76.0 and
  76.2 s after). The 1 CPU numbers are one run each.

## How everything here was measured

- Clip: `longvid.mov` (47 s, 1431 frames, 6 shots, portrait 720x1280, HEVC 10-bit).
- Path: the same function the API runs for an upload (`run_processing_job` in
  `backend/app.py`), so the H.264 step is included.
- Machine: Docker on an Apple M5 Pro laptop, container pinned to 2 CPUs and 4 GB
  (`--cpuset-cpus 0,1 --memory 4g`). Pinning matters: with a plain `--cpus 2` limit the
  code still sees all 15 laptop CPUs and starts too many threads.
- **This is a stand-in for the server, not the server.** The laptop is ARM and the
  container gets 2 real cores. The server is Intel and its 2 vCPUs are two hyperthreads of
  **one** real core. A hyperthread is a second lane on the same core. It is worth roughly
  20 to 30% extra, not 100%.
- That is why there is also a 1 CPU column. Most of the gain comes from doing things at the
  same time, which needs spare CPU. The server should land somewhere between the 1 CPU
  result (18%) and the 2 CPU result (30%).
- Runs are only compared back to back. Repeat runs differ by under 1 s.
- "Identical" means: every number in `frames.jsonl` (except `yolo_fps`, which is a
  stopwatch reading), `pose.jsonl` and `shot_events.jsonl` is equal, and the form pictures
  are the same bytes.

## Where the time went before

| Stage | 2 CPUs | 1 CPU | What it is |
|---|---|---|---|
| Ball detector | 46 s | 75 s | YOLO on the full frame plus zoomed-in crops, 2302 model runs |
| Form pass | 25 s | 29 s | MediaPipe pose on the 2.5 s before each shot (450 frames) |
| H.264 conversion | 17 s | 30 s | ffmpeg re-encodes the whole annotated video |
| Read frames | 14 s | 22 s | Decode the video and turn each frame into a BGR picture |
| Write video (mp4v) | 4 s | 4 s | OpenCV's first encode of the annotated video |
| Form pictures | 3 s | 4 s | The cropped pictures for each form number |
| Drawing, tracking, JSON, loading | 2 s | 2 s | |
| **Whole job** | **109 s** | **165 s** | |

What a closer look inside the stages showed (2 CPUs):

- **The detector is almost pure model time.** One full-frame run is 21.1 ms, of which
  19.8 ms is the model itself. Ultralytics' own Python work around it is about 1.2 ms.
- **OpenVINO settings do not help.** Same speed with CPU pinning off. One thread is 1.8x
  slower. A fixed input shape is not faster (19.1 against 18.0 ms) and moves the output
  numbers (largest difference 0.008).
- **Reading a frame costs 10.4 ms, but decoding is only 1.4 ms of it.** The other 9 ms is
  turning the 10-bit iPhone picture into the 8-bit BGR picture OpenCV hands back, plus
  rotating it. One thread.
- **The pose model uses one thread** (48 ms a frame). MediaPipe's Python package has no
  setting for more.
- So the old pipeline did one thing at a time, and about half of those things can only use
  one CPU. While they ran, the second CPU sat idle.

On the real server the same clip took 171 s of processing plus 40 s of H.264 conversion
before these changes (`docs/deploy.md`, measured when it was deployed). So the server is
about twice as slow as the laptop stand-in, and the H.264 step was a bigger share there.

## What was built (all give identical results)

Each row was timed back to back against the row above it.

| # | Change | 2 CPUs | 1 CPU | Where |
|---|---|---|---|---|
| | Start | 111 s | 167 s | |
| 1 | **Encode the video once.** The drawn frames are piped straight into one ffmpeg H.264 encode (`-preset veryfast`) that runs next to the detector. Before, OpenCV wrote `mp4v` and ffmpeg then re-encoded the whole file. | 96 s | | `vision/video_writer.py`, `backend/app.py` |
| 2 | **Form pass in a second thread.** Each shot is handed to a worker thread as soon as it is found, instead of after the whole video. One thread, shots in order, so the pose model sees the same frames in the same order. | 83 s | 141 s | `FormPass` in `vision/offline_runner.py` |
| 3 | **Full-frame detector one frame ahead.** The full-frame pass needs nothing from the frame before. A helper thread reads the next frame and runs it while the main loop does the current frame's crops, tracking and drawing. Needs a second copy of the model (+92 MB). | 76 s | 135 s | `read_frame` in `vision/offline_runner.py`, `detect_full_frame` in `vision/yolo_detector.py` |
| 4 | **Dockerfile layer order.** The model conversion now comes before the code is copied, so a code-only change does not redo it. No effect on processing speed. | | | `Dockerfile` |

(The start row is from the first day's runs, 110 and 112 s. The final back-to-back runs
gave 109 s for the same old image.)

Checks after the changes:

- `longvid.mov`: identical, on 2 CPUs and on 1 CPU.
- Six eval clips (`eval/score.py` in Docker, 2 CPUs): 63 found, 61 fully correct, 0 false.
  All six clips identical to a baseline run made the same hour. The run took 747 s against
  903 s before. That "before" does not even include the H.264 conversion, because the eval
  calls the detector directly and the conversion used to happen afterwards in the API.
- Natively on the Mac (GPU path): change 3 gives identical results, 30 s to 27 s.
- `pytest`: 82 passed.

Things to know about the new code:

- The stages in `timings.json` now overlap, so they add up to more than `total`.
- `yolo_fps` in `frames.jsonl` now only covers the crops, since the full frame runs in the
  helper thread.
- The video is one compression generation better than before (no `mp4v` step in between).

## Tried and dropped

| Idea | What was measured | Why dropped |
|---|---|---|
| Read one frame ahead, without the detector | 82.6 s against 82.2 and 83.1 s without it | No gain. Both CPUs were already busy. It only pays off together with the full-frame pass (change 3). |
| Run ffmpeg at low priority (`nice`) | 82.8 s against 82.2 and 83.1 s without it | No gain. |
| One OpenVINO thread per model for change 3 | 96 s against 77 s with the default | Slower. |
| Faster x264 presets | `veryfast` 10.0 MB at 10 CPU-seconds. `superfast` 17.7 MB at 7. `ultrafast` 39.7 MB at 6. | `veryfast` is the sweet spot. The default (`medium`) costs 29 CPU-seconds for 11.0 MB. |
| 8-bit model (INT8) on the laptop | 2071 ms a frame against 19 ms | The ARM laptop cannot run it properly, so it cannot be tested here. See below. |
| Trim Ultralytics' Python overhead | 1.2 ms of a 21 ms call | Nothing to win. |
| Remove the unused `plot()` in `yolo_detector.py` | 0.4 ms a frame | 0.5 s a clip. Not worth touching. |
| OpenVINO threads, pinning, fixed shapes | No gain | Fixed shapes also move the outputs. |

Looked at on paper only, and not built:

- **More threads for MediaPipe.** Not possible from Python. It would need a custom build.
- **Lighter pose model, or pose on every other frame.** Already turned down: they change
  the elbow number.
- **Pose model through OpenVINO.** Not bit-identical, and MediaPipe's own tracking and
  smoothing would have to be rewritten.
- **Detect every N frames and let the tracker fill in.** The papers (Detect to Track,
  FGFA, Detect or Track) show it works for big slow objects and loses badly on small fast
  ones. The make rule needs the ball seen twice under the rim, which is only a few frames.
- **Skip frames where nothing moves** (NoScope, Reducto). Built for fixed cameras. This one
  is handheld.
- **Keep recent frames in memory so the form pass does not read the video again.** Saves
  about 6 CPU-seconds a clip for about 330 MB of memory, and the memory can grow if shots
  come quickly. Not worth the risk on a 4 GB server.
- **Draw the form pictures in the form thread.** About 3 s on 2 CPUs, nothing on 1.

## Still on the table: needs Andrew's decision

### 1. Measure on the real server (free)

Nothing above was timed on EC2. After the next deploy, upload `longvid.mov` to the live
site, then on the server:

```bash
cat /srv/courtiq/storage/results/<session id>/timings.json
```

`total` in that file is the whole job now (there is no separate H.264 step). Compare it
with the 171 + 40 = 211 s measured before.

### 2. 16-bit floats on the server (faster, but it changed a result once)

- The server's chip has AMX, a feature that runs 16-bit maths (bf16) much faster.
  `with_full_precision()` in `vision/yolo_detector.py` turns it off on purpose.
- Measured on the server when it was deployed (`docs/deploy.md`): the detector took 48 s
  with bf16 and 79 s without. That is 31 s on one clip, more than everything in this plan.
- The cost, also measured then: the `longvid.mov` shot at 10.6 s flipped from miss to make.
- Not known: whether the six-clip score (63, 61, 0) survives bf16. That is one eval run on
  the server. If it does not survive, this is closed for good.

### 3. A server with 2 real cores (costs money)

| Type | Real cores | $ per month (730 h, us-east-2) | Note |
|---|---|---|---|
| `c7i-flex.large` (now) | 1 (2 hyperthreads) | 61.90 | |
| `c7a.large` | 2 | 74.93 | AMD, no hyperthreading |
| `c8a.large` | 2 | 78.67 | Newer AMD. Geekbench 6: about +30% single-core, +90% multi-core against the current one |
| `c7i-flex.xlarge` | 2 (4 hyperthreads) | 123.79 | Same chip, double everything |

- The new pipeline runs four things at once (helper thread, main loop, form thread,
  ffmpeg). With 2 real cores it should behave like the "2 CPUs" column above. With 1 real
  core it is closer to the "1 CPU" column.
- A different chip can change detector numbers in the last decimal places, so the six-clip
  eval has to be re-run after a switch.
- Prices were read from AWS and Vantage pages on 2026-11-25. How much faster CourtIQ is on
  each type has not been measured.

### 4. Other ideas that change results (not recommended without the eval)

- **8-bit model (INT8).** Intel's benchmark for a YOLO nano model on this chip family
  shows 2.6x. Published accuracy loss for nano models is 0.5 to 2.7 mAP. It needs fixed
  input shapes on this chip (OpenVINO issue 37577), which change the detections too. Can
  only be tested on EC2.
- **Full frame every 2nd or 3rd frame while the ball is tracked**
  (`OFFLINE_FULL_FRAME_INTERVAL`), or crops at 384 instead of 448. Estimated 1.1 to 1.25x
  on the detector. Changes detections.

## CI/CD

- Nothing here needs a new package, model file, setting or environment variable. ffmpeg is
  already in the image and in the CI test job. `.github/workflows/ci.yml` and
  `deploy/redeploy.sh` ship it unchanged.
- The Dockerfile layer order (change 4) only helps where Docker keeps layers between
  builds, which GitHub's runners do not do by default.
- **Not done, because it cannot be tested without pushing: a build cache for the deploy
  job.** Today every deploy rebuilds every layer from nothing, so the server most likely
  downloads close to the whole 3 GB image each time. Replacing the `docker build` and
  `docker push` lines with this would let unchanged layers (PyTorch, the pip installs, the
  model conversion) be reused, so the server only pulls what changed:

  ```yaml
      - uses: docker/setup-buildx-action@v4
      - uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ${{ steps.ecr.outputs.registry }}/courtiq:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: false
  ```

  Free on GitHub (10 GB limit, entries unused for 7 days are deleted). This YAML has not
  been run.

## Round 2: about twice as fast, with results allowed to change

Measured 2026-11-25. The goal changed for this round: speed comes first, and results no
longer have to stay identical. The floor is 90% of the labelled shots fully correct.

### Result in one table

| | Before (main) | After | Change |
|---|---|---|---|
| Six eval clips, 2 CPUs | 757 s | 418 s | 45% less time (1.8x faster) |
| `longvid.mov`, 2 CPUs | 80 s | 42 s | 47% less time (1.9x faster) |
| `longvid.mov`, 1 CPU | 136 s | 71 s | 48% less time (1.9x faster) |
| CPU-seconds, six clips | 1,422 | 774 | |
| Shots fully correct, six clips | 61 of 63 (97%) | 60 of 63 (95%) | one shot lost |
| Shots fully correct, `longvid.mov` | 6 of 6 | 5 of 6 | one miss called a make |
| False shots | 0 | 0 | |
| Frames the detector looks at | 100% | 40% | |
| Frames the pose model looks at, six clips | 4,709 | 3,431 | |
| Frames with the ring on the ball, six clips | 81% | 76% | |
| Peak memory, `longvid.mov` | 922 MB | 1,107 MB | |
| Annotated video, `longvid.mov` | 7.6 MB | 5.8 MB | |

- Machine: the same stand-in as above. Docker on an Apple M5 Pro laptop, container pinned
  with `--cpuset-cpus`. **Not measured on the EC2 server yet.**
- "Before" is `main` after the first speed round and the new overlay, timed the same hour.
- `longvid.mov` on 2 CPUs was run twice after the changes: 42.2 and 42.0 s. Everything else
  is one run.
- CPU-seconds is the work added up over every thread and both ffmpeg processes. On the
  server's single real core that number matters more than the 2 CPU time.
- Peak memory here includes files the system keeps in memory, so it reads higher than the
  877 and 969 MB at the top of this page.

### What was built

| # | Change | Where |
|---|---|---|
| 1 | **Frames are read through ffmpeg.** OpenCV took 10.4 ms a frame on iPhone clips, 9 ms of it turning the 10-bit HDR picture into a normal one. ffmpeg hands over plain 8-bit YUV and OpenCV turns that into BGR: 2.8 ms a frame. The picture comes out a little darker, because OpenCV was also brightening the HDR picture. | `vision/video_reader.py` |
| 2 | **The detector looks at every 4th frame, and at every frame while a shot is on its way.** "On its way" is the rule the rim crop already used: the ball was seen high above the rim in the last second, or a shot is being watched. On the skipped frames the Kalman tracker predicts where the ball is. | `DETECT_EVERY` and `read_frame` in `vision/offline_runner.py` |
| 3 | **Only one zoomed-in crop is left, the one on the rim.** The crop that followed the ball is gone. With it the score was the same, the form numbers were within noise, and the ring was on the ball in 3% more frames. | `vision/offline_runner.py` |
| 4 | **A flat box is not a ball.** With frames skipped, the model twice called a flat strip at the edge of a crop a ball (once on the rim, once on a roof beside it), and at rim height that started a shot early. A box under half as tall as it is wide is now ignored. | `MIN_BALL_HEIGHT` in `vision/rim_shot_detector.py` |
| 5 | **The form pass fills in the frames the detector skipped, and stops once the ball is in the air.** The release is found from the ball's position on every frame, so the form pass runs the ball detector on its own frames where the main loop did not. Pose stops 0.35 s after the ball leaves the hands, because no number is read later than that. | `FormPass` in `vision/offline_runner.py`, `ball_in_hand` in `vision/shot_form.py` |
| 6 | **The ring rides the tracker's prediction over skipped frames**, so it does not blink. | `vision/overlay.py` |

### What it costs

- **One labelled shot is lost.** `s4.mov` at 8.8 s is an airball that leaves the picture at
  rim height. The old code only caught it from a 13-pixel slice of ball that the ball crop
  found. Almost every change tried here lost it, on its own.
- **One `longvid.mov` miss is called a make** (10.6 s). The ball drops just beside the net.
  The old code saw it below the rim once, the new code twice, and two sightings is a make.
- **The video looks different.** It is a little darker and less washed out, and the ring is
  on the ball in 76% of frames against 81%. While the shot is in the air it is on 75% of
  frames. The loss is mostly while the shooter is holding the ball.
- **The form numbers move a little.** Same shots, compared one by one with `main`:

  | Number | Shots measured before | After | Average change | Largest change |
  |---|---|---|---|---|
  | Knee bend (°) | 62 | 62 | 1.0 | 3.1 |
  | Elbow bend (°) | 43 | 42 | 2.3 | 10.6 |
  | Arm angle (°) | 62 | 62 | 1.2 | 5.2 |
  | Jump (shoulder-heights) | 61 | 62 | 0.007 | 0.03 |
  | Flight time (s) | 62 | 62 | 0.009 | 0.10 |

  The averages over all shots barely move (knee 98.7 to 99.4, elbow 63.1 to 62.8, arm 46.9
  to 47.1). Stopping pose early changes nothing by itself: on saved pose data 0 of 63 shots
  changed. The rest is the pose model and the ball detector seeing a slightly different picture.

### Every option that was measured

Shots only (no pose, no video), six clips, each run once. "Runs per frame" is how many times
the YOLO model runs per video frame, which is what the detector's time follows.

| Option | Fully correct | Runs per frame | Note |
|---|---|---|---|
| Start (first speed round) | 61 of 63 | 1.54 | |
| ffmpeg frame reader | 60 | 1.48 | loses the `s4` airball |
| Detector every 2nd frame | 60 | 0.96 | a flat box started one shot early |
| Detector every 3rd frame | 60 | 0.76 | same, on another shot |
| Detector every 4th frame | 61 | 0.66 | |
| No ball crop | 60 | 1.12 | loses the `s4` airball |
| Full frame at 512 | 61 | 1.54 | each full frame takes 11.6 ms against 18.4 |
| Full frame at 416 | 51 | 1.56 | misses 9 shots |
| Crops at 384 | 60 | 1.51 | |
| Crops at 320 | 60 | 1.49 | |

With the flat-box rule added:

| Option | Fully correct | Runs per frame | Ring on the ball |
|---|---|---|---|
| Every 4th frame, full 512, crops 320 | 61 | 0.64 | 56% |
| Every 8th frame, full 512, crops 320 | 61 | 0.48 | 33% |
| Every 4th, rim crop only while a shot arrives | 60 | 0.50 | 56% |
| The same with no ball crop | 60 | 0.43 | 50% |
| Every 8th, rim crop only while a shot arrives | 60 | 0.33 | |
| Every 4th, rim crop only while a shot arrives, ffmpeg reader | 60 | 0.50 | 58% |
| The same, picture brightened back with a lookup table | 60 | 0.51 | |
| Every 4th, full 640, crop 320, no ball crop | 60 | 0.52 | 76% |
| The same, plus look again right after losing the ball | 60 | 0.60 | 79% |
| Look-again rule, full 576 | 61 | 0.63 | 67% |
| Every 2nd, full 640 | 60 | 0.72 | 81% |
| **Every 4th, full 640, rim crop 448, no ball crop (kept)** | **60** | | **76%** |

The score moves by one shot from run to run of nearly the same settings, so 60 against 61
is inside the noise of a 63-shot test. The ring is what told the options apart: a 512 full
frame loses the ball about a third of the time when the shooter is holding it.

Whole pipeline on `longvid.mov`, 2 CPUs, one run each unless noted:

| Option | Time | CPU-seconds | Shots right |
|---|---|---|---|
| `main` | 80 s | 151 | 6 of 6 |
| Every 4th, full 512, crops 320, only the rim crop while a shot arrives, form window 2.0 s | 34 s | 61 | 6 of 6 |
| The same, every 8th | 32 s | 52 | 6 of 6 |
| Every 4th, full 512, crop 320, form window back to 2.5 s | 36 s (two runs) | 65 | 6 of 6 |
| Every 4th, full 640, crop 320 | 40 s (two runs) | 74 | 5 of 6 |
| **Every 4th, full 640, crop 448 (kept)** | **42 s (two runs)** | **77** | **5 of 6** |

### Tried and dropped

| Idea | What was measured | Why dropped |
|---|---|---|
| Full frame at 512 | 36 s against 42 s on `longvid.mov`, same six-clip score | The ring is on the ball in 52% of frames against 76%. This is the one to flip if speed matters more than the ring. |
| Pose on every other frame | Knee moves 3.5° on average on saved pose data | More than half its shot-to-shot spread. |
| Form window 2.0 s in place of 2.5 s | Two knee numbers jumped by 11° and 25° | The pose model's first frames of each shot are unsteady, and at 2.0 s they fall inside the knee search. |
| Brightening the ffmpeg picture back to OpenCV's look | Same score with and without | No gain for the extra code. |
| Detector every 8th frame | 2 s faster on `longvid.mov` | The ring is on the ball in a third of the frames. |
| Looking again right after the tracker loses the ball | Ring 79% against 76% for 15% more model runs | Not worth the extra rule. |
| Faster x264 presets, or handing ffmpeg YUV in place of BGR | About 1 ms a frame at best | Bigger files for almost nothing. |
| A lighter pose model | Not run again | Already measured in `docs/form-results.md`: it loses the elbow. |

### Still on the table

- **Measure on EC2.** Same as before: upload `longvid.mov` after the deploy and read
  `timings.json`. The server's chip is different, so the gain there may be larger or smaller
  than 1.9x.
- **16-bit floats on the server** (section 2 above). The reason it was turned off was one
  flipped `longvid.mov` shot. With the new floor of 90% it may be allowed back, but it needs
  one six-clip eval on the server first.
- **60 fps uploads cost double.** Everything counts frames, so a 60 fps clip runs pose and
  the detector twice as often per second of video. Capping both at 30 a second is a small
  change that has not been tried.
- **The video is still decoded twice** (once for the detector, once for the form pass):
  an estimated 6 of the 77 CPU-seconds on `longvid.mov`. Keeping recent frames in memory
  would remove it for 150 MB or more.
- **The form pictures read the video a third time with OpenCV**: 2.7 s on `longvid.mov`, and
  they keep OpenCV's brighter look.
