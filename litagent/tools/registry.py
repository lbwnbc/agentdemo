"""工具注册表与调用治理钩子。"""
from __future__ import annotations

from dataclasses import dataclass

from litagent.types import ToolResult


@dataclass
class ToolDecision:
    """前置钩子的返回值；block 为真时不再执行工具。"""

    block: bool = False
    reason: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._before_hooks = []
        self._after_hooks = []

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError("工具重复注册: {}".format(tool.name))
        self._tools[tool.name] = tool

    def add_before_hook(self, hook):
        self._before_hooks.append(hook)

    def add_after_hook(self, hook):
        self._after_hooks.append(hook)

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

        try:
            for hook in self._before_hooks:
                decision = hook(call)
                if decision is not None and decision.block:
                    return ToolResult.error(
                        call.id, "调用被拦截: {}".format(decision.reason or "未说明原因")
                    )
        except Exception as exc:
            return ToolResult.error(
                call.id, "前置钩子异常: {}: {}".format(type(exc).__name__, exc)
            )

        result = tool.execute(call)

        try:
            for hook in self._after_hooks:
                replacement = hook(call, result)
                if replacement is not None:
                    result = replacement
        except Exception as exc:
            return ToolResult.error(
                call.id, "后置钩子异常: {}: {}".format(type(exc).__name__, exc)
            )
        return result
