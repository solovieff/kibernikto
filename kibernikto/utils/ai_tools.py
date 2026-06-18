import asyncio
import functools
import inspect
import json
import logging
import pprint
from typing import Callable, List, Optional

# Initialize logger
logger = logging.getLogger("kibernikto.ai_tools")

from dict2xml import dict2xml
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function

from .text import parse_json_garbage
from ..interactors.tools import Toolbox


def tool_to_claude_dict(tool: Toolbox):
    tool_dict = tool.definition
    tool_func = tool_dict['function']
    parameters = []
    if 'parameters' in tool_func and 'properties' in tool_func['parameters']:
        for prop in tool_func['parameters']['properties'].items():
            name, prop_params = prop
            parameters.append({
                'name': name,
                'description': prop_params.get('description', name),
                'type': prop_params['type']
            })
    claude_dict = {"tool_name": tool_func['name'],
                   "description": tool_func['description'],
                   "parameters": {"parameter": parameters}
                   }

    return claude_dict


def is_function_call(choice: Choice):
    return choice.finish_reason == "tool_calls" or (choice.message.tool_calls and len(choice.message.tool_calls) > 0)


async def run_tool_calls_sequential(choice: Choice, available_tools: list[Toolbox], unique_id: str, call_session_id: str = None):
    """
    Legacy sequential execution of tool calls. Returns messages to inject back into conversation.
    """
    if not choice.message.tool_calls:
        raise ValueError("No tools provided!")

    tool_call_messages = []

    for tool_call in choice.message.tool_calls:
        fn_name = tool_call.function.name
        function_impl = get_tool_impl(available_tools=available_tools, fn_name=fn_name)
        if not function_impl:
            logger.error(f"no impl for {fn_name}")
            pprint.pprint(tool_call)
            try:
                tool_call_result = parse_json_garbage(f"ERROR: no impl for {fn_name}")
            except Exception:
                tool_call_result = f"ERROR: no impl for {fn_name}"
        else:
            additional_params = dict(key=unique_id, call_session_id=call_session_id)
            tool_call_result = await execute_tool_call_function(tool_call, function_impl=function_impl,
                                                                additional_params=additional_params)

        tool_call_messages += get_tool_call_serving_messages(tool_call, tool_call_result, choice=choice)

    return tool_call_messages


