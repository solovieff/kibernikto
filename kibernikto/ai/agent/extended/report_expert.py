"""ReportExpert — deep research reports via Jina deepsearch / VseGPT fallback.

Migrates the old ReportExpert: generate_report with effort-based model selection.
Result is saved as .txt and delivered to the user via deps.attachments.
"""

from __future__ import annotations

import logging
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
    "pro": "vsegpt:anthropic/claude-3.7-sonnet-deep-online",
    "extra": "vsegpt:anthropic/claude-3.7-sonnet-deep-research-1.0",
}


def _pick_effort_model(effort_level: int) -> str:
    """Pick model by effort level: <4 base, <8 pro, <11 extra."""
    if effort_level < 4:
        return _EFFORT_MODELS["base"]
    if effort_level < 8:
        return _EFFORT_MODELS["pro"]
    return _EFFORT_MODELS["extra"]


async def _jina_deepsearch(request: str) -> str:
    """Run deepsearch via Jina AI."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                _JINA_DEEPSEARCH_URL,
                json={
                    "model": "jina-deepsearch-v1",
                    "messages": [{"role": "user", "content": request}],
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
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