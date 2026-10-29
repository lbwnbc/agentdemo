"""内置工具集合。"""
from litagent.tools.registry import ToolRegistry
from litagent.tools.weather import WEATHER_TOOL


def build_default_registry():
    registry = ToolRegistry()
    registry.register(WEATHER_TOOL)
    return registry
