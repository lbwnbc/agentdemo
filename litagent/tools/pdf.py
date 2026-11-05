"""PDF 工具：下载论文并按页精读（5b）。

整篇 PDF 一次性塞进上下文会挤爆预算，因此 read_paper 强制按页窗口读取，
返回体上限 max_chars，并提示下一页位置。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from litagent.tools.base import Tool
from litagent.workspace import session_dir

USER_AGENT = "litagent-demo/0.1 (+https://github.com/lbwnbc/agentdemo)"
DEFAULT_MAX_CHARS = 8000


def _safe_id(arxiv_id):
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(arxiv_id or "").strip())
    if not cleaned:
        raise ValueError("arxiv_id 不能为空")
    return cleaned


def _papers_dir():
    path = session_dir() / "papers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _paper_path(arxiv_id):
    return _papers_dir() / "{}.pdf".format(_safe_id(arxiv_id))


def _load_reader(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            raise RuntimeError("需要安装 pypdf 或 PyPDF2 才能解析 PDF")
    return PdfReader(str(path))


def fetch_pdf(arxiv_id, pdf_url=None, force=False):
    path = _paper_path(arxiv_id)
    if path.exists() and path.stat().st_size > 0 and not force:
        reader = _load_reader(path)
        return {
            "status": "ok",
            "arxiv_id": arxiv_id,
            "path": str(path),
            "pages": len(reader.pages),
            "cached": True,
        }

    url = pdf_url or "https://arxiv.org/pdf/{}".format(arxiv_id)
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("pdf_url 必须是 http/https 链接")

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    except requests.RequestException as exc:
        raise ValueError("下载失败: {}".format(exc))
    if response.status_code != 200:
        raise ValueError("下载失败: HTTP {}".format(response.status_code))
    content = response.content
    if not content.startswith(b"%PDF"):
        raise ValueError("下载内容不是 PDF（可能被反爬页面替代）")

    temp_path = path.with_suffix(".part")
    temp_path.write_bytes(content)
    temp_path.replace(path)

    reader = _load_reader(path)
    return {
        "status": "ok",
        "arxiv_id": arxiv_id,
        "path": str(path),
        "pages": len(reader.pages),
        "bytes": len(content),
        "cached": False,
    }


def read_paper(arxiv_id, start_page=1, max_pages=3, max_chars=DEFAULT_MAX_CHARS):
    path = _paper_path(arxiv_id)
    if not path.exists():
        return {
            "status": "error",
            "message": "本地没有这篇论文的 PDF，请先调用 fetch_pdf(arxiv_id='{}')".format(
                arxiv_id
            ),
        }

    max_pages = max(1, min(int(max_pages), 10))
    max_chars = max(1000, min(int(max_chars), 20000))
    reader = _load_reader(path)
    total_pages = len(reader.pages)
    begin = max(1, min(int(start_page), total_pages))
    end = min(total_pages, begin + max_pages - 1)

    chunks = []
    for page_number in range(begin, end + 1):
        text = reader.pages[page_number - 1].extract_text() or ""
        chunks.append("--- page {} ---\n{}".format(page_number, text.strip()))
    body = "\n\n".join(chunks)

    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars] + "\n[已截断：本次只返回前 {} 字符]".format(max_chars)

    return {
        "status": "ok",
        "arxiv_id": arxiv_id,
        "page_range": [begin, end],
        "total_pages": total_pages,
        "truncated": truncated,
        "text": body,
        "next_page": end + 1 if end < total_pages else None,
    }


FETCH_PDF_TOOL = Tool(
    name="fetch_pdf",
    description=(
        "下载 arXiv 论文 PDF 到本地工作区，返回页数。已有文件会直接复用；"
        "下载后必须用 read_paper 按页精读，不要整篇读入。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "arxiv_id": {"type": "string", "description": "arXiv 编号，如 2405.12345"},
            "pdf_url": {"type": "string", "description": "可选，直接指定 PDF 链接；默认按 arXiv 编号推导"},
            "force": {"type": "boolean", "description": "可选，为 true 时重新下载"},
        },
        "required": ["arxiv_id"],
    },
    handler=fetch_pdf,
)

READ_PAPER_TOOL = Tool(
    name="read_paper",
    description=(
        "按页读取已下载的论文正文，一次最多 10 页、约 8000 字符。"
        "先用较小页数确认目录和结论，需要细节时用 start_page 继续读。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "arxiv_id": {"type": "string", "description": "arXiv 编号"},
            "start_page": {"type": "integer", "description": "起始页，从 1 开始，默认 1"},
            "max_pages": {"type": "integer", "description": "本次读取页数，1-10，默认 3"},
            "max_chars": {"type": "integer", "description": "返回文本上限，1000-20000，默认 8000"},
        },
        "required": ["arxiv_id"],
    },
    handler=read_paper,
)

PDF_TOOLS = [FETCH_PDF_TOOL, READ_PAPER_TOOL]
