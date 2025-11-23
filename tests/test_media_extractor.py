from io import BytesIO

import pytest
from PIL import Image

from modules.nsfw_guard.media_extractor import MediaFrameExtractor


def _gif_bytes() -> bytes:
    frames = [
        Image.new("RGB", (2, 2), (255, 0, 0)),
        Image.new("RGB", (2, 2), (0, 0, 255)),
    ]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buffer.getvalue()


def _video_bytes(tmp_path) -> bytes:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    video_path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 1.0, (2, 2)
    )
    writer.write(np.full((2, 2, 3), (255, 0, 0), dtype=np.uint8))
    writer.write(np.full((2, 2, 3), (0, 0, 255), dtype=np.uint8))
    writer.release()
    return video_path.read_bytes()


def _frame_color(frame_bytes: bytes) -> tuple[int, int, int]:
    frame = Image.open(BytesIO(frame_bytes)).convert("RGB")
    return frame.getpixel((0, 0))


def _assert_close_color(actual: tuple[int, int, int], expected: tuple[int, int, int]) -> None:
    assert all(abs(a - b) <= 2 for a, b in zip(actual, expected))


def test_extract_gif_first_and_last_frames():
    extractor = MediaFrameExtractor()
    frames = extractor.extract_frames(_gif_bytes(), mime_type="image/gif")

    assert len(frames) == 2
    _assert_close_color(_frame_color(frames[0]), (255, 0, 0))
    _assert_close_color(_frame_color(frames[-1]), (0, 0, 255))


def test_extract_video_first_and_last_frames(tmp_path):
    extractor = MediaFrameExtractor()
    frames = extractor.extract_frames(_video_bytes(tmp_path), mime_type="video/mp4", file_name="sample.mp4")

    assert len(frames) == 2
    _assert_close_color(_frame_color(frames[0]), (255, 0, 0))
    _assert_close_color(_frame_color(frames[-1]), (0, 0, 255))
