# 交接文档：文献调研智能体（agentdemo）

> 用途：在上下文切换 / 换人接手时快速恢复项目状态。最后更新于第 8 步完成 + Web 交互界面落地。

## 一、项目目标

把最初的单文件 ReAct demo（原 `main.py` + 智谱 API + 天气工具）逐步演进为一个**文献调研智能体**，架构仿照开源项目 [pi-mono](https://github.com/earendil-works/pi) 的分层：

`llm 适配层 → Agent Loop → 工具协议/治理 → 提示词 SOP → 会话/压缩 → 工作流 → 评测`

仓库：https://github.com/lbwnbc/agentdemo （public）

## 二、当前状态（一句话）

框架层第 1–8 步已完成并真实跑通：检索 arXiv → 精读 PDF → 记录证据笔记 → 带引用综合 → 会话持久化/续聊 → 超阈值上下文压缩 → 三阶段工作流编排。第 9 步的“交互”部分已先落地：本地零依赖 Web 界面（`python main.py --web`）。剩余第 9 步的评测（golden set / 指标 / tests），以及被推迟的 Skills。

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
| `f425419` | 交接文档补充推送状态与网络诊断 |
| `e10b18a` | 第 8 步：研究工作流编排（Plan → Collect → Synthesize） |

**当前已全部推送到 GitHub**（`origin/main` 与本地一致）。旧智谱 key 已在后台禁用并更换，新 key 只存在本地 `.env`（已 gitignore）。

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
  workflow.py                 三阶段编排：阶段重试/resume、产物落盘、引用校验
  prompt/system.md            调研 SOP、引用规则、输出格式
  prompt/__init__.py          load_system_prompt() / load_workflow_prompt()
  prompt/workflow/*.md        plan / collect / outline / report 四份阶段提示词
  net.py                      RateLimiter / DiskCache / HttpClient（get_text、get_json）
  workspace.py                workspace/<session>/ 约定，LITAGENT_WORKSPACE / LITAGENT_SESSION
  tools/base.py               Tool 协议、JSON Schema 校验、异常归一化、文本截断
  tools/registry.py           ToolRegistry、before/after hooks、ToolDecision
  tools/paths.py              resolve_workspace_path（拒绝绝对路径与 .. 穿越）
  tools/arxiv.py              search_arxiv / get_arxiv_paper / parse_arxiv_feed
  tools/pdf.py                fetch_pdf / read_paper（按页窗口、字符上限）
  tools/notes.py              save_note / search_notes（notes.jsonl）
  tools/workflow_tools.py     submit_plan / submit_evidence / submit_outline / submit_report
  tools/__init__.py           build_default_registry()（6 个工具）
  web/server.py               本地 Web 服务：ThreadingHTTPServer 路由 + SSE + 单任务 JobManager（零新增依赖）
  web/static/index.html       单页前端：主题表单、阶段卡片、实时日志、报告/大纲/证据/计划四视图
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
8. **工作流用“提交工具”而不是解析文本**：`submit_plan` / `submit_evidence` / `submit_outline` / `submit_report` 把结构化产物直接写进 `StageStore`；前三个提交后靠 `ToolResult.terminate` 立即结束阶段。这样不需要从模型自由文本里抠 JSON，也不会因为格式抖动而失败。
9. **阶段可断点续跑**：产物落盘后 `--workflow --resume` 会跳过 plan/collect/outline。真实跑时 report 阶段连续两次 read timeout，靠这个省掉了重跑 collect 的 23 万 tokens。
10. **引用校验在图之外**：`validate_citations()` 只认证据库里的 `[eN]`、arXiv 号和 DOI，校验不过会把问题清单回喂给模型重写一次；仍不过就降级，把问题写进 `report.md` 末尾而不是丢掉报告。
11. **Web 界面零新增依赖**：标准库 `ThreadingHTTPServer` 做路由，SSE 单向下发阶段与工具事件；前端是自包含单页（无构建、无 CDN），报告用极简 Markdown 渲染器，`[eN]` 可点击跳到证据卡。`JobManager` 串行执行并缓存全部事件，页面刷新后从 0 回放。

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

# 5) 三阶段工作流：产物写 workspace/<session>/workflow/
python main.py --workflow "LLM agent memory 的研究现状"

# 6) 阶段失败后接着跑（跳过已落盘的 plan/evidence/outline）
$env:ZHIPU_TIMEOUT=300   # 报告这类长输出容易撞默认 60s 超时
python main.py --workflow --resume "同一主题"

# 7) 本地 Web 交互界面（浏览器打开 http://127.0.0.1:8000）
python main.py --web --port 8000
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
- **第 8 步**：离线验证阶段提交、产物落盘、非法引用触发 retry 后通过、未提交产物抛 `WorkflowError`、`resume` 只跑失败阶段；真实跑通完整流程——plan 4 子问题、collect 10 轮 7 篇 PDF 产出 12 条证据卡（23.5 万 tokens）、outline 2345 字、report 6423 字；引用校验 12/12 全部被引用、零非法 id/arXiv 号/DOI。产出报告里两处「证据不足」是模型主动标注，不是漏写。
- **Web 界面**：`python main.py --web` 启动后浏览器实测无控制台报错，空态、历史产物（wf-real 12 条证据）与报告引用芯片渲染正常；用 `resume=true` 只跑 report，SSE 依次收到 plan/collect/outline `skipped`、report `start`、`submit_report` 工具调用、report `done`（14,996 tokens）与 `finished`，共 12 条事件；`/api/result` 返回新报告 5,636 字、引用自检 0 问题。

## 八、已知限制与坑

1. **GitHub 推送时好时坏**：2026-11-05 上午 TCP 可达但 TLS 握手失败（curl 退出码 35），同日下午已恢复正常推送。若再遇到 `Failed to connect to github.com port 443`，先 `git push` 重试，别急着查凭据。
2. **长输出阶段容易超时**：report 一次要生成 7K+ completion tokens，默认 `ZHIPU_TIMEOUT=60` 会撞 read timeout。跑 `--workflow` 前建议设 `ZHIPU_TIMEOUT=300`。
3. **PDF 下载恢复但不算稳定**：此前 `arxiv.org/pdf` 超时，2026-11-05 实测 7 篇全部下载成功。失败时 collect 提示词允许降级为摘要级证据（`kind=background`）。
4. **GitHub 仓库是 public**，旧 key 已禁用更换；新 key 只在本地 `.env`。
5. **缺少提交到仓库的自动化测试**：目前的验证脚本是临时的（写在 `%TEMP%`），删掉即失。第 9 步应把 golden set 与工具测试固化到 `tests/`。
6. **笔记库按会话隔离**，没有跨会话的长期文献库；同一篇论文重复精读会产生重复笔记。
7. **压缩摘要可能丢细节**：摘要由同一个模型生成，长会话多次压缩后早期实验数字可能失真，重要结论应尽早写入 `notes.jsonl`。
8. **无上下文长度硬校验**：阈值默认 30000 tokens，按模型实际窗口需调（`LITAGENT_COMPACT_THRESHOLD`）。
9. **工作流没有接入 session/compaction**：四个阶段各自独立统计用量，`--workflow` 不写 `session.jsonl`，也不能 `--export`；另外 `--workflow` 新跑会覆盖上一轮的四个产物文件。
10. **collect 阶段成本高**：真实跑满 10 轮用了 23.5 万 tokens，因为每轮都携带检索摘要与 PDF 正文。后续可考虑按论文拆子代理、或把已读页压缩成证据再丢弃原文。
11. **Web 端是单任务串行**：`JobManager` 同时只允许一个工作流，因为 `LITAGENT_SESSION` 是进程级环境变量，并发跑不同会话会互相串目录；页面刷新后靠内存中的 job 回放事件，服务重启则历史任务不可再查（产物仍在磁盘，可切会话读取）。
12. **Web 端默认放宽读超时**：`serve()` 用 `setdefault("ZHIPU_TIMEOUT", "300")`，避免报告阶段撞 60s；`.env` 显式设置可覆盖。

## 九、下一步（按建议顺序）

1. **Skills（原第 6 步后半，也是唯一还欠的框架能力）**。`litagent/prompt/skills/*/SKILL.md` + `load_skill` 工具做渐进式披露：主提示词只放索引，按需加载全文。参考 pi 的 `skills.ts`、`resource-loader.ts`。验收：开/关 skills 的产出可对比，引用格式统一。
2. **第 9 步：评测（交互部分已完成）**。golden set（10 个主题 + 期望覆盖的关键工作）、指标（候选召回 / 引用真实率 / 证据覆盖率 / 工具失败率 / 成本），把 `%TEMP%` 里的验证脚本固化进 `tests/`；Web 界面已提供阶段进度、实时事件流与产物阅读，可直接复用其事件数据做展示层回归。
3. **增强检索**：Semantic Scholar 引文滚雪球（注意限速，建议申请 key）、跨会话文献库、去重。
4. **工作流增强**（可选）：把 `--workflow` 的事件接进 `session.jsonl` 以支持 `--export`；collect 按论文拆子代理降低 23 万 tokens 的上下文成本；多主题运行时不覆盖旧产物。

## 十、给接手者的四句话

- 先读 `ROADMAP.md` 了解全貌，再读 `litagent/agent/loop.py`（所有能力的地基）。
- 改工具就改 `tools/`，别把业务塞进 `loop.py`；loop 只依赖 `client.chat` 和 `registry` 两个接口。
- 任何“让模型更聪明”的改动，优先改 `prompt/system.md`，而不是加代码分支。
- 要改工作流，先看 `litagent/workflow.py` 的四个 `_run_stage` 调用点；阶段产物全靠提交工具落盘，别改成解析模型文本。
