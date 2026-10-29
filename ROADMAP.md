# 文献调研智能体 · 分步实施计划

目标：把当前的单文件 ReAct demo（`main.py`）逐步演进为能够检索、精读、综合并核查引用的文献调研智能体。

架构参考 [pi-mono（现 earendil-works/pi）](https://github.com/earendil-works/pi) 的四层结构：

```text
packages/ai          一次 LLM 调用（供应商适配、流式、用量）
packages/agent       Agent 循环、状态、事件
coding-agent/core    工具、提示词、Skills、会话、上下文压缩
tui + evals          交互渲染与回归评测
```

即：先在 Python 里把这四层各自落一遍，而不是照搬 TypeScript 实现。

## 现状

- `main.py` 是标准的单文件 ReAct 实现：`TOOLS` → `call_zhipu_api` → `agent_loop`，缺的是框架层而不是功能层。
- 待修项：密钥硬编码（已改为读环境变量）、`temperature: 1.0` 对工具调用偏高、`json.loads(arguments)` 缺少异常保护。
- `tool.py` 为空，作为 `tools` 包的起点。

## 目标目录

```text
agentdemo/
  main.py                      # 只保留入口
  .env.example                 # 密钥模板
  litagent/
    config.py                  # 模型、密钥、预算
    types.py                   # Message / ToolCall / ToolResult / AgentEvent
    llm/                       # provider 适配（zhipu，后续可加 openai）
    agent/                     # loop.py, agent.py, context.py
    tools/                     # base.py, registry.py, arxiv.py, s2.py, pdf.py, notes.py
    prompt/                    # system.md, skills/*/SKILL.md
    session/                   # JSONL 存储、resume
    compaction.py
    cli.py
  workspace/<session_id>/      # 下载的 PDF、笔记、检索缓存
  eval/cases/                  # 评测用例
```

## 分步计划

### 第 0 步｜先定边界（不写代码）

- **实现**：明确输入（研究问题或已有文献列表）、输出（综述报告 + 证据表 + BibTeX）、数据源（arXiv / Semantic Scholar / 本地 PDF）与预算（token 与请求上限）。
- **参考**：`coding-agent/README.md` 与 docs，学习它如何区分“框架能力”和“应用能力”。
- **验收**：一页需求，能说清“什么算做完”。

### 第 1 步｜工程基线 + LLM 适配层

- **实现**：拆分 `main.py`；密钥移入 `.env`；`temperature` 降到 0.2~0.3；封装 `LLMClient.chat(messages, tools) -> LLMResponse`，统一超时、429/5xx 重试、用量统计、错误归一化。智谱 v4 是 OpenAI 兼容协议，适配代码可复用到 OpenAI。
- **参考**：[packages/ai/src](https://github.com/earendil-works/pi/tree/main/packages/ai/src)、[model-registry.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/model-registry.ts)、[model-resolver.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/model-resolver.ts)。
- **验收**：天气 demo 行为不变跑通，日志能打印每轮 token；换模型只改配置。

### 第 2 步｜类型契约 + 工具协议

- **实现**：`types.py` 定义内容块（text / thinking / tool_call / tool_result）、消息、事件枚举；`tools/base.py` 定义 `Tool(name, description, schema, execute)` 与注册表，用 jsonschema / pydantic 校验参数，把异常转成 `ToolResult(is_error=True)` 而不是抛出；加入大文本截断策略（保留头尾 + 提示“用分片读取”）。
- **参考**：[types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts)（`AgentTool`、`AgentContext`、参数校验、事件类型）、[truncate.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/truncate.ts)、[read.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)。
- **验收**：未知工具、坏参数、超长输出都不会中断会话。

### 第 3 步｜Agent Loop（地基）

- **实现**：`run_loop()`：调用模型 → 有 tool_calls 就执行 → 结果回填 → 下一轮；终止条件为“无工具调用 / 步数上限 / token 预算 / 用户中断”。同轮多个工具用 `asyncio.gather` 并行，结果按 assistant 原顺序回填；补 `run_loop_continue()` 支持断点续跑；对外发事件（turn start、message delta、tool start/end、agent end）。
- **参考**：[agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) 的 `runLoop` / `executeToolCalls` / `agentLoopContinue`；[agent.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent.ts) 的 `AgentState`、`pendingToolCalls`、steering / follow-up 队列。
- **验收**：用假的 stream 函数写 3 个测试（无工具、单工具、并行双工具），断言事件顺序。

### 第 4 步｜工具治理：hooks、权限、限速、缓存

- **实现**：`before_tool_call` / `after_tool_call`（可 block、可改结果、可 terminate）；网络工具统一超时、退避、按 API 限速（arXiv 建议约 3 秒/请求）、磁盘缓存；写文件只允许落在 `workspace/<session_id>/`。
- **参考**：[types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts) 的 `BeforeToolCallResult` / `AfterToolCallResult`；[project-trust.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/project-trust.ts)、[output-guard.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/output-guard.ts)、[file-mutation-queue.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/file-mutation-queue.ts)、[bash.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/bash.ts)。
- **验收**：检索工具连续失败不拖垮会话；越界写路径被拒绝。

### 第 5 步｜文献工具集（研究能力的核心）

- **实现**第一批 5~6 个工具：`search_arxiv`、`search_s2` / `get_citations`（引文网络滚雪球）、`fetch_pdf`、`read_paper(paper_id, section/page_range)`、`save_note(claim, quote, source)` 与 `search_notes`。关键点是 `read_paper` 按小节读取，不把整篇 PDF 塞进上下文。
- **参考**：[read.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)（offset/limit 与错误文案）、[grep.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/grep.ts) / [find.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/find.ts) / [ls.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/ls.ts)、[tool-definition-wrapper.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/tool-definition-wrapper.ts)。
- **验收**：给定一个主题，产出 10 篇候选 + 3 篇精读笔记，且不超预算。

### 第 6 步｜系统提示词与 Skills

- **实现**：system prompt 固化 SOP（澄清 → 拆子问题 → 生成检索式 → 检索筛选 → 精读 → 证据卡 → 综合 → 引用校验），并明确“每个论断必须绑定 evidence id，禁止编造引用”；`skills/` 放 `SKILL.md`，主提示词只放索引、按需加载（渐进式披露）。
- **参考**：[system-prompt.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/system-prompt.ts)、[skills.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/skills.ts)、[prompt-templates.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/prompt-templates.ts)、[resource-loader.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/resource-loader.ts)。
- **验收**：开启/关闭 skills 的产出可对比，引用格式统一。

### 第 7 步｜会话持久化 + 上下文压缩

- **实现**：JSONL 追加写入每条消息与事件，支持 resume 与导出 markdown；token 超阈值时触发 compaction（保留 system + 最近 N 轮 + 旧轮摘要，工具原文只留 evidence id + 片段）；每个 session 独立 workspace。
- **参考**：[session-manager.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)、[agent-session.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/agent-session.ts)、[session-export.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-export.ts)、[compaction/](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/src/core/compaction)、[usage-totals.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/usage-totals.ts)。
- **验收**：30 轮 + 10 篇全文之后仍可继续，重启能恢复。

### 第 8 步｜研究工作流编排

- **实现**显式三阶段：Plan（拆子问题、生成检索式）→ Collect（每篇论文交给一个受限子代理，输出结构化证据卡）→ Synthesize（大纲 → 写作 → 引用校验）；阶段产物落盘 `plan.json` / `evidence.jsonl` / `outline.md` / `report.md`。
- **参考**：[agent-session-runtime.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/agent-session-runtime.ts)、[nested-tool-calls.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/nested-tool-calls.ts)、[pi-subagents](https://pi.dev/packages/pi-subagents?name=subagents)。
- **验收**：报告里每条论断可回溯到 evidence id，DOI / arXiv 号能通过校验。

### 第 9 步｜评测与交互

- **实现** golden set（10 个主题 + 期望覆盖的关键工作），指标包括候选召回、引用真实率、证据覆盖率、工具失败率、成本/耗时；先做 rich CLI 渲染事件流，再考虑 Web。
- **参考**：[agent-loop.test.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/test/agent-loop.test.ts)、[packages/evals](https://github.com/earendil-works/pi/tree/main/packages/evals)、[packages/tui](https://github.com/earendil-works/pi/tree/main/packages/tui)、[telemetry.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/telemetry.ts)。
- **验收**：一条命令跑完评测，指标可比对。

## 执行顺序

`1 → 2 → 3 → 5 → 6 → 4 → 7 → 8 → 9`

先把 loop 与文献工具跑通，治理、持久化和评测后补。每一步都应保持仓库可运行、可回滚。

## 参考资源

- [earendil-works/pi 仓库](https://github.com/earendil-works/pi)（原 `badlogic/pi-mono`）
- [Agent Loop & State Machine - DeepWiki](https://deepwiki.com/badlogic/pi-mono/3.1-agent-loop-and-state-machine)
- [pi-agent-core: Agent Framework - DeepWiki](https://deepwiki.com/badlogic/pi-mono/3-pi-agent-core:-agent-framework)
- [pi-agent-core Python 移植版（alpha，仅供对照）](https://pypi.org/project/pi-agent-core/)
