"""深度分层精读（第 12 步）：每篇论文一个独立子循环，只回传证据卡。

这样模型上下文里始终只有一篇 PDF，证据卡进入共享 StageStore，
精读成本从「候选集规模」降为「K 篇 × 单篇读取」。
"""
from __future__ import annotations

from litagent.agent import run_loop
from litagent.prompt import load_workflow_prompt
from litagent.tools.registry import ToolRegistry
from litagent.tools.workflow_tools import build_evidence_tool
from litagent.workflow import _merge_usage, _phase

READ_TURNS = 8
READ_ATTEMPTS = 2
READ_TOOL_NAMES = ("fetch_pdf", "read_paper")


def _paper_message(paper, plan):
    questions = "\n".join(
        "- {}：{}".format(item.get("id"), item.get("question"))
        for item in (plan or {}).get("sub_questions") or []
    )
    authors = ", ".join(paper.get("authors") or []) or "未知"
    return (
        "## 本轮论文\n"
        "- arXiv: {arxiv_id}\n"
        "- 标题: {title}\n"
        "- 作者: {authors}\n"
        "- 年份: {year}\n\n"
        "## 摘要\n{abstract}\n\n"
        "## 计划子问题\n{questions}\n\n"
        "请先下载并精读这篇论文，然后提交 2-4 条证据卡，"
        "每条用 sub_question 标注回答的是哪个子问题。"
    ).format(
        arxiv_id=paper.get("arxiv_id"),
        title=paper.get("title") or "",
        authors=authors,
        year=paper.get("year") or "-",
        abstract=paper.get("abstract") or "（没有摘要）",
        questions=questions or "（计划里没有子问题）",
    )


def _reading_registry(registry, store, paper, read_round, state):
    """只暴露下载、读页、提交证据三个工具，其它工具一律不可见。"""
    scoped = ToolRegistry()
    for name in READ_TOOL_NAMES:
        tool = registry.get(name)
        if tool is not None:
            scoped.register(tool)
    scoped.register(
        build_evidence_tool(
            store,
            locked_id=paper["arxiv_id"],
            source=lambda: "fulltext" if state["read_ok"] else "abstract",
            read_round=read_round,
        )
    )
    scoped.add_after_hook(
        lambda call, result: _note_reading(call, result, state)
    )
    return scoped


def _note_reading(call, result, state):
    if call.name == "read_paper" and not getattr(result, "is_error", True):
        state["read_ok"] = True
    return None


def read_papers(
    client,
    registry,
    papers,
    plan,
    store,
    on_event=None,
    on_phase=None,
    attempts=READ_ATTEMPTS,
):
    """逐篇精读；返回统计与完成度，不抛异常（单篇失败不影响其它篇）。"""
    summary = {
        "selected": len(papers),
        "fulltext": [],
        "abstract": [],
        "failed": [],
        "steps": 0,
        "usage": {},
    }

    for index, paper in enumerate(papers, 1):
        arxiv_id = paper["arxiv_id"]
        before = len(store.evidence)
        state = {"read_ok": False}
        _phase(
            on_phase,
            "collect",
            "start",
            reading={
                "index": index,
                "total": len(papers),
                "arxiv_id": arxiv_id,
                "title": (paper.get("title") or "")[:70],
            },
        )

        messages = [
            {"role": "system", "content": load_workflow_prompt("read")},
            {"role": "user", "content": _paper_message(paper, plan)},
        ]
        for attempt in range(1, attempts + 1):
            scoped = _reading_registry(registry, store, paper, attempt, state)
            outcome = run_loop(
                client,
                scoped,
                messages,
                max_turns=READ_TURNS,
                on_event=on_event,
            )
            summary["steps"] += outcome.steps
            _merge_usage(summary["usage"], outcome.usage)
            records = store.evidence[before:]
            if any(record.get("source") == "fulltext" for record in records):
                break
            if attempt < attempts:
                messages.append(
                    {
                        "role": "user",
                        "content": "这一篇还没有可引用的全文证据。请继续 read_paper 读取正文，"
                        "再提交 1-3 条证据卡；PDF 确实不可用时才按摘要写。",
                    }
                )

        records = store.evidence[before:]
        if any(record.get("source") == "fulltext" for record in records):
            summary["fulltext"].append(arxiv_id)
        elif records:
            summary["abstract"].append(arxiv_id)
        else:
            summary["failed"].append(arxiv_id)

    return summary
