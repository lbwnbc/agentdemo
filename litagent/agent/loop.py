"""Agent Loop：驱动模型调用与工具执行的循环。

语义对齐 pi 的 runLoop / executeToolCalls / agentLoopContinue：
- 每轮调用模型，有工具调用就执行并把结果回填，没有则结束；
- 同轮多个工具并行执行，结果按模型给出的顺序回填；
- 支持步数上限、token 预算、外部中断和断点续跑。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from litagent.types import AgentEvent, Event, ToolCall


DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_WORKERS = 4


@dataclass
class LoopResult:
    content: str
    messages: list
    stop_reason: str
    steps: int
    usage: dict = field(default_factory=dict)


def run_loop(
    client,
    registry,
    messages,
    max_turns=DEFAULT_MAX_TURNS,
    token_budget=None,
    max_workers=DEFAULT_MAX_WORKERS,
    should_stop=None,
    on_event=None,
):
    """从当前消息开始跑循环；messages 会被就地追加。"""
    return _run(
        client,
        registry,
        messages,
        max_turns,
        token_budget,
        max_workers,
        should_stop,
        on_event,
        resolve_pending=False,
    )


def run_loop_continue(
    client,
    registry,
    messages,
    max_turns=DEFAULT_MAX_TURNS,
    token_budget=None,
    max_workers=DEFAULT_MAX_WORKERS,
    should_stop=None,
    on_event=None,
):
    """续跑：先执行最后一条 assistant 消息里未完成的工具调用，再继续循环。"""
    return _run(
        client,
        registry,
        messages,
        max_turns,
        token_budget,
        max_workers,
        should_stop,
        on_event,
        resolve_pending=True,
    )


def _start_pending_tool_calls(last_message):
    if not last_message or last_message.get("role") != "assistant":
        return None
    raw_calls = last_message.get("tool_calls") or []
    if not raw_calls:
        return None
    return [ToolCall.from_raw(raw) for raw in raw_calls]


def _run(
    client,
    registry,
    messages,
    max_turns,
    token_budget,
    max_workers,
    should_stop,
    on_event,
    resolve_pending,
):
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    steps = 0
    content = ""
    stop_reason = "max_turns"
    _emit(on_event, AgentEvent.AGENT_START, messages=messages)

    if resolve_pending:
        calls = _start_pending_tool_calls(messages[-1] if messages else None)
        if calls is None:
            raise ValueError("最后一条消息不是待执行的工具调用，无法续跑")
        results = _execute_tool_calls(registry, calls, max_workers, on_event)
        messages.extend(result.to_message() for result in results)
        if any(result.terminate for result in results):
            _emit(
                on_event,
                AgentEvent.AGENT_END,
                stop_reason="terminated",
                steps=0,
                usage=usage_total,
            )
            return LoopResult(
                content=content,
                messages=messages,
                stop_reason="terminated",
                steps=0,
                usage=usage_total,
            )

    while steps < max_turns:
        if should_stop is not None and should_stop():
            stop_reason = "interrupted"
            break

        steps += 1
        _emit(on_event, AgentEvent.TURN_START, step=steps)

        response = client.chat(messages, tools=registry.specs())
        for key in usage_total:
            usage_total[key] += response.usage.get(key, 0)
        messages.append(response.message)
        _emit(
            on_event,
            AgentEvent.MESSAGE,
            message=response.message,
            usage=response.usage,
        )

        content = response.content or ""
        if not response.tool_calls:
            stop_reason = "completed"
            break

        calls = [ToolCall.from_raw(raw) for raw in response.tool_calls]
        results = _execute_tool_calls(registry, calls, max_workers, on_event)
        messages.extend(result.to_message() for result in results)

        if any(result.terminate for result in results):
            stop_reason = "terminated"
            break

        if token_budget is not None and usage_total["total_tokens"] >= token_budget:
            stop_reason = "token_budget"
            break

    _emit(
        on_event,
        AgentEvent.AGENT_END,
        stop_reason=stop_reason,
        steps=steps,
        usage=usage_total,
    )
    return LoopResult(
        content=content,
        messages=messages,
        stop_reason=stop_reason,
        steps=steps,
        usage=usage_total,
    )


def _execute_tool_calls(registry, calls, max_workers, on_event):
    for call in calls:
        _emit(on_event, AgentEvent.TOOL_START, call=call)

    if len(calls) == 1:
        results = [registry.execute(calls[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(calls))) as pool:
            futures = [pool.submit(registry.execute, call) for call in calls]
            results = [future.result() for future in futures]

    for result in results:
        _emit(on_event, AgentEvent.TOOL_END, result=result)
    return results


def _emit(on_event, event_type, **data):
    if on_event is None:
        return
    on_event(Event(event_type, data))
