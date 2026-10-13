"""Delegation capability: stock harness ``SubAgents`` with Kibernikto's own roster instructions."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai_harness.subagents import SubAgent, SubAgents

# Roster preamble replacing the harness default: decide, delegate with full context, answer.
DELEGATION_GUIDE = (
    "You have access to LLM agents for solving various tasks via the `delegate_task` function.\n"
    "When receiving a request, you must:\n"
    "1. Determine if any agents can be useful for completing the task.\n"
    "2. Use these agents to obtain necessary information or perform actions. An agent does not see this "
    "conversation: pass it everything it needs (exact question, links, names, dates, the user's language).\n"
    "3. Provide the user with an accurate and helpful response to their request.\n"
    "Do not bother agents if you can do the job yourself with GOOD quality. You cannot know anything current "
    "or recent yourself: never answer such questions from memory."
)


@dataclass
class KiberniktoSubAgents(SubAgents):
    """Stock ``SubAgents`` delegation with ``DELEGATION_GUIDE`` instead of the harness roster text."""

    def get_instructions(self) -> str | None:
        # The stock text is None when delegation is off (max depth) or nobody is listed: keep that contract.
        if super().get_instructions() is None:
            return None
        roster = "\n".join(_roster_line(sub_agent) for sub_agent in self.agents)
        return f"{DELEGATION_GUIDE}\n\nAvailable agents:\n{roster}"


def _roster_line(sub_agent: SubAgent) -> str:
    name = sub_agent.name or sub_agent.agent.name
    description = sub_agent.description or sub_agent.agent.description
    return f"- {name}: {description}" if description else f"- {name}"
