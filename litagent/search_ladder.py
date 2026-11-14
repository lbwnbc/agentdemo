"""逐级放宽检索（第 11 步）：L0 原式 → L1 拆词 → L2 同义词 → L3 分类浏览。

只用代码做确定性放宽，不调用模型：仅搜集模式的成本必须与篇数无关。
网络错误只记录、不终止；走完全部级别仍不足下限时返回 partial 与缺口。
"""
from __future__ import annotations

import re

from litagent.tools.arxiv import search_arxiv

LEVELS = ("L0", "L1", "L2", "L3")
MAX_QUERIES_PER_LEVEL = 3
PAGE_SIZE = 100
MAX_PAGES_PER_LEVEL = 5

STOPWORDS = {
    "a", "an", "the", "of", "for", "in", "on", "and", "or", "to", "with",
    "via", "using", "based", "how", "what", "are", "is", "do", "does",
}

# 小而可读的同义/上位词表；L2 只做替换，不做语义推断。
SYNONYMS = {
    "agent": ("agent", "assistant"),
    "agents": ("agents", "agent"),
    "memory": ("memory", "memories", "recall"),
    "memories": ("memories", "memory"),
    "llm": ("llm", "large language model"),
    "retrieval": ("retrieval", "retrieval-augmented"),
    "survey": ("survey", "review", "overview"),
    "benchmark": ("benchmark", "evaluation"),
    "evaluation": ("evaluation", "benchmark"),
    "poisoning": ("poisoning", "attack"),
    "compression": ("compression", "compaction"),
    "context": ("context", "long context"),
    "multimodal": ("multimodal", "vision language"),
    "reasoning": ("reasoning", "chain-of-thought"),
}

DEFAULT_CATEGORIES = ("cs.CL", "cs.AI", "cs.LG")


def normalise_id(arxiv_id):
    """去掉版本后缀并小写，用于跨检索式去重。"""
    value = str(arxiv_id or "").strip().lower()
    return re.sub(r"v\d+$", "", value)


def _unique(items):
    seen = set()
    ordered = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


def _terms(query):
    """从检索式里抽出关键词：去字段前缀、引号和布尔词。"""
    text = re.sub(r"\b(?:all|ti|abs|au|cat|co|jr|rn|id):", " ", str(query or ""))
    text = text.replace('"', " ")
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text)
    return [word for word in words if word.lower() not in STOPWORDS and len(word) > 1]


def level_queries(queries):
    """把 Plan 给出的检索式展开成 [(level, [query, ...]), ...]。"""
    base = _unique([str(query) for query in queries if str(query).strip()])[
        :MAX_QUERIES_PER_LEVEL
    ]
    levels = [("L0", base)]

    l1 = []
    l2 = []
    for query in base:
        terms = _terms(query)
        if not terms:
            continue
        l1.append(" OR ".join('all:"{}"'.format(term) for term in terms[:6]))
        expanded = []
        for term in terms[:3]:
            aliases = SYNONYMS.get(term.lower(), (term,))
            expanded.extend('all:"{}"'.format(alias) for alias in aliases[:3])
        l2.append(" OR ".join(_unique(expanded)))
    levels.append(("L1", _unique(l1)[:MAX_QUERIES_PER_LEVEL]))
    levels.append(("L2", _unique(l2)[:MAX_QUERIES_PER_LEVEL]))
    levels.append(("L3", ["cat:{}".format(name) for name in DEFAULT_CATEGORIES]))
    return levels


class PaperPool:
    """按 arXiv ID 去重的候选池，保留首次命中的级别与全部命中检索式。"""

    def __init__(self):
        self._records = {}
        self._order = []

    def __len__(self):
        return len(self._order)

    def add(self, entries, level, query_label):
        added = 0
        for entry in entries:
            key = normalise_id(entry.get("arxiv_id"))
            if not key:
                continue
            record = self._records.get(key)
            if record is None:
                published = str(entry.get("published") or "")
                record = {
                    "arxiv_id": key,
                    "title": entry.get("title") or "",
                    "authors": list(entry.get("authors") or []),
                    "year": int(published[:4]) if published[:4].isdigit() else None,
                    "abstract": entry.get("abstract") or "",
                    "categories": list(entry.get("categories") or []),
                    "url": "https://arxiv.org/abs/{}".format(key),
                    "matched_queries": [],
                    "query_level": level,
                }
                self._records[key] = record
                self._order.append(key)
                added += 1
            if query_label not in record["matched_queries"]:
                record["matched_queries"].append(query_label)
        return added

    def papers(self):
        return [self._records[key] for key in self._order]


def digest(papers, abstract_limit=1200):
    """代码归集：排序、截断摘要、编号，不逐条过模型。"""
    for rank, paper in enumerate(papers, 1):
        paper["rank"] = rank
        paper["abstract"] = " ".join(paper["abstract"].split())[:abstract_limit]
    return papers


def run_ladder(queries, target_min, target_max, search=None):
    """逐级检索直到达到上限或走完 L3，返回 (papers, provenance)。"""
    search = search or search_arxiv
    pool = PaperPool()
    provenance = {
        "status": "done",
        "count": 0,
        "shortfall": 0,
        "max_level": None,
        "queries": [],
        "levels": [],
        "errors": [],
    }

    for level, level_queries_ in level_queries(queries):
        if not level_queries_:
            continue
        stats = {"level": level, "queries": 0, "requests": 0, "added": 0}
        for query in level_queries_:
            if len(pool) >= target_max:
                break
            stats["queries"] += 1
            provenance["queries"].append({"level": level, "query": query})
            start = 0
            pages = 0
            while pages < MAX_PAGES_PER_LEVEL and len(pool) < target_max:
                wanted = min(PAGE_SIZE, target_max - len(pool))
                result = search(query, max_results=wanted, start=start)
                stats["requests"] += 1
                pages += 1
                if result.get("status") != "ok":
                    provenance["errors"].append(
                        {
                            "level": level,
                            "query": query,
                            "error": result.get("error", "检索失败"),
                            "retryable": bool(result.get("retryable", True)),
                        }
                    )
                    break
                entries = result.get("results") or []
                added = pool.add(entries, level, "{}:{}".format(level, query))
                stats["added"] += added
                start += len(entries)
                if not entries or start >= int(result.get("total") or 0):
                    break
        provenance["levels"].append(stats)
        if len(pool) >= target_max:
            break
        if len(pool) >= target_min:
            break

    provenance["max_level"] = provenance["levels"][-1]["level"] if provenance["levels"] else None
    provenance["count"] = len(pool)
    if len(pool) < target_min:
        provenance["status"] = "partial"
        provenance["shortfall"] = target_min - len(pool)
    return digest(pool.papers()), provenance
