"""Helpers to collect media frames for NSFW evaluation."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional

import aiohttp
from PIL import Image


URL_REGEX = re.compile(r"https?://[^\s]+", re.IGNORECASE)


@dataclass
class MediaFrame:
    """Container for a single media frame."""

    data: bytes
    description: str


class MediaFrameCollector:
    """Collects image-like bytes from Telegram messages and embed links."""

    MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024
    MAX_EMBED_SIZE = 5 * 1024 * 1024

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    async def collect(self, message) -> List[MediaFrame]:
        frames: List[MediaFrame] = []

        collectors = (
            self._collect_photo,
            self._collect_image_document,
            self._collect_animation,
            self._collect_video,
            self._collect_video_note,
            self._collect_sticker,
            self._collect_embed_links,
        )

        for collector in collectors:
            frames.extend(await collector(message))

        return frames

    async def _collect_photo(self, message) -> List[MediaFrame]:
        if not message.photo:
            return []
        frame = await self._download_telegram_file(message, message.photo[-1], "photo")
        return [frame] if frame else []

    async def _collect_image_document(self, message) -> List[MediaFrame]:
        document = message.document
        if not document or not document.mime_type or not document.mime_type.startswith("image/"):
            return []
        frame = await self._download_telegram_file(message, document, "document")
        return [frame] if frame else []

    async def _collect_animation(self, message) -> List[MediaFrame]:
        animation = getattr(message, "animation", None)
        if not animation:
            return []
        return await self._extract_video_like_frames(message, animation, "animation")

    async def _collect_video(self, message) -> List[MediaFrame]:
        video = getattr(message, "video", None)
        if not video:
            return []
        return await self._extract_video_like_frames(message, video, "video")

    async def _collect_video_note(self, message) -> List[MediaFrame]:
        video_note = getattr(message, "video_note", None)
        if not video_note:
            return []
        return await self._extract_video_like_frames(message, video_note, "video_note")

    async def _collect_sticker(self, message) -> List[MediaFrame]:
        sticker = getattr(message, "sticker", None)
        if not sticker:
            return []

        frames: List[MediaFrame] = []

        if not getattr(sticker, "is_animated", False) and not getattr(
            sticker, "is_video", False
        ):
            frame = await self._download_telegram_file(message, sticker, "sticker")
            if frame:
                frames.append(frame)
        thumbnail = getattr(sticker, "thumbnail", None) or getattr(sticker, "thumb", None)
        if thumbnail:
            thumb_frame = await self._download_telegram_file(
                message, thumbnail, "sticker_thumb"
            )
            if thumb_frame:
                frames.append(thumb_frame)
        return frames

    async def _collect_embed_links(self, message) -> List[MediaFrame]:
        text = message.text or message.caption or ""
        urls = URL_REGEX.findall(text)
        frames: List[MediaFrame] = []

        for url in urls:
            content = await self._download_url_content(url)
            if content is None:
                continue
            if self._is_gif_bytes(content):
                frames.extend(self._extract_gif_frames(content, "embed_gif"))
                continue
            frames.append(MediaFrame(content, f"embed:{url}"))

        return frames

    async def _extract_video_like_frames(self, message, media, description: str) -> List[MediaFrame]:
        frames: List[MediaFrame] = []

        thumbnail = getattr(media, "thumbnail", None) or getattr(media, "thumb", None)
        if thumbnail:
            thumb_frame = await self._download_telegram_file(
                message, thumbnail, f"{description}_thumb"
            )
            if thumb_frame:
                frames.append(thumb_frame)

        media_frame = await self._download_telegram_file(message, media, description)
        if not media_frame:
            return frames

        if self._is_gif_bytes(media_frame.data):
            frames.extend(self._extract_gif_frames(media_frame.data, description))
            return frames

        video_frames = await self._extract_video_frames(media_frame.data, description)
        frames.extend(video_frames)
        return frames

    async def _download_telegram_file(self, message, media_object, description: str) -> Optional[MediaFrame]:
        bot = message.bot
        if bot is None:
            return None

        if not self._can_download(media_object):
            self._logger.warning(
                "Skipping %s: size exceeds limit (%s bytes)",
                description,
                getattr(media_object, "file_size", None),
            )
            return None

        buffer = BytesIO()
        try:
            await bot.download(media_object, destination=buffer)
            return MediaFrame(buffer.getvalue(), description)
        except Exception:
            self._logger.exception("Failed to download %s", description)
            return None

    def _can_download(self, media_object) -> bool:
        size = getattr(media_object, "file_size", None)
        if size is None:
            return True
        return size <= self.MAX_TELEGRAM_FILE_SIZE

    async def _download_url_content(self, url: str) -> Optional[bytes]:
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        self._logger.warning("Skipping embed %s: status %s", url, resp.status)
                        return None

                    content_type = resp.headers.get("Content-Type", "").lower()
                    if not content_type.startswith("image/") and not content_type.startswith(
                        "video/"
                    ):
                        self._logger.warning(
                            "Skipping embed %s: unsupported content type %s", url, content_type
                        )
                        return None

                    data = await resp.content.read(self.MAX_EMBED_SIZE + 1)
                    if len(data) > self.MAX_EMBED_SIZE:
                        self._logger.warning("Skipping embed %s: size exceeds limit", url)
                        return None
                    return data
        except Exception:
            self._logger.exception("Failed to download embed preview from %s", url)
            return None

    def _is_gif_bytes(self, data: bytes) -> bool:
        return data[:6] in {b"GIF87a", b"GIF89a"}

    def _extract_gif_frames(self, data: bytes, description: str) -> List[MediaFrame]:
        frames: List[MediaFrame] = []
        try:
            with Image.open(BytesIO(data)) as img:
                total_frames = getattr(img, "n_frames", 1)
                target_indexes = {0, max(total_frames - 1, 0)}
                for index in sorted(target_indexes):
                    img.seek(index)
                    frame_buffer = BytesIO()
                    img.convert("RGB").save(frame_buffer, format="JPEG")
                    frames.append(MediaFrame(frame_buffer.getvalue(), f"{description}_frame_{index}"))
        except Exception:
            self._logger.exception("Failed to extract GIF frames for %s", description)
        return frames

    async def _extract_video_frames(self, data: bytes, description: str) -> List[MediaFrame]:
        if not shutil.which("ffmpeg"):
            self._logger.debug("ffmpeg not available, using raw video bytes for %s", description)
            return []

        frames: List[MediaFrame] = []
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4") as src:
                src.write(data)
                src.flush()

                first = await self._run_ffmpeg(src.name, "0", f"{description}_first")
                last = await self._run_ffmpeg(src.name, "-1", f"{description}_last")

                if first:
                    frames.append(first)
                if last:
                    frames.append(last)
        except Exception:
            self._logger.exception("Failed to extract video frames for %s", description)
        return frames

    async def _run_ffmpeg(self, input_path: str, offset: str, description: str) -> Optional[MediaFrame]:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as output:
            cmd = ["ffmpeg", "-y"]
            if offset == "-1":
                cmd.extend(["-sseof", "-1"])
            cmd.extend(["-i", input_path, "-vframes", "1", output.name])

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                self._logger.warning("ffmpeg timed out extracting %s", description)
                return None

            output.seek(0)
            data = output.read()
            if data:
                return MediaFrame(data, description)
            return None
