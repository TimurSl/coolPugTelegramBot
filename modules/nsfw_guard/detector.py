"""NSFW image detection service using Hugging Face transformers pipeline."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Iterable, Optional

try:  # pragma: no cover - optional dependency resolution
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency resolution
    Image = None

try:  # pragma: no cover - optional dependency resolution
    import torch
    from transformers import AutoImageProcessor, AutoModelForImageClassification
except ImportError:  # pragma: no cover - optional dependency resolution
    torch = None
    AutoImageProcessor = None
    AutoModelForImageClassification = None


class NsfwDetectionService:
    """Detect NSFW content in images using a configurable transformer pipeline."""

    DEFAULT_MODEL = "Falconsai/nsfw_image_detection"
    NSFW_LABELS = {"porn", "hentai", "sexy", "nsfw"}

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._processor = None
        self._model = None
        self._logger = logging.getLogger(__name__)

    def _load_model(self) -> None:
        if torch is None or AutoImageProcessor is None or AutoModelForImageClassification is None:
            raise RuntimeError(
                "transformers[torch] is required for NSFW detection; install optional dependencies"
            )
        if self._processor is None or self._model is None:
            self._logger.info("Loading NSFW detection model: %s", self.model_name)
            self._processor = AutoImageProcessor.from_pretrained(self.model_name)
            self._model = AutoModelForImageClassification.from_pretrained(self.model_name)
            self._model.eval()

    def _classify_sync(self, image_bytes: bytes) -> bool:
        if Image is None:
            raise RuntimeError("Pillow is required for NSFW detection; install optional dependencies")
        self._load_model()
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = self._model(**inputs)
            probabilities = torch.nn.functional.softmax(outputs.logits, dim=1)
            top_class_id = int(probabilities.argmax(dim=1).item())

        label = self._model.config.id2label.get(top_class_id, "")
        self._logger.debug("Top classification label: %s", label)
        return self._is_nsfw_label(label)

    def _select_label(self, results) -> str:
        if isinstance(results, str):
            return results.strip().lower()
        if not isinstance(results, Iterable) or isinstance(results, (bytes, bytearray)):
            return ""

        best_label = ""
        best_score: Optional[float] = None
        for item in results:
            if isinstance(item, dict):
                label_value = item.get("label", "")
                score_value = item.get("score")
            else:
                label_value = item
                score_value = None

            label = str(label_value).strip().lower()
            score = score_value if isinstance(score_value, (int, float)) else None

            if not label:
                continue

            if best_score is None:
                best_label = label
                best_score = score
                continue

            if score is not None and (best_score is None or score > best_score):
                best_label = label
                best_score = score

        return best_label

    def _is_nsfw_label(self, results) -> bool:
        label = self._select_label(results)
        return label in self.NSFW_LABELS

    def is_nsfw_label(self, results) -> bool:
        """Expose label evaluation for easier testing."""

        return self._is_nsfw_label(results)

    async def is_nsfw(self, image_bytes: bytes) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._classify_sync, image_bytes)

    def unload(self) -> None:
        self._processor = None
        self._model = None

