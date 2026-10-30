"""Bước 1: đọc RSS/Atom và API JSON công khai của mọi nguồn, song song.

Mỗi loại nguồn (type trong sources.yaml) có một hàm fetch_<type>. Các hàm này nhận
hàm `get(url, params)` để tải dữ liệu, nên test có thể thay bằng dữ liệu mẫu, không cần mạng.
Một nguồn lỗi chỉ được ghi vào FetchResult, không làm dừng chương trình.
"""

from __future__ import annotations

import calendar
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import feedparser
import requests

from .models import ARXIV_ID_RE, Article, FetchResult, Source

# get(url, params) -> nội dung (bytes)
Getter = Callable[[str, dict[str, Any] | None], bytes]


@dataclass
class FetchContext:
    """Thông tin chung cho một lần thu thập."""

    now: datetime  # thời điểm chạy (UTC)
    since: datetime  # chỉ cần tin sau mốc này (đầu khung gom sự kiện)
    until: datetime  # mốc chốt của bản tin
    max_items: int = 2000
    max_summary_chars: int = 1200
    # URL đã thấy của từng nguồn sitemap; None = chưa từng đọc
    sitemap_known: dict[str, set[str] | None] = field(default_factory=dict)


# ---------------------------------------------------------------- Tiện ích văn bản

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
ARXIV_PREFIX_RE = re.compile(r"^arXiv:\S+\s+Announce Type:\s*\S+\s*(Abstract:\s*)?", re.IGNORECASE)


def clean_text(raw: str | None, max_chars: int = 0) -> str:
    """Bỏ thẻ HTML, giải mã ký tự đặc biệt, gộp khoảng trắng, cắt độ dài ở ranh giới từ."""
    if not raw:
        return ""
    text = html.unescape(TAG_RE.sub(" ", raw))
    text = SPACE_RE.sub(" ", text).strip()
    if max_chars and len(text) > max_chars:
        cut = text[:max_chars].rsplit(" ", 1)[0]
        text = cut.rstrip(" ,;:.") + "…"
    return text


def find_arxiv_ids(*texts: str | None) -> set[str]:
    """Tìm các mã arXiv được nhắc tới (qua link) trong URL hoặc HTML."""
    ids: set[str] = set()
    for t in texts:
        if t:
            ids.update(ARXIV_ID_RE.findall(t))
    return ids


