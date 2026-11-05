"""系统提示词加载。"""
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def load_system_prompt():
    return (PROMPT_DIR / "system.md").read_text(encoding="utf-8").strip()


def load_workflow_prompt(name):
    """加载工作流阶段提示词，如 plan / collect / outline / report。"""
    path = PROMPT_DIR / "workflow" / "{}.md".format(name)
    if not path.exists():
        raise ValueError("缺少阶段提示词: {}".format(path))
    return path.read_text(encoding="utf-8").strip()
