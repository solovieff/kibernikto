"""Image-generation sub-agent and the ``generate_image`` tool.

Provider routing in :func:`generate_image`:

* **OpenRouter** (``OpenRouterModel``) and **routerai** (``RouterAiProvider``,
  detected by ``provider.name``) — hits ``/chat/completions`` with
  ``modalities=["image","text"]`` + ``image_config``.
* **vsegpt** (``OpenAIChatModel``, remaining) — standard ``/images/generate``
  endpoint, ``response_format="b64_json"``.
* **Everything else** — sub-agent fallback (may not return images).

Generated binaries are ferried to the user via ``ctx.deps.attachments``; the
transport layer reads them out after the run and delivers them.

The sub-agent is created lazily (on first call) so importing this module does
not crash when ``AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME`` is ``None``.
"""

import base64
import binascii
import logging
from typing import Any

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import BinaryContent, ImageUrl, UserContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

_IMAGE_SYSTEM_PROMPT = (
    "You are an image engine. Produce a single image that best matches the "
    "user's prompt. If reference images are attached, treat them as the "
    "starting point — edit, restyle or compose with them according to the "
    "prompt. Do not ask clarifying questions."
)

_DEFAULT_ASPECT_RATIO = "1:1"
_DEFAULT_IMAGE_SIZE = "1K"

# Lazy singleton — populated the first time generate_image() is called.
_image_agent: Agent | None = None


def _get_image_agent() -> Agent:
    """Return the image sub-agent, creating it on the first call."""
    global _image_agent
    if _image_agent is not None:
        return _image_agent

    model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME)
    if model is None:
        raise RuntimeError(
            "IMAGE_MODEL_NAME is not configured. "
            "Set AGENT_KIBERNIKTO_IMAGE_MODEL_NAME to enable image generation."
        )

    _image_agent = Agent(model=model, system_prompt=_IMAGE_SYSTEM_PROMPT)
    return _image_agent


# ── Input helpers ─────────────────────────────────────────────────────────────

def _extract_input_images(deps: KiberniktoDeps) -> list[ImageUrl]:
    return [p for p in deps.user_message_parts if isinstance(p, ImageUrl)]


def _image_url_to_openrouter_part(image: ImageUrl) -> dict[str, Any]:
    """Project a pydantic-ai ``ImageUrl`` onto the OpenRouter content-part shape."""
    return {"type": "image_url", "image_url": {"url": image.url}}


def _build_openrouter_messages(request: str | list[UserContent]) -> list[dict[str, Any]]:
    """Turn a ``UserContent`` request into OpenRouter chat-completion messages."""
    if isinstance(request, str):
        return [{"role": "user", "content": request}]

    parts: list[dict[str, Any]] = []
    for item in request:
        if isinstance(item, ImageUrl):
            parts.append(_image_url_to_openrouter_part(item))
        else:
            text = getattr(item, "content", None) or str(item)
            parts.append({"type": "text", "text": text})
    return [{"role": "user", "content": parts}]


# ── Binary decoding ──────────────────────────────────────────────────────────

def _decode_data_url(url: str) -> tuple[bytes, str]:
    """Decode a ``data:<media>;base64,<payload>`` URL. Falls back to ``image/png``."""
    media_type = "image/png"
    payload = url
    if url.startswith("data:") and "," in url:
        header, payload = url.split(",", 1)
        if ";" in header:
            media_type = header[5:].split(";", 1)[0] or media_type
        else:
            media_type = header[5:] or media_type
    try:
        return base64.b64decode(payload, validate=True), media_type
    except (binascii.Error, ValueError):
        return payload.encode("utf-8"), media_type


