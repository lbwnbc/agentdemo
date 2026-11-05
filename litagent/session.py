"""会话持久化：JSONL 追加、恢复与 Markdown 导出。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from litagent.workspace import session_dir

_lock = threading.Lock()
SESSION_FILE = "session.jsonl"


def session_path():
    return session_dir() / SESSION_FILE


def _now():
    return datetime.now(timezone.utc).isoformat()


def _append(record):
    path = session_path()
    with _lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_message(message):
    _append({"type": "message", "created_at": _now(), "message": message})


def append_run(stop_reason, steps, usage):
    _append(
        {
            "type": "run",
            "created_at": _now(),
            "stop_reason": stop_reason,
            "steps": steps,
            "usage": usage,
        }
    )


def _load_records():
    path = session_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def load_messages():
    return [
        record["message"]
        for record in _load_records()
        if record.get("type") == "message" and "message" in record
    ]


def reset_session():
    path = session_path()
    if path.exists():
        path.unlink()


def _render_message(message):
    role = message.get("role", "unknown")
    content = message.get("content") or ""
    lines = []
    if role == "user":
        lines.append("## 用户\n\n{}\n".format(content))
    elif role == "assistant":
        lines.append("## 助手\n\n{}\n".format(content) if content else "## 助手\n")
        for raw in message.get("tool_calls") or []:
            function = raw.get("function", {})
            lines.append(
                "> 工具调用 `{}`：`{}`\n".format(
                    function.get("name", "?"), function.get("arguments", "")
                )
            )
    elif role == "tool":
        preview = content[:200] + ("…" if len(content) > 200 else "")
        lines.append(
            "### 工具结果 `{}`\n\n```\n{}\n```\n".format(
                message.get("tool_call_id", "?"), preview
            )
        )
    return "\n".join(lines)


def export_markdown(path=None):
    records = _load_records()
    messages = [record["message"] for record in records if record.get("type") == "message"]
    if not messages:
        raise ValueError("当前会话还没有消息，无法导出")

    runs = [record for record in records if record.get("type") == "run"]
    footer = []
    for run in runs:
        footer.append(
            "- {} | 停止原因={} | 轮次={} | tokens={}".format(
                run.get("created_at", ""),
                run.get("stop_reason", ""),
                run.get("steps", ""),
                (run.get("usage") or {}).get("total_tokens", 0),
            )
        )

    body = ["# 会话记录", "", "- 消息数：{}".format(len(messages)), ""]
    body.extend(_render_message(message) for message in messages)
    if footer:
        body.extend(["## 运行记录", ""] + footer + [""])

    target = Path(path) if path else session_dir() / "session.md"
    target.write_text("\n".join(body), encoding="utf-8")
    return target
