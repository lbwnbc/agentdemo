"""证据笔记：把精读出的论断、原文引用和来源固化下来（5b）。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from litagent.tools.base import Tool
from litagent.workspace import session_dir

_lock = threading.Lock()


def _notes_path():
    return session_dir() / "notes.jsonl"


def _load_records():
    path = _notes_path()
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


def save_note(claim, quote="", arxiv_id="", section="", tags=None):
    claim = " ".join(str(claim or "").split())
    if not claim:
        raise ValueError("claim 不能为空")

    with _lock:
        records = _load_records()
        record = {
            "id": "n{}".format(len(records) + 1),
            "arxiv_id": arxiv_id,
            "claim": claim,
            "quote": quote,
            "section": section,
            "tags": tags or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = _notes_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "status": "ok",
        "id": record["id"],
        "path": str(path),
        "total": len(records) + 1,
    }


def search_notes(query, limit=10):
    query = str(query or "").strip().casefold()
    if not query:
        raise ValueError("query 不能为空")
    limit = max(1, min(int(limit), 50))

    matches = []
    for record in _load_records():
        haystack = " ".join(
            str(value)
            for value in (
                record.get("arxiv_id"),
                record.get("claim"),
                record.get("quote"),
                record.get("section"),
                " ".join(record.get("tags") or []),
            )
        ).casefold()
        if query in haystack:
            matches.append(record)
        if len(matches) >= limit:
            break
    return {"status": "ok", "query": query, "count": len(matches), "results": matches}


SAVE_NOTE_TOOL = Tool(
    name="save_note",
    description=(
        "把一条精读结论写入证据库，必须包含可回查的来源（arxiv_id）和原文引用（quote）。"
        "后续写综述时只允许引用已保存的证据 id，避免编造。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "claim": {"type": "string", "description": "一句话论断，用自己的话概括"},
            "quote": {"type": "string", "description": "支持该论断的原文片段"},
            "arxiv_id": {"type": "string", "description": "来源论文编号"},
            "section": {"type": "string", "description": "来源章节或页码，如 3.2 或 page 5"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主题标签，便于后续检索",
            },
        },
        "required": ["claim", "arxiv_id"],
    },
    handler=save_note,
)

SEARCH_NOTES_TOOL = Tool(
    name="search_notes",
    description="在已保存的证据笔记中检索关键词，返回笔记 id、论断、引用和来源。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词"},
            "limit": {"type": "integer", "description": "最多返回条数，1-50，默认 10"},
        },
        "required": ["query"],
    },
    handler=search_notes,
)

NOTES_TOOLS = [SAVE_NOTE_TOOL, SEARCH_NOTES_TOOL]
