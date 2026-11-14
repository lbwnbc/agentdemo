"""仅搜集模式（第 11 步）：Plan 出检索式 → 代码逐级检索 → Digest → 写清单。

这个模式不做任何推断：模型只负责把主题拆成检索式，
篇数、去重、排序、摘要截断全部由代码完成，因此模型调用次数与篇数无关。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from litagent.prompt import load_workflow_prompt
from litagent.search_ladder import run_ladder
from litagent.tools.registry import ToolRegistry
from litagent.tools.workflow_tools import StageStore, build_plan_tool
from litagent.workspace import session_dir
from litagent.workflow import (
    WorkflowResult,
    _merge_usage,
    _phase,
    _phase_with_meta,
    _run_stage,
)

SURVEY_PLAN_TURNS = 2


def surveys_dir():
    path = session_dir() / "surveys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_survey_id(topic):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:4]
    return "sv_{}_{}".format(stamp, digest)


def _validate_survey_plan(store):
    if not store.plan:
        return ["还没有调用 submit_plan"]
    queries = [
        str(query).strip()
        for item in store.plan.get("sub_questions") or []
        for query in (item.get("queries") or [])
        if str(query).strip()
    ]
    if not queries:
        return ["子问题里没有任何检索式，仅搜集模式无法开始检索"]
    return []


def plan_queries(plan):
    queries = []
    for item in (plan or {}).get("sub_questions") or []:
        for query in item.get("queries") or []:
            query = " ".join(str(query).split())
            if query and query.lower() not in {existing.lower() for existing in queries}:
                queries.append(query)
    return queries


def read_index(root):
    path = root / "index.json"
    if not path.exists():
        return {"surveys": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"surveys": []}
    if isinstance(data, list):
        return {"surveys": data}
    if not isinstance(data.get("surveys"), list):
        data["surveys"] = []
    return data


def write_papers(path, papers):
    lines = [json.dumps(paper, ensure_ascii=False) for paper in papers]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_index(root, entry):
    index = read_index(root)
    others = [item for item in index["surveys"] if item.get("survey_id") != entry["survey_id"]]
    index["surveys"] = others + [entry]
    (root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_survey(client, registry, spec, on_event=None, on_phase=None):
    """执行仅搜集流程，返回带 survey 字段的 WorkflowResult。"""
    on_phase = _phase_with_meta(on_phase, spec)
    root = surveys_dir()
    survey_id = new_survey_id(spec.topic)
    target = root / survey_id
    target.mkdir(parents=True, exist_ok=True)

    store = StageStore()
    result = WorkflowResult(
        topic=spec.topic,
        mode=spec.mode,
        level=spec.level,
        target_min=spec.target_min,
        target_max=spec.target_max,
        read_k=spec.read_k,
    )

    # 1) Plan：只产出检索式
    plan_registry = ToolRegistry()
    plan_registry.register(build_plan_tool(store))
    _phase(on_phase, "plan", "start")
    steps, usage = _run_stage(
        client,
        plan_registry,
        "plan",
        load_workflow_prompt("survey_plan"),
        "研究主题：{}\n\n本轮目标：{}".format(spec.topic, spec.describe()),
        lambda: _validate_survey_plan(store),
        SURVEY_PLAN_TURNS,
        on_event,
        on_phase,
    )
    result.stages.append({"name": "plan", "steps": steps, "usage": usage})
    _merge_usage(result.usage, usage)
    result.plan = store.plan
    queries = plan_queries(store.plan)

    # 2) 检索 + 逐级放宽（纯代码，不消耗模型额度）
    _phase(on_phase, "collect", "start", queries=len(queries))
    papers, provenance = run_ladder(queries, spec.target_min, spec.target_max)
    if provenance["status"] == "partial":
        _phase(
            on_phase,
            "collect",
            "degraded",
            count=provenance["count"],
            shortfall=provenance["shortfall"],
            max_level=provenance["max_level"],
            problems=[
                "只归集到 {} 篇，低于档位下限 {} 篇（已走完 {}）".format(
                    provenance["count"], spec.target_min, provenance["max_level"]
                )
            ],
        )
    else:
        _phase(
            on_phase,
            "collect",
            "done",
            count=provenance["count"],
            steps=0,
            usage={},
            max_level=provenance["max_level"],
        )
    result.stages.append({"name": "collect", "steps": 0, "usage": {}})

    # 3) Digest：清单落盘 + 注册表
    papers_path = target / "papers.jsonl"
    write_papers(papers_path, papers)
    entry = {
        "survey_id": survey_id,
        "topic": spec.topic,
        "mode": spec.mode,
        "level": spec.level,
        "count": len(papers),
        "status": provenance["status"],
        "shortfall": provenance["shortfall"],
        "max_level": provenance["max_level"],
        "queries": queries,
        "levels": provenance["levels"],
        "errors": provenance["errors"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_index(root, entry)

    result.survey = entry
    result.paths = {
        "survey_id": survey_id,
        "papers": str(papers_path),
        "index": str(root / "index.json"),
    }
    return result
