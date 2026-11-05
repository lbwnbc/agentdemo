"""工作流阶段的结构化提交工具。

每个阶段通过"提交工具"把产物交给编排层，而不是让模型在自由文本里手写 JSON：
- submit_plan / submit_outline / submit_report 提交后立即终止当前阶段循环；
- submit_evidence 可以多次调用，把证据卡累积到列表里。

这样阶段产物天然是结构化数据，编排层不需要解析模型输出。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from litagent.tools.base import Tool
from litagent.types import ToolError


@dataclass
class StageStore:
    """一个工作流运行期间的阶段产物。"""

    plan: dict = None
    outline: str = None
    report: str = None
    evidence: list = field(default_factory=list)


def _clean(text):
    return " ".join(str(text or "").split())


def _normalise_plan(topic_boundary, sub_questions):
    boundary = _clean(topic_boundary)
    items = []
    for index, item in enumerate(sub_questions or [], 1):
        if isinstance(item, str):
            question = _clean(item)
            queries, rationale = [], ""
        elif isinstance(item, dict):
            question = _clean(item.get("question"))
            queries = [
                _clean(query)
                for query in (item.get("queries") or [])
                if _clean(query)
            ]
            rationale = _clean(item.get("rationale"))
        else:
            continue
        if not question:
            continue

        sub_id = _clean(item.get("id")) if isinstance(item, dict) else ""
        if not sub_id:
            sub_id = "sq{}".format(index)
        items.append(
            {
                "id": sub_id,
                "question": question,
                "queries": queries,
                "rationale": rationale,
            }
        )

    if not items:
        raise ToolError("sub_questions 不能为空，至少给出 1 个子问题")
    return {"topic_boundary": boundary, "sub_questions": items}


def _normalise_evidence(store, arguments):
    arxiv_id = _clean(arguments.get("arxiv_id"))
    claim = _clean(arguments.get("claim"))
    if not arxiv_id:
        raise ToolError("arxiv_id 不能为空")
    if not claim:
        raise ToolError("claim 不能为空")

    for existing in store.evidence:
        if existing["arxiv_id"] == arxiv_id and existing["claim"] == claim:
            return {
                "status": "duplicate",
                "id": existing["id"],
                "total": len(store.evidence),
            }

    record = {
        "id": "e{}".format(len(store.evidence) + 1),
        "arxiv_id": arxiv_id,
        "doi": _clean(arguments.get("doi")),
        "title": _clean(arguments.get("title")),
        "claim": claim,
        "quote": str(arguments.get("quote") or "").strip(),
        "section": _clean(arguments.get("section")),
        "sub_question": _clean(arguments.get("sub_question")),
        "kind": _clean(arguments.get("kind")) or "other",
    }
    store.evidence.append(record)
    return {"status": "ok", "id": record["id"], "total": len(store.evidence)}


def build_plan_tool(store):
    def handler(topic_boundary="", sub_questions=None):
        store.plan = _normalise_plan(topic_boundary, sub_questions)
        return {
            "status": "ok",
            "sub_questions": len(store.plan["sub_questions"]),
        }

    return Tool(
        name="submit_plan",
        description=(
            "提交调研计划：主题边界与 2-4 个可独立检索的子问题。"
            "每个子问题给出英文检索式；提交后本阶段结束。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic_boundary": {
                    "type": "string",
                    "description": "一句话说明检索边界（子领域、时间范围、任务类型）",
                },
                "sub_questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "question": {"type": "string"},
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "rationale": {"type": "string"},
                        },
                        "required": ["question"],
                    },
                    "description": "子问题列表，每项含 question、queries（可多组）、rationale",
                },
            },
            "required": ["sub_questions"],
        },
        handler=handler,
        terminate=True,
    )


def build_evidence_tool(store):
    def handler(
        arxiv_id,
        claim,
        quote="",
        section="",
        sub_question="",
        title="",
        doi="",
        kind="other",
    ):
        return _normalise_evidence(
            store,
            {
                "arxiv_id": arxiv_id,
                "claim": claim,
                "quote": quote,
                "section": section,
                "sub_question": sub_question,
                "title": title,
                "doi": doi,
                "kind": kind,
            },
        )

    return Tool(
        name="submit_evidence",
        description=(
            "提交一张证据卡：论文编号、论断、支撑引文、出处。"
            "同一篇论文可以提交多条证据；重复提交会被去重。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string", "description": "来源 arXiv 编号"},
                "claim": {"type": "string", "description": "一句话论断，用自己的话概括"},
                "quote": {
                    "type": "string",
                    "description": "支撑该论断的原文片段；未获取全文时可引用摘要并说明",
                },
                "section": {"type": "string", "description": "章节或页码，如 3.2 或 page 5"},
                "sub_question": {
                    "type": "string",
                    "description": "这条证据回答哪个子问题（填子问题 id 或原文）",
                },
                "title": {"type": "string", "description": "论文标题"},
                "doi": {"type": "string", "description": "论文 DOI，没有则留空"},
                "kind": {
                    "type": "string",
                    "description": "证据类型",
                    "enum": ["method", "result", "limitation", "background", "other"],
                },
            },
            "required": ["arxiv_id", "claim"],
        },
        handler=handler,
    )


def build_outline_tool(store):
    def handler(outline):
        text = str(outline or "").strip()
        if not text:
            raise ToolError("outline 不能为空")
        store.outline = text
        return {"status": "ok", "chars": len(text)}

    return Tool(
        name="submit_outline",
        description="提交综述大纲（Markdown），每个小节标注准备使用的证据 id。提交后本阶段结束。",
        parameters={
            "type": "object",
            "properties": {
                "outline": {"type": "string", "description": "Markdown 大纲正文"},
            },
            "required": ["outline"],
        },
        handler=handler,
        terminate=True,
    )


def build_report_tool(store):
    def handler(report):
        text = str(report or "").strip()
        if not text:
            raise ToolError("report 不能为空")
        store.report = text
        return {"status": "ok", "chars": len(text)}

    return Tool(
        name="submit_report",
        description=(
            "提交最终综述报告（Markdown）。每条论断必须用 [eN] 标注证据 id，"
            "参考文献只能包含证据库里出现过的论文。提交后本阶段结束。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "report": {"type": "string", "description": "Markdown 报告正文"},
            },
            "required": ["report"],
        },
        handler=handler,
        terminate=True,
    )
