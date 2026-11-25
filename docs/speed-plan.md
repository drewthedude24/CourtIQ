# Speed plan: faster video processing on the server

The goal is to make one uploaded video finish as fast as possible on the real server
(Docker on a 2 vCPU, 4 GB Intel EC2 `c7i-flex.large`) without changing what the detector
finds or what the form numbers say.

## How everything here was measured

- Clip: `longvid.mov` (47 s, 1431 frames, 6 shots, portrait 720x1280, HEVC 10-bit).
- Path: the same function the API runs for an upload (`run_processing_job` in
  `backend/app.py`), so the H.264 step is included.
- Machine: Docker on an Apple M5 Pro laptop, container pinned to 2 CPUs and 4 GB
  (`--cpuset-cpus 0,1 --memory 4g`). Pinning matters: with a plain `--cpus 2` limit the
  code still sees all 15 laptop CPUs and starts too many threads.
- **This is a stand-in for the server, not the server.** The laptop is ARM and has 2 real
  cores in the container. The server is Intel and its 2 vCPUs are two hyperthreads of
  **one** real core (a hyperthread is a second lane on the same core, worth roughly 20 to
  30% extra, not 100%). So anything that wins by "using the second core" will win less on
  the server. Nothing here has been measured on EC2 yet.
- Runs are only compared back to back. Two baseline runs gave 110.2 s and 112.1 s, so
  differences under about 2 s are noise.

## Baseline (before any change)

| Stage | 2 CPUs | 1 CPU | What it is |
|---|---|---|---|
| Ball detector | 46.5 s | 76.0 s | YOLO on the full frame plus zoomed-in crops, 2302 model runs |
| Form pass | 25.8 s | 29.1 s | MediaPipe pose on the 2.5 s before each shot (450 frames) |
| H.264 conversion | 17.1 s | 31.1 s | ffmpeg re-encodes the whole annotated video |
| Read frames | 14.1 s | 21.6 s | Decode the video and turn each frame into a BGR picture |
| Write video (mp4v) | 3.9 s | 3.9 s | OpenCV's first encode of the annotated video |
| Form pictures | 2.7 s | 3.9 s | The cropped pictures for each form number |
| Drawing, tracking, JSON | 1.0 s | 1.0 s | |
| **Whole job** | **111 s** | **167 s** | |

What a closer look inside the stages showed (2 CPUs):

- **The detector is almost pure model time.** One full-frame run is 21.1 ms, of which
  19.8 ms is the model itself. Ultralytics' own Python work around it is about 1.2 ms, and
  the unused `plot()` call is 0.4 ms. So there is nothing to win by trimming Python there.
- **OpenVINO settings do not help.** Same speed with CPU pinning off. One thread is 1.8x
  slower. A fixed input shape is not faster (19.1 against 18.0 ms) and moves the output
  numbers slightly (largest difference 0.008), so it was dropped.
- **Reading a frame costs 10.4 ms, but decoding is only 1.4 ms of it.** The other 9 ms is
  turning the 10-bit iPhone picture into the 8-bit BGR picture OpenCV hands back, plus
  rotating it. That work is single-threaded.
- **The pose model uses one thread.** 48 ms a frame, and the form pass is barely slower on
  1 CPU than on 2. MediaPipe's Python package has no setting for more threads (checked in
  its source by the research pass).
- So the pipeline today does one thing at a time, and about half of those things can only
  use one CPU. While they run, the second CPU sits idle.

## The plan, ranked

### Group A: same results, build now

| # | Idea | Expected gain (2 CPU stand-in) | Risk to results | Effort | Proof |
|---|---|---|---|---|---|
| A1 | **Encode the video once.** Pipe the drawn frames straight into one ffmpeg H.264 encode (`-preset veryfast`) instead of OpenCV `mp4v` and then a second ffmpeg pass. | About 15 s (removes 3.9 + 17.1 s, adds one cheap encode) | None for shots and form. The video is one compression generation better. File size may change. | Small | Timed back to back. `frames.jsonl`, `pose.jsonl`, `shot_events.jsonl` identical to baseline. Video plays, is H.264, same frame count. |
| A2 | **Run the form pass while the detector is still going.** A second thread starts on a shot's 2.5 s as soon as the shot is known, instead of waiting for the whole video. Same frames in the same order, so the same numbers. | Up to about 20 s | None if the pose model sees the same frames in the same order. Proved by comparing `pose.jsonl`. | Medium | `pose.jsonl` and `shot_events.jsonl` identical to baseline. |
| A3 | **Read one frame ahead.** A helper thread decodes and converts the next frame while the detector works on the current one. | Up to about 10 s | None. Same OpenCV call, same pixels. | Small | `frames.jsonl` identical to baseline. |
| A4 | **Dockerfile layer order.** Convert the model before copying the code, so a code-only change does not redo the conversion. | No change to processing. Quicker rebuilds. | None | Tiny | Image builds, eval passes in it. |

