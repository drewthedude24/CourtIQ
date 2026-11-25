import subprocess

import numpy as np

from vision.video_writer import start_video_writer


def probe(path, entry):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", f"stream={entry}", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def test_video_writer_makes_an_h264_video_with_every_frame(tmp_path):
    path = tmp_path / "annotated.mp4"
    writer = start_video_writer(path, fps=30, width=64, height=48)
    for _ in range(10):
        writer.stdin.write(np.zeros((48, 64, 3), dtype=np.uint8).data)
    writer.stdin.close()

    assert writer.wait() == 0
    assert probe(path, "codec_name") == "h264"
    assert probe(path, "nb_read_frames") == "10"
