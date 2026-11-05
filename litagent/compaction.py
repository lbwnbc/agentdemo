"""上下文压缩：把较早的调研轮次摘要成一条事实说明，保留最近对话。

切分点永远落在 user 消息之前，保证 assistant 的 tool_calls 与后续 tool 结果
不会被拆开——否则模型会收到孤立的工具结果。
"""
from __future__ import annotations

SUMMARY_SYSTEM = (
    "你是调研对话的摘要助手。把历史压缩成事实清单，供后续继续调研时当作上下文使用。"
)

SUMMARY_INSTRUCTIONS = """请把下面的调研历史压缩成一段摘要（不超过 400 字），必须保留：
1. 用户的研究目标与已确认的检索边界；
2. 已经检索到或精读过的论文编号、标题要点；
3. 已保存的证据笔记编号及其论断（如 n1: ...）；
4. 未完成的子问题或下一步计划。
丢弃重复的工具原始输出和客套话。只输出摘要正文，不要加标题。

历史：
{history}
"""


def _truncate(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _render_message(message, max_chars):
    role = message.get("role", "unknown")
    content = _truncate(message.get("content") or "", max_chars)
    if role == "assistant":
        calls = message.get("tool_calls") or []
        if calls:
            names = []
            for raw in calls:
                function = raw.get("function", {})
                names.append(
                    "{} {}".format(
                        function.get("name", "?"),
                        _truncate(function.get("arguments", ""), 120),
                    )
                )
            return "assistant: {} | 调用: {}".format(content or "(无正文)", "; ".join(names))
        return "assistant: {}".format(content)
    return "{}: {}".format(role, content)


def split_for_compaction(messages, keep_turns=2):
    """返回 (system, older, recent)；轮次不足时返回 None。"""
    system = [message for message in messages if message.get("role") == "system"]
    body = [message for message in messages if message.get("role") != "system"]
    user_positions = [
        index for index, message in enumerate(body) if message.get("role") == "user"
    ]
    if len(user_positions) <= keep_turns:
        return None
    cut = user_positions[-keep_turns]
    if cut <= 0:
        return None
    return system, body[:cut], body[cut:]


def compact_messages(
    messages,
    client,
    keep_turns=2,
    max_chars_per_message=600,
    summary_limit=400,
):
    """压缩历史；没有可压缩内容时返回 None。"""
    parts = split_for_compaction(messages, keep_turns)
    if parts is None:
        return None
    system, older, recent = parts

    history = "\n".join(
        _render_message(message, max_chars_per_message) for message in older
    )
    response = client.chat(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {
                "role": "user",
                "content": SUMMARY_INSTRUCTIONS.format(history=history),
            },
        ],
        tools=None,
    )
    summary = _truncate((response.content or "").strip(), summary_limit)
    if not summary:
        raise ValueError("压缩失败：模型没有返回摘要")

    summary_message = {"role": "user", "content": "【历史摘要】\n" + summary}
    return system + [summary_message] + recent
