# Old code, kept for reference

Nothing in this folder is used by the app, the API or the tests in `tests/`. It is the
earlier version of the shot logic and the scripts that went with it.

- `shot_detector.py`, `shot_result_detector.py`: the first shot logic. It waited for the
  pose model to see a release before checking the rim. Replaced by
  `vision/rim_shot_detector.py` (see `docs/detector-results.md` for why).
- `pose_detector.py`: the YOLO pose model wrapper. Not run anymore. It needs the `lap`
  package, which is no longer in `requirements.txt`.
- `ball_tracker.py`: the first ball tracker, replaced by a Kalman-filter tracker, and that by `vision/ball_path.py`.
- `main.py`, `camera.py`: the live webcam prototype.
- `offline_run.py`, `clean_offline_runner.py`, `stitched_offline_runner.py`,
  `compare_missing_frames.py`: one-off scripts for running and comparing clips.
- `test_shot_result_detector.py`: tests for the old shot logic. Run them with
  `.venv/bin/python -m pytest -q vision/old`.

The scripts import their neighbours by bare name (for example `from yolo_detector import`),
which worked when they sat in `vision/`. They need their imports fixed before they run from here.
