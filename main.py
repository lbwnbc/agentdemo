"""第 1 步验收 demo：天气工具 + LLM 适配层。"""
import json

from litagent.config import load_settings
from litagent.llm.zhipu import ZhipuClient


def get_weather(city, date=None):
    return {"status": "successful", "message": "27°C 晴"}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市在指定日期的天气情况",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如北京"},
                    "date": {"type": "string", "description": "日期，格式YYYY-MM-DD"},
                },
                "required": ["city"],
            },
        },
    }
]


def call_tool(name, arguments):
    if name == "get_weather":

        return get_weather(**arguments)
    return {"status": "error", "message": "未知工具: {}".format(name)}


def agent_loop(user_input, client, max_turns=5):
    messages = [
        {"role": "system", "content": "你是一个智能助手。若用户需要查询天气，请调用get_weather"},
        {"role": "user", "content": user_input},
    ]
    for turn in range(1, max_turns + 1):
        response = client.chat(messages, tools=TOOLS)
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

        for tool_call in response.tool_calls:
            name = tool_call["function"]["name"]
            try:
                arguments = json.loads(tool_call["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(
                            {"status": "error", "message": "参数解析失败: {}".format(exc)},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            result = call_tool(name, arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return "reach max turns limit"


def main():
    settings = load_settings()
    client = ZhipuClient(settings)
    print(agent_loop("今天北京天气如何？", client))


if __name__ == "__main__":
    main()
