"""ImageExpert — image recognition, editing and generation agent.

Migrates the old ImageExpert: describe_image (vision), edit_image (img2img).
generate_image is reused from core/image.py.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ImageUrl

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

IMAGE_SYSTEM_PROMPT = (
    "You are an image expert. You can describe images, generate new ones and edit existing ones. "
    "When describing, be detailed and precise. When generating or editing, the result is delivered "
    "to the user automatically — just describe what you created."
)

# Vision model for image recognition.
_VISION_MODEL_NAME = "openrouter:google/gemini-2.5-flash"
_vision_agent: Agent | None = None


def _get_vision_agent() -> Agent:
    """Lazy vision agent for image recognition."""
    global _vision_agent
    if _vision_agent is None:
        _vision_agent = Agent(
            model=infer_kibernikto_model(_VISION_MODEL_NAME),
            system_prompt="Describe the image in detail. Answer in Russian unless asked otherwise.",
        )
    return _vision_agent


# ── Agent ─────────────────────────────────────────────────────────────────────

image_agent = KiberniktoAgent(
    model=infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.POOR_MODEL),
    name="image_expert",
    description="Describes, generates and edits images.",
    system_prompt=IMAGE_SYSTEM_PROMPT,
    deps_type=KiberniktoDeps,
)


@image_agent.tool
async def describe_image(ctx: RunContext[KiberniktoDeps], image_url: str, request: str) -> str:
    """Recognize and describe an image by its URL.

    For images attached to the user's message, the real URL is picked up from
    deps automatically — do not pass the provider's internal file name
    (e.g. input_file_0.png); it is not a usable URL.
    """
    logger.info("describe_image: url=%s request=%r", image_url, request[:100])
    try:
        agent = _get_vision_agent()
        from kibernikto.ai.agent.core.image import _extract_input_images, _is_valid_image_url

        if _is_valid_image_url(image_url):
            parts: list = [ImageUrl(url=image_url), request]
        else:
            attached = _extract_input_images(ctx.deps)
            if not attached:
                return "Image recognition failed: no valid image URL provided."
            parts = [*attached, request]
        result = await agent.run(parts)
        return result.output
    except Exception as exc:
        logger.exception("Image recognition failed: %s", exc)
        return f"Image recognition failed: {exc}"


@image_agent.tool
async def edit_image(ctx: RunContext[KiberniktoDeps], image_url: str = "", request: str = "") -> str:
    """Edit an image according to the request; result is delivered to the user.

    Images attached to the user's message are picked up automatically from
    deps — do NOT pass the provider's internal file name (e.g. input_file_0.png),
    it is not a usable URL. Provide image_url only for an external http(s)
    image, or leave it empty when editing an attached photo.
    """
    logger.info("edit_image: url=%s request=%r", image_url, request[:100])
    from kibernikto.ai.agent.core.image import _is_valid_image_url, generate_image

    # Trust only a real URL from the model; attached images ride in deps anyway.
    if _is_valid_image_url(image_url):
        ctx.deps.user_message_parts.append(ImageUrl(url=image_url))
    return await generate_image(ctx, request)
