import logging
import traceback

logger = logging.getLogger("task_delegator")

from kibernikto.interactors.tools import Toolbox
from kibernikto.agent.kibernikto_context import kibernikto_context


async def delegate_task(agent_label: str,
                        instruction: str, effort_level: int = 5, key: str = "unknown", call_session_id: str = None):
    logger.info(
        f"\n\t- [delegate_task] \n"
        f"agent_label='{agent_label}'\n"
        f"instruction='{instruction}'\n"
        f"effort_level='{effort_level}'\n"
        f"key='{key}'\n"
        f"call_session_id='{call_session_id}'\n")
    initiator, delegate = kibernikto_context.get_task_delegate(key=key, agent_label=agent_label)
    try:
        if not delegate:
            raise AttributeError(f"ERROR: No agent found for {agent_label}")

        if call_session_id:
            kibernikto_context.add_call_session_data(session_key=call_session_id, label="delegate_task",
                                                     data={"initiator": initiator.label, "delegate": delegate.label})

        result = await delegate.query(message=instruction, effort_level=effort_level, call_session_id=call_session_id)

        call_result = f"[internal agent {agent_label}]: {result}"

        return f"{call_result}"

    except Exception as error:
        error_message = f"[internal agent {agent_label} error]: {error} [ACTION FAILED]"
        logger.error(error_message, exc_info=True)
        return error_message


def delegate_task_tool():
    return {
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": "Use delegate_task(task_type, instruction) to call specialized LLMs according to user orders and your common sense if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_label": {
                        "type": "string",
                        "description": "Label of agent to delegate this task to."
                    },
                    "instruction": {
                        "type": "string",
                        "description": f"""Clear step by step description what to do with concrete result."""
                    },

                    "effort_level": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 10,
                        "default": 5,
                        "description": f"""How hard the agent should try from 0 to 10 according to your common sense."""
                    }
                },
                "required": ["agent_label", "instruction"]
            }
        }
    }


delegate_box: Toolbox = Toolbox(function_name="delegate_task",
                                definition=delegate_task_tool(), implementation=delegate_task)
