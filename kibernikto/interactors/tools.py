import logging
from inspect import getmembers, isfunction, ismodule
from typing import Any, Callable

from pydantic import BaseModel


class Toolbox(BaseModel):
    function_name: str
    definition: dict
    implementation: Callable

def get_tools_from_module(python_module, permitted_names=[]):
    tools = []
    for tool_name, tool_module in getmembers(python_module, ismodule):
        # print(f"\nfound {tool_name}")
        if permitted_names and tool_name not in permitted_names:
            continue
        for function_name, function in getmembers(tool_module, isfunction):
            if tool_name in function_name:
                if function_name.endswith("_tool"):
                    definition = function()
                else:
                    implementation = function
        try:
            tools.append(Toolbox(function_name=tool_name, definition=definition, implementation=implementation))
        except Exception as e:
            logging.warning(f"skipping '{tool_name}' in tools {python_module.__name__}: {e}")
    return tools
