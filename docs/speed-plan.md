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
