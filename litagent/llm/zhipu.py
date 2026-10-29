"""智谱（OpenAI 兼容协议）LLM 适配器。"""
from __future__ import annotations

import time

import requests

from litagent.config import Settings
from litagent.llm.base import LLMClient, LLMError, LLMResponse

# 可重试的状态码：限流与服务端错误
RETRY_STATUS = {429, 500, 502, 503, 504}


class ZhipuClient(LLMClient):
    def __init__(self, settings: Settings):
        self.settings = settings

    def chat(self, messages, tools=None) -> LLMResponse:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": self.settings.api_key,
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = requests.post(
                    self.settings.chat_url,
                    headers=headers,
                    json=payload,
                    timeout=self.settings.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    return self._parse(response)
                if response.status_code not in RETRY_STATUS:
                    raise LLMError(
                        "API 调用失败: {}, {}".format(response.status_code, response.text)
                    )
                last_error = LLMError(
                    "API 调用失败: {}, {}".format(response.status_code, response.text)
                )

            if attempt < self.settings.max_retries:
                time.sleep(2 ** attempt)

        raise LLMError("重试 {} 次后仍失败: {}".format(self.settings.max_retries, last_error))

    @staticmethod
    def _parse(response):
        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError("响应格式异常: {}".format(data)) from exc
        return LLMResponse(
            message=message,
            usage=data.get("usage") or {},
            model=data.get("model", ""),
        )
