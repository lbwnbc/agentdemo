"""Top-K 选择（第 12 步）：候选集 → 有序精读列表。

打分只用确定性信号（命中检索式数、兜底级别、年份、分类、与计划的关键词重合），
同一份候选集每次选出的结果完全一致，便于复现与评测。
"""
import re

PLAN_STOPWORDS = {
    "a", "an", "the", "of", "for", "in", "on", "and", "or", "to", "with",
    "via", "using", "based", "how", "what", "are", "is", "do", "does",
    "which", "can", "does", "literature", "paper", "papers",
}


def _words(text):
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", str(text or "").lower())
    return {word for word in words if word not in PLAN_STOPWORDS and len(word) > 1}


def plan_keywords(plan):
    words = set()
    for sub in (plan or {}).get("sub_questions") or []:
        words.update(_words(sub.get("question")))
        for query in sub.get("queries") or []:
            words.update(_words(query))
    return words


def plan_categories(plan):
    categories = set()
    for sub in (plan or {}).get("sub_questions") or []:
        for query in sub.get("queries") or []:
            categories.update(
                match.lower() for match in re.findall(r"cat:([A-Za-z][A-Za-z\-]+)", query)
            )
    return categories


def score_paper(paper, keywords, categories, latest_year):
    score = 0
    score += 3 * len(paper.get("matched_queries") or [])
    score += {"L0": 3, "L1": 2, "L2": 1}.get(paper.get("query_level"), 0)

    year = paper.get("year") or 0
    if latest_year and year:
        if year >= latest_year - 1:
            score += 3
        elif year == latest_year - 2:
            score += 2
        elif year == latest_year - 3:
            score += 1

    paper_categories = {str(item).lower() for item in paper.get("categories") or []}
    if categories and paper_categories & categories:
        score += 2

    title_hits = len(keywords & _words(paper.get("title")))
    abstract_hits = len(keywords & _words(paper.get("abstract")))
    score += 2 * title_hits + min(abstract_hits, 5)
    return score


def select_top_k(candidates, plan, k, latest_year=None):
    """返回按得分降序的候选（带 score 字段），最多 k 篇。"""
    k = int(k or 0)
    if k <= 0 or not candidates:
        return []
    keywords = plan_keywords(plan)
    categories = plan_categories(plan)
    years = [paper.get("year") for paper in candidates if paper.get("year")]
    latest = latest_year or (max(years) if years else None)

    scored = []
    for paper in candidates:
        indexed = dict(paper)
        indexed["score"] = score_paper(indexed, keywords, categories, latest)
        scored.append(indexed)
    scored.sort(
        key=lambda paper: (
            -paper["score"],
            -(paper.get("year") or 0),
            paper.get("rank") or 0,
        )
    )
    return scored[:k]
