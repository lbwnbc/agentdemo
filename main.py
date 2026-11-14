"""命令行入口：Agent Loop + 会话持久化；--workflow 走三阶段调研。"""
import argparse
import json
from pathlib import Path

from litagent.agent import run_loop
from litagent.compaction import compact_messages
from litagent.config import load_settings
from litagent.llm.openai_compat import OpenAICompatClient
from litagent.prompt import load_system_prompt
from litagent.session import (
    append_message,
    append_run,
    export_markdown,
    load_messages,
    reset_session,
)
from litagent.run_spec import MODES, LEVELS, resolve
from litagent.tools import build_default_registry
from litagent.types import AgentEvent
from litagent.web.server import serve as serve_web
from litagent.workflow import WorkflowError, run_workflow

SYSTEM_PROMPT = load_system_prompt()
DEFAULT_QUESTION = "帮我检索 3 篇关于 LLM agent memory 的论文，并简要总结它们各自关注什么。"


def print_event(event):
    if event.type == AgentEvent.TURN_START:
        print("[turn {}]".format(event.data["step"]))
    elif event.type == AgentEvent.MESSAGE:
        usage = event.data["usage"]
        print(
            "tokens: prompt={} completion={} total={}".format(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )
        )
    elif event.type == AgentEvent.COMPACTED:
        print("[compact] messages {} -> {}".format(event.data["before"], event.data["after"]))
    elif event.type == AgentEvent.TOOL_START:
        call = event.data["call"]
        print("call tool {}({})".format(call.name, call.arguments))
    elif event.type == AgentEvent.TOOL_END:
        result = event.data["result"]
        status = "error" if result.is_error else "ok"
        print("tool {}: {}".format(status, result.content[:100]))
    elif event.type == AgentEvent.AGENT_END:
        print(
            "stop: {} after {} steps, total tokens={}".format(
                event.data["stop_reason"],
                event.data["steps"],
                event.data["usage"]["total_tokens"],
            )
        )


def record_event(event):
    print_event(event)
    if event.type == AgentEvent.MESSAGE:
        append_message(event.data["message"])
    elif event.type == AgentEvent.TOOL_END:
        append_message(event.data["result"].to_message())


def print_phase(name, status, info):
    if status == "start" and info.get("reading"):
        item = info["reading"]
        print(
            "[collect] 精读 {}/{}：{} {}".format(
                item.get("index"),
                item.get("total"),
                item.get("arxiv_id"),
                item.get("title") or "",
            )
        )
    elif status == "start":
        print("[{}] start".format(name))
    elif status == "done" and "candidates" in info:
        print(
            "[{}] done: {} 篇全文 / 选中 {} 篇（候选 {} 篇，摘要级 {} 篇，失败 {} 篇）".format(
                name,
                info.get("count", 0),
                info.get("selected", 0),
                info.get("candidates") or "-",
                len(info.get("abstract") or []),
                len(info.get("failed") or []),
            )
        )
    elif status == "done" and "count" in info:
        print(
            "[{}] done: {} 篇（最宽级别 {}）".format(
                name, info["count"], info.get("max_level") or "-"
            )
        )
    elif status == "done":
        print(
            "[{}] done: {} steps, {} tokens".format(
                name,
                info.get("steps", 0),
                (info.get("usage") or {}).get("total_tokens", 0),
            )
        )
    elif status == "degraded" and "candidates" in info:
        print(
            "[{}] degraded: {} 篇全文 / 选中 {} 篇（候选 {} 篇，摘要级 {} 篇，失败 {} 篇）".format(
                name,
                info.get("count", 0),
                info.get("selected", 0),
                info.get("candidates") or "-",
                len(info.get("abstract") or []),
                len(info.get("failed") or []),
            )
        )
    elif status in ("retry", "degraded"):
        print("[{}] {}: {}".format(name, status, "；".join(info.get("problems") or [])))
    elif status == "skipped":
        print("[{}] skipped（复用已落盘产物）".format(name))
    elif status == "failed":
        print("[{}] failed".format(name))


