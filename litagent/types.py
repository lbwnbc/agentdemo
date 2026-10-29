"""工具调用与工具结果的数据契约。

消息本身沿用 OpenAI 兼容协议的 dict 形式（这是实际传输格式），
这里只定义工具调用/结果的归一化类型，避免两套消息表示互相转换。
"""
from __future__ import annotations

import json
from dataclasses import dataclass


class ToolError(Exception):
    """工具参数不合法或工具执行失败。"""


@dataclass
class ToolCall:
    """模型发起的一次工具调用。"""

    id: str
    name: str
    arguments: str = ""

    @classmethod
    def from_raw(cls, raw):
        function = raw.get("function") or {}
        return cls(
            id=raw.get("id", ""),
            name=function.get("name", ""),
            arguments=function.get("arguments") or "",
        )

    def parse_arguments(self):
        try:
            arguments = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ToolError("参数不是合法 JSON: {}".format(exc))
        if not isinstance(arguments, dict):
            raise ToolError("参数必须是 JSON 对象")
        return arguments


@dataclass
class ToolResult:
    """要回填给模型的工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False

    @classmethod
    def error(cls, tool_call_id, message):
        return cls(
            tool_call_id=tool_call_id,
            content=json.dumps({"status": "error", "message": message}, ensure_ascii=False),
            is_error=True,
        )

    def to_message(self):
        return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content}

