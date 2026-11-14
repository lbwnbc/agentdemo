"""本地 Web 交互界面：零依赖 HTTP 服务 + SSE 实时事件流。

浏览器端完成三件事：
- 填写研究主题与会话，启动 Plan → Collect → Synthesize 工作流；
- 四个阶段卡片与日志面板实时接收 on_event / on_phase 回调；
- 结束后在同一页面查看报告、大纲、证据库与计划，并下载产物。

不引入 FastAPI/Flask：ThreadingHTTPServer 负责路由，SSE 负责推送，
单任务串行执行，避免多个请求同时改环境变量与工作区产物。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from litagent.config import PROJECT_ROOT, _load_dotenv, load_settings
from litagent.llm.openai_compat import OpenAICompatClient
from litagent.run_spec import resolve
from litagent.survey import read_index
from litagent.tools import build_default_registry
from litagent.types import AgentEvent
from litagent.workflow import WorkflowError, run_workflow
from litagent.workspace import workspace_root

STATIC_DIR = Path(__file__).resolve().parent / "static"
PHASES = ("plan", "collect", "outline", "report")
SURVEY_PHASES = ("plan", "collect")
MODE_PHASES = {"deep": PHASES, "survey": SURVEY_PHASES}
ARTIFACTS = {
    "plan": ("plan.json", "application/json"),
    "evidence": ("evidence.jsonl", "application/x-ndjson"),
    "outline": ("outline.md", "text/markdown"),
    "report": ("report.md", "text/markdown"),
}
SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]")
SURVEY_ID_RE = re.compile(r"^sv_[A-Za-z0-9_]+$")


def safe_session(value):
    """会话名只允许字母数字与 _.-，防止跨目录写文件。"""
    name = SESSION_RE.sub("", str(value or "").strip())[:64]
    if not name or name in (".", ".."):
        return "default"
    return name


def workflow_paths(session):
    return workspace_root() / session / "workflow"


def _read_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _read_jsonl(path):
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _read_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def read_artifacts(session):
    """读取会话已落盘的工作流产物，用于页面直接预览历史结果。"""
    base = workflow_paths(session)
    plan = _read_json(base / "plan.json")
    evidence = _read_jsonl(base / "evidence.jsonl")
    outline = _read_text(base / "outline.md")
    report = _read_text(base / "report.md")
    if not any((plan, evidence, outline, report)):
        return None
    paths = {}
    for key, (filename, _) in ARTIFACTS.items():
        path = base / filename
        paths[key] = str(path) if path.exists() else ""
    return {
        "topic": "",
        "session": session,
        "plan": plan,
        "evidence": evidence,
        "outline": outline,
        "report": report,
        "issues": [],
        "usage": {},
        "stages": [],
        "paths": paths,
        "stats": {
            "tokens": 0,
            "steps": 0,
            "evidence": len(evidence),
            "issues": 0,
        },
        "source": "disk",
    }


def list_sessions():
    root = workspace_root()
    items = []
    if not root.exists():
        return items
    for path in root.iterdir():
        if not path.is_dir():
            continue
        base = path / "workflow"
        report = base / "report.md"
        evidence = base / "evidence.jsonl"
        count = 0
        if evidence.exists():
            count = sum(
                1 for line in evidence.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        items.append(
            {
                "name": path.name,
                "plan": (base / "plan.json").exists(),
                "outline": (base / "outline.md").exists(),
                "report": report.exists(),
                "evidence": count,
                "mtime": report.stat().st_mtime if report.exists() else path.stat().st_mtime,
            }
        )
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


def surveys_paths(session):
    return workspace_root() / session / "surveys"


def _read_jsonl_any(path):
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def list_surveys(session):
    """列出会话下的仅搜集清单（第 14 步）：读 surveys/index.json。"""
    index = read_index(surveys_paths(session))
    items = []
    for entry in index.get("surveys") or []:
        survey_id = entry.get("survey_id")
        if not survey_id or not SURVEY_ID_RE.match(str(survey_id)):
            continue
        items.append(
            {
                "survey_id": survey_id,
                "topic": entry.get("topic") or "",
                "mode": entry.get("mode") or "survey",
                "level": entry.get("level") or "",
                "count": entry.get("count") or 0,
                "status": entry.get("status") or "",
                "shortfall": entry.get("shortfall") or 0,
                "max_level": entry.get("max_level") or "",
                "created_at": entry.get("created_at") or "",
            }
        )
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def read_survey(session, survey_id):
    """读取单份清单的注册信息与论文列表。"""
    survey_id = str(survey_id or "").strip()
    if not SURVEY_ID_RE.match(survey_id):
        raise ValueError("清单 id 不合法")
    entry = None
    for item in list_surveys(session):
        if item["survey_id"] == survey_id:
            entry = item
            break
    if entry is None:
        raise ValueError("清单不存在：{}".format(survey_id))
    papers = _read_jsonl_any(surveys_paths(session) / survey_id / "papers.jsonl")
    return entry, papers


def _describe_event(event, tool_names):
    """把 Event 转成前端可渲染的小体积 JSON，避免把完整消息塞进 SSE。"""
    kind = event.type
    data = event.data or {}

    if kind == AgentEvent.AGENT_START:
        return {"kind": "agent_start", "messages": len(data.get("messages") or [])}

    if kind == AgentEvent.TURN_START:
        return {"kind": "turn", "step": data.get("step", 0)}

    if kind == AgentEvent.MESSAGE:
        message = data.get("message") or {}
        calls = [
            (call.get("function") or {}).get("name", "")
            for call in message.get("tool_calls") or []
        ]
        return {
            "kind": "message",
            "content": _clip(message.get("content"), 420),
            "tool_calls": calls,
            "usage": data.get("usage") or {},
        }

    if kind == AgentEvent.COMPACTED:
        return {
            "kind": "compacted",
            "before": data.get("before", 0),
            "after": data.get("after", 0),
        }

    if kind == AgentEvent.TOOL_START:
        call = data.get("call")
        tool_names[call.id] = call.name
        return {
            "kind": "tool_start",
            "tool": call.name,
            "arguments": _clip(call.arguments, 260),
        }

    if kind == AgentEvent.TOOL_END:
        result = data.get("result")
        return {
            "kind": "tool_end",
            "tool": tool_names.get(result.tool_call_id, "tool"),
            "error": bool(result.is_error),
            "content": _clip(result.content, 360),
        }

    if kind == AgentEvent.AGENT_END:
        return {
            "kind": "agent_end",
            "stop_reason": data.get("stop_reason", ""),
            "steps": data.get("steps", 0),
            "usage": data.get("usage") or {},
        }

    return {"kind": "unknown", "type": str(kind)}


class Job:
    """一次工作流执行：缓存全部事件，供迟到的浏览器从 0 回放。"""

    def __init__(self, topic, session, resume, spec):
        self.id = uuid.uuid4().hex[:10]
        self.topic = topic
        self.session = session
        self.resume = resume
        self.spec = spec
        self.events = []
        self.stages = {
            name: "pending" for name in MODE_PHASES.get(spec.mode, PHASES)
        }
        self.result = None
        self.error = None
        self.done = False
        self.created = time.time()
        self._cond = threading.Condition()

    def push(self, payload):
        with self._cond:
            payload["seq"] = len(self.events)
            self.events.append(payload)
            if payload.get("kind") == "phase":
                self.stages[payload["phase"]] = payload["status"]
            if payload.get("kind") == "finished":
                self.done = True
            self._cond.notify_all()

    def count(self):
        with self._cond:
            return len(self.events)

    def wait_events(self, index, timeout=10.0):
        with self._cond:
            if index >= len(self.events) and not self.done:
                self._cond.wait(timeout)
            return list(self.events[index:]), self.done

    def snapshot(self):
        return {
            "id": self.id,
            "topic": self.topic,
            "session": self.session,
            "resume": self.resume,
            "mode": self.spec.mode,
            "level": self.spec.level,
            "target_min": self.spec.target_min,
            "survey_ids": list(self.spec.survey_ids),
            "stages": dict(self.stages),
            "done": self.done,
            "error": self.error,
        }


class JobManager:
    """单任务管理器：同一时间只跑一个工作流。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}
        self._current = None

    def get(self, job_id):
        if not job_id:
            return None
        return self._jobs.get(job_id)

    def current(self):
        return self._current

    def start(self, topic, session, resume, spec):
        with self._lock:
            if self._current is not None and not self._current.done:
                raise RuntimeError("已有调研任务在运行，请等待完成")
            job = Job(topic, session, resume, spec)
            self._jobs[job.id] = job
            self._current = job
            thread = threading.Thread(target=self._run, args=(job,), daemon=True)
            thread.start()
            return job

    def _run(self, job):
        previous_session = os.environ.get("LITAGENT_SESSION")
        os.environ["LITAGENT_SESSION"] = job.session
        tool_names = {}
        current_phase = {"name": "plan"}
        active_phase = {"name": None}

        def on_event(event):
            payload = _describe_event(event, tool_names)
            payload["phase"] = current_phase["name"]
            job.push(payload)

        def on_phase(name, status, info):
            if status == "start":
                current_phase["name"] = name
                active_phase["name"] = name
            elif status in ("done", "failed", "degraded", "skipped"):
                if active_phase["name"] == name:
                    active_phase["name"] = None
            payload = {
                "kind": "phase",
                "phase": name,
                "status": status,
                "info": info or {},
            }
            job.push(payload)

        try:
            settings = load_settings()
            client = OpenAICompatClient(settings)
            result = run_workflow(
                client,
                build_default_registry(),
                job.spec,
                on_event=on_event,
                on_phase=on_phase,
                resume=job.resume,
            )
            job.result = {
                "topic": result.topic,
                "session": job.session,
                "mode": result.mode,
                "level": result.level,
                "target_min": result.target_min,
                "target_max": result.target_max,
                "read_k": result.read_k,
                "plan": result.plan,
                "survey": result.survey,
                "partial": result.partial,
                "evidence": result.evidence,
                "outline": result.outline,
                "report": result.report,
                "issues": result.issues,
                "usage": result.usage,
                "stages": result.stages,
                "paths": result.paths,
                "stats": {
                    "tokens": result.usage.get("total_tokens", 0),
                    "steps": sum(stage.get("steps", 0) for stage in result.stages),
                    "evidence": len(result.evidence),
                    "issues": len(result.issues),
                },
                "source": "run",
            }
            job.push({"kind": "finished", "ok": True, "stats": job.result["stats"]})
        except Exception as exc:
            if isinstance(exc, WorkflowError):
                job.error = str(exc)
            else:
                job.error = "{}: {}".format(type(exc).__name__, exc)
            # 阶段内部抛异常（如 LLM 网络失败）不会走 validator 的 failed 回调，
            # 这里补一条 phase failed，避免界面一直停在“进行中”
            if active_phase["name"]:
                job.push(
                    {
                        "kind": "phase",
                        "phase": active_phase["name"],
                        "status": "failed",
                        "info": {"problems": [job.error]},
                    }
                )
            job.push({"kind": "error", "message": job.error})
            job.push({"kind": "finished", "ok": False, "error": job.error})
        finally:
            if previous_session is None:
                os.environ.pop("LITAGENT_SESSION", None)
            else:
                os.environ["LITAGENT_SESSION"] = previous_session


