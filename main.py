"""第 3 步验收 demo：Agent Loop + 事件输出。"""
from litagent.agent import run_loop
from litagent.config import load_settings
from litagent.llm.zhipu import ZhipuClient
from litagent.tools import build_default_registry
from litagent.types import AgentEvent

SYSTEM_PROMPT = (
    "你是一个文献调研助手。用户给出研究主题时，先用 search_arxiv 检索论文，"
    "必要时用 get_arxiv_paper 获取单篇元数据。回答时列出 arXiv 编号、标题和一句话结论，"
    "不要编造未检索到的文献。"
)


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


def main():
    settings = load_settings()
    client = ZhipuClient(settings)
    registry = build_default_registry()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "帮我检索 3 篇关于 LLM agent memory 的论文，并简要总结它们各自关注什么。"},
    ]
    result = run_loop(client, registry, messages, max_turns=6, on_event=print_event)
    print(result.content)


if __name__ == "__main__":
    main()
