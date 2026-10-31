"""第 3 步验收 demo：Agent Loop + 事件输出。"""
from litagent.agent import run_loop
from litagent.config import load_settings
from litagent.llm.zhipu import ZhipuClient
from litagent.tools import build_default_registry
from litagent.types import AgentEvent

SYSTEM_PROMPT = "你是一个智能助手。若用户需要查询天气，请调用 get_weather。"


def print_event(event):
    if event.type == AgentEvent.TURN_START:
        print("[turn {}]".format(event.data["step"]))
    elif event.type == AgentEvent.MESSAGE:
        usage = event.data["usage"]
        print(
            "tokens: prompt={} completion={} total={}".format(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )
        )
    elif event.type == AgentEvent.TOOL_START:
        call = event.data["call"]
        print("call tool {}({})".format(call.name, call.arguments))
    elif event.type == AgentEvent.TOOL_END:
        result = event.data["result"]
        status = "error" if result.is_error else "ok"
        print("tool {}: {}".format(status, result.content[:100]))
    elif event.type == AgentEvent.AGENT_END:
        print(
            "stop: {} after {} steps, total tokens={}".format(
                event.data["stop_reason"],
                event.data["steps"],
                event.data["usage"]["total_tokens"],
            )
        )


def main():
    settings = load_settings()
    client = ZhipuClient(settings)
    registry = build_default_registry()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "今天北京天气如何？"},
    ]
    result = run_loop(client, registry, messages, max_turns=6, on_event=print_event)
    print(result.content)


if __name__ == "__main__":
    main()