async def run_tool_calls_parallel(choice: Choice, available_tools: list[Toolbox], unique_id: str, call_session_id: str = None,
                                  max_concurrency: Optional[int] = None):
    """
    Run tool calls concurrently and return messages to inject back into the conversation.
    Preserves the original order of tool_calls in the returned messages.
    """
    if not choice.message.tool_calls:
        raise ValueError("No tools provided!")

    tool_call_messages = []

    sem = asyncio.Semaphore(max_concurrency) if (max_concurrency and max_concurrency > 0) else None

    async def _exec_with_limit(tool_call, function_impl, additional_params, sem: Optional[asyncio.Semaphore]):
        if sem is not None:
            async with sem:
                return await execute_tool_call_function(tool_call, function_impl=function_impl,
                                                        additional_params=additional_params)
        else:
            return await execute_tool_call_function(tool_call, function_impl=function_impl,
                                                    additional_params=additional_params)

    tasks = []
    for tool_call in choice.message.tool_calls:
        fn_name = tool_call.function.name
        function_impl = get_tool_impl(available_tools=available_tools, fn_name=fn_name)
        if not function_impl:
            logger.error(f"no impl for {fn_name}")
            pprint.pprint(tool_call)

            async def _missing_impl(_tc=tool_call, _fn=fn_name):
                try:
                    return parse_json_garbage(f"ERROR: no impl for {_fn}")
                except Exception:
                    return f"ERROR: no impl for {_fn}"

            task = asyncio.create_task(_missing_impl())
        else:
            additional_params = dict(key=unique_id, call_session_id=call_session_id)
            task = asyncio.create_task(_exec_with_limit(tool_call, function_impl, additional_params, sem))
        tasks.append((tool_call, task))

    results = await asyncio.gather(*(t for (_, t) in tasks), return_exceptions=True)

    for (tool_call, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Tool call raised: {result}", exc_info=True)
            try:
                tool_call_result = parse_json_garbage(f"ERROR: {result}")
            except Exception:
                tool_call_result = f"ERROR: {result}"
        else:
            tool_call_result = result

        tool_call_messages += get_tool_call_serving_messages(tool_call, tool_call_result, choice=choice)

    return tool_call_messages


async def run_tool_calls(choice: Choice, available_tools: list[Toolbox], unique_id: str, call_session_id: str = None,
                         parallel: bool = False, max_concurrency: Optional[int] = None):
    """
    Dispatcher: run tool calls sequentially or in parallel based on `parallel` flag.
    """
    if parallel:
        return await run_tool_calls_parallel(choice, available_tools, unique_id, call_session_id,
                                             max_concurrency=max_concurrency)
    return await run_tool_calls_sequential(choice, available_tools, unique_id, call_session_id)


def get_tool_impl(available_tools: list[Toolbox], fn_name: str) -> Callable:
    for x in available_tools:
        if x.function_name == fn_name:
            return x.implementation
    return None


async def execute_tool_call_function(tool_call: ChatCompletionMessageToolCall,
                                     function_impl: Callable, additional_params: Optional[dict] = None):
    """
    Execute a single tool call. Supports async functions and sync functions (runs sync in threadpool).
    Returns the raw result (dict/list/str/etc) or an error-string wrapper when the call fails.
    """
    if additional_params is None:
        additional_params = {}

    tool_call_function: Function = tool_call.function
    fn_name = tool_call_function.name
    arguments: str = tool_call_function.arguments

    if arguments is None:
        dict_args = {}
    else:
        dict_args = json.loads(arguments)

    impl_params = inspect.getfullargspec(function_impl)[0]

    for key in additional_params:
        if key in impl_params:
            dict_args[key] = additional_params[key]
    logger.info(f"👷‍♀️ running '{fn_name}' with params {dict_args}")

    try:
        # If function_impl is a coroutine function, await it.
        if asyncio.iscoroutinefunction(function_impl):
            result = await function_impl(**dict_args)
        else:
            # Run sync function in threadpool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, functools.partial(function_impl, **dict_args))
    except Exception as e:
        logger.error(f"{e}", exc_info=True)
        try:
            result = parse_json_garbage(
                f"ERROR: {e} [TOOL CALL FAILED]"
            )
        except Exception as e:
            result = f"ERROR: {e} [TOOL CALL FAILED]"
    return result


def get_tool_call_serving_messages(tool_call: ChatCompletionMessageToolCall, tool_call_result, choice: Choice = None):
    call_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                }
            }
        ]
    }

    if choice and choice.message:
        if choice.message.content:
            call_message['content'] = choice.message.content

        if hasattr(choice.message, 'reasoning_details'):
            call_message['reasoning_details'] = choice.message.reasoning_details

    if isinstance(tool_call_result, (dict, list)):
        result_content = json.dumps(tool_call_result, ensure_ascii=False, default=str)
    else:
        result_content = str(tool_call_result)

    result_message = {
        # "role": "function",
        "role": "tool",
        "tool_call_id": tool_call.id,
        # "name": tool_call.function.name,
        "content": result_content
    }
    return [call_message, result_message]


def get_tools_xml(tools: List[Toolbox]):
    function_xml_descriptions = []
    for tool in tools:
        claude_tool_dict = tool_to_claude_dict(tool)
        function_xml_descriptions.append(claude_tool_dict)
    all_tools = {
        "tools": {"tool_description": function_xml_descriptions}
    }
    xml = dict2xml(all_tools)
    print(xml)
    return xml
