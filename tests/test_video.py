import subprocess

import cv2 as cv
import numpy as np

from backend.app import convert_to_h264


def video_codec(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def test_convert_to_h264_rewrites_mp4v_video_in_place(tmp_path):
    path = tmp_path / "annotated.mp4"
    writer = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*"mp4v"), 30, (64, 64))
    for _ in range(10):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    assert video_codec(path) == "mpeg4"

    convert_to_h264(path)

    assert video_codec(path) == "h264"
