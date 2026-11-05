"""命令行入口：Agent Loop + 会话持久化；--workflow 走三阶段调研。"""
import argparse

from litagent.agent import run_loop
from litagent.compaction import compact_messages
from litagent.config import load_settings
from litagent.llm.zhipu import ZhipuClient
from litagent.prompt import load_system_prompt
from litagent.session import (
    append_message,
    append_run,
    export_markdown,
    load_messages,
    reset_session,
)
from litagent.tools import build_default_registry
from litagent.types import AgentEvent
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
    if status == "start":
        print("[{}] start".format(name))
    elif status == "done":
        print(
            "[{}] done: {} steps, {} tokens".format(
                name,
                info.get("steps", 0),
                (info.get("usage") or {}).get("total_tokens", 0),
            )
        )
    elif status in ("retry", "degraded"):
        print("[{}] {}: {}".format(name, status, "；".join(info.get("problems") or [])))
    elif status == "skipped":
        print("[{}] skipped（复用已落盘产物）".format(name))
    elif status == "failed":
        print("[{}] failed".format(name))


def run_workflow_mode(topic, resume=False):
    settings = load_settings()
    client = ZhipuClient(settings)
    try:
        result = run_workflow(
            client,
            build_default_registry(),
            topic,
            on_event=print_event,
            on_phase=print_phase,
            resume=resume,
        )
    except WorkflowError as exc:
        raise SystemExit("工作流失败: {}".format(exc))

    print()
    print(result.report)
    print()
    for name, path in result.paths.items():
        print("{}: {}".format(name, path))
    print("总 tokens: {}".format(result.usage.get("total_tokens", 0)))
    if result.issues:
        print("注意：引用自检未通过，问题已写入 report.md 末尾")


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
    args = parser.parse_args()

    if args.export:
        try:
            path = export_markdown()
        except ValueError as exc:
            raise SystemExit(str(exc))
        print("已导出: {}".format(path))
        return

    if args.workflow:
        run_workflow_mode(args.prompt, resume=args.resume)
        return

    settings = load_settings()
    client = ZhipuClient(settings)
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
