"""Media frame extraction utilities for NSFW classification."""

from __future__ import annotations

import logging
import os
import re
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import List, Optional

try:  # pragma: no cover - optional dependency
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

try:  # pragma: no cover - optional dependency
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None


class MediaFrameExtractor:
    """Extract representative frames from images, GIFs and videos."""

    IMAGE_MIME_PREFIX = "image/"
    VIDEO_MIME_PREFIX = "video/"

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def extract_frames(
        self, media_bytes: bytes, mime_type: Optional[str] = None, file_name: Optional[str] = None
    ) -> List[bytes]:
        if self._is_gif(media_bytes, mime_type, file_name):
            return self._extract_gif_frames(media_bytes)
        if self._is_video(mime_type, file_name):
            return self._extract_video_frames(media_bytes, file_name)
        return [media_bytes]

    def _is_gif(self, media_bytes: bytes, mime_type: Optional[str], file_name: Optional[str]) -> bool:
        if mime_type and mime_type.lower().startswith("image/gif"):
            return True
        if file_name and file_name.lower().endswith(".gif"):
            return True
        return media_bytes.startswith(b"GIF8")

    def _is_video(self, mime_type: Optional[str], file_name: Optional[str]) -> bool:
        if mime_type and mime_type.lower().startswith(self.VIDEO_MIME_PREFIX):
            return True
        if mime_type and mime_type.lower().startswith("application/octet-stream") and file_name:
            return bool(re.search(r"\.(mp4|mov|mkv|avi|webm)$", file_name, re.IGNORECASE))
        if file_name and re.search(r"\.(mp4|mov|mkv|avi|webm)$", file_name, re.IGNORECASE):
            return True
        return False

    def _extract_gif_frames(self, media_bytes: bytes) -> List[bytes]:
        if Image is None:
            self._logger.warning("Pillow is required to process GIFs")
            return []
        try:
            image = Image.open(BytesIO(media_bytes))
            frame_indices = {0, max(getattr(image, "n_frames", 1) - 1, 0)}
            frames: List[bytes] = []
            for index in sorted(frame_indices):
                image.seek(index)
                buffer = BytesIO()
                image.convert("RGB").save(buffer, format="JPEG")
                frames.append(buffer.getvalue())
            return frames
        except Exception:
            self._logger.exception("Failed to extract frames from GIF")
            return []

    def _extract_video_frames(self, media_bytes: bytes, file_name: Optional[str]) -> List[bytes]:
        if cv2 is None:
            self._logger.warning("OpenCV is required to process videos")
            return []

        suffix = os.path.splitext(file_name or "video.mp4")[1] or ".mp4"
        with NamedTemporaryFile(suffix=suffix) as temp_file:
            temp_file.write(media_bytes)
            temp_file.flush()

            capture = cv2.VideoCapture(temp_file.name)
            if not capture.isOpened():
                self._logger.warning("Failed to open video for NSFW check")
                return []

            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            targets = {0, max(frame_count - 1, 0)}

            frames: List[bytes] = []
            for index in sorted(targets):
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                success, frame = capture.read()
                if not success:
                    continue
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                buffer = BytesIO()
                Image.fromarray(rgb_frame).save(buffer, format="JPEG")
                frames.append(buffer.getvalue())

            capture.release()
            return frames
