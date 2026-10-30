"""Bước 5: phân mục theo nội dung (và mục con cho Nghiên cứu)."""

from __future__ import annotations

from typing import Any

from .models import Source, Story
from .scorer import find_terms


def _best(keywords: dict[str, list[str]], order: list[str], text: str) -> str | None:
    """Mục có nhiều từ khóa khớp nhất; hòa thì theo thứ tự trong `order`."""
    best, best_hits = None, 0
    for cat in order:
        hits = len(find_terms(keywords.get(cat, []), text))
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def classify(story: Story, sources: dict[str, Source], settings: dict[str, Any]) -> None:
    """Gán category (và subcategory nếu là research) cho một sự kiện."""
    cfg = settings["categories"]
    primary = story.primary
    tags = " ".join(t for a in story.articles for t in a.extra.get("tags", []))
    text = "\n".join(f"{a.title}\n{a.summary}" for a in story.articles) + "\n" + tags

    category = cfg["by_source"].get(primary.source_id)
    if not category:
        category = _best(cfg["keywords"], cfg["order"], text)
    if not category:
        category = cfg.get("default_by_group", {}).get(sources[primary.source_id].group, "other")

    sub = None
    if category == "research":
        rs = cfg["research_subcategories"]
        sub = _best(rs["keywords"], rs["order"], text) or "other"

    story.category = category
    story.subcategory = sub


def classify_all(stories: list[Story], sources: dict[str, Source], settings: dict[str, Any]) -> None:
    for s in stories:
        classify(s, sources, settings)
