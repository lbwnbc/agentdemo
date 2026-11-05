"""工作区与会话目录。

默认布局：workspace/<session>/，可用 LITAGENT_WORKSPACE / LITAGENT_SESSION 覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path


def workspace_root():
    return Path(
        os.environ.get("LITAGENT_WORKSPACE", str(Path.cwd() / "workspace"))
    )


def session_id():
    return os.environ.get("LITAGENT_SESSION", "default")


def session_dir():
    path = workspace_root() / session_id()
    path.mkdir(parents=True, exist_ok=True)
    return path
