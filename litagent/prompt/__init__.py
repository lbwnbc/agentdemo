"""系统提示词加载。"""
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def load_system_prompt():
    return (PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()
