"""Image hosting abstraction — publish bytes to a public URL the model can fetch.

The concrete provider is selected by ``IMAGE_HOSTING_PROVIDER`` (default
``imgbb``). To swap hosting, implement :class:`ImageHosting` and register it
in :func:`get_image_hosting` — call sites only ever talk to the interface.
"""

import logging
import os
from abc import ABC, abstractmethod

import aiohttp

logger = logging.getLogger(__name__)


class ImageHosting(ABC):
    """Publish image bytes and return a publicly fetchable URL (or ``None``)."""

    @abstractmethod
    async def publish(self, image_bytes: bytes, name: str) -> str | None:
        """Upload ``image_bytes``; return the public URL on success."""


class ImgbbImageHosting(ImageHosting):
    """imgbb.com hosting (https://api.imgbb.com/1/upload)."""

    URL = "https://api.imgbb.com/1/upload"
    API_KEY = os.environ.get("IMAGE_STORAGE_API_KEY", "")
    # imgbb `expiration` is in seconds; 0 = no expiration. URLs stored in
    # history must stay alive, so the default is no TTL.
    EXPIRATION = int(os.environ.get("IMAGE_STORAGE_EXPIRATION", "0"))

    async def publish(self, image_bytes: bytes, name: str) -> str | None:
        try:
            payload = {"key": self.API_KEY, "image": image_bytes, "name": name}
            if self.EXPIRATION:
                payload["expiration"] = str(self.EXPIRATION)
            async with aiohttp.ClientSession() as session:
                async with session.post(self.URL, data=payload) as response:
                    resp = await response.json()
                    if response.status == 200:
                        return resp["data"]["url"]
                    logger.error("Image upload failed: %s", resp)
                    return None
        except Exception as exc:
            logger.error("Image upload failed: %s", exc)
            return None


def get_image_hosting() -> ImageHosting:
    """Return the configured image hosting provider (by ``IMAGE_HOSTING_PROVIDER``)."""
    provider = os.environ.get("IMAGE_HOSTING_PROVIDER", "imgbb").strip().lower()
    if provider == "imgbb":
        return ImgbbImageHosting()
    raise ValueError(f"Unknown IMAGE_HOSTING_PROVIDER: {provider!r}")


#: Module-level singleton — reuse one provider (and its aiohttp sessions).
image_hosting: ImageHosting = get_image_hosting()