def run_workflow_mode(topic, resume=False, mode="deep", level="low", survey_ids=None):
    settings = load_settings()
    client = OpenAICompatClient(settings)
    try:
        spec = resolve(topic, mode=mode, level=level, survey_ids=survey_ids)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("[spec] {}：{}".format(spec.label, spec.describe()))
    if spec.survey_ids:
        print("[spec] 候选池来自清单：{}".format("、".join(spec.survey_ids)))
    try:
        result = run_workflow(
            client,
            build_default_registry(),
            spec,
            on_event=print_event,
            on_phase=print_phase,
            resume=resume,
        )
    except (WorkflowError, ValueError) as exc:
        raise SystemExit("工作流失败: {}".format(exc))

    print()
    if result.survey:
        print_survey(result)
    else:
        print(result.report)
    print()
    if result.partial:
        print(
            "注意：候选池只 {} 篇，低于档位下限 {} 篇（差 {} 篇）；"
            "清单导入不补检，已标记 partial".format(
                result.partial["candidate_count"],
                result.partial["target_min"],
                result.partial["shortfall"],
            )
        )
    for name, path in result.paths.items():
        print("{}: {}".format(name, path))
    print("总 tokens: {}".format(result.usage.get("total_tokens", 0)))
    if result.issues:
        print("注意：引用自检未通过，问题已写入 report.md 末尾")


def print_survey(result):
    """仅搜集模式打印清单表：编号 / 年份 / arXiv / 标题。"""
    survey = result.survey
    print(
        "清单 {}：{} 篇，状态 {}，最宽级别 {}".format(
            survey["survey_id"],
            survey["count"],
            survey["status"],
            survey.get("max_level") or "-",
        )
    )
    if survey.get("shortfall"):
        print("缺口：还差 {} 篇到档位下限 {}".format(survey["shortfall"], result.target_min))
    path = Path(result.paths.get("papers", ""))
    if not path.exists():
        return
    papers = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print("{:>4}  {:<4}  {:<14}  {}".format("#", "年份", "arXiv", "标题"))
    for paper in papers[:20]:
        print(
            "{:>4}  {:<4}  {:<14}  {}".format(
                paper.get("rank", ""),
                paper.get("year") or "-",
                paper.get("arxiv_id", ""),
                paper.get("title", ""),
            )
        )
    if len(papers) > 20:
        print("…其余 {} 篇见清单文件".format(len(papers) - 20))


def main():
    parser = argparse.ArgumentParser(description="文献调研智能体")
    parser.add_argument("prompt", nargs="?", default=DEFAULT_QUESTION, help="研究主题或追问")
    parser.add_argument("--resume", action="store_true", help="复用当前会话历史；--workflow 下改为复用已落盘的阶段产物")
    parser.add_argument("--export", action="store_true", help="导出当前会话为 Markdown 后退出")
    parser.add_argument(
        "--workflow",
        action="store_true",
        help="按 Plan → Collect → Synthesize 三阶段执行，产物写入 workspace/<session>/workflow/",
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES),
        default="deep",
        help="调研模式：deep 深度调研（默认）/ survey 仅搜集；仅对 --workflow 生效",
    )
    parser.add_argument(
        "--level",
        choices=list(LEVELS),
        default="low",
        help="档位：low / mid / high，决定目标篇数与 Collect 轮数预算；仅对 --workflow 生效",
    )
    parser.add_argument(
        "--from-survey",
        nargs="+",
        metavar="SURVEY_ID",
        help="导入 1-3 份仅搜集清单作为候选池（不检索、不补检），仅用于 --workflow deep",
    )
    parser.add_argument("--web", action="store_true", help="启动本地 Web 交互界面")
    parser.add_argument("--port", type=int, default=8000, help="Web 界面端口，默认 8000")
    args = parser.parse_args()

    if args.web:
        serve_web(port=args.port)
        return

    if args.export:
        try:
            path = export_markdown()
        except ValueError as exc:
            raise SystemExit(str(exc))
        print("已导出: {}".format(path))
        return

    if args.workflow:
        for survey_id in args.from_survey or []:
            if not survey_id.startswith("sv_"):
                raise SystemExit(
                    "无法识别清单 id：{}。--from-survey 会把后面的参数都当成清单 id，"
                    "请把研究主题放在命令最前面".format(survey_id)
                )
        run_workflow_mode(
            args.prompt,
            resume=args.resume,
            mode=args.mode,
            level=args.level,
            survey_ids=args.from_survey,
        )
        return

    if args.from_survey:
        raise SystemExit("--from-survey 需要配合 --workflow 使用")

    settings = load_settings()
    client = OpenAICompatClient(settings)
    registry = build_default_registry()

    if args.resume:
        history = load_messages()
        if not history:
            raise SystemExit("当前会话没有历史，请去掉 --resume 重新开始")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    else:
        reset_session()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    user_message = {"role": "user", "content": args.prompt}
    messages.append(user_message)
    append_message(user_message)

    result = run_loop(
        client,
        registry,
        messages,
        max_turns=8,
        on_event=record_event,
        compact_threshold=settings.compact_threshold,
        compactor=lambda history: compact_messages(history, client),
    )
    append_run(result.stop_reason, result.steps, result.usage)
    print(result.content)


if __name__ == "__main__":
    main()
