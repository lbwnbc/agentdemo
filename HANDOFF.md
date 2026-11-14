# 交接文档：文献调研智能体（agentdemo）

> 用途：在上下文切换 / 换人接手时快速恢复项目状态。最后更新于 2026-11-14（第 14 步：Web 集成与评测基线）。

## 一、项目目标

把最初的单文件 ReAct demo（原 `main.py` + 智谱 API + 天气工具）逐步演进为一个**文献调研智能体**，架构仿照开源项目 [pi-mono](https://github.com/earendil-works/pi) 的分层：

`llm 适配层 → Agent Loop → 工具协议/治理 → 提示词 SOP → 会话/压缩 → 工作流 → 评测`

仓库：https://github.com/lbwnbc/agentdemo （public）

## 二、当前状态（一句话）

框架层第 1–8 步已完成并真实跑通：检索 arXiv → 精读 PDF → 记录证据笔记 → 带引用综合 → 会话持久化/续聊 → 超阈值上下文压缩 → 三阶段工作流编排。第 9 步的“交互”部分已先落地：本地零依赖 Web 界面（`python main.py --web`）。第二轮迭代按 `DESIGN.md` 推进：第 10 步「工作流参数化」、第 11 步「仅搜集模式」、第 12 步「深度分层」、第 13 步「清单导入」（`--from-survey`，候选池严格限定在清单并集、不补检）与第 14 步「Web 集成与评测基线」（模式/档位/清单多选、`/api/surveys`、清单阅读导出、`--eval` 对比表）已完成。剩余第 9 步的评测（golden set / 指标 / tests）、被推迟的 Skills 与可选的成本优化。

**当前本机运行时状态（2026-11-14）**：8000 端口有一个 Web 实例在跑（`python main.py --web --port 8000`），空闲；它是第 13 步之前启动的进程，**不包含第 14 步的 `/api/surveys` 等新路由，需重启后才能用新界面**。LLM 已从智谱切到 OpenAI 兼容中转站（`LLM_*` 环境变量，默认 `deepseek-v4.1-flash`），密钥只在本机 `.env`。工作区里 `default/workflow` 是第 12 步 deep/low 的完整产物（15 篇候选 / 8 篇选中 / 32 条全文证据 / 报告），`wf-real` 是第 8 步的四件套（4 子问题 / 12 证据 / 报告），`new` 只有 `plan.json`，`survey-real` 有一份 13 篇的真实清单 + 第 13 步导入模式的完整产物（13 候选 / 8 选中 / 28 条证据 / 报告），`web-step14` 是第 14 步 Web 端真实跑出的 15 篇清单，`eval-<case>-<mode>-<level>` 是评测矩阵的隔离会话。评测结果在 `eval/results/`（`20261114_150927-records.json` + `-table.md`）。

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
| `2f0dee3` | Web 交互界面：本地 HTTP 服务 + SSE + 单页前端（`main.py --web`） |
| `8c3ed87` | 交接文档补充 Web 界面提交记录 |
| `b9ab4e6` | 修复：工作流异常时标记失败阶段，避免界面停在「进行中」 |
| `c050180` | 修复：规划阶段强制沿用主题中的年份范围 |
| `de1a8eb` | 交接文档更新到 2026-11-07，系统提示词遵循用户时间范围 |
| `acb6441` | LLM 适配层改为 OpenAI 兼容协议；补 collect 覆盖校验；新增 `DESIGN.md` 与第 10–14 步计划 |
| `b19ffe5` | 第 10 步：工作流参数化（`RunSpec` + 六档预设 + 档位驱动校验） |
| `1d959fb` | 第 11 步：仅搜集模式（检索式规划 + L0–L3 逐级放宽 + 清单落盘） |
| `4032a87` | 第 12 步：深度分层（候选集 + Top-K 选择 + 逐篇精读，证据分 `fulltext`/`abstract`） |
| `7641a1b` | 交接与设计文档同步第 12 步（实测成本、两条新坑） |
| `9eb623a` | 交接文档补齐第 12 步提交记录与运行配置说明 |
| `74a8ac1` | 第 13 步：清单导入（`--from-survey` + 清单并集候选池 + `candidate_source`） |
| `2d478da` | 第 14 步：Web 集成（模式/档位/清单多选、`/api/surveys`、清单阅读导出、partial 展示）与评测基线（`--eval`） |

**当前已全部推送到 GitHub**（`origin/main` 与本地一致）。旧智谱 key 已在后台禁用并更换，新 key 只存在本地 `.env`（已 gitignore）。

## 四、代码地图

```text
main.py                       CLI 入口：prompt / --resume / --export，串起 loop + session + compaction
litagent/
  config.py                   Settings：.env + 环境变量（LLM_* / LITAGENT_*）
  types.py                    ToolCall / ToolResult / ToolError，AgentEvent 枚举与 Event
  llm/base.py                 LLMResponse、LLMClient 抽象
  llm/openai_compat.py        OpenAICompatClient：Bearer 鉴权、超时、429/5xx 退避重试、响应字段白名单
  agent/loop.py               run_loop / run_loop_continue、终止条件、并行工具、压缩钩子
  compaction.py               按用户轮次切分 + 摘要历史（保留工具配对）
  session.py                  JSONL 记录、历史恢复、Markdown 导出、reset
  workflow.py                 三阶段编排：阶段重试/resume、产物落盘、引用校验
  run_spec.py                 RunSpec + 六档 PRESETS（survey/deep × low/mid/high）+ resolve()
  search_ladder.py            L0–L3 逐级放宽、arXiv 去重、分页取数、provenance（纯代码）
  survey.py                   仅搜集流程：survey_plan → 检索 → Digest → papers.jsonl + index.json；load_survey_papers 读清单并集供导入
  select.py                   Top-K 选择：确定性规则打分（命中检索式 / 兜底级别 / 年份 / 分类 / 关键词）
  deep_read.py                逐篇精读调度：每篇独立 messages + 独立 run_loop，只回传证据卡
  eval.py                     评测基线：用例 × 六种组合，计算召回/证据覆盖/引用真实率/tokens/耗时并输出对比表
  prompt/system.md            调研 SOP、引用规则、输出格式
  prompt/__init__.py          load_system_prompt() / load_workflow_prompt()
  prompt/workflow/*.md        plan / collect / outline / report / survey_plan / read 阶段提示词
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
  web/server.py               本地 Web 服务：ThreadingHTTPServer 路由 + SSE + 单任务 JobManager + /api/surveys 清单接口
  web/static/index.html       单页前端：模式/档位/清单多选、阶段卡片随模式切换、报告/大纲/证据/计划/清单五视图
  eval/cases/cases.json       评测用例（3 个主题）
  eval/results/               评测落盘：<stamp>-records.json + <stamp>-table.md
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
12. **深度分层是“代码筛选 + 上下文隔离”**：候选集只取摘要（`candidates.jsonl`），Top-K 用 `select.py` 的确定性打分（不用模型），精读由 `deep_read.py` 逐篇起独立 `run_loop`——每篇只看到自己的 PDF，读完只把证据卡写回共享 `StageStore`，主上下文不再累积全文。证据卡带 `source`（`fulltext`/`abstract`）与 `read_round`，由调度代码注入、覆盖模型自填值；`validate_citations()` 与 outline/report 的提示词只使用 `fulltext` 证据（旧数据缺省视为 `fulltext`）。精读彻底失败的论文直接判失败；只有摘要证据的记 `degraded`，但可引用篇数要求过半。
13. **评测只做结构级指标**：`litagent/eval.py` 不引入人工标注，召回 = 候选去重篇数 / 档位下限，证据覆盖 = 有全文证据的论文数 / 应精读篇数，引用真实率 = 报告中 `[eN]` 能在全文证据库找到的比例；每个「用例 × 组合」使用独立会话（`eval-<case>-<mode>-<level>`），结果同时落 JSON 与 Markdown，便于横向比较。真正的 golden set（期望覆盖的关键工作）留到第 9 步。
14. **Web 的阶段集合由 mode 决定**：`server.MODE_PHASES` 与前端 `MODE_PHASES` 同源（deep 四段、survey 两段），`Job.stages` 在创建时按 `spec.mode` 初始化；`partial` 同时出现在阶段卡片（琥珀色）、报告顶部横幅、统计卡「候选/下限」与清单页徽章，不靠日志判断。清单按会话隔离，`/api/surveys` 读当前会话的 `surveys/index.json`，导出走 `/api/file?name=survey&id=sv_...`。

## 六、运行方式

```powershell
# 1) 首次：复制 .env.example 为 .env，填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（OpenAI 兼容，默认 deepseek-v4.1-flash）
python main.py "LLM agent memory 的研究现状"

# 2) 续聊（复用 session.jsonl 历史）
python main.py --resume "再补 2 篇关于 memory poisoning 的"

# 3) 导出会话 Markdown
python main.py --export

# 4) 修改压缩阈值（默认 30000）
$env:LITAGENT_COMPACT_THRESHOLD=3000

# 5) 三阶段工作流：产物写 workspace/<session>/workflow/
python main.py --workflow "LLM agent memory 的研究现状"

# 5b) 指定模式与档位（默认 deep/low；档位决定目标篇数与 Collect 轮数）
python main.py --workflow --mode deep --level mid "LLM agent memory 的研究现状"
#    deep 产物：plan.json → candidates.jsonl → selected.json → evidence.jsonl → outline.md → report.md
#    仅搜集：只规划检索式，篇数/去重/排序全由代码完成，产物在 workspace/<session>/surveys/
python main.py --workflow --mode survey --level low "2026年智能体记忆机制前沿进展"

# 5c) 导入 1–3 份仅搜集清单作为候选池（不检索、不补检；主题必须写在最前面）
#     清单按会话隔离，需用同一会话：$env:LITAGENT_SESSION=<产出清单的会话>
$env:LITAGENT_SESSION="survey-real"
python main.py "2026年智能体记忆机制前沿进展" --workflow --mode deep --level low --from-survey sv_20261114_140755_6ed0

# 6) 阶段失败后接着跑（跳过已落盘的 plan/evidence/outline）
$env:LLM_TIMEOUT=300   # 报告这类长输出容易撞默认超时
python main.py --workflow --resume "同一主题"

# 7) 本地 Web 交互界面（浏览器打开 http://127.0.0.1:8000）
python main.py --web --port 8000

# 8) 评测基线：eval/cases/ 的 3 个用例 × 六种组合，输出对比表并写 eval/results/
python main.py --eval
python main.py --eval --eval-cases agent-memory --eval-combos survey/low,deep/low
```

可用环境变量：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_TEMPERATURE`、`LLM_TIMEOUT`、`LLM_MAX_RETRIES`、`LITAGENT_COMPACT_THRESHOLD`、`LITAGENT_WORKSPACE`、`LITAGENT_SESSION`。

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
- **失败态修复（2026-11-07）**：用错误 key 起 8124 测试实例，SSE 事件为 `plan start → agent_start → turn → phase plan failed → error → finished(ok=false)`；浏览器实测「规划」卡片标红、提示 401，其余阶段保持等待，控制台零报错。旧行为只会发 `error`/`finished`，卡片永远停在「进行中」。
- **年份约束修复（2026-11-07）**：真实复现「2026 年智能体记忆机制前沿进展」被规划成 `arXiv 2024–2026`；定位为 `plan.md` 只要求写时间范围、`system.md` 又有「优先近 2-3 年」偏好，模型据此自行放宽。已在 `plan.md` 增加「明确年份必须原样沿用」规则；2026-11-14 第 13 步真实运行复验通过（`topic_boundary` 锁定 2026-01-01～2026-12-31）。
- **第 10 步（2026-11-14）**：离线验证 17 项——六种组合的 `target_min/target_max/read_k/max_turns` 全部符合 `DESIGN.md` §2.2、非法组合与空主题报错、`survey` 拒绝清单导入、`_validate_collect` 在 `target_min=5/10` 下行为正确、`run_workflow` 传字符串等价 `deep/low`、phase 事件带 `mode/level/target_min`、`survey` 模式明确报「第 11 步」；真实 `--workflow --resume --mode deep --level low` 只跑 report（9,790 tokens），档位日志与 resume 行为正常。Web 侧 `POST /api/run` 的 `mode/level` 透传与非法组合 400 也已验证。
- **第 11 步（2026-11-14）**：离线 33 项——L0–L3 检索式展开（每级 ≤3 条）、版本号去重且保留首次命中级别、分页取到 `target_max` 上限、全级断网不抛异常而是 `partial` + `shortfall`、`run_survey` 端到端写出 `papers.jsonl`/`index.json` 且字段齐全、模型只参与 Plan。真实跑 `--mode survey --level low`「2026年智能体记忆机制前沿进展」：plan 5 个子问题，L0 三条检索式中两条超时、一条返回 13 篇即达到下限 10 篇（状态 `done`，全程 2,205 tokens），验证了「单条检索失败不终止、够数即停」。
- **第 14 步（2026-11-14）**：离线 26 项——指标口径（deep：13 候选 / 8 选中 / 3 处引用 → 召回 1.0、证据覆盖 1.0、引用真实率 2/3、tokens 与耗时）、survey partial 召回 0.6 且无覆盖/引用率、默认六种组合顺序与非法组合报错、3 条用例加载、`list_surveys`/`read_survey` 读 `survey-real`（13 篇）与非法 id 拒绝；本地 HTTP 实测 `GET /api/surveys`、`GET /api/survey`（13 篇）、`GET /api/file?name=survey`（`attachment` + JSONL）、`POST /api/run` 在 survey 模式带清单时返回 400。真实 `--eval --eval-combos survey/low,survey/mid,survey/high` 三用例 9 次全部 `done`：low 15 篇/9.2s、mid 100 篇/10–33s、high 300–500 篇/46–243s（`code-agent-tools` 的 low 因 arXiv 抖动耗 471s），每轮 tokens 1,636–2,108、召回均为 1.0；记录与对比表在 `eval/results/20261114_150927-*`。浏览器实测（端口 8012）：survey 模式只有「规划/检索」2 张阶段卡、deep 为 4 张；`清单` 页列出 `survey-real` 的 13 篇清单，查看/导出正常；Web 端真实跑 survey/low（会话 `web-step14`，15 篇）后自动切到清单详情，报告页显示「仅搜集模式不产出报告」；用 `partial-demo` 会话验证清单行「partial · 缺 5」、`partial` 徽章与「候选池未达档位下限」横幅。deep 三档未在矩阵中实跑：单次 deep/low 约 53 万 tokens，mid/high 更高，留待有预算时用 `--eval-combos deep/low` 等命令补齐。
- **第 13 步（2026-11-14）**：离线 10 项——两份清单并集按 arXiv ID 去重（`2501.00004v2` 归一为 `2501.00004`）、`matched_queries`/`from_surveys` 合并、单份导入、并集低于下限标 `partial`（缺口 8）、未知清单/非法状态/超 3 份报错、`resolve` 拒绝 survey 模式、导入模式零检索（把 `run_ladder` 换成抛异常的桩）且 `partial` 与 `candidate_source` 落盘、真实 `survey-real` 清单可读。真实跑 `--from-survey sv_20261114_140755_6ed0`（deep/low，「2026年智能体记忆机制前沿进展」）：候选 13 篇全部来自清单、检索调用 0 次；选中 8 篇、28 条证据全部 `fulltext` 且 `read_round` 全为 1（第 12 步把 `READ_TURNS` 6→8 + 「先提交已有证据卡」的调整生效，不再每篇读两遍），报告 8,814 字、引用自检一次通过；tokens plan 2,067 / outline 16,274 / report 19,157，整轮 531,475（比第 12 步 deep/low 的 747,864 降 29%）。`plan.json` 写入 `candidate_source`：`type=survey`、`survey_ids`、`count=13`、`status=imported`、`sources`。
- **第 12 步（2026-11-14）**：离线 21 项——Top-K 选择确定性与排序/截断、逐篇精读上下文隔离（每篇只看到自己的 arXiv 编号）、`source` 与 `read_round` 由调度注入并覆盖模型自填值、只读摘要归 `abstract`、无证据归 `failed`、`validate_citations` 拒绝引用摘要级证据、旧数据缺省 `fulltext` 仍兼容、`_validate_collect` 按全文论文数计下限。真实跑 `--mode deep --level low`「LLM agent memory mechanisms」：plan 2 子问题→候选 15 篇→选中 8 篇→32 条全文证据（8 篇 × 4 条，零摘要级）→报告 9,451 字、32/32 引用全部可回溯、自检 0 问题；阶段 tokens：plan 2,036 / outline 16,025 / report 22,206，整轮 747,864，耗时约 6.5 分钟。产物齐全：`candidates.jsonl` / `selected.json`（带 `score`）/ `evidence.jsonl`（带 `source`、`read_round`）。首轮每篇都用满 6 轮读取才提交证据，导致全部走第二遍（`read_round` 恒为 2）；已把单篇轮数上限提到 8，并在 `read.md` 要求「先提交已有证据卡再补读」。

## 八、已知限制与坑

1. **GitHub 推送时好时坏**：2026-11-05 上午 TCP 可达但 TLS 握手失败（curl 退出码 35），同日下午已恢复正常推送。若再遇到 `Failed to connect to github.com port 443`，先 `git push` 重试，别急着查凭据。
2. **长输出阶段容易超时**：report 一次要生成 7K+ completion tokens，默认 `LLM_TIMEOUT=120` 仍可能撞 read timeout。跑 `--workflow` 前建议设 `LLM_TIMEOUT=300`。
3. **PDF 下载偶发失败**：2026-11-05 实测 7 篇全部成功，第 12 步 8 篇也全部成功；失败时 `read_paper` 返回结构化错误，模型按摘要写卡，由调度把该卡标成 `abstract`（不可被报告引用），整篇完全无产出才算精读失败。
4. **GitHub 仓库是 public**，旧 key 已禁用更换；新 key 只在本地 `.env`。
5. **缺少提交到仓库的自动化测试**：目前的验证脚本是临时的（写在 `%TEMP%`），删掉即失。第 9 步应把 golden set 与工具测试固化到 `tests/`。
6. **笔记库按会话隔离**，没有跨会话的长期文献库；同一篇论文重复精读会产生重复笔记。
7. **压缩摘要可能丢细节**：摘要由同一个模型生成，长会话多次压缩后早期实验数字可能失真，重要结论应尽早写入 `notes.jsonl`。
8. **无上下文长度硬校验**：阈值默认 30000 tokens，按模型实际窗口需调（`LITAGENT_COMPACT_THRESHOLD`）。
9. **工作流没有接入 session/compaction**：四个阶段各自独立统计用量，`--workflow` 不写 `session.jsonl`，也不能 `--export`；另外 `--workflow` 新跑会覆盖上一轮的四个产物文件。
10. **collect 阶段仍然是 token 大头**：第 8 步单循环跑满 10 轮用了 23.5 万 tokens；第 12 步改成逐篇隔离后，deep/low 整轮 74.8 万（8 篇 PDF 正文各自进上下文，且首轮读满 6 轮才提交证据、每篇多烧一遍）。若还要降本，下一步是做“页级摘要后再读”或按页丢弃已读正文，而不是继续调提示词。
11. **Web 端是单任务串行**：`JobManager` 同时只允许一个工作流，因为 `LITAGENT_SESSION` 是进程级环境变量，并发跑不同会话会互相串目录；页面刷新后靠内存中的 job 回放事件，服务重启则历史任务不可再查（产物仍在磁盘，可切会话读取）。
12. **Web 端默认放宽读超时**：`serve()` 用 `setdefault("LLM_TIMEOUT", "300")`，避免报告阶段撞默认超时；`.env` 显式设置可覆盖。
13. **代理环境变量会让 LLM 调用瞬间失败**：2026-11-07 某次 Web 实例继承了不可用的代理配置，collect 的第一次 LLM 调用就 `ProxyError`（重试 3 次后 `LLMError`），任务随即结束。同一台机器新开进程 `requests.utils.getproxies()` 为空、直连 `open.bigmodel.cn` 返回 200。处理办法：在干净 shell 重启服务；必要时清理 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`。
14. **`resume` 会复用旧 `plan.json`**：改了主题或 `plan.md` 之后，必须取消「复用已落盘产物」或删除 `workspace/<session>/workflow/plan.json`，否则规划阶段直接跳过，旧边界会一直沿用。
15. **界面状态 ≠ 任务存活**：服务重启会丢掉内存里的 job，旧任务的产物仍在磁盘；排查时先看 `GET /api/status` 的 `done/error/stages`，不要只看阶段卡片。
16. **survey 的检索质量取决于 arXiv 可用性**：真实一次 L0 三条检索式中两条超时，属于限速/网络抖动。当前策略是记录错误后继续，篇数够 `target_min` 仍算 `done`，否则 `partial` 并在阶段信息/CLI 里显示缺口；失败原因保留在 `surveys/index.json` 的 `errors`。
17. **survey 目前忽略 `--resume`**：清单是只读快照，重跑会生成新的 `survey_id` 目录；要复用旧清单等第 13 步的清单导入。
18. **deep 的 `resume` 会复用 `candidates.jsonl` / `selected.json`**：改了检索式或换了主题后要一起删掉，否则会继续精读上一轮的 Top-K；只删 `evidence.jsonl` 时仍会复用候选集。
19. **精读的证据工具会吞掉模型的额外参数**：`submit_evidence` 的 handler 带 `**_ignored`，因为 `source` / `read_round` 由调度注入；模型若自填这两个字段会被静默覆盖，不要指望它自己标注证据级别。
20. **`--from-survey` 会吞掉后面的主题**：`nargs="+"` 会把标志后面的所有参数都当成清单 id；主题必须写在命令最前面（`python main.py "主题" --workflow --from-survey sv_a`）。已加 `sv_` 前缀校验，误用时会直接报错，而不是去查一个叫主题的清单。
21. **清单按会话隔离**：`surveys/` 位于 `workspace/<session>/`，导入时必须使用产出清单的同一 `LITAGENT_SESSION`，否则报「清单不存在」。
22. **导入模式不做补检**：并集小于档位下限时仍会精读已有篇目并出报告，只在 `result.partial`、collect 阶段事件、`plan.json` 与 `report.md` 末尾标注缺口；这是设计约定（可复现性优先于覆盖度），不是 bug。
23. **Web 前端是单文件内联脚本**：一处引号不匹配就会让整页 JS 失效（第 14 步真遇到一次），页面只剩静态骨架。改完 `index.html` 务必用浏览器控制台做一次冒烟，别只看 `py_compile` 通过。
24. **`--eval` 默认 18 次真实运行**：deep/mid/high 成本很高。先用 `--eval-cases` / `--eval-combos` 缩小范围；结果按时间戳落盘，不会互相覆盖。单个组合失败会记 `status=error` 并继续跑完矩阵。
25. **`/api/surveys` 只读当前会话**：清单按会话隔离，跨会话找清单要先切会话；`partial` 的缺口来自清单篇数与档位 `target_min` 的差，不代表还有“补检”这一步。

## 九、下一步（按建议顺序）

1. **成本优化（可选，优先级看实测）**：deep/low 整轮 53 万 tokens，仍主要在 PDF 正文；可做页级摘要、已读页丢弃、或降低 `read_paper` 的 `max_pages`。
2. **第 9 步评测**：golden set（10 个主题 + 期望覆盖的关键工作）、扩展指标（工具失败率、deep mid/high 补跑）、把 `%TEMP%` 里的验证脚本固化进 `tests/`；第 14 步的 `eval/cases`、`--eval` 与 Web 事件流可直接复用。
3. **Skills（原第 6 步后半）**：`litagent/prompt/skills/*/SKILL.md` + `load_skill` 工具做渐进式披露：主提示词只放索引，按需加载全文。参考 pi 的 `skills.ts`、`resource-loader.ts`。验收：开/关 skills 的产出可对比，引用格式统一。
4. **增强检索**：Semantic Scholar 引文滚雪球（注意限速，建议申请 key）、跨会话文献库、去重。
5. **工作流增强**（可选）：把 `--workflow` 的事件接进 `session.jsonl` 以支持 `--export`；精读阶段继续瘦身（丢弃已读页正文）；多主题运行时不覆盖旧产物。

## 十、给接手者的四句话

- 先读 `ROADMAP.md` 了解全貌，再读 `litagent/agent/loop.py`（所有能力的地基）。
- 改工具就改 `tools/`，别把业务塞进 `loop.py`；loop 只依赖 `client.chat` 和 `registry` 两个接口。
- 任何“让模型更聪明”的改动，优先改 `prompt/system.md`，而不是加代码分支。
- 要改工作流，先看 `litagent/workflow.py` 的四个 `_run_stage` 调用点；阶段产物全靠提交工具落盘，别改成解析模型文本。
- 界面卡住 / 状态可疑时，先 `GET /api/status` 看 `done` 与 `error`，再 `GET /api/events?job=<id>&from=0` 回放事件；服务端 `_stream` 会把缓存事件全量重发，不必重新跑任务。
