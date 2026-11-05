"""内置工具集合。"""
from litagent.tools.arxiv import ARXIV_TOOLS
from litagent.tools.notes import NOTES_TOOLS
from litagent.tools.pdf import PDF_TOOLS
from litagent.tools.registry import ToolRegistry


def build_default_registry():
    registry = ToolRegistry()
    for tool in ARXIV_TOOLS + PDF_TOOLS + NOTES_TOOLS:
        registry.register(tool)
    return registry
