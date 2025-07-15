# openai_executor_utils.py
import logging


def get_tool_implementation(executor, tool_name):
    """
    Gets the implementation of a tool by its name.

    Args:
        executor: Instance of OpenAIExecutor (to access configuration)
        tool_name: Name of the tool

    Returns:
        Tool handler function
    """
    for tool in executor.tools:
        if tool.get("name") == tool_name:
            if not tool.get("callable", None):
                return None
            return tool["callable"]
    return None


def calculate_max_messages(config):
    """
    Calculates the maximum number of messages based on configuration.

    This function determines the maximum number of messages to keep in history,
    adjusting for tools and ensuring an odd number for balanced conversation.

    Args:
        config: OpenAiExecutorConfig instance with configuration parameters

    Returns:
        int: Calculated maximum number of messages
    """
    history_len = config.max_messages

    # Adjust history length if tools are present
    if config.tools:
        history_len = config.max_messages + len(config.tools) * 2

    # Ensure odd number for balanced conversation
    if config.max_messages % 2 == 0:
        return history_len
    else:
        return history_len + 1


def check_word_overflow(messages: list, max_words: int):
    """
    Checks if the word count in messages exceeds the given threshold.

    Args:
        messages: List of messages
        max_words: Maximum word count

    Returns:
        bool: True if the word count exceeds the threshold
    """

    if max_words == 0:
        return False
    word_count = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            word_count += len(content.split())

    return word_count > max_words


def aware_overflow(messages, max_messages):
    """
    Checks if the number of messages exceeds the given threshold,
    taking into account the system message.

    Args:
        messages: List of messages
        max_messages: Maximum number of messages

    Returns:
        bool: True if the message count exceeds the threshold
    """
    if len(messages) <= max_messages:
        return False

    # Don't count the system message if it exists
    adjusted_count = len(messages)
    if messages and messages[0].get("role") == "system":
        adjusted_count -= 1

    return adjusted_count > max_messages


def default_headers(executor):
    """
    Creates standard headers for API requests.

    Args:
        executor: Instance of OpenAIExecutor (to access configuration)

    Returns:
        dict: Headers for API request
    """
    return {
        "x-app-id": executor.full_config.app_id,
        "x-device-type": "desktop",
        "x-device-id": executor.unique_id
    }


def has_pricing(config):
    """
    Checks if both input and output prices are set in the configuration.

    Args:
        config: OpenAiExecutorConfig instance

    Returns:
        bool: True if both input and output prices are set
    """
    return config.input_price is not None and config.output_price is not None


def process_usage(usage: dict, executor):
    """
    Processes API usage information from the response.

    Args:
        usage: API response usage information
        executor: Instance of OpenAIExecutor

    Returns:
        dict: API usage information
    """
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    input_price = executor.full_config.input_price
    output_price = executor.full_config.output_price

    input_cost = prompt_tokens * input_price / 1000
    output_cost = completion_tokens * output_price / 1000
    total_cost = input_cost + output_cost

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost
    }


def prepare_message_prompt(messages_to_check: list) -> list:
    messages_list: list = messages_to_check.copy()

    def is_bad_first_message() -> bool:
        if not len(messages_list):
            return False
        first_message = messages_list[0]
        return first_message['role'] != 'user'

    while is_bad_first_message():
        logging.debug("removing bad first message")
        messages_list.pop(0)

    return messages_list


def should_react(executor, message_content):
    """
    Determines if a reaction to the message is needed.

    Args:
        executor: Instance of OpenAIExecutor
        message_content: Message content

    Returns:
        bool: True if a reaction is needed
    """
    if not executor.full_config.reaction_calls:
        return False

    # Check if the message contains any of the reaction triggers
    for pattern in executor.full_config.reaction_calls:
        if pattern.lower() in message_content.lower():
            return True

    return False
