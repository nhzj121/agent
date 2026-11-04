"""Guard a local tool view without changing its implementation or Agent loop."""
from hello_agents.tools.base import Tool
from services.execution_control import tool_boundary


class ControlledTool(Tool):
    def __init__(self, tool):
        super().__init__(tool.name, tool.description, tool.expandable)
        self.tool = tool

    def get_parameters(self):
        return self.tool.get_parameters()

    def get_expanded_tools(self):
        tools = self.tool.get_expanded_tools()
        return [ControlledTool(tool) for tool in tools] if tools else None

    def run(self, parameters):
        # Local tools are short filesystem operations; serialize with accepted cancel.
        with tool_boundary():
            result = self.tool.run(parameters)
        # A commit accepted before cancellation remains a truthful tool result.
        # The next tool/model boundary checks cancellation again.
        return result
