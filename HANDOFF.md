# 交接文档：文献调研智能体（agentdemo）

> 用途：在上下文切换 / 换人接手时快速恢复项目状态。最后更新于第 7 步完成时。

## 一、项目目标

把最初的单文件 ReAct demo（原 `main.py` + 智谱 API + 天气工具）逐步演进为一个**文献调研智能体**，架构仿照开源项目 [pi-mono](https://github.com/earendil-works/pi) 的分层：

`llm 适配层 → Agent Loop → 工具协议/治理 → 提示词 SOP → 会话/压缩 → 工作流 → 评测`

仓库：https://github.com/lbwnbc/agentdemo （public）

## 二、当前状态（一句话）

框架层第 1–7 步已完成并真实跑通：检索 arXiv → 精读 PDF → 记录证据笔记 → 带引用综合 → 会话持久化/续聊 → 超阈值上下文压缩。剩余第 8（工作流编排）、9（评测与交互）两阶段，以及被推迟的 Skills。

## 三、提交记录

| 提交 | 内容 |
| --- | --- |
| `743b93a` | 初始化仓库 + `ROADMAP.md` 分步计划 |
| `42717e7` | 第 1 步：LLM 适配层与配置层 |
| `c476f2f` | 第 2 步：工具协议与注册表 |
| `eb352b1` | 第 3 步：Agent Loop（并行工具、续跑） |
| `80f5ccd` | 第 4 步：工具治理与网络基础设施 |
| `b903b78` | 第 5a 步：arXiv 检索工具 |
| `80a2318` | 第 5b 步：PDF 精读与证据笔记 |
| `6aacabc` | 第 6 步：调研 SOP 系统提示词（移除 get_weather） |
| `50c3d8c` | 第 7 步：会话持久化 + 上下文压缩 |
| `5026ffa` | 本交接文档初版 |

**注意：`6aacabc` / `50c3d8c` / `5026ffa` 以及本文件的后续更新都还没推到 GitHub。** 本机到 github.com:443 的 TLS 握手与连接均失败（详见第八节第 1 条），本地 `main` 领先 `origin/main` 若干提交。网络恢复后执行：

```powershell
git push origin main
```

推送成功后请顺手把本表补上自己的提交号，免得后面接手的人误判已同步。

## 四、代码地图

```text
main.py                       CLI 入口：prompt / --resume / --export，串起 loop + session + compaction
litagent/
  config.py                   Settings：.env + 环境变量（ZHIPU_* / LITAGENT_*）
  types.py                    ToolCall / ToolResult / ToolError，AgentEvent 枚举与 Event
  llm/base.py                 LLMResponse、LLMClient 抽象
  llm/zhipu.py                ZhipuClient：超时、429/5xx 退避重试、响应校验
  agent/loop.py               run_loop / run_loop_continue、终止条件、并行工具、压缩钩子
  compaction.py               按用户轮次切分 + 摘要历史（保留工具配对）
  session.py                  JSONL 记录、历史恢复、Markdown 导出、reset
  prompt/system.md            调研 SOP、引用规则、输出格式
  prompt/__init__.py          load_system_prompt()
  net.py                      RateLimiter / DiskCache / HttpClient（get_text、get_json）
  workspace.py                workspace/<session>/ 约定，LITAGENT_WORKSPACE / LITAGENT_SESSION
  tools/base.py               Tool 协议、JSON Schema 校验、异常归一化、文本截断
  tools/registry.py           ToolRegistry、before/after hooks、ToolDecision
  tools/paths.py              resolve_workspace_path（拒绝绝对路径与 .. 穿越）
  tools/arxiv.py              search_arxiv / get_arxiv_paper / parse_arxiv_feed
  tools/pdf.py                fetch_pdf / read_paper（按页窗口、字符上限）
  tools/notes.py              save_note / search_notes（notes.jsonl）
  tools/__init__.py           build_default_registry()（6 个工具）
requirements.txt              requests、PyPDF2==3.0.1
ROADMAP.md                    原始分步计划与 pi 代码参考
```

数据落在 `workspace/<session>/`：`session.jsonl`、`session.md`、`papers/<arxiv_id>.pdf`、`notes.jsonl`、`cache/arxiv/`（已 gitignore）。

## 五、关键设计决定（改代码前先读）

1. **消息就是 OpenAI 兼容 dict**，没有再包一层 `Message` 类，避免双表示转换；类型约束只落在工具侧（`ToolCall` / `ToolResult`）。
2. **Loop 是同步实现**，同轮多工具用 `ThreadPoolExecutor` 并行、结果按模型给出的顺序回填。计划里写的 `asyncio.gather` 暂缓，等 LLM 层异步化后再切换，接口不变。
3. **压缩切分点固定在 user 消息之前**，保证 assistant 的 `tool_calls` 不会和后续 `tool` 结果被拆散。阈值按上一轮 `prompt_tokens` 判断。
4. **`--resume` 复用同一个会话文件**；不带 `--resume` 的新运行会 `reset_session()` 清空 `session.jsonl`（但不会删 PDF/笔记）。需要多会话隔离时用 `LITAGENT_SESSION=<name>`。
5. **PDF 解析双后端**：先试 `pypdf`，失败回落 `PyPDF2`。原因是本机 Python 3.7，新版 pypdf 依赖 `typing.Protocol`（3.8+），导入即失败。`requirements.txt` 固定 `PyPDF2==3.0.1`。
6. **工具治理用钩子 + 路径守卫**，没有实现完整的 project-trust / file-mutation-queue；真有并发写文件需求时再补。
7. **提示词决定行为**：第 6 步换成 SOP 后，模型从“检索+罗列”变成“检索 → 证据固化 → 带引用综合”，并会自动去重上一轮已交付的论文。

## 六、运行方式

```powershell
# 1) 首次：复制 .env.example 为 .env，填入新的智谱 key（旧 key 已泄露，务必作废重发）
python main.py "LLM agent memory 的研究现状"

# 2) 续聊（复用 session.jsonl 历史）
python main.py --resume "再补 2 篇关于 memory poisoning 的"

# 3) 导出会话 Markdown
python main.py --export

# 4) 修改压缩阈值（默认 30000）
$env:LITAGENT_COMPACT_THRESHOLD=3000
```

可用环境变量：`ZHIPU_API_KEY`、`ZHIPU_BASE_URL`、`ZHIPU_MODEL`、`ZHIPU_TEMPERATURE`、`ZHIPU_TIMEOUT`、`ZHIPU_MAX_RETRIES`、`LITAGENT_COMPACT_THRESHOLD`、`LITAGENT_WORKSPACE`、`LITAGENT_SESSION`。

## 七、已验证内容

- **第 1 步**：mock 验证 429→500→200 重试、usage/tool_calls 解析、400 直接抛 `LLMError`。
- **第 2 步**：8 项工具协议测试（未知工具、坏 JSON、缺参、类型错误、内部异常、20000 字符截断、spec 结构）。
- **第 3 步**：9 项 loop 测试（含用 `threading.Barrier` 证明两个 handler 同时进入；四种终止原因；续跑前置校验）。
- **第 4 步**：8 类治理测试（钩子拦截/异常/改写、`terminate`、路径穿越、限速、缓存 TTL、本地 HTTP server 的 503 重试与 404）。
- **第 5 步**：arXiv 真实检索成功；离线验证 Feed 解析、分页箭头、PDF 文本抽取、页码钳制、笔记编号与检索。
- **第 6 步**：真实跑通 4 轮 / 27896 tokens，输出四段式报告并带 `[n1]` 引用。
- **第 7 步**：会话往返/导出/空会话报错；真实 `--resume` 1 轮直接复用历史；真实压缩触发 `[compact] messages 10 -> 7`，且模型记得上一轮论文编号并主动去重。

## 八、已知限制与坑

1. **GitHub 推送不稳定 / 当前不可用**：多次出现 `Failed to connect to github.com port 443`。2026-11-05 复测：TCP 443 可达（`Test-NetConnection` 为 True），但 `curl https://github.com` 返回 `http=000`、curl 退出码 35（TLS 连接失败），`git push` 无论是否加 `http.version=HTTP/1.1` 都失败。与代码、凭据、sandbox 无关，属于本机网络环境问题。恢复后重试 `git push origin main` 即可。
2. **arxiv.org/pdf 下载在本网络超时**，`export.arxiv.org` API 正常。因此真实 PDF 下载链路未端到端验证过（解析逻辑本身已用本地构造 PDF 验证）。
3. **GitHub 仓库是 public**，且早期 API key 曾明文出现在 `main.py` 和对话里，务必去智谱后台轮换。
4. **缺少提交到仓库的自动化测试**：目前的验证脚本是临时的（写在 `%TEMP%`），删掉即失。第 9 步应把 golden set 与工具测试固化到 `tests/`。
5. **笔记库按会话隔离**，没有跨会话的长期文献库；同一篇论文重复精读会产生重复笔记。
6. **压缩摘要可能丢细节**：摘要由同一个模型生成，长会话多次压缩后早期实验数字可能失真，重要结论应尽早写入 `notes.jsonl`。
7. **无上下文长度硬校验**：阈值默认 30000 tokens，按模型实际窗口需调（`LITAGENT_COMPACT_THRESHOLD`）。

## 九、下一步（按建议顺序）

1. **补齐并推送**（网络恢复后）：`git push origin main`。
2. **第 8 步：研究工作流编排**。显式三阶段 Plan → Collect → Synthesize，产物落盘 `plan.json` / `evidence.jsonl` / `outline.md` / `report.md`。pi 参考：`agent-session-runtime.ts`（阶段状态）、`nested-tool-calls.ts`（子代理式嵌套调用）。
3. **Skills（原第 6 步后半）**。`litagent/prompt/skills/*/SKILL.md` + `load_skill` 工具做渐进式披露。参考：`skills.ts`、`resource-loader.ts`。
4. **第 9 步：评测与交互**。golden set（10 个主题）、指标（候选召回/引用真实率/证据覆盖率/工具失败率/成本），把离线测试固化进 `tests/`；先做 rich CLI，再考虑 Web。
5. **增强检索**：Semantic Scholar 引文滚雪球（注意限速，建议申请 key）、跨会话文献库、去重。

## 十、给接手者的三句话

- 先读 `ROADMAP.md` 了解全貌，再读 `litagent/agent/loop.py`（所有能力的地基）。
- 改工具就改 `tools/`，别把业务塞进 `loop.py`；loop 只依赖 `client.chat` 和 `registry` 两个接口。
- 任何“让模型更聪明”的改动，优先改 `prompt/system.md`，而不是加代码分支。
