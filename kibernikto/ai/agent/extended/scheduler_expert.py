"""SchedulerExpert — cron notifications and event management.

Migrates the old SchedulerExpert: plan_event, plan_many, replan_event, delete_event, clear_all, set_user_timezone.
Events are stored in JSON. Cron execution (daemon) is a separate concern, not implemented here.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

SCHEDULER_SYSTEM_PROMPT = (
    "You are a scheduler expert. You manage cron-based notifications and reminders for the user. "
    "Cron format: minute hour day month weekday. 'Today' lasts until the user sleeps, not until midnight. "
    "Alert messages should be in Russian. Default language is Russian."
)


# ── Data models ───────────────────────────────────────────────────────────────

class SchedulerEvent(BaseModel):
    """One scheduled cron event."""

    jobid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_text: str
    schedule_utc: str  # cron string in UTC
    next_run_utc: Optional[str] = None
    next_run_local: Optional[str] = None
    recurring: bool = True


class SchedulerInfo(BaseModel):
    """Per-user scheduler data: timezone and events."""

    timezone: str = "Europe/Moscow"
    events: list[SchedulerEvent] = Field(default_factory=list)


# ── JSON storage ──────────────────────────────────────────────────────────────

class SchedulerStorage:
    """Per-chat JSON storage under ~/.kibernikto/scheduler/{chat_id}.json."""

    _BASE_DIR = Path.home() / ".kibernikto" / "scheduler"

    @classmethod
    def _path(cls, chat_id: int) -> Path:
        cls._BASE_DIR.mkdir(parents=True, exist_ok=True)
        return cls._BASE_DIR / f"{chat_id}.json"

    @classmethod
    def load(cls, chat_id: int) -> SchedulerInfo:
        """Load SchedulerInfo for chat_id, creating defaults on first use."""
        path = cls._path(chat_id)
        if path.exists():
            try:
                return SchedulerInfo.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load scheduler data for %s: %s", chat_id, exc)
        return SchedulerInfo()

    @classmethod
    def save(cls, chat_id: int, info: SchedulerInfo) -> None:
        """Persist SchedulerInfo to JSON."""
        path = cls._path(chat_id)
        path.write_text(info.model_dump_json(indent=2), encoding="utf-8")


# ── Agent ─────────────────────────────────────────────────────────────────────

scheduler_agent = KiberniktoAgent(
    model=infer_kibernikto_model("openrouter:google/gemini-2.5-flash"),
    name="scheduler_expert",
    description="Manages cron-based notifications, reminders and user timezone.",
    system_prompt=SCHEDULER_SYSTEM_PROMPT,
    deps_type=KiberniktoDeps,
)


@scheduler_agent.tool
async def plan_event(
    ctx: RunContext[KiberniktoDeps],
    local_cron: str,
    utc_cron: str,
    alert_message: str,
    one_time: bool = False,
) -> dict:
    """Create a cron-based event. Use standard cron format for local_cron and utc_cron."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    event = SchedulerEvent(
        task_text=alert_message,
        schedule_utc=utc_cron,
        recurring=not one_time,
    )
    info.events.append(event)
    SchedulerStorage.save(chat_id, info)
    logger.info("plan_event: chat=%s cron=%s msg=%r", chat_id, utc_cron, alert_message[:80])
    return {"result": "ok", "alert_message": alert_message, "jobid": event.jobid}


@scheduler_agent.tool
async def plan_many(
    ctx: RunContext[KiberniktoDeps],
    events: list[dict],
) -> dict:
    """Create multiple cron events at once. Each event dict: {local_cron, utc_cron, alert_message, one_time}."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    created = []
    for ev in events:
        event = SchedulerEvent(
            task_text=ev.get("alert_message", ""),
            schedule_utc=ev.get("utc_cron", ""),
            recurring=not ev.get("one_time", False),
        )
        info.events.append(event)
        created.append(event.jobid)
    SchedulerStorage.save(chat_id, info)
    logger.info("plan_many: chat=%s count=%d", chat_id, len(created))
    return {"result": "ok", "created": len(created), "jobids": created}


@scheduler_agent.tool
async def replan_event(
    ctx: RunContext[KiberniktoDeps],
    description: str,
    new_utc_cron: str,
    new_alert_message: str = "",
) -> dict:
    """Modify an existing event by matching its description."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    # Find events matching the description (case-insensitive substring).
    matches = [e for e in info.events if description.lower() in e.task_text.lower()]
    if not matches:
        return {"error": f"No events found matching {description!r}."}
    for ev in matches:
        ev.schedule_utc = new_utc_cron
        if new_alert_message:
            ev.task_text = new_alert_message
    SchedulerStorage.save(chat_id, info)
    logger.info("replan_event: chat=%s matched=%d", chat_id, len(matches))
    return {"result": "ok", "modified": len(matches)}


@scheduler_agent.tool
async def delete_event(ctx: RunContext[KiberniktoDeps], description: str) -> dict:
    """Delete events matching the description (case-insensitive substring)."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    before = len(info.events)
    info.events = [e for e in info.events if description.lower() not in e.task_text.lower()]
    deleted = before - len(info.events)
    SchedulerStorage.save(chat_id, info)
    logger.info("delete_event: chat=%s deleted=%d", chat_id, deleted)
    return {"result": "ok", "deleted": deleted}


@scheduler_agent.tool
async def clear_all(ctx: RunContext[KiberniktoDeps]) -> dict:
    """Delete all scheduled events for the user."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    count = len(info.events)
    info.events.clear()
    SchedulerStorage.save(chat_id, info)
    logger.info("clear_all: chat=%s cleared=%d", chat_id, count)
    return {"result": "ok", "cleared": count}


@scheduler_agent.tool
async def set_user_timezone(ctx: RunContext[KiberniktoDeps], new_timezone: str) -> dict:
    """Set the user's timezone (e.g. 'Europe/Moscow', 'America/New_York')."""
    chat_id = ctx.deps.chat_id if ctx.deps else None
    if chat_id is None:
        return {"error": "No chat context available."}
    info = SchedulerStorage.load(chat_id)
    info.timezone = new_timezone
    SchedulerStorage.save(chat_id, info)
    logger.info("set_user_timezone: chat=%s tz=%s", chat_id, new_timezone)
    return {"result": "ok", "timezone": new_timezone}