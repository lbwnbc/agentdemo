"""研究工作流编排（第 8 步）：Plan → Collect → Synthesize。

与自由模式的 Agent Loop 不同，这里把"想做什么"和"怎么做"分开：

- Plan：拆子问题、生成检索式，产物 plan.json；
- Collect：检索 + 按需精读 + 提交证据卡，产物 evidence.jsonl；
- Synthesize：先出大纲 outline.md，再写报告 report.md，最后做引用校验。

每个阶段的产物都由"提交工具"写入 StageStore，而不是解析模型自由文本，
因此阶段之间传递的是结构化数据，报告里的 [eN] 也能直接回溯到证据卡。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from litagent.agent import run_loop
from litagent.prompt import load_workflow_prompt
from litagent.tools.registry import ToolRegistry
from litagent.tools.workflow_tools import (
    StageStore,
    build_evidence_tool,
    build_outline_tool,
    build_plan_tool,
    build_report_tool,
)
from litagent.workspace import session_dir

PLAN_TURNS = 2
COLLECT_TURNS = 10
SYNTHESIS_TURNS = 2

EVIDENCE_REF = re.compile(r"\[e(\d+)\]")
ARXIV_REF = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
DOI_REF = re.compile(r"10\.\d{4,}/[^\s，。；、）)\]]+")


class WorkflowError(Exception):
    """某个阶段连续两次没有产出结构化结果。"""


@dataclass
class WorkflowResult:
    topic: str
    plan: dict = None
    evidence: list = field(default_factory=list)
    outline: str = ""
    report: str = ""
    issues: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)
    stages: list = field(default_factory=list)


def workflow_dir():
    path = session_dir() / "workflow"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalise_arxiv_id(value):
    return str(value or "").strip().lower().split("v")[0]


def validate_citations(report, evidence):
    """检查报告里的证据 id、arXiv 号、DOI 是否都能回溯到证据库。"""
    issues = []
    known_ids = set(record["id"] for record in evidence)

    used_ids = ["e{}".format(raw) for raw in EVIDENCE_REF.findall(report)]
    for evidence_id in used_ids:
        if evidence_id not in known_ids:
            issues.append("引用了不存在的证据 id [{}]".format(evidence_id))
    if evidence and not used_ids:
        issues.append("报告没有任何 [eN] 证据引用，无法回溯")

    known_arxiv = set(_normalise_arxiv_id(record["arxiv_id"]) for record in evidence)
    for found in ARXIV_REF.findall(report):
        if _normalise_arxiv_id(found) not in known_arxiv:
            issues.append(
                "引用了证据库之外的 arXiv 号 {}，请先补交证据卡或删除该引用".format(found)
            )

    known_dois = set(
        record.get("doi", "").rstrip(".").lower()
        for record in evidence
        if record.get("doi")
    )
    for found in DOI_REF.findall(report):
        if found.rstrip(".").lower() not in known_dois:
            issues.append("引用了证据库之外的 DOI {}".format(found))

    return issues


def _merge_usage(total, usage):
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + (usage or {}).get(key, 0)
    return total


def _phase(on_phase, name, status, **info):
    if on_phase is not None:
        on_phase(name, status, info)


def _clone_registry(source):
    """复制工具定义，避免给调用方的注册表塞进阶段专用工具。"""
    registry = ToolRegistry()
    for tool in source.iter_tools():
        registry.register(tool)
    return registry


def _evidence_text(evidence):
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in evidence)


def _read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def _read_jsonl(path):
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("id"):
            records.append(record)
    return records


def _read_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _retry_message(name, problems):
    lines = ["你还没有完成 {} 阶段，原因：".format(name)]
    lines.extend("- {}".format(problem) for problem in problems)
    lines.append("请按系统提示修正后重新提交。")
    return "\n".join(lines)


def _run_stage(
    client,
    registry,
    name,
    system_prompt,
    user_prompt,
    validator,
    max_turns,
    on_event,
    on_phase,
    attempts=2,
):
    """跑一个阶段；validator 返回问题列表，空列表表示产物合格。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    usage_total = {}
    steps_total = 0
    problems = ["未提交产物"]

    for attempt in range(1, attempts + 1):
        result = run_loop(
            client,
            registry,
            messages,
            max_turns=max_turns,
            on_event=on_event,
        )
        steps_total += result.steps
        _merge_usage(usage_total, result.usage)

        problems = validator()
        if not problems:
            _phase(
                on_phase,
                name,
                "done",
                attempt=attempt,
                steps=steps_total,
                usage=usage_total,
            )
            return steps_total, usage_total

        _phase(on_phase, name, "retry", attempt=attempt, problems=problems)
        messages.append({"role": "user", "content": _retry_message(name, problems)})

    _phase(on_phase, name, "failed", problems=problems)
    raise WorkflowError(
        "阶段 {} 连续 {} 次没有产出合格结果：{}".format(
            name, attempts, "；".join(problems)
        )
    )


