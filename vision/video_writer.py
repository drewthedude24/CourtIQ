"""Write the annotated video as H.264, the codec every browser can play."""
import subprocess


def start_video_writer(path, fps, width, height):
    """Start ffmpeg and return it. Each frame written to its stdin becomes a frame of the video.

    H.264 is the codec every browser can play, and OpenCV on Linux can't write it. ffmpeg
    encodes in its own process, so it works on one frame while the detector is on the next.
    """
    return subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         # What comes in: raw BGR pictures, the way OpenCV holds a frame in memory.
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
         # What goes out. "veryfast" encodes about 3x faster than the default for a slightly
         # bigger file. "faststart" lets the browser start playing before the download ends.
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE,
    )