class Handler(BaseHTTPRequestHandler):
    server_version = "LitAgentWeb/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def manager(self):
        return self.server.manager

    def log_message(self, fmt, *args):
        print("[web] {}".format(fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

        if route in ("/", "/index.html"):
            return self._send_static(STATIC_DIR / "index.html")
        if route == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if route == "/api/status":
            return self._send_json(self._status())
        if route == "/api/sessions":
            return self._send_json({"ok": True, "sessions": list_sessions()})
        if route == "/api/surveys":
            session = safe_session(
                query.get("session") or os.environ.get("LITAGENT_SESSION", "default")
            )
            return self._send_json(
                {"ok": True, "session": session, "surveys": list_surveys(session)}
            )
        if route == "/api/survey":
            session = safe_session(
                query.get("session") or os.environ.get("LITAGENT_SESSION", "default")
            )
            try:
                entry, papers = read_survey(session, query.get("id"))
            except ValueError as exc:
                return self._send_json({"ok": False, "error": str(exc)}, 404)
            return self._send_json(
                {"ok": True, "session": session, "survey": entry, "papers": papers}
            )
        if route == "/api/artifacts":
            session = safe_session(query.get("session"))
            return self._send_json(
                {"ok": True, "result": read_artifacts(session)}
            )
        if route == "/api/result":
            return self._result(query)
        if route == "/api/file":
            return self._download(query)
        if route == "/api/events":
            return self._stream(query)
        return self._send_json({"ok": False, "error": "接口不存在"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            return self._send_json({"ok": False, "error": "接口不存在"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._send_json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
        if not isinstance(payload, dict):
            return self._send_json({"ok": False, "error": "请求体必须是对象"}, 400)

        topic = " ".join(str(payload.get("topic") or "").split())
        if not topic:
            return self._send_json({"ok": False, "error": "研究主题不能为空"}, 400)
        if len(topic) > 2000:
            return self._send_json({"ok": False, "error": "研究主题过长（上限 2000 字）"}, 400)
        session = safe_session(payload.get("session"))
        resume = bool(payload.get("resume"))
        survey_ids = payload.get("survey_ids") or []
        if isinstance(survey_ids, str):
            survey_ids = [survey_ids]
        if not isinstance(survey_ids, list):
            return self._send_json({"ok": False, "error": "survey_ids 必须是数组"}, 400)
        survey_ids = [str(item).strip() for item in survey_ids if str(item).strip()]
        try:
            spec = resolve(
                topic,
                mode=payload.get("mode") or "deep",
                level=payload.get("level") or "low",
                survey_ids=survey_ids,
            )
        except ValueError as exc:
            return self._send_json({"ok": False, "error": str(exc)}, 400)
        try:
            job = self.manager.start(topic, session, resume, spec)
        except RuntimeError as exc:
            return self._send_json({"ok": False, "error": str(exc)}, 409)
        return self._send_json(
            {
                "ok": True,
                "job": {
                    "id": job.id,
                    "session": session,
                    "resume": resume,
                    "mode": job.spec.mode,
                    "level": job.spec.level,
                    "target_min": job.spec.target_min,
                    "survey_ids": list(job.spec.survey_ids),
                },
            }
        )

    # ---- 各接口实现 ----

    def _status(self):
        model = None
        api_key = True
        try:
            model = load_settings().model
        except RuntimeError:
            api_key = False
        job = self.manager.current()
        return {
            "ok": True,
            "api_key": api_key,
            "model": model,
            "session": os.environ.get("LITAGENT_SESSION", "default"),
            "running": bool(job and not job.done),
            "job": job.snapshot() if job else None,
        }

    def _result(self, query):
        job = self.manager.get(query.get("job"))
        if job is None:
            return self._send_json({"ok": False, "error": "任务不存在"}, 404)
        if not job.done:
            return self._send_json({"ok": False, "error": "任务仍在运行"}, 202)
        if job.error:
            return self._send_json({"ok": False, "error": job.error}, 500)
        return self._send_json({"ok": True, "result": job.result})

    def _download(self, query):
        session = safe_session(query.get("session"))
        name = query.get("name")
        if name == "survey":
            survey_id = str(query.get("id") or "").strip()
            if not SURVEY_ID_RE.match(survey_id):
                return self._send_json({"ok": False, "error": "清单 id 不合法"}, 404)
            path = surveys_paths(session) / survey_id / "papers.jsonl"
            if not path.exists():
                return self._send_json({"ok": False, "error": "清单不存在"}, 404)
            return self._send_file(
                path.read_bytes(),
                "application/x-ndjson",
                "{}-{}.jsonl".format(session, survey_id),
            )
        if name not in ARTIFACTS:
            return self._send_json({"ok": False, "error": "未知产物"}, 404)
        filename, content_type = ARTIFACTS[name]
        path = workflow_paths(session) / filename
        if not path.exists():
            return self._send_json({"ok": False, "error": "产物不存在，请先运行"}, 404)
        return self._send_file(
            path.read_bytes(), content_type, "{}-{}".format(session, filename)
        )

    def _send_file(self, body, content_type, filename):
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition", 'attachment; filename="{}"'.format(filename)
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, query):
        job = self.manager.get(query.get("job"))
        if job is None:
            return self._send_json({"ok": False, "error": "任务不存在"}, 404)
        try:
            index = int(query.get("from") or 0)
        except ValueError:
            index = 0

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        try:
            while True:
                events, done = job.wait_events(index, timeout=10.0)
                for payload in events:
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(("data: {}\n\n".format(data)).encode("utf-8"))
                index += len(events)
                if not events and not done:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if done and index >= job.count():
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path):
        if not path.exists():
            return self._send_json({"ok": False, "error": "页面缺失"}, 500)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class LitAgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.manager = JobManager()


def serve(host="127.0.0.1", port=8000):
    """启动本地服务；默认只监听回环地址。"""
    # 先读 .env，避免下面两个默认值覆盖用户在 .env 里的配置
    _load_dotenv()
    os.environ.setdefault("LITAGENT_WORKSPACE", str(PROJECT_ROOT / "workspace"))
    # 报告阶段输出长，读超时默认放宽到 300 秒（.env 里显式设置可覆盖）
    os.environ.setdefault("LLM_TIMEOUT", "300")

    server = LitAgentServer((host, port))
    print("LitAgent Web 已启动: http://{}:{}".format(host, port))
    print("工作区: {}".format(workspace_root()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务")
    finally:
        server.server_close()