async def _download_image(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient() as session:
        response = await session.get(url, timeout=120)
        response.raise_for_status()
        media_type = response.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
        return response.content, media_type


def _coerce_image_field(image: Any) -> str | None:
    """Pull the ``image_url.url`` out of an OpenRouter image item (dict or pydantic)."""
    if image is None:
        return None
    if isinstance(image, dict):
        image_url = image.get("image_url")
        if isinstance(image_url, dict):
            return image_url.get("url")
        return image_url if isinstance(image_url, str) else None
    image_url = getattr(image, "image_url", None)
    if image_url is None:
        return None
    url = getattr(image_url, "url", None)
    if url is not None:
        return url
    return image_url.get("url") if isinstance(image_url, dict) else None


# ── Provider-specific generators ─────────────────────────────────────────────

async def _openrouter_generate_images(
        request: str | list[UserContent],
        *,
        aspect_ratio: str = _DEFAULT_ASPECT_RATIO,
        image_size: str = _DEFAULT_IMAGE_SIZE,
) -> list[BinaryContent]:
    """OpenRouter / routerai: ``/chat/completions`` with ``modalities=["image","text"]``."""
    agent = _get_image_agent()
    model = agent.model
    provider = model._provider  # noqa: SLF001
    client = provider.client
    logger.info("image provider: name=%r base_url=%r", provider.name, provider.base_url)

    completion = await client.chat.completions.create(
        model=model.model_name,
        messages=_build_openrouter_messages(request),
        modalities=["image", "text"],
        extra_body={"image_config": {"aspect_ratio": aspect_ratio, "image_size": image_size}},
    )

    if not completion.choices:
        logger.warning("OpenRouter image call returned no choices")
        return []

    message = completion.choices[0].message
    images = list(getattr(message, "images", None) or [])
    if not images:
        logger.warning("OpenRouter image call returned a message without images")
        return []

    binaries: list[BinaryContent] = []
    for image in images:
        url = _coerce_image_field(image)
        if not url:
            logger.warning("Skipping image with no URL: %r", image)
            continue
        if url.startswith("data:"):
            data, media_type = _decode_data_url(url)
        else:
            try:
                data, media_type = await _download_image(url)
            except Exception as exc:
                logger.warning("Failed to download image %r: %s", url, exc)
                continue
        binaries.append(BinaryContent(data=data, media_type=media_type))

    return binaries


async def _images_generate(
        prompt: str,
        *,
        size: str = "1024x1024",
        aspect_ratio: str = _DEFAULT_ASPECT_RATIO,
) -> list[BinaryContent]:
    """vsegpt: standard OpenAI ``/images/generate`` endpoint (b64_json)."""
    agent = _get_image_agent()
    model = agent.model
    provider = model._provider  # noqa: SLF001
    client = provider.client
    response = await client.images.generate(
        model=model.model_name,
        prompt=prompt,
        n=1,
        size=size,
        response_format="b64_json",
        extra_body={"aspect_ratio": aspect_ratio},
    )
    data_item = response.data[0] if response.data else None
    if not data_item or not getattr(data_item, "b64_json", None):
        logger.warning("images.generate returned no b64_json data")
        return []
    return [BinaryContent(data=base64.b64decode(data_item.b64_json), media_type="image/png")]


# ── Public tool ───────────────────────────────────────────────────────────────

async def generate_image(ctx: RunContext[KiberniktoDeps], prompt: str) -> str:
    """Generate (or edit) an image from a text prompt; it is delivered to the user automatically.

    Use this whenever the user asks to draw, paint, render or otherwise
    produce an image. If the user sent an image in the same message, it is
    forwarded to the image model so the result is based on it (image-to-image
    / edit). The generated image is queued for delivery — just describe in
    your own reply what you created; do not try to embed or return the image
    yourself.
    """
    input_images = _extract_input_images(ctx.deps)
    request: str | list[UserContent] = [prompt, *input_images] if input_images else prompt

    logger.info("image tool: prompt=%r, input_images=%d", prompt, len(input_images))

    try:
        agent = _get_image_agent()
    except RuntimeError as exc:
        return str(exc)

    model = agent.model
    provider_name = getattr(getattr(model, "_provider", None), "name", "")  # noqa: SLF001

    try:
        if isinstance(model, OpenRouterModel) or provider_name == "routerai":
            binaries = await _openrouter_generate_images(request)
        elif isinstance(model, OpenAIChatModel):
            binaries = await _images_generate(prompt)
        else:
            logger.warning("Image model %r is unrecognised; falling back to sub-agent.", model)
            result = await agent.run(request)
            binaries = list(result.response.images)
    except Exception as exc:
        logger.exception("Image generation failed: %s", exc)
        return f"Image generation failed: {exc}"

    if not binaries:
        logger.warning("Image model returned no images for prompt: %r", prompt)
        return "Image generation failed: the model returned no image."

    ctx.deps.add_attachments(binaries)
    return f"Generated {len(binaries)} image(s); they are delivered to the user."
