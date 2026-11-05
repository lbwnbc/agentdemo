"""arXiv 检索工具（5a）。

走官方 Atom API，无需 key。按官方建议对同一接口限速 3 秒/次，
结果缓存 1 小时，避免模型重复检索把配额和上下文都烧掉。
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

from litagent.net import DiskCache, HttpClient, RateLimiter
from litagent.tools.base import Tool

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "litagent-demo/0.1 (+https://github.com/lbwnbc/agentdemo)"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_client = None


def get_client():
    global _client
    if _client is None:
        cache_root = Path(
            os.environ.get(
                "LITAGENT_CACHE_DIR",
                str(Path.cwd() / "workspace" / "cache"),
            )
        )
        _client = HttpClient(
            cache=DiskCache(cache_root / "arxiv", ttl=3600),
            limiter=RateLimiter(3.0),
            timeout=30,
            retries=2,
            backoff=2.0,
        )
    return _client


def build_search_query(query, category=None):
    """把普通关键词或高级语法转成 arXiv 的 search_query 表达式。"""
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("query 不能为空")
    if ":" in query:
        expression = query
    else:
        terms = ['all:"{}"'.format(term) for term in query.split()]
        expression = " AND ".join(terms)
    if category:
        expression = "{} AND cat:{}".format(expression, category)
    return expression


def _clean(text):
    return " ".join((text or "").split())


def _parse_total(root):
    raw = root.findtext("opensearch:totalResults", default="0", namespaces=NS) or "0"
    try:
        return int(raw)
    except ValueError:
        return 0


def parse_arxiv_feed(xml_text):
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall("atom:entry", NS):
        raw_id = entry.findtext("atom:id", default="", namespaces=NS) or ""
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1] or raw_id
        authors = [
            _clean(author.findtext("atom:name", default="", namespaces=NS))
            for author in entry.findall("atom:author", NS)
        ]
        primary = entry.find("arxiv:primary_category", NS)
        pdf_url = None
        abs_url = None
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
            elif link.get("rel") == "alternate":
                abs_url = link.get("href")
        entries.append(
            {
                "arxiv_id": arxiv_id,
                "title": _clean(entry.findtext("atom:title", default="", namespaces=NS)),
                "abstract": _clean(entry.findtext("atom:summary", default="", namespaces=NS)),
                "authors": authors,
                "published": entry.findtext("atom:published", default="", namespaces=NS),
                "updated": entry.findtext("atom:updated", default="", namespaces=NS),
                "primary_category": primary.get("term") if primary is not None else None,
                "abs_url": abs_url or "https://arxiv.org/abs/{}".format(arxiv_id),
                "pdf_url": pdf_url or "https://arxiv.org/pdf/{}".format(arxiv_id),
                "doi": entry.findtext("arxiv:doi", default=None, namespaces=NS),
            }
        )
    return {"total": _parse_total(root), "entries": entries}


def search_arxiv(query, max_results=5, category=None, sort_by="relevance"):
    max_results = max(1, min(int(max_results), 20))
    params = {
        "search_query": build_search_query(query, category),
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    xml_text = get_client().get_text(API_URL, params=params, headers={"User-Agent": USER_AGENT})
    parsed = parse_arxiv_feed(xml_text)
    return {
        "status": "ok",
        "query": query,
        "total": parsed["total"],
        "returned": len(parsed["entries"]),
        "results": parsed["entries"],
    }


def get_arxiv_paper(arxiv_id):
    arxiv_id = str(arxiv_id or "").strip()
    if not arxiv_id:
        raise ValueError("arxiv_id 不能为空")
    params = {"id_list": arxiv_id, "max_results": 1}
    xml_text = get_client().get_text(API_URL, params=params, headers={"User-Agent": USER_AGENT})
    parsed = parse_arxiv_feed(xml_text)
    if not parsed["entries"]:
        return {"status": "not_found", "arxiv_id": arxiv_id}
    paper = parsed["entries"][0]
    paper["status"] = "ok"
    return paper


SEARCH_ARXIV_TOOL = Tool(
    name="search_arxiv",
    description=(
        "在 arXiv 检索论文，返回标题、作者、摘要、发布时间、分类和 PDF 链接。"
        "先用它做主题初筛，再按需精读。每次请求有 3 秒限速，避免短时间大量调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": '检索词，如 "agent memory"；也支持 arXiv 高级语法，如 au:smith AND cat:cs.AI',
            },
            "max_results": {
                "type": "integer",
                "description": "返回条数，1-20，默认 5",
            },
            "category": {
                "type": "string",
                "description": "限定 arXiv 分类，如 cs.AI、cs.CL、cs.LG",
            },
            "sort_by": {
                "type": "string",
                "description": "排序方式：relevance（相关度）、submittedDate（提交时间）、lastUpdatedDate（更新时间）",
                "enum": ["relevance", "submittedDate", "lastUpdatedDate"],
            },
        },
        "required": ["query"],
    },
    handler=search_arxiv,
)

GET_ARXIV_PAPER_TOOL = Tool(
    name="get_arxiv_paper",
    description="按 arXiv 编号获取单篇论文的元数据与摘要，编号形如 2405.12345 或 2405.12345v2。",
    parameters={
        "type": "object",
        "properties": {
            "arxiv_id": {"type": "string", "description": "arXiv 编号，如 2405.12345"},
        },
        "required": ["arxiv_id"],
    },
    handler=get_arxiv_paper,
)


ARXIV_TOOLS = [SEARCH_ARXIV_TOOL, GET_ARXIV_PAPER_TOOL]