def _run_report_stage(
    client,
    registry,
    store,
    system_prompt,
    user_prompt,
    on_event,
    on_phase,
    attempts=2,
):
    """报告阶段允许降级：两次校验都失败时保留报告并把问题写进文件。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    usage_total = {}
    steps_total = 0
    issues = []

    for attempt in range(1, attempts + 1):
        result = run_loop(
            client,
            registry,
            messages,
            max_turns=SYNTHESIS_TURNS,
            on_event=on_event,
        )
        steps_total += result.steps
        _merge_usage(usage_total, result.usage)

        if not store.report:
            issues = ["未提交报告"]
        else:
            issues = validate_citations(store.report, store.evidence)
            if not issues:
                _phase(
                    on_phase,
                    "report",
                    "done",
                    attempt=attempt,
                    steps=steps_total,
                    usage=usage_total,
                )
                return steps_total, usage_total, []

        _phase(on_phase, "report", "retry", attempt=attempt, problems=issues)
        messages.append(
            {"role": "user", "content": _retry_message("report", issues)}
        )

    _phase(on_phase, "report", "degraded", problems=issues)
    return steps_total, usage_total, issues


def run_workflow(client, registry, topic, on_event=None, on_phase=None, resume=False):
    """执行一次完整的三阶段调研，产物写入 workspace/<session>/workflow/。

    resume=True 时读取已落盘的 plan.json / evidence.jsonl / outline.md，
    跳过对应阶段，用于阶段失败后接着跑而不重烧 token。
    """
    topic = " ".join(str(topic or "").split())
    if not topic:
        raise ValueError("研究主题不能为空")

    store = StageStore()
    result = WorkflowResult(topic=topic)
    target = workflow_dir()
    if not resume:
        for filename in ("plan.json", "evidence.jsonl", "outline.md", "report.md"):
            stale = target / filename
            if stale.exists():
                stale.unlink()
    else:
        store.plan = _read_json(target / "plan.json", None)
        store.evidence = _read_jsonl(target / "evidence.jsonl")
        store.outline = _read_text(target / "outline.md") or None

    # 1) Plan
    if store.plan:
        _phase(on_phase, "plan", "skipped")
        result.stages.append({"name": "plan", "steps": 0, "usage": {}})
    else:
        plan_registry = ToolRegistry()
        plan_registry.register(build_plan_tool(store))
        _phase(on_phase, "plan", "start")
        steps, usage = _run_stage(
            client,
            plan_registry,
            "plan",
            load_workflow_prompt("plan"),
            "研究主题：{}".format(topic),
            lambda: [] if store.plan else ["还没有调用 submit_plan"],
            PLAN_TURNS,
            on_event,
            on_phase,
        )
        result.stages.append({"name": "plan", "steps": steps, "usage": usage})
        _merge_usage(result.usage, usage)
        (target / "plan.json").write_text(
            json.dumps(store.plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    result.plan = store.plan

    # 2) Collect
    if store.evidence:
        _phase(on_phase, "collect", "skipped", count=len(store.evidence))
        result.stages.append({"name": "collect", "steps": 0, "usage": {}})
    else:
        collect_registry = _clone_registry(registry)
        collect_registry.register(build_evidence_tool(store))
        _phase(on_phase, "collect", "start")
        collect_prompt = "{}\n\n当前计划：\n{}".format(
            load_workflow_prompt("collect"),
            json.dumps(store.plan, ensure_ascii=False, indent=2),
        )
        steps, usage = _run_stage(
            client,
            collect_registry,
            "collect",
            collect_prompt,
            "请按计划开始检索与精读，把证据写进证据库。",
            lambda: [] if store.evidence else ["还没有调用 submit_evidence"],
            COLLECT_TURNS,
            on_event,
            on_phase,
        )
        result.stages.append({"name": "collect", "steps": steps, "usage": usage})
        _merge_usage(result.usage, usage)
        (target / "evidence.jsonl").write_text(
            _evidence_text(store.evidence) + "\n", encoding="utf-8"
        )
    result.evidence = list(store.evidence)

    # 3) Synthesize：大纲
    if store.outline:
        _phase(on_phase, "outline", "skipped")
        result.stages.append({"name": "outline", "steps": 0, "usage": {}})
    else:
        outline_registry = ToolRegistry()
        outline_registry.register(build_outline_tool(store))
        _phase(on_phase, "outline", "start")
        outline_prompt = "{}\n\n计划：\n{}\n\n证据库：\n{}".format(
            load_workflow_prompt("outline"),
            json.dumps(store.plan, ensure_ascii=False, indent=2),
            _evidence_text(store.evidence),
        )
        steps, usage = _run_stage(
            client,
            outline_registry,
            "outline",
            outline_prompt,
            "请基于计划与证据库提交综述大纲。",
            lambda: [] if store.outline else ["还没有调用 submit_outline"],
            SYNTHESIS_TURNS,
            on_event,
            on_phase,
        )
        result.stages.append({"name": "outline", "steps": steps, "usage": usage})
        _merge_usage(result.usage, usage)
        (target / "outline.md").write_text(store.outline, encoding="utf-8")
    result.outline = store.outline

    # 3) Synthesize：报告 + 引用校验
    report_registry = ToolRegistry()
    report_registry.register(build_report_tool(store))
    _phase(on_phase, "report", "start")
    report_prompt = "{}\n\n计划：\n{}\n\n大纲：\n{}\n\n证据库：\n{}".format(
        load_workflow_prompt("report"),
        json.dumps(store.plan, ensure_ascii=False, indent=2),
        store.outline,
        _evidence_text(store.evidence),
    )
    steps, usage, issues = _run_report_stage(
        client,
        report_registry,
        store,
        report_prompt,
        "请基于大纲与证据库提交最终报告。",
        on_event,
        on_phase,
    )
    result.issues = issues
    result.report = store.report or ""
    if issues:
        result.report = "{}\n\n## 自检未通过\n\n{}\n".format(
            result.report,
            "\n".join("- {}".format(issue) for issue in issues),
        )
    (target / "report.md").write_text(result.report, encoding="utf-8")
    result.stages.append({"name": "report", "steps": steps, "usage": usage})
    _merge_usage(result.usage, usage)

    result.paths = {
        "plan": str(target / "plan.json"),
        "evidence": str(target / "evidence.jsonl"),
        "outline": str(target / "outline.md"),
        "report": str(target / "report.md"),
    }
    return result
