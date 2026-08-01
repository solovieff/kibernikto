"""ReportExpert — deep research reports via Jina deepsearch / VseGPT fallback.

Migrates the old ReportExpert: generate_report with effort-based model selection.
Result is saved as .txt and delivered to the user via deps.attachments.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import httpx
from pydantic_ai import RunContext

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = (
    "You are a report expert. You generate deep, detailed research reports. "
    "The report is saved as a .txt file and delivered to the user automatically. "
    "Default language is Russian."
)

# Jina deepsearch endpoint.
_JINA_DEEPSEARCH_URL = "https://deepsearch.jina.ai/v1/chat/completions"

# Effort-based model selection for VseGPT fallback.
_EFFORT_MODELS = {
    "base": "vsegpt:meta-llama/llama-4-maverick-online-hq",
    "pro": "vsegpt:anthropic/claude-sonnet-4.6-online-hq",
    "extra": "vsegpt:anthropic/claude-sonnet-4.6-deep-research-1.0",
}


def _pick_effort_model(effort_level: int) -> str:
    """Pick model by effort level: <4 base, <8 pro, <11 extra."""
    if effort_level < 4:
        return _EFFORT_MODELS["base"]
    if effort_level < 8:
        return _EFFORT_MODELS["pro"]
    return _EFFORT_MODELS["extra"]


async def _jina_deepsearch(request: str) -> str:
    """Run deepsearch via Jina AI (streaming keeps long searches alive)."""
    api_key = os.getenv("JINA_AI_API_KEY")
    if not api_key:
        raise RuntimeError("JINA_AI_API_KEY environment variable is not set.")
    try:
        payload = {
            "model": "jina-deepsearch-v1",
            "messages": [{"role": "user", "content": request}],
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {api_key}",
        }
        parts: list[str] = []
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream("POST", _JINA_DEEPSEARCH_URL, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    # Final answer is streamed as type=text; type=think is reasoning.
                    if delta.get("type") == "text":
                        parts.append(delta.get("content", ""))
        return "".join(parts)
    except Exception as exc:
        logger.warning("Jina deepsearch failed: %s", exc)
        raise


async def _vsegpt_fallback(request: str, effort_level: int) -> str:
    """Fallback: run via VseGPT with effort-based model selection."""
    from pydantic_ai import Agent

    model_name = _pick_effort_model(effort_level)
    model = infer_kibernikto_model(model_name)
    agent = Agent(model=model, system_prompt="Generate a detailed research report.")
    result = await agent.run(request)
    return result.output


# ── Agent ─────────────────────────────────────────────────────────────────────

report_agent = KiberniktoAgent(
    model=infer_kibernikto_model("vsegpt:meta-llama/llama-4-maverick-online-hq"),
    name="report_expert",
    description="Generates deep research reports and delivers them as .txt files.",
    system_prompt=REPORT_SYSTEM_PROMPT,
    deps_type=KiberniktoDeps,
)


@report_agent.tool
async def generate_report(ctx: RunContext[KiberniktoDeps], request: str, effort_level: int = 5) -> str:
    """Generate a deep research report and attach it as a .txt file."""
    logger.info("generate_report: effort=%d request=%r", effort_level, request[:100])

    # Try Jina deepsearch first, fallback to VseGPT.
    try:
        report_text = await _jina_deepsearch(request)
    except Exception:
        logger.info("Falling back to VseGPT for report generation")
        report_text = await _vsegpt_fallback(request, effort_level)

    if not report_text:
        return "Report generation failed: empty result."

    # Save as .txt and deliver via attachments.
    from pydantic_ai.messages import BinaryContent

    file_content = f"Research Report\n{'=' * 60}\n\n{report_text}\n".encode("utf-8")
    ctx.deps.add_attachment(BinaryContent(data=file_content, media_type="text/plain"))
    logger.info("Report generated, length=%d", len(report_text))
    return f"Report file is ready ({len(report_text)} chars) and will be attached."