After each one: time it back to back, compare every output file with the baseline, run
`eval/score.py` in Docker (must stay 63 found, 61 fully correct, 0 false), check the form
numbers, run pytest.

### Group B: faster, but they change results. Andrew decides, and they need EC2

These cannot even be timed on the laptop, because they depend on Intel-only chip features.

| # | Idea | What the sources say | Why it is not in group A |
|---|---|---|---|
| B1 | **Let OpenVINO use 16-bit floats (bf16) on the server.** The server's chip has AMX, a feature that runs 16-bit maths much faster. `with_full_precision()` in `vision/yolo_detector.py` turns it off on purpose. | Intel's own benchmark for a YOLO nano model on this chip family: 938 frames a second in 32-bit, 2433 in bf16 (2.6x). | It already flipped one `longvid.mov` shot from miss to make, which is why it was turned off. Worth one test on EC2 against the 63-shot eval before ruling it out for good. |
| B2 | **8-bit model (INT8 quantization).** | Same Intel benchmark: 2401 frames a second (2.6x). Published accuracy loss for nano models: 0.5 to 2.7 mAP. | Changes detections. Needs fixed input shapes on this chip (OpenVINO issue 37577), which also change detections. On the ARM laptop it ran 100x slower (2071 ms a frame against 19 ms), so it can only be tested on EC2. |
| B3 | **Run the full frame less often** (`OFFLINE_FULL_FRAME_INTERVAL` 2 or 3 while the ball is tracked), or smaller crops (384 instead of 448). | Research estimate 1.1 to 1.25x on the detector. | Changes detections. A made ball is only under the rim for a few frames, so missing frames can turn makes into misses. |

### Group C: the server itself (costs money, Andrew decides)

| Type | Real cores | $ per month (730 h, us-east-2) | Note |
|---|---|---|---|
| `c7i-flex.large` (now) | 1 (2 hyperthreads) | 61.90 | |
| `c7a.large` | 2 | 74.93 | AMD, no hyperthreading |
| `c8a.large` | 2 | 78.67 | Newer AMD. Geekbench: about +30% single-core, +90% multi-core against the current one |
| `c7i-flex.xlarge` | 2 (4 hyperthreads) | 123.79 | Same chip, double everything |

- Group A makes the pipeline run several things at once. That pays off most with 2 real
  cores, which is exactly what the laptop numbers show. So a 2-real-core server should
  land close to the laptop numbers, and the current server will land somewhere between the
  1 CPU and 2 CPU columns.
- A different chip (AMD) can change detector numbers in the last decimal place, so the
  eval has to be re-run after a switch. ARM servers are cheaper but a bigger change.
- Prices are from AWS and Vantage pages read on 2026-11-25. Not measured: how much faster
  CourtIQ actually is on each.

### Group D: looked at and dropped

| Idea | Why dropped |
|---|---|
| Trim Ultralytics' Python overhead, call OpenVINO directly | Measured: only about 1.2 ms of a 21 ms call. |
| Remove the unused `plot()` in `yolo_detector.py` | Measured: 0.4 ms a frame, 0.5 s a clip. Not worth touching shared code. |
| OpenVINO threads, pinning, fixed shapes | Measured: no gain, and fixed shapes move the outputs. |
| Batch the crops with the full frame | Different sizes, and no gain on one core per the OpenVINO docs. |
| More threads for MediaPipe | Not possible from Python. Would need a custom build. |
| Lighter pose model, every other frame | Already turned down: they change the elbow number. |
| Pose model through OpenVINO | Not bit-identical, and MediaPipe's tracking and smoothing would have to be rewritten. Days of work. |
| Detect every N frames with the tracker filling in | The papers show large losses on small fast objects, and the make rule needs the ball seen twice under the rim. |
| Skip frames where nothing moves | Handheld camera, so everything always moves. |
| Decode at lower resolution, hardware decode | The server has no video hardware, and other pixels mean other detections. |

### CI/CD

- Nothing in group A needs a new package, model file or setting. ffmpeg is already in the
  image and in the CI test job. So the existing workflow ships it as it is.
- A4 (layer order) is in this branch.
- Not done, because it cannot be tested without pushing: a build cache for the deploy job.
  Today every deploy rebuilds every layer from nothing, so the server downloads close to
  the whole 3 GB image each time. With `docker/build-push-action` and
  `cache-from: type=gha` / `cache-to: type=gha,mode=max`, unchanged layers (PyTorch,
  the pip installs, the model conversion) would be reused and the server would only pull
  what changed. Free on GitHub (10 GB limit, entries unused for 7 days are deleted).

## Results

Filled in as each idea is built and measured.
