"""Các lớp dữ liệu dùng chung: nguồn (Source), bài (Article), sự kiện (Story)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Mã bài arXiv dạng mới: 2610.12345 (bỏ phần phiên bản v1, v2…)
ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", re.IGNORECASE)


@dataclass
class Source:
    """Một nguồn tin, đọc từ config/sources.yaml."""

    id: str
    name: str
    homepage: str
    group: str
    role: str
    weight: float
    lang: str
    type: str
    url: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Source:
        return cls(
            id=d["id"],
            name=d["name"],
            homepage=d.get("homepage", ""),
            group=d["group"],
            role=d["role"],
            weight=float(d["weight"]),
            lang=d.get("lang", "en"),
            type=d["type"],
            url=d["url"],
            enabled=bool(d.get("enabled", True)),
            options=d.get("options") or {},
        )


def normalize_url(url: str, strip_params: list[str] | tuple[str, ...] = ()) -> str:
    """Chuẩn hóa URL để so trùng: https, bỏ www., bỏ #, bỏ tham số theo dõi, bỏ / cuối.

    Link arXiv /pdf/ và /html/ được đưa về /abs/ và bỏ số phiên bản.
    """
    url = (url or "").strip()
    if not url:
        return ""
    m = ARXIV_ID_RE.search(url)
    if m:
        return f"https://arxiv.org/abs/{m.group(1)}"
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    strip = {p.lower() for p in strip_params}
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in strip]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


def url_id(normalized_url: str) -> str:
    """Mã tin = sha1 của URL đã chuẩn hóa."""
    return hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()


@dataclass
class Article:
    """Một bài lấy từ một nguồn (chưa gộp với nguồn khác)."""

    url: str
    source_id: str
    title: str
    summary: str
    published_at: datetime  # luôn có múi giờ
    lang: str = "en"
    # Thông tin riêng theo nguồn: hn_points, hf_upvotes, hn_url, cve_id, tags…
    extra: dict[str, Any] = field(default_factory=dict)
    # Điền bởi filters.prepare(): URL chuẩn hóa, mã tin, các mã arXiv nhắc tới
    norm_url: str = ""
    id: str = ""
    arxiv_ids: set[str] = field(default_factory=set)


@dataclass
class Story:
    """Một sự kiện: bài gốc (primary) và các bài khác cùng đưa tin."""

    primary: Article
    others: list[Article] = field(default_factory=list)
    score: float = 0.0
    label: str | None = None  # "important" | "notable" | None (bị loại)
    category: str = "other"
    subcategory: str | None = None
    matched_keywords: list[str] = field(default_factory=list)
    # Ghi chú vì sao được chọn/loại, giúp chỉnh cấu hình
    reasons: list[str] = field(default_factory=list)
    # Điền bởi bước dịch
    title_vi: str = ""
    summary_vi: str = ""
    translated: bool = False
    translation_source: str | None = None  # "claude" | "google" | "original" | None

    @property
    def id(self) -> str:
        return self.primary.id

    @property
    def articles(self) -> list[Article]:
        return [self.primary, *self.others]

    @property
    def source_ids(self) -> set[str]:
        return {a.source_id for a in self.articles}

    def to_dict(self) -> dict[str, Any]:
        """Chuyển sang dict theo cấu trúc JSON ngày trong PLAN.md."""
        p = self.primary
        signals = {}
        for a in self.articles:
            for key in ("hn_points", "hf_upvotes"):
                if key in a.extra:
                    signals[key] = max(signals.get(key, 0), a.extra[key])
        return {
            "id": self.id,
            "url": p.url,
            "source_id": p.source_id,
            "published_at": p.published_at.isoformat(),
            "lang": p.lang,
            "title_orig": p.title,
            "summary_orig": p.summary,
            "title_vi": self.title_vi,
            "summary_vi": self.summary_vi,
            "translated": self.translated,
            "translation_source": self.translation_source,
            "also_covered_by": [
                # Với Hacker News, link tới trang thảo luận thay vì bài gốc (thường trùng với url ở trên)
                {"source_id": a.source_id, "url": a.extra.get("hn_url") or a.url, "title": a.title}
                for a in self.others
            ],
            "category": self.category,
            "subcategory": self.subcategory,
            "score": round(self.score, 2),
            "label": self.label,
            "matched_keywords": self.matched_keywords,
            "signals": signals,
            "reasons": self.reasons,
            "article_ids": [a.id for a in self.articles],
        }


@dataclass
class FetchResult:
    """Kết quả đọc một nguồn, dùng cho phần "Tình trạng nguồn"."""

    source_id: str
    ok: bool
    articles: list[Article] = field(default_factory=list)
    error: str | None = None
    note: str | None = None  # ví dụ: "khởi tạo sitemap", "bỏ 3 mục không có ngày"
    seconds: float = 0.0
    # Riêng nguồn sitemap: toàn bộ URL đã thấy, để lưu lại sau khi chạy xong
    sitemap_urls: set[str] | None = None

    def status_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "ok": self.ok,
            "items": len(self.articles),
            "error": self.error,
            "note": self.note,
        }
