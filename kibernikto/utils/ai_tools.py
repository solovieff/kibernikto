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


def is_function_call(choice: Choice, xml=False):
    if not xml:
        return choice.finish_reason == "tool_calls"
    else:
        if 'function_name' in choice.message.content and 'call_id' in choice.message.content:
            try:
                logging.warning(choice.message.content)
                function_string = choice.message.content.replace('\n', ' ').replace('\r', '')
                call_dict = parse_json_garbage(function_string)
                # call_dict = json.loads(json_string)
                pprint.pprint(call_dict)
            except JSONDecodeError as err:
                logging.error(str(err))
                return False
            new_ai_tool_call = ChatCompletionMessageToolCall(
                id=str(call_dict['call_id']),
                type="function",
                function=Function(name=call_dict['function_name'],
                                  arguments=json.dumps(call_dict['parameters'])
                                  ))
            choice.message.tool_calls = [new_ai_tool_call]
            return True
    return False


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
        result = str(e)
    return result


def get_tool_call_serving_messages(tool_call: ChatCompletionMessageToolCall, tool_call_result, xml=False):
    if not xml:
        call_message = {
            "role": "assistant",
            "tool_call_id": tool_call.id,
            "content": None,
            "function_call": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }
        result_message = {
            "role": "function",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": f'{{"result": {str(tool_call_result)} }}'}
        return [call_message, result_message]
    elif xml:
        call_message = f"""
            <function_calls>
                <invoke>
                    <tool_name>{tool_call.function.name}</tool_name>
                    <parameters>
                        {tool_call.function.arguments}
                    </parameters>
                </invoke>
            </function_calls>
        """

        result_xml_string = f"""
                    <function_results>
                        <result>
                            <tool_name>{tool_call.function.name}</tool_name>
                            <stdout>
                                {str(tool_call_result)}
                            </stdout>
                        </result>
                    </function_results>
                """
        result_message = {
            "role": "user",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": result_xml_string
        }
        return [result_message]


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
