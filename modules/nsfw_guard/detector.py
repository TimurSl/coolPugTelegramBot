from __future__ import annotations

import os
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()


class NsfwDetectionService:
    """Detect NSFW content in images via external FastAPI detector."""

    DEFAULT_URL = "http://localhost:8060/detect"

    def __init__(self, model_name: str = "external") -> None:
        # Сохраняем только имя модели для логов
        self.model_name = model_name

        # URL к твоему Docker API
        self.api_url = os.getenv("NSFW_API_URL", self.DEFAULT_URL)

        self._logger = logging.getLogger(__name__)

    async def is_nsfw(self, image_bytes: bytes) -> bool:
    """Sends the image bytes to external API and returns True if NSFW."""
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    image_bytes,
                    filename="image.jpg",
                    content_type="image/jpeg"
                )
    
                async with session.post(
                    self.api_url,
                    data=form,
                    timeout=5,
                ) as resp:
    
                    if resp.status != 200:
                        self._logger.error(
                            "NSFW API returned %s for URL %s", resp.status, self.api_url
                        )
                        return False  # fail-safe
    
                    data = await resp.json()
    
        except Exception as e:
            self._logger.exception("Failed to contact NSFW API at %s: %s", self.api_url, e)
            return False
    
        return data.get("label", "").lower() == "nsfw"

        except Exception as e:
            self._logger.exception("Failed to contact NSFW API at %s: %s", self.api_url, e)
            return False  # fail-safe
            
        label = data.get("label", "").lower()

        return label == "nsfw"

    def unload(self) -> None:
        """Kept for compatibility with old API (does nothing now)."""
        pass
