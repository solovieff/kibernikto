import json
import logging
import pprint
import uuid
from json import JSONDecodeError

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function

from .text import parse_json_garbage


def tool_to_claude_xml(tool_dict):
    tool_func = tool_dict['function']
    parameters = []
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


def is_function_call(choice: Choice, model: str):
    if "gpt" in model:
        return choice.finish_reason == "tool_calls"
    if "claude" in model:
        if 'function_name' in choice.message.content and 'parameters' in choice.message.content:
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
                id=str(uuid.uuid4()),
                type="function",
                function=Function(name=call_dict['function_name'],
                                  arguments=json.dumps(call_dict['parameters'])
                                  ))
            choice.message.tool_calls = [new_ai_tool_call]
            return True
    return False


async def execute_tool_call_function(available_functions, tool_call: ChatCompletionMessageToolCall):
    tool_call_function: Function = tool_call.function
    fn_name = tool_call_function.name
    arguments: str = tool_call_function.arguments

    dict_args = json.loads(arguments)

    function = getattr(available_functions, fn_name)
    try:
        result = await function(**dict_args)
    except Exception as e:
        result = str(e)
    return result


def get_tool_call_serving_messages(tool_call: ChatCompletionMessageToolCall, tool_call_result, model: str):
    if "gpt" in model:
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
    elif "claude" in model:
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
