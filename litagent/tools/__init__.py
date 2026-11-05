"""内置工具集合。"""
from litagent.tools.arxiv import ARXIV_TOOLS
from litagent.tools.registry import ToolRegistry
from litagent.tools.weather import WEATHER_TOOL


def build_default_registry():
    registry = ToolRegistry()
    registry.register(WEATHER_TOOL)
    for tool in ARXIV_TOOLS:
        registry.register(tool)
    return registry
