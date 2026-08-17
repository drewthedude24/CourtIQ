# CourtIQ

CourtIQ is a basketball shot detection and tracking project focused on computer vision first.

Current goal:
- Point a camera at a hoop
- Detect basketball attempts
- Detect makes and misses
- Store basic shot metadata
- Build the CV system before adding backend, database, or frontend

This repository is being developed in milestones. The first phase is entirely focused on computer vision.

## Current phase

We are currently working on:
- live webcam capture
- OpenCV frame processing
- YOLO object detection
- basketball and rim detection
- tracking
- shot trajectory analysis

We are not yet building:
- React frontend
- FastAPI backend
- PostgreSQL
- ML training
- replay video system
- fatigue analysis

## Repo structure

```text
courtiq/
├── vision/
├── backend/
├── frontend/
├── tests/
├── data/
├── experiments/
├── docs/
├── README.md
└── .gitignore
```

At this stage, work is happening primarily inside:
- `vision/`

## Milestones

1. Display webcam feed
2. Run YOLO on webcam
3. Detect basketball
4. Detect rim
5. Track basketball center
6. Detect shot attempts
7. Classify make vs miss
8. Save shot metadata

## Project principles

- Build one visible milestone at a time
- Keep every milestone testable
- Do not add backend or UI until CV works
- Learn the camera loop before using YOLO
- Use real basketball footage during testing
- Treat custom training as a later step only if necessary

## Development workflow

For every milestone:
1. Define the problem
2. Predict the solution
3. Research the underlying concept
4. Read official docs
5. Implement a minimal version
6. Test on a small example
7. Observe failures
8. Fix the issue
9. Commit work
10. Write a short learning note

## Environment

Planned stack:
- Python
- OpenCV
- Ultralytics YOLO
- FastAPI
- PostgreSQL
- React + TypeScript

## V1 target

The first version is:

- camera on
- live basketball tracking
- attempt detection
- make / miss classification
- metadata storage

This is the target before any additional product features are added.

## Notes

This README is intentionally focused on the current stage of the project. It will evolve as the system moves from CV prototype to production-ready application.

## Status

- Phase 0: project setup
- Phase 1: live camera capture
- Next milestone: webcam feed + FPS + clean exit