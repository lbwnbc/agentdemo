"""第 2 步验收 demo：天气工具 + 工具注册表。"""
from litagent.config import load_settings
from litagent.llm.zhipu import ZhipuClient
from litagent.tools import build_default_registry
from litagent.types import ToolCall


def agent_loop(user_input, client, registry, max_turns=5):
    messages = [
        {"role": "system", "content": "你是一个智能助手。若用户需要查询天气，请调用get_weather"},
        {"role": "user", "content": user_input},
    ]
    for turn in range(1, max_turns + 1):
        response = client.chat(messages, tools=registry.specs())
        messages.append(response.message)

        usage = response.usage
        print(
            "[turn {}] tokens: prompt={} completion={} total={}".format(
                turn,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )
        )

        if not response.tool_calls:
            return response.content

        for raw_call in response.tool_calls:
            call = ToolCall.from_raw(raw_call)
            print("call tool {}".format(call.name))
            result = registry.execute(call)
            messages.append(result.to_message())

    return "reach max turns limit"


def main():
    settings = load_settings()
    client = ZhipuClient(settings)
    registry = build_default_registry()
    print(agent_loop("今天北京天气如何？", client, registry))


if __name__ == "__main__":
    main()
