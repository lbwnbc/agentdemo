import os
import requests
import json


def get_weather(city,date=None):
    return {"status":"successful","message":"27°C 晴"}
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
                    "date": {"type": "string", "description": "日期，格式YYYY-MM-DD"}
                },
                "required": ["city"]
            }
        }
    }

]
def call_tool(name: str, arguments: dict) -> dict:
    if name == "get_weather":
        print("call tool get_weather")
        return get_weather(**arguments)
    else:
        return {"status": "error", "message": f"未知工具: {name}"}
def call_zhipu_api(messages, model="glm-5.3-flash"):
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置环境变量 ZHIPU_API_KEY（可参考 .env.example）")
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": messages,
        "tools":TOOLS,
        "tool_choice":"auto",
        "temperature": 1.0
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API调用失败: {response.status_code}, {response.text}")
def agent_loop(user_input,max_turns=5):
    messages = [
        {"role": "system", "content": "你是一个智能助手。若用户需要查询天气，请调用get_weather"},
        {"role": "user", "content": user_input}
    ]
    for i in range(max_turns):
        result=call_zhipu_api(messages)
        messages.append(result['choices'][0]['message'])
        print("this is step "+str(i+1))
        # print(result)
        # print(result['usage'])
        # print(result['choices'][0]['finish_reason'])
        # print(result['choices'][0]['message']['content'])
        if not result['choices'][0]['message'].get("tool_calls"):
            return result['choices'][0]['message']["content"]
        else:
            for tool_call in result['choices'][0]['message']["tool_calls"]:
                fn_name = tool_call["function"]["name"]
                fn_args = json.loads(tool_call["function"]["arguments"])
                result = call_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False)
                })
    return "reach max turns limitions"



# 按间距中的绿色按钮以运行脚本。
if __name__ == '__main__':
    print(agent_loop("今天北京天气如何？"))





