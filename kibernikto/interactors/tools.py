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
        if permitted_names and not tool_name in permitted_names:
            continue
        for function_name, function in getmembers(tool_module, isfunction):

            if tool_name in function_name:
                if function_name.endswith("_tool"):
                    definition = function()
                else:
                    implementation = function
        tools.append(Toolbox(function_name=tool_name, definition=definition, implementation=implementation))
    return tools