def parse_iso(value: str | None) -> datetime | None:
    """Đọc thời gian ISO 8601; thiếu múi giờ thì coi là UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clamp_future(dt: datetime, ctx: FetchContext) -> datetime:
    """Giờ đăng ở tương lai (feed ghi sai) được đưa về thời điểm chạy."""
    return min(dt, ctx.now)


def slug_to_title(url: str) -> str:
    """Tạo tiêu đề tạm từ đường dẫn: /news/claude-new-model -> "Claude new model"."""
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    words = re.sub(r"[-_]+", " ", slug).strip()
    return words[:1].upper() + words[1:]


# ---------------------------------------------------------------- Từng loại nguồn


def fetch_rss(source: Source, ctx: FetchContext, get: Getter) -> tuple[list[Article], str | None]:
    feed = feedparser.parse(get(source.url, None))
    if not feed.entries:
        problem = feed.get("bozo_exception")
        raise ValueError(f"feed không có mục nào{': ' + str(problem)[:80] if problem else ''}")
    skip_types = set(source.options.get("skip_announce_types", []))
    articles: list[Article] = []
    no_date = skipped = 0
    for e in feed.entries[: ctx.max_items]:
        if skip_types and e.get("arxiv_announce_type") in skip_types:
            skipped += 1
            continue
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        link = e.get("link", "")
        title = clean_text(e.get("title"))
        if not parsed:
            no_date += 1
            continue
        if not link or not title:
            continue
        published = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
        raw_summary = e.get("summary", "")
        content = " ".join(c.get("value", "") for c in e.get("content", []))
        summary = ARXIV_PREFIX_RE.sub("", clean_text(raw_summary))
        summary = clean_text(summary, ctx.max_summary_chars)
        a = Article(
            url=link,
            source_id=source.id,
            title=title,
            summary=summary,
            published_at=clamp_future(published, ctx),
            lang=source.lang,
            extra={"tags": [t.get("term") for t in e.get("tags", []) if t.get("term")]},
        )
        a.arxiv_ids = find_arxiv_ids(link, raw_summary, content)
        articles.append(a)
    notes = []
    if skipped:
        notes.append(f"bỏ {skipped} mục cập nhật bài cũ")
    if no_date:
        notes.append(f"bỏ {no_date} mục không có ngày")
    return articles, "; ".join(notes) or None


def fetch_hf_papers(source: Source, ctx: FetchContext, get: Getter) -> tuple[list[Article], str | None]:
    """HF Daily Papers: lấy danh sách của từng ngày (UTC) trong khung thời gian."""
    articles: list[Article] = []
    day = ctx.since.astimezone(timezone.utc).date()
    last = ctx.until.astimezone(timezone.utc).date()
    while day <= last:
        for entry in json.loads(get(source.url, {"date": day.isoformat()})):
            paper = entry.get("paper", {})
            pid = paper.get("id", "")
            title = clean_text(paper.get("title") or entry.get("title"))
            published = parse_iso(paper.get("submittedOnDailyAt") or entry.get("publishedAt"))
            if not pid or not title or not published:
                continue
            a = Article(
                url=f"https://huggingface.co/papers/{pid}",
                source_id=source.id,
                title=title,
                summary=clean_text(paper.get("summary") or entry.get("summary"), ctx.max_summary_chars),
                published_at=clamp_future(published, ctx),
                lang=source.lang,
                extra={"hf_upvotes": int(paper.get("upvotes") or 0)},
            )
            if paper.get("githubRepo"):
                a.extra["github_repo"] = paper["githubRepo"]
            a.arxiv_ids = find_arxiv_ids(f"arxiv.org/abs/{pid}")
            articles.append(a)
        day += timedelta(days=1)
    return articles, None


def fetch_hackernews(source: Source, ctx: FetchContext, get: Getter) -> tuple[list[Article], str | None]:
    """Hacker News qua API Algolia: bài đạt từ min_points điểm trong khung thời gian."""
    min_points = int(source.options.get("min_points", 200))
    params = {
        "tags": "story",
        "numericFilters": (
            f"points>={min_points},"
            f"created_at_i>={int(ctx.since.timestamp())},"
            f"created_at_i<{int(ctx.until.timestamp())}"
        ),
        "hitsPerPage": int(source.options.get("hits_per_page", 100)),
    }
    data = json.loads(get(source.url, params))
    articles: list[Article] = []
    for hit in data.get("hits", []):
        title = clean_text(hit.get("title"))
        published = parse_iso(hit.get("created_at"))
        if not title or not published:
            continue
        hn_url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        url = hit.get("url") or hn_url
        a = Article(
            url=url,
            source_id=source.id,
            title=title,
            summary=clean_text(hit.get("story_text"), ctx.max_summary_chars),
            published_at=clamp_future(published, ctx),
            lang=source.lang,
            extra={
                "hn_points": int(hit.get("points") or 0),
                "hn_comments": int(hit.get("num_comments") or 0),
                "hn_url": hn_url,
            },
        )
        a.arxiv_ids = find_arxiv_ids(url)
        articles.append(a)
    return articles, None


def fetch_cisa_kev(source: Source, ctx: FetchContext, get: Getter) -> tuple[list[Article], str | None]:
    """Danh mục CISA KEV: lỗ hổng mới được thêm (dateAdded) trong khung thời gian.

    dateAdded chỉ có ngày (giờ Mỹ), nên quy ước giờ đăng là 12:00 UTC của ngày đó.
    """
    data = json.loads(get(source.url, None))
    articles: list[Article] = []
    for v in data.get("vulnerabilities", []):
        try:
            added = date.fromisoformat(v.get("dateAdded", ""))
        except ValueError:
            continue
        published = datetime(added.year, added.month, added.day, 12, tzinfo=timezone.utc)
        if published < ctx.since - timedelta(days=1):
            continue
        cve = v.get("cveID", "")
        summary = v.get("shortDescription", "")
        if v.get("knownRansomwareCampaignUse") == "Known":
            summary += " Known to be used in ransomware campaigns."
        articles.append(
            Article(
                url=f"https://nvd.nist.gov/vuln/detail/{cve}",
                source_id=source.id,
                title=clean_text(f"{cve}: {v.get('vulnerabilityName', '')}"),
                summary=clean_text(summary, ctx.max_summary_chars),
                published_at=clamp_future(published, ctx),
                lang=source.lang,
                extra={
                    "cve_id": cve,
                    "vendor": v.get("vendorProject"),
                    "product": v.get("product"),
                    "due_date": v.get("dueDate"),
                },
            )
        )
    return articles, None


def fetch_crossref(source: Source, ctx: FetchContext, get: Getter) -> tuple[list[Article], str | None]:
    """Bài tạp chí qua API Crossref (dùng cho CACM), mới nhất trước."""
    params = {"sort": "created", "order": "desc", "rows": int(source.options.get("rows", 50))}
    items = json.loads(get(source.url, params))["message"]["items"]
    articles: list[Article] = []
    for it in items:
        title = clean_text((it.get("title") or [""])[0])
        published = parse_iso((it.get("created") or {}).get("date-time"))
        url = it.get("URL")
        if not title or not published or not url:
            continue
        articles.append(
            Article(
                url=url,
                source_id=source.id,
                title=title,
                summary=clean_text(it.get("abstract"), ctx.max_summary_chars),
                published_at=clamp_future(published, ctx),
                lang=source.lang,
                extra={"doi": it.get("DOI")},
            )
        )
    return articles, None


SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap(content: bytes, path_prefix: str) -> dict[str, datetime | None]:
    """Trả về {url: lastmod} cho các URL có đường dẫn bắt đầu bằng path_prefix."""
    root = ET.fromstring(content)
    prefix = path_prefix.rstrip("/")
    found: dict[str, datetime | None] = {}
    for node in root.iter(f"{SITEMAP_NS}url"):
        loc = (node.findtext(f"{SITEMAP_NS}loc") or "").strip()
        path = urlsplit(loc).path.rstrip("/")
        if not loc or not path.startswith(prefix + "/"):
            continue
        found[loc] = parse_iso(node.findtext(f"{SITEMAP_NS}lastmod"))
    return found


def fetch_sitemap(
    source: Source, ctx: FetchContext, get: Getter
) -> tuple[list[Article], str | None, set[str]]:
    """Nguồn không có RSS: tin mới = URL chưa từng thấy trong sitemap.

    Lần đầu chỉ ghi nhận URL hiện có, không đăng (tránh đăng hàng trăm bài cũ).
    lastmod là ngày sửa chứ không phải ngày đăng, nên chỉ dùng khi nó nằm trong khung thời gian.
    """
    found = parse_sitemap(get(source.url, None), source.options.get("path_prefix", "/"))
    if not found:
        raise ValueError("sitemap không có đường dẫn nào khớp path_prefix")
    known = ctx.sitemap_known.get(source.id)
    if known is None:
        return [], f"khởi tạo: ghi nhận {len(found)} đường dẫn, lần sau mới đăng tin mới", set(found)
    articles: list[Article] = []
    for url in sorted(set(found) - known):
        lastmod = found[url]
        published = lastmod if lastmod and lastmod >= ctx.since else ctx.now
        articles.append(
            Article(
                url=url,
                source_id=source.id,
                title=slug_to_title(url),
                summary="",
                published_at=clamp_future(published, ctx),
                lang=source.lang,
                extra={"title_from_slug": True},
            )
        )
    return articles, None, known | set(found)


FETCHERS: dict[str, Callable[..., Any]] = {
    "rss": fetch_rss,
    "hf_papers": fetch_hf_papers,
    "hackernews": fetch_hackernews,
    "cisa_kev": fetch_cisa_kev,
    "crossref": fetch_crossref,
    "sitemap": fetch_sitemap,
}


# ---------------------------------------------------------------- Chạy song song


def make_getter(user_agent: str, timeout: float) -> Getter:
    """Tạo hàm tải qua HTTP, có User-Agent và timeout; lỗi HTTP thành ngoại lệ."""

    def get(url: str, params: dict[str, Any] | None) -> bytes:
        r = requests.get(url, params=params, headers={"User-Agent": user_agent}, timeout=timeout)
        r.raise_for_status()
        return r.content

    return get


def short_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, requests.Timeout):
        return "quá thời gian chờ"
    return f"{type(exc).__name__}: {str(exc)[:150]}"


def fetch_source(source: Source, ctx: FetchContext, get: Getter) -> FetchResult:
    start = time.monotonic()
    try:
        fn = FETCHERS.get(source.type)
        if fn is None:
            raise ValueError(f"không hỗ trợ type '{source.type}'")
        out = fn(source, ctx, get)
        result = FetchResult(source.id, ok=True, articles=out[0], note=out[1])
        if source.type == "sitemap":
            result.sitemap_urls = out[2]
    except Exception as exc:  # một nguồn lỗi không làm dừng chương trình
        result = FetchResult(source.id, ok=False, error=short_error(exc))
    result.seconds = round(time.monotonic() - start, 2)
    return result


def fetch_all(
    sources: list[Source], ctx: FetchContext, get: Getter, max_workers: int = 8
) -> list[FetchResult]:
    """Đọc mọi nguồn song song; kết quả giữ đúng thứ tự trong sources.yaml."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda s: fetch_source(s, ctx, get), sources))
