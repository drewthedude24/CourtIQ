"""Read a video's frames through ffmpeg, as pictures OpenCV can use."""
import subprocess

import cv2 as cv
import numpy as np


class VideoReader:
    """Gives the frames of a video in order.

    iPhones record 10-bit HDR video, and OpenCV's own reader spent about 9 ms a frame turning
    that into a normal picture. Here ffmpeg decodes in its own process and hands over 8-bit YUV
    (the brightness-plus-colour layout video is stored in), which OpenCV turns into its usual
    BGR picture in under a millisecond. The picture comes out a little darker than OpenCV's.

    ffmpeg also shrinks the frames to `width` x `height` when the video is bigger (a phone
    records 1080p, the detector looks at 720p), so Python never handles the full-size frames.
    """

    def __init__(self, path, width, height):
        # One YUV frame is a full-size brightness plane with two quarter-size colour planes under it.
        self.shape = (height * 3 // 2, width)
        self.ffmpeg = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", path,
             # passthrough: every frame of the video exactly once, none repeated or dropped.
             "-fps_mode", "passthrough", "-vf", f"scale={width}:{height}",
             "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE,
        )

    def read(self):
        """The next frame as ffmpeg hands it over (raw YUV, half the size of a BGR picture).
        None at the end of the video."""
        size = self.shape[0] * self.shape[1]
        yuv = self.ffmpeg.stdout.read(size)
        return yuv if len(yuv) == size else None

    def picture(self, yuv):
        """A frame from read(), as a BGR picture."""
        return cv.cvtColor(np.frombuffer(yuv, np.uint8).reshape(self.shape), cv.COLOR_YUV2BGR_I420)

    def release(self):
        self.ffmpeg.kill()  # It may still be decoding frames nobody will read.
        self.ffmpeg.wait()
        self.ffmpeg.stdout.close()
