"""天气查询工具（第 2 步用来验证工具协议）。"""
from litagent.tools.base import Tool


def get_weather(city, date=None):
    return {"status": "successful", "message": "27°C 晴", "city": city, "date": date}


WEATHER_TOOL = Tool(
    name="get_weather",
    description="查询指定城市在指定日期的天气情况",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名，如北京"},
            "date": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
        },
        "required": ["city"],
    },
    handler=get_weather,
)
