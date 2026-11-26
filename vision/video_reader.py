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
    """

    def __init__(self, path, width, height):
        # One YUV frame is a full-size brightness plane with two quarter-size colour planes under it.
        self.shape = (height * 3 // 2, width)
        self.ffmpeg = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", path,
             # passthrough: every frame of the video exactly once, none repeated or dropped.
             "-fps_mode", "passthrough", "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE,
        )

    def grab(self):
        """Move to the next frame without making a picture of it. False at the end of the video."""
        size = self.shape[0] * self.shape[1]
        self.yuv = self.ffmpeg.stdout.read(size)
        return len(self.yuv) == size

    def retrieve(self):
        """The frame grab() moved to, as a BGR picture."""
        yuv = np.frombuffer(self.yuv, np.uint8).reshape(self.shape)
        return cv.cvtColor(yuv, cv.COLOR_YUV2BGR_I420)

    def release(self):
        self.ffmpeg.kill()  # It may still be decoding frames nobody will read.
        self.ffmpeg.wait()
        self.ffmpeg.stdout.close()
