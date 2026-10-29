"""工具注册表。"""
from __future__ import annotations

from litagent.types import ToolResult


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError("工具重复注册: {}".format(tool.name))
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return sorted(self._tools)

    def specs(self):
        return [self._tools[name].spec() for name in sorted(self._tools)]

    def execute(self, call):
        tool = self.get(call.name)
        if tool is None:
            return ToolResult.error(
                call.id,
                "未知工具: {}，可用工具: {}".format(call.name, ", ".join(self.names())),
            )
        return tool.execute(call)
