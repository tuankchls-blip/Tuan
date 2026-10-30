"""Dữ liệu dùng chung cho test: cấu hình thật, nguồn giả lập, hàm tạo bài nhanh."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from digest import storage
from digest.fetcher import FetchContext
from digest.models import Article, Source

FIXTURES = Path(__file__).parent / "fixtures"

# Ngày bản tin dùng trong test: khung 24 giờ là [29/10 00:00 UTC, 30/10 00:00 UTC)
DAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)


def make_source(id: str, role: str, weight: float, group: str = "lab", type: str = "rss",
                lang: str = "en", **options) -> Source:
    return Source(id=id, name=id, homepage="", group=group, role=role, weight=weight,
                  lang=lang, type=type, url=f"https://{id}.example.com/feed", options=options)


@pytest.fixture
def settings():
    return storage.load_settings()


@pytest.fixture
def sources() -> dict[str, Source]:
    items = [
        make_source("lab", "origin", 3),
        make_source("lab2", "origin", 2, group="infra"),
        make_source("arxiv", "preprint", 2, group="research", skip_announce_types=["replace", "replace-cross"]),
        make_source("hf-papers", "community", 2, group="research", type="hf_papers"),
        make_source("hackernews", "community", 1, group="community", type="hackernews", min_points=200),
        make_source("expert", "expert", 2, group="expert"),
        make_source("press", "press", 2, group="press"),
        make_source("press2", "press", 2, group="press"),
        make_source("press3", "press", 3, group="press"),
        make_source("cisa-kev", "official", 3, group="security", type="cisa_kev"),
        make_source("cacm", "peer_reviewed", 3, group="research", type="crossref"),
        make_source("anthropic", "origin", 3, type="sitemap", path_prefix="/news/"),
        make_source("vnexpress-sohoa", "press", 1, group="vietnam", lang="vi"),
    ]
    return {s.id: s for s in items}


@pytest.fixture
def ctx() -> FetchContext:
    return FetchContext(now=NOW, since=SINCE, until=UNTIL)


def fixture_getter(name: str):
    """Hàm get giả: luôn trả về nội dung file mẫu, ghi lại tham số đã gọi."""
    calls = []

    def get(url, params):
        calls.append((url, params))
        return (FIXTURES / name).read_bytes()

    get.calls = calls
    return get


def art(source_id: str, title: str, url: str | None = None, summary: str = "",
        published: datetime | None = None, lang: str = "en", **extra) -> Article:
    """Tạo nhanh một bài đã qua bước prepare."""
    from digest.filters import prepare

    a = Article(url=url or f"https://{source_id}.example.com/{abs(hash(title))}", source_id=source_id,
                title=title, summary=summary,
                published_at=published or datetime(2026, 10, 29, 12, tzinfo=timezone.utc),
                lang=lang, extra=extra)
    return prepare([a], [])[0]
