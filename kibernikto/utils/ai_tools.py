import inspect
import json
import logging
import pprint
import uuid
from json import JSONDecodeError
from typing import Callable, List

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


async def run_tool_calls(choice: Choice, available_tools: list[Toolbox], unique_id: str):
    if not choice.message.tool_calls:
        raise ValueError("No tools provided!")

    # if is None it's a recursive tool call
    tool_call_messages = []

    for tool_call in choice.message.tool_calls:
        fn_name = tool_call.function.name
        function_impl = get_tool_impl(available_tools=available_tools, fn_name=fn_name)
        if not function_impl:
            logging.error(f"no impl for {fn_name}")
            pprint.pprint(tool_call)
        additional_params = dict(key=unique_id)
        tool_call_result = await execute_tool_call_function(tool_call, function_impl=function_impl,
                                                            additional_params=additional_params)
        tool_call_messages += get_tool_call_serving_messages(tool_call, tool_call_result)

    return tool_call_messages


def get_tool_impl(available_tools: list[Toolbox], fn_name: str) -> Callable:
    for x in available_tools:
        if x.function_name == fn_name:
            return x.implementation
    return None


async def execute_tool_call_function(tool_call: ChatCompletionMessageToolCall,
                                     function_impl: Callable, additional_params: dict = {}):
    tool_call_function: Function = tool_call.function
    fn_name = tool_call_function.name
    arguments: str = tool_call_function.arguments

    dict_args = json.loads(arguments)

    impl_params = inspect.getfullargspec(function_impl)[0]

    for key in additional_params:
        if key in impl_params:
            dict_args[key] = additional_params[key]
    logging.info(f"running {fn_name} with params {dict_args}")
    try:
        result = await function_impl(**dict_args)
    except Exception as e:
        logging.error(f"{e}")
        result = str(e)
    return result


def get_tool_call_serving_messages(tool_call: ChatCompletionMessageToolCall, tool_call_result):
    call_message = {
        "role": "assistant",
        "content": None,
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
    result_message = {
        # "role": "function",
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.function.name,
        "content": f'{str(tool_call_result)}'}
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


def get_claude_tools_info(xml_string):
    call_example = """
                {
                    "function_name": $TOOL_NAME,
                    "parameters": {
                        "$PARAM_NAME": $PARAM_VALUE
                        ...
                    },
                    "call_id": $RANDOM
                }
            """
    tools_content = f"""
    In this environment you have access to a set of tools you can use to answer the user's question. 
    To let me know you want to call a tool return only tool call description JSON without any comments.
    Like this:
    {call_example}\n
    Call the tools only if you need to!
    Here are the tools available:\n{xml_string}
            """
    return tools_content
