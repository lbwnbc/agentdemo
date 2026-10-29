"""工具协议：定义、参数校验、执行与输出截断。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from litagent.types import ToolCall, ToolError, ToolResult

DEFAULT_MAX_OUTPUT_CHARS = 8000

_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def truncate_text(text, limit=DEFAULT_MAX_OUTPUT_CHARS):
    """保留首尾，避免一次工具输出吃掉整个上下文。"""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return (
        "{}\n\n[输出已截断：原始 {} 字符，保留首尾各约 {} 字符；"
        "需要更多内容请缩小查询范围或分片读取]\n\n{}"
    ).format(text[:head], len(text), head, text[-tail:])


def validate_arguments(schema, arguments):
    """校验 JSON Schema 的最小子集：required 与基础类型。"""
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in arguments:
            raise ToolError("缺少必填参数: {}".format(key))
    for key, value in arguments.items():
        spec = properties.get(key)
        if not spec:
            continue
        expected = _JSON_TYPES.get(spec.get("type"))
        if expected and not isinstance(value, expected):
            raise ToolError(
                "参数 {} 类型错误：期望 {}，实际 {}".format(
                    key, spec.get("type"), type(value).__name__
                )
            )
        enum = spec.get("enum")
        if enum and value not in enum:
            raise ToolError("参数 {} 必须是 {} 之一".format(key, enum))


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS

    def spec(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, call):
        try:
            arguments = call.parse_arguments()
            validate_arguments(self.parameters, arguments)
            output = self.handler(**arguments)
        except ToolError as exc:
            return ToolResult.error(call.id, str(exc))
        except TypeError as exc:
            return ToolResult.error(call.id, "参数与工具签名不匹配: {}".format(exc))
        except Exception as exc:
            return ToolResult.error(
                call.id, "工具执行失败: {}: {}".format(type(exc).__name__, exc)
            )

        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False)
        return ToolResult(
            tool_call_id=call.id,
            content=truncate_text(output, self.max_output_chars),
        )
