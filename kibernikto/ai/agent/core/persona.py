"""Persona: the agent's character prompt rendered as a Handlebars template against a small ``Persona`` model.

The template source is ``{FILESTORE}/{name}-instructions.txt`` or ``AGENT_KIBERNIKTO_WHO_AM_I``; text
without ``{{`` stays a plain static instruction. Values come from a ``PersonaSource`` per run, so a static
source can later be swapped for one backed by storage, mood, chat, etc. without touching the template.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic_ai import RunContext, TemplateStr

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.storage.config import STORAGE_SETTINGS


@dataclass(frozen=True, slots=True)
class Persona:
    """Template variables: ``{{name}}``, ``{{traits.sarcasm}}``, ``{{#each traits}}{{@key}}: {{this}}{{/each}}``."""

    name: str
    traits: dict[str, int] = field(default_factory=dict)


class PersonaSource(Protocol):
    """Supplies persona values for one run; ``deps`` is the run's deps (may be ``None``)."""

    async def get(self, deps: object) -> Persona: ...


DEFAULT_PERSONA_NAME = "Kibernikto"


@dataclass(frozen=True, slots=True)
class StaticPersona:
    """Env-backed persona: ``AGENT_KIBERNIKTO_PERSONA_NAME`` + ``AGENT_KIBERNIKTO_PERSONA_TRAITS``."""

    name: str | None = None
    traits: dict[str, int] | None = None

    def resolve_name(self) -> str:
        """Explicit arg → env override → default; transports override to add their own name."""
        return self.name or AGENT_KIBERNIKTO_SETTINGS.PERSONA_NAME or DEFAULT_PERSONA_NAME

    async def get(self, deps: object) -> Persona:
        traits = AGENT_KIBERNIKTO_SETTINGS.PERSONA_TRAITS if self.traits is None else self.traits
        return Persona(name=self.resolve_name(), traits=dict(traits))


def persona_source_text(name: str) -> str:
    """Raw persona text: ``{FILESTORE}/{name}-instructions.txt`` if present, else ``WHO_AM_I``."""
    path = Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / f"{name}-instructions.txt"
    return path.read_text(encoding="utf-8") if path.exists() else AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I


@dataclass(frozen=True, slots=True)
class PersonaPrompt:
    """Instruction callable: renders the compiled template with the source's values each run."""

    template: TemplateStr[Persona]
    source: PersonaSource

    async def __call__(self, ctx: RunContext[object]) -> str:
        return self.template.render(await self.source.get(ctx.deps))


def compile_persona(text: str, source: PersonaSource) -> str | PersonaPrompt:
    """Plain text stays static; a template is compiled now so a bad field name fails at startup."""
    if "{{" not in text:
        return text
    return PersonaPrompt(TemplateStr(text, deps_type=Persona), source)
