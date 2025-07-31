from kibernikto.agent.kibernikto_context import kibernikto_context
from kibernikto.interactors.tools import Toolbox


async def get_session_data(key: str, call_session_id: str) -> dict:
    call_initiator, _ = kibernikto_context.get_task_delegate(key=key, agent_label=None)
    call_session_data = kibernikto_context.get_call_session_data(session_key=call_session_id)
    return call_session_data


def get_session_data_tool():
    """
    Returns the OpenAI tool specification for the get_session_data function.

    :return: A dictionary describing the tool and its parameters.
    """
    return {
        "type": "function",
        "function": {
            "name": "get_session_data",
            "description": "Returns current session data.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }


session_data_tool = Toolbox(function_name="get_session_data", definition=get_session_data_tool(),
                            implementation=get_session_data)
