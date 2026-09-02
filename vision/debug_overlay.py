import cv2 as cv


def draw_debug_overlay(
    annotated_frame,
    tracked_ball,
    state,
    timestamp_s,
    shot_result=None,
):
    """Draw tracker and shot-state information onto an annotated video frame."""
    history = list(tracked_ball["history"])

    # The recent path makes incorrect ball selections visible while reviewing video.
    for index in range(1, len(history)):
        start = tuple(map(int, history[index - 1]))
        end = tuple(map(int, history[index]))
        cv.line(annotated_frame, start, end, (0, 255, 255), 2)

    tracking_status = tracked_ball.get(
        "tracking_status",
        "DETECTED" if tracked_ball["detected"] else "LOST",
    )
    ball_center = tracked_ball.get("center")
    predicted_center = tracked_ball.get("predicted_center")

    if predicted_center is not None:
        predicted_x, predicted_y = map(int, predicted_center)
        cv.drawMarker(
            annotated_frame,
            (predicted_x, predicted_y),
            (255, 160, 0),
            cv.MARKER_CROSS,
            18,
            2,
        )

    if ball_center is not None:
        ball_x, ball_y = map(int, ball_center)
        if tracking_status == "DETECTED":
            cv.circle(annotated_frame, (ball_x, ball_y), 9, (0, 255, 0), -1)
        elif tracking_status == "PREDICTED":
            cv.circle(annotated_frame, (ball_x, ball_y), 10, (0, 255, 255), 3)

    velocity_x, velocity_y = tracked_ball["velocity"]
    confidence = tracked_ball.get("selected_confidence")
    selected_source = tracked_ball.get("selected_source") or "--"
    confidence_text = "--" if confidence is None else f"{confidence:.2f}"
    cv.putText(
        annotated_frame,
        f"Track: {tracking_status} | conf: {confidence_text} | source: {selected_source}",
        (20, 110),
        cv.FONT_HERSHEY_SIMPLEX,
        0.82,
        (0, 255, 0) if tracking_status == "DETECTED" else (0, 255, 255),
        3,
        cv.LINE_AA,
    )
    cv.putText(
        annotated_frame,
        f"Ball velocity: ({velocity_x:.1f}, {velocity_y:.1f})",
        (20, 145),
        cv.FONT_HERSHEY_SIMPLEX,
        0.82,
        (0, 255, 255),
        3,
        cv.LINE_AA,
    )

    cv.putText(
        annotated_frame,
        f"State: {state}",
        (20, 40),
        cv.FONT_HERSHEY_SIMPLEX,
        1.05,
        (0, 255, 0),
        3,
        cv.LINE_AA,
    )
    cv.putText(
        annotated_frame,
        f"Time: {timestamp_s:.2f}s",
        (20, 75),
        cv.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        3,
        cv.LINE_AA,
    )
    cv.putText(
        annotated_frame,
        f"Missing frames: {tracked_ball['missing_frames']}",
        (20, 180),
        cv.FONT_HERSHEY_SIMPLEX,
        0.82,
        (0, 165, 255),
        3,
        cv.LINE_AA,
    )

    acceleration_x, acceleration_y = tracked_ball.get(
        "kalman_acceleration",
        (0.0, 0.0),
    )
    uncertainty = tracked_ball.get("prediction_uncertainty")
    uncertainty_text = "--" if uncertainty is None else f"{uncertainty:.1f}px"
    cv.putText(
        annotated_frame,
        f"Kalman a: ({acceleration_x:.1f}, {acceleration_y:.1f}) | sigma: {uncertainty_text}",
        (20, 215),
        cv.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 200, 0),
        3,
        cv.LINE_AA,
    )

    if shot_result is not None:
        _draw_shot_result(annotated_frame, shot_result)

    return annotated_frame


def _draw_shot_result(annotated_frame, shot_result):
    rim_center = shot_result.get("rim_center")
    scoring_window = shot_result.get("scoring_window")
    if rim_center is not None and scoring_window is not None:
        rim_x, rim_y = map(int, rim_center)
        scoring_left, scoring_right = map(int, scoring_window)
        cv.line(
            annotated_frame,
            (scoring_left, rim_y),
            (scoring_right, rim_y),
            (255, 0, 255),
            3,
        )
        cv.circle(annotated_frame, (rim_x, rim_y), 6, (255, 0, 255), -1)

    result_status = shot_result.get("status", "WAITING")
    if result_status == "TRACKING":
        label = "Result: checking rim"
        if shot_result.get("provisional_make"):
            label = "Result: provisional make"
        color = (0, 215, 255)
        scale = 0.9
    elif result_status == "MAKE":
        label = "MAKE"
        color = (0, 255, 0)
        scale = 1.8
    elif result_status == "MISS":
        label = "MISS"
        color = (0, 0, 255)
        scale = 1.8
    else:
        label = "Result: waiting for release"
        color = (200, 200, 200)
        scale = 0.8

    text_size, _ = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, scale, 3)
    text_x = max(20, annotated_frame.shape[1] - text_size[0] - 30)
    cv.putText(
        annotated_frame,
        label,
        (text_x, 55),
        cv.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        3,
        cv.LINE_AA,
    )


def draw_shot_counter(frame, make_count, miss_count, large=False):
    """Draw a persistent cumulative score with a readable background."""
    label = f"MAKES: {make_count}   MISSES: {miss_count}"
    font_scale = 1.45 if large else 1.15
    thickness = 4 if large else 3
    text_size, baseline = cv.getTextSize(
        label,
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
    )
    text_x = max(20, (frame.shape[1] - text_size[0]) // 2)
    text_y = 115 if large else 280
    padding = 16
    cv.rectangle(
        frame,
        (text_x - padding, text_y - text_size[1] - padding),
        (text_x + text_size[0] + padding, text_y + baseline + padding),
        (20, 20, 20),
        -1,
    )
    cv.putText(
        frame,
        label,
        (text_x, text_y),
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        thickness,
        cv.LINE_AA,
    )


def draw_clean_result_overlay(frame, shot_result, make_count, miss_count):
    """Draw only the user-facing result and cumulative score."""
    draw_shot_counter(frame, make_count, miss_count, large=True)
    status = shot_result.get("status")
    if status not in {"MAKE", "MISS"}:
        return frame

    color = (0, 255, 0) if status == "MAKE" else (0, 0, 255)
    font_scale = 2.5
    thickness = 7
    text_size, baseline = cv.getTextSize(
        status,
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
    )
    text_x = (frame.shape[1] - text_size[0]) // 2
    text_y = max(220, frame.shape[0] // 5)
    padding = 24
    cv.rectangle(
        frame,
        (text_x - padding, text_y - text_size[1] - padding),
        (text_x + text_size[0] + padding, text_y + baseline + padding),
        (20, 20, 20),
        -1,
    )
    cv.putText(
        frame,
        status,
        (text_x, text_y),
        cv.FONT_HERSHEY_SIMPLEX,
        font_scale,
        color,
        thickness,
        cv.LINE_AA,
    )
    return frame
