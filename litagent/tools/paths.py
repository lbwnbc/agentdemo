"""工作区路径守卫：写操作只能落在当前会话的工作区里。"""
from __future__ import annotations

from pathlib import Path


class PathNotAllowed(Exception):
    """路径越界或格式非法。"""


def resolve_workspace_path(root, relative):
    root = Path(root).resolve()
    relative = str(relative or "").strip()
    if not relative:
        raise PathNotAllowed("路径不能为空")
    if relative.startswith(("/", "\\")) or Path(relative).is_absolute():
        raise PathNotAllowed("不允许绝对路径: {}".format(relative))

    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise PathNotAllowed("路径超出工作区: {}".format(relative))
    return target
