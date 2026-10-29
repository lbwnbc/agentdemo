"""LLM 层的通用类型与接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LLMError(Exception):
    """LLM 调用失败：网络异常、鉴权失败、响应格式错误等。"""


@dataclass
class LLMResponse:
    """一次模型调用的归一化结果。"""

    message: dict
    usage: dict = field(default_factory=dict)
    model: str = ""

    @property
    def content(self):
        return self.message.get("content")

    @property
    def tool_calls(self):
        return self.message.get("tool_calls") or []


class LLMClient(ABC):
    """所有 provider 适配器需要实现的最小接口。"""

    @abstractmethod
    def chat(self, messages, tools=None) -> LLMResponse:
        raise NotImplementedError
