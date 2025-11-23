"""NSFW image detection service using Hugging Face transformers pipeline."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Iterable

try:  # pragma: no cover - optional dependency resolution
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency resolution
    Image = None

try:  # pragma: no cover - optional dependency resolution
    from transformers import pipeline
except ImportError:  # pragma: no cover - optional dependency resolution
    pipeline = None


class NsfwDetectionService:
    """Detect NSFW content in images using a configurable transformer pipeline."""

    DEFAULT_MODEL = "Falconsai/nsfw_image_detection"
<<<<<<< ours
    NSFW_LABELS = {"porn", "hentai", "sexy", "nsfw"}
=======
    NSFW_LABELS = {"nsfw"}
>>>>>>> theirs

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._pipeline = None
        self._logger = logging.getLogger(__name__)

    def _load_pipeline(self) -> None:
        if pipeline is None:
            raise RuntimeError(
                "transformers is required for NSFW detection; install optional dependencies"
            )
        if self._pipeline is None:
            self._logger.info("Loading NSFW detection model: %s", self.model_name)
            self._pipeline = pipeline(
                "image-classification",
                model=self.model_name,
            )

    def _classify_sync(self, image_bytes: bytes) -> bool:
        if Image is None:
            raise RuntimeError("Pillow is required for NSFW detection; install optional dependencies")
        self._load_pipeline()
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        results = self._pipeline(image)
        if not isinstance(results, Iterable):
            self._logger.debug("Unexpected pipeline result type: %s", type(results))
            return False
        return self._is_nsfw_label(results)

    def _is_nsfw_label(self, results: Iterable[dict]) -> bool:
        try:
            top_result = max(results, key=lambda item: item.get("score", 0))
        except (TypeError, ValueError):
            self._logger.debug("Failed to evaluate pipeline results: %s", results)
            return False
        label = str(top_result.get("label", "")).strip().lower()
        self._logger.debug("Top classification label: %s", label)
        return label in self.NSFW_LABELS

    def is_nsfw_label(self, results: Iterable[dict]) -> bool:
        """Expose label evaluation for easier testing."""

        return self._is_nsfw_label(results)

    async def is_nsfw(self, image_bytes: bytes) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._classify_sync, image_bytes)

    def unload(self) -> None:
        self._pipeline = None

