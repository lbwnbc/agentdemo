"""评测基线（第 14 步）：固定用例 × 六种组合，输出可横向比较的指标。

指标口径（与 DESIGN.md §5 对齐，只做结构级校验）：

- 召回（档位达成率）：候选池去重篇数 / 档位下限，上限 1.0；
- 证据覆盖：有全文证据的论文数 / 应精读篇数（selected 与 read_k 取小），上限 1.0；
- 引用真实率：报告里出现的 [eN] 中能在全文证据库找到的比例；
- tokens / 耗时：整轮用量与墙钟时间；partial 与错误单独标记。

每个组合使用独立会话（workspace/eval-<case>-<mode>-<level>），互不覆盖。
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from litagent.config import PROJECT_ROOT, load_settings
from litagent.llm.openai_compat import OpenAICompatClient
from litagent.run_spec import LEVELS, MODES, resolve
from litagent.search_ladder import normalise_id
from litagent.tools import build_default_registry
from litagent.workflow import EVIDENCE_REF, run_workflow

DEFAULT_CASES = PROJECT_ROOT / "eval" / "cases" / "cases.json"
DEFAULT_OUT = PROJECT_ROOT / "eval" / "results"
SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]")
UNKNOWN = "—"


def load_cases(path=None):
    path = Path(path or DEFAULT_CASES)
    if not path.exists():
        raise ValueError("评测用例文件不存在：{}".format(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError("评测用例不是合法 JSON：{}".format(exc))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测用例为空：{}".format(path))
    cleaned = []
    for index, item in enumerate(cases, 1):
        if not isinstance(item, dict):
            continue
        topic = " ".join(str(item.get("topic") or "").split())
        if not topic:
            continue
        cleaned.append(
            {
                "id": str(item.get("id") or "case{}".format(index)),
                "topic": topic,
            }
        )
    if not cleaned:
        raise ValueError("评测用例里没有有效主题")
    return cleaned


def parse_combos(text=None):
    """解析 "survey/low,deep/low"；缺省返回六种组合。"""
    if not text:
        return [(mode, level) for mode in MODES for level in LEVELS]
    combos = []
    for raw in str(text).replace(";", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        if "/" not in item:
            raise ValueError("组合格式应为 mode/level，例如 deep/low：{}".format(item))
        mode, level = [part.strip() for part in item.split("/", 1)]
        if mode not in MODES or level not in LEVELS:
            raise ValueError(
                "未知组合 {}，mode 可选 {}，level 可选 {}".format(
                    item, "/".join(MODES), "/".join(LEVELS)
                )
            )
        if (mode, level) not in combos:
            combos.append((mode, level))
    if not combos:
        raise ValueError("没有指定任何模式/档位组合")
    return combos


def _stage(result, name):
    for stage in result.stages or []:
        if stage.get("name") == name:
            return stage
    return {}


def _fulltext_papers(evidence):
    papers = set()
    for record in evidence or []:
        if str(record.get("source") or "fulltext") != "fulltext":
            continue
        key = normalise_id(record.get("arxiv_id"))
        if key:
            papers.add(key)
    return papers


def compute_metrics(result, seconds):
    """把一次 WorkflowResult 折算成一行可比较的指标。"""
    evidence = result.evidence or []
    fulltext = _fulltext_papers(evidence)
    metrics = {
        "mode": result.mode,
        "level": result.level,
        "target_min": result.target_min,
        "candidates": None,
        "recall": None,
        "selected": None,
        "evidence": len(evidence),
        "fulltext_papers": len(fulltext),
        "coverage": None,
        "citation_valid": None,
        "citation_total": None,
        "citation_rate": None,
        "issues": len(result.issues or []),
        "tokens": (result.usage or {}).get("total_tokens", 0),
        "seconds": round(seconds, 1),
        "status": "done",
        "error": "",
    }

    if result.survey:
        survey = result.survey
        metrics["candidates"] = survey.get("count") or 0
        metrics["recall"] = round(
            min(1.0, float(metrics["candidates"]) / max(1, result.target_min)), 3
        )
        metrics["status"] = "partial" if survey.get("status") == "partial" else "done"
    else:
        collect = _stage(result, "collect")
        candidates = collect.get("candidates")
        if candidates is None and result.plan:
            source = (result.plan or {}).get("candidate_source") or {}
            candidates = source.get("count")
        metrics["candidates"] = candidates
        metrics["selected"] = len(collect.get("selected") or [])

        if candidates:
            metrics["recall"] = round(
                min(1.0, float(candidates) / max(1, result.target_min)), 3
            )

        expected = min(metrics["selected"] or 0, result.read_k or 0)
        if expected:
            metrics["coverage"] = round(
                min(1.0, float(len(fulltext)) / expected), 3
            )

        citable = set(
            record["id"]
            for record in evidence
            if str(record.get("source") or "fulltext") == "fulltext"
        )
        used = [
            "e{}".format(raw)
            for raw in EVIDENCE_REF.findall(result.report or "")
        ]
        valid = [item for item in used if item in citable]
        metrics["citation_total"] = len(used)
        metrics["citation_valid"] = len(valid)
        if used:
            metrics["citation_rate"] = round(float(len(valid)) / len(used), 3)

        if result.partial:
            metrics["status"] = "partial"
        elif result.issues:
            metrics["status"] = "issues"
    return metrics


def _fmt(value, suffix=""):
    if value is None:
        return UNKNOWN
    return "{}{}".format(value, suffix)


def _width(text):
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in str(text)
    )


def _pad(text, width):
    return str(text) + " " * max(0, width - _width(text))


def format_table(records):
    headers = [
        "用例", "组合", "候选/下限", "召回", "证据覆盖",
        "引用真实率", "引用问题", "tokens", "耗时(s)", "状态",
    ]
    rows = [headers]
    for record in records:
        metrics = record["metrics"]
        if metrics["status"] == "error":
            rows.append(
                [
                    record["case_id"], record["combo"], UNKNOWN, UNKNOWN, UNKNOWN,
                    UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN, "error: " + record["error"],
                ]
            )
            continue
        rate = metrics["citation_rate"]
        rows.append(
            [
                record["case_id"],
                record["combo"],
                "{}/{}".format(_fmt(metrics["candidates"]), metrics["target_min"]),
                _fmt(metrics["recall"]),
                _fmt(metrics["coverage"]),
                UNKNOWN if rate is None else "{:.0%}".format(rate),
                metrics["issues"],
                metrics["tokens"],
                metrics["seconds"],
                metrics["status"],
            ]
        )
    widths = [max(_width(row[i]) for row in rows) for i in range(len(headers))]
    lines = []
    for row in rows:
        cells = [
            _pad(cell, widths[index])
            for index, cell in enumerate(row)
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def format_markdown(records, stamp):
    lines = [
        "# 评测基线 {}".format(stamp),
        "",
        "| 用例 | 组合 | 候选/下限 | 召回 | 证据覆盖 | 引用真实率 | 引用问题 | tokens | 耗时(s) | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        metrics = record["metrics"]
        if metrics["status"] == "error":
            lines.append(
                "| {} | {} | — | — | — | — | — | — | — | error: {} |".format(
                    record["case_id"], record["combo"], record["error"]
                )
            )
            continue
        rate = metrics["citation_rate"]
        lines.append(
            "| {} | {} | {}/{} | {} | {} | {} | {} | {} | {} | {} |".format(
                record["case_id"],
                record["combo"],
                _fmt(metrics["candidates"]),
                metrics["target_min"],
                _fmt(metrics["recall"]),
                _fmt(metrics["coverage"]),
                UNKNOWN if rate is None else "{:.0%}".format(rate),
                metrics["issues"],
                metrics["tokens"],
                metrics["seconds"],
                metrics["status"],
            )
        )
    lines.append("")
    lines.append(
        "口径：召回=候选去重篇数/档位下限；证据覆盖=有全文证据的论文数/应精读篇数；"
        "引用真实率=[eN] 能在全文证据库中找到的比例。"
    )
    return "\n".join(lines)


def _session_name(case_id, mode, level):
    raw = "eval-{}-{}-{}".format(case_id, mode, level)
    return SESSION_RE.sub("-", raw)[:64] or "eval"


def run_eval(cases, combos, out_dir=None, client=None, on_phase=None, verbose=True):
    """按用例 × 组合顺序执行；单个组合失败不终止整个矩阵。"""
    client = client or OpenAICompatClient(load_settings())
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_dir or DEFAULT_OUT)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    previous_session = os.environ.get("LITAGENT_SESSION")
    try:
        for case in cases:
            for mode, level in combos:
                combo = "{}/{}".format(mode, level)
                session = _session_name(case["id"], mode, level)
                os.environ["LITAGENT_SESSION"] = session
                if verbose:
                    print(
                        "[eval] {} · {} · 会话 {}".format(case["id"], combo, session)
                    )
                started = time.time()
                spec = None
                try:
                    spec = resolve(case["topic"], mode=mode, level=level)
                    result = run_workflow(
                        client,
                        build_default_registry(),
                        spec,
                        on_phase=on_phase,
                    )
                    record = {
                        "case_id": case["id"],
                        "topic": case["topic"],
                        "combo": combo,
                        "session": session,
                        "metrics": compute_metrics(result, time.time() - started),
                    }
                except Exception as exc:  # 单次失败也要留下记录，便于比较
                    record = {
                        "case_id": case["id"],
                        "topic": case["topic"],
                        "combo": combo,
                        "session": session,
                        "error": "{}: {}".format(type(exc).__name__, exc),
                        "metrics": {
                            "mode": mode,
                            "level": level,
                            "target_min": spec.target_min if spec else 0,
                            "status": "error",
                            "error": "{}: {}".format(type(exc).__name__, exc),
                            "tokens": 0,
                            "seconds": round(time.time() - started, 1),
                        },
                    }
                records.append(record)
                if verbose:
                    print("        → {}".format(format_line(record)))
    finally:
        if previous_session is None:
            os.environ.pop("LITAGENT_SESSION", None)
        else:
            os.environ["LITAGENT_SESSION"] = previous_session

    json_path = out_dir / "{}-records.json".format(stamp)
    md_path = out_dir / "{}-table.md".format(stamp)
    json_path.write_text(
        json.dumps({"stamp": stamp, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(format_markdown(records, stamp), encoding="utf-8")
    return records, json_path, md_path


def format_line(record):
    metrics = record["metrics"]
    if metrics.get("status") == "error":
        return "error: {}".format(record.get("error", ""))
    return "候选 {}/{} · 召回 {} · 覆盖 {} · tokens {} · {:.0f}s · {}".format(
        _fmt(metrics.get("candidates")),
        metrics.get("target_min"),
        _fmt(metrics.get("recall")),
        _fmt(metrics.get("coverage")),
        metrics.get("tokens"),
        metrics.get("seconds") or 0,
        metrics.get("status"),
    )
