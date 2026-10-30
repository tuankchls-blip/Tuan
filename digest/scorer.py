"""Bước 4: chấm điểm quan trọng và gắn nhãn Quan trọng / Đáng chú ý.

Điểm = trọng số nguồn + số nguồn cùng đưa tin + tín hiệu cộng đồng
       + từ khóa ưu tiên − từ khóa loại trừ
Một số loại tin luôn được gắn nhãn Quan trọng (xem settings.yaml > scoring.always_important).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .models import Source, Story


def is_acronym(term: str) -> bool:
    """Từ viết tắt toàn chữ hoa (AI, LLM, GPT-4, cả LLMs) thì so khớp phân biệt hoa thường."""
    core = term[:-1] if term.endswith("s") and term[:-1].isupper() else term
    return core.isupper()


@lru_cache(maxsize=None)
def compile_term(term: str) -> re.Pattern[str]:
    """Biên dịch một từ khóa thành biểu thức tìm theo ranh giới từ.

    Mục bắt đầu bằng "re:" là biểu thức chính quy viết sẵn.
    """
    if term.startswith("re:"):
        return re.compile(term[3:], re.IGNORECASE)
    pattern = r"(?<!\w)" + re.escape(term).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.compile(pattern, 0 if is_acronym(term) else re.IGNORECASE)


def find_terms(terms: list[str], text: str) -> list[str]:
    """Trả về các từ khóa (theo thứ tự trong cấu hình) xuất hiện trong text."""
    return [t for t in terms if compile_term(t).search(text)]


def story_text(story: Story, primary_only: bool = False) -> str:
    """Ghép tiêu đề và tóm tắt gốc để so khớp từ khóa."""
    arts = [story.primary] if primary_only else story.articles
    return "\n".join(f"{a.title}\n{a.summary}" for a in arts)


def tier_points(value: int, tiers: dict[Any, Any]) -> int:
    """Điểm theo bậc: lấy bậc cao nhất mà value đạt tới."""
    points = 0
    for threshold, pts in sorted((int(k), int(v)) for k, v in tiers.items()):
        if value >= threshold:
            points = pts
    return points


def score_story(story: Story, sources: dict[str, Source], settings: dict[str, Any]) -> None:
    """Tính điểm, từ khóa khớp và nhãn cho một sự kiện (ghi thẳng vào story)."""
    sc = settings["scoring"]
    kw = settings["keywords"]
    primary_src = sources[story.primary.source_id]
    reasons: list[str] = []

    score = primary_src.weight
    reasons.append(f"nguồn {primary_src.id} +{primary_src.weight:g}")

    n_sources = len(story.source_ids)
    if n_sources > 1:
        bonus = sc["per_extra_source"] * (n_sources - 1)
        score += bonus
        reasons.append(f"{n_sources} nguồn cùng đưa tin +{bonus:g}")

    # Tín hiệu cộng đồng
    hn = max((a.extra.get("hn_points", 0) for a in story.articles), default=0)
    hf = max((a.extra.get("hf_upvotes", 0) for a in story.articles), default=0)
    for name, value, tiers in (
        ("Hacker News", hn, sc["community"]["hackernews_points"]),
        ("HF Papers", hf, sc["community"]["hf_upvotes"]),
    ):
        pts = tier_points(value, tiers)
        if pts:
            score += pts
            reasons.append(f"{name} {value} +{pts}")

    # Từ khóa ưu tiên: mỗi nhóm cộng một lần
    text = story_text(story)
    matched: list[str] = []
    for group in kw["priority"]:
        hits = find_terms(group["terms"], text)
        if hits:
            score += group["points"]
            matched.extend(h for h in hits if h not in matched)
            reasons.append(f"từ khóa {group['group']} +{group['points']}")

    # Từ khóa loại trừ: chỉ xét bài gốc, để một tiêu đề HN không kéo cả sự kiện xuống
    excluded = find_terms(kw["exclude"]["terms"], story_text(story, primary_only=True))
    if excluded:
        penalty = kw["exclude"]["penalty"] * len(excluded)
        score -= penalty
        reasons.append(f"loại trừ {', '.join(excluded)} -{penalty}")

    # Luật "luôn đưa vào" (không áp dụng khi dính từ khóa loại trừ)
    always: list[str] = []
    if not excluded:
        rules = sc["always_important"]
        for a in story.articles:
            s = sources[a.source_id]
            if s.role in rules["roles"] and s.weight >= rules["min_weight"]:
                always.append(f"công bố gốc từ {s.id}")
                break
        if story.source_ids & set(rules.get("source_ids", [])):
            always.append("danh mục CISA KEV")
        not_independent = set(sc.get("not_independent_roles", []))
        independent = {sid for sid in story.source_ids if sources[sid].role not in not_independent}
        if len(independent) >= sc["important_min_sources"]:
            always.append(f"{len(independent)} nguồn độc lập đưa tin")
        policy = rules.get("policy") or {}
        if find_terms(policy.get("subject", []), text) and find_terms(policy.get("action", []), text):
            always.append("luật/quy định về AI")

    # Bài preprint chưa được xác nhận
    unconfirmed = all(sources[a.source_id].role == "preprint" for a in story.articles)
    notable_min = sc.get("notable_by_group", {}).get(primary_src.group, sc["thresholds"]["notable"])

    community_only = all(sources[a.source_id].role == "community" for a in story.articles)

    if unconfirmed and sc["preprint"]["drop_unconfirmed"]:
        label = None
        reasons.append("preprint chưa được xác nhận")
    elif community_only and sc.get("community_only_requires_keyword") and not matched:
        label = None
        reasons.append("chỉ có nguồn cộng đồng, không khớp từ khóa ưu tiên")
    elif always:
        label = "important"
        reasons.extend(f"luôn đưa vào: {r}" for r in always)
    elif score >= sc["thresholds"]["important"]:
        label = "important"
    elif score >= notable_min:
        label = "notable"
    else:
        label = None
        reasons.append(f"dưới ngưỡng {notable_min:g}")

    story.score = score
    story.label = label
    story.matched_keywords = matched
    story.reasons = reasons


def score_all(
    stories: list[Story], sources: dict[str, Source], settings: dict[str, Any]
) -> tuple[list[Story], list[Story]]:
    """Chấm mọi sự kiện; trả về (giữ lại, bị loại). Danh sách giữ lại xếp theo nhãn rồi điểm."""
    for s in stories:
        score_story(s, sources, settings)
    kept = [s for s in stories if s.label]
    dropped = [s for s in stories if not s.label]
    kept.sort(key=lambda s: (s.label != "important", -s.score, -s.primary.published_at.timestamp()))
    return kept, dropped
