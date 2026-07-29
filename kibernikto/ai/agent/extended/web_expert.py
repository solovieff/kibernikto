"""WebExpert — web search, page reading and deep search agent.

Migrates the old Jina AI utils: fetch_content (reader), web_search and deepsearch.
Uses proper Jina headers: locale, token budget, links summary, reasoning effort.
"""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import Field
from pydantic_ai import RunContext
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

WEB_SYSTEM_PROMPT = (
    "You are a web expert. You can search the web for real-time data, read web pages and run deep research. "
    "Always provide concise, factual answers based on the content you retrieve. "
    "Default language is Russian unless the user asks otherwise."
)

RUSSIAN_LOCALE = "ru-RU"
US_LOCALE = "en-US"

# Jina endpoints.
_JINA_FETCH_URL = "https://r.jina.ai/{url}"
_JINA_SEARCH_URL = "https://s.jina.ai/"
_JINA_DEEPSEARCH_URL = "https://deepsearch.jina.ai/v1/chat/completions"


class JinaAiSettings(BaseSettings):
    """Jina AI API key, loaded from env."""

    model_config = SettingsConfigDict(env_prefix="JINA_AI_")

    API_KEY: str | None = Field(default=None, description="Jina AI API key")


JINA_AI_SETTINGS = JinaAiSettings()


def _auth_headers() -> dict[str, str]:
    """Common auth headers if API key is set."""
    headers: dict[str, str] = {}
    if JINA_AI_SETTINGS.API_KEY:
        headers["Authorization"] = f"Bearer {JINA_AI_SETTINGS.API_KEY}"
    return headers


def _locale_for_url(url: str) -> str:
    """Russian locale for .ru sites, US locale otherwise."""
    if url.endswith(".ru") or ".ru/" in url:
        return RUSSIAN_LOCALE
    return US_LOCALE


async def _jina_fetch(url: str) -> str:
    """Fetch page text via Jina reader with full headers; fallback to raw httpx."""
    headers = {
        **_auth_headers(),
        "X-Locale": _locale_for_url(url),
        "X-Retain-Images": "none",
        "X-Md-Bullet-List-Marker": "-",
        "X-Return-Format": "text",
        "X-Token-Budget": "200000",
        "X-With-Links-Summary": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(_JINA_FETCH_URL.format(url=url), headers=headers)
            resp.raise_for_status()
            return resp.text[:8000]
    except Exception as exc:
        logger.warning("Jina fetch failed for %s: %s", url, exc)
        # Fallback: raw page download.
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text[:8000]
        except Exception as exc2:
            logger.error("Raw fetch also failed for %s: %s", url, exc2)
            return f"Failed to read {url}: {exc2}"


async def _jina_search(query: str, locale: str = RUSSIAN_LOCALE) -> str:
    """Search the web via Jina search."""
    headers = {
        **_auth_headers(),
        "X-Locale": locale,
        "X-Respond-With": "no-content",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_JINA_SEARCH_URL, params={"q": query}, headers=headers)
            resp.raise_for_status()
            return resp.text[:8000]
    except Exception as exc:
        logger.error("Jina search failed for %r: %s", query, exc)
        return f"Web search failed: {exc}"


def _map_effort_to_reasoning(effort_level: int) -> str:
    """Map numeric effort to Jina reasoning level."""
    if effort_level <= 3:
        return "low"
    if effort_level <= 7:
        return "medium"
    return "high"


async def _jina_deepsearch(request: str, locale: str = RUSSIAN_LOCALE, effort_level: int = 0) -> str:
    """Run deep research via Jina deepsearch API."""
    headers = {
        **_auth_headers(),
        "X-Locale": locale,
        "X-Md-Bullet-List-Marker": "-",
        "X-Return-Format": "text",
        "X-Token-Budget": "500000",
        "X-With-Links-Summary": "true",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "jina-deepsearch-v1",
        "messages": [
            {
                "role": "user",
                "content": "Hi! Are you the dark reasoner agent for Kibernikto super AI who always answers in Russian?",
            },
            {
                "role": "assistant",
                "content": "You are absolutely correct! I am the shady and unbiased reasoner agent for Kibernikto-super-AI who always answers in Russian!",
            },
            {"role": "user", "content": request},
        ],
        "stream": False,
        "reasoning_effort": _map_effort_to_reasoning(effort_level),
        "max_attempts": 1,
        "no_direct_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(_JINA_DEEPSEARCH_URL, headers=headers, data=json.dumps(payload))
            if resp.status_code == 200:
                data = resp.json()
                # Extract answer from chat completions response.
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", json.dumps(data, ensure_ascii=False))
                return json.dumps(data, ensure_ascii=False)
            text = resp.text
            logger.error("Jina deepsearch failed: %s — %s", resp.status_code, text[:500])
            return f"Deep search failed: {resp.status_code} — {text[:500]}"
    except Exception as exc:
        logger.error("Jina deepsearch error: %s", exc)
        return f"Deep search error: {exc}"


# ── Agent ─────────────────────────────────────────────────────────────────────

web_agent = KiberniktoAgent(
    model=infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME),
    name="web_expert",
    description="Searches the web, reads pages and runs deep research via Jina.",
    system_prompt=WEB_SYSTEM_PROMPT,
    deps_type=KiberniktoDeps,
)


@web_agent.tool
async def read_web(ctx: RunContext[KiberniktoDeps], url: str, user_request: str) -> str:
    """Read a web page and answer the user's request based on its content."""
    logger.info("read_web: url=%s request=%r", url, user_request[:100])
    content = await _jina_fetch(url)
    return f"Page content from {url}:\n\n{content}\n\nAnswer this request: {user_request}"


@web_agent.tool
async def web_search(ctx: RunContext[KiberniktoDeps], query: str) -> str:
    """Search the web for current information."""
    logger.info("web_search: %r", query[:100])
    return await _jina_search(query)


@web_agent.tool
async def deep_search(ctx: RunContext[KiberniktoDeps], request: str, effort_level: int = 5) -> str:
    """Run deep research on a complex question using Jina deepsearch."""
    logger.info("deep_search: %r effort=%s", request[:100], effort_level)
    return await _jina_deepsearch(request, effort_level=effort_level)