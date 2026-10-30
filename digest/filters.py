"""Bước 2–3: lọc theo thời gian, bỏ tin đã đăng, bỏ trùng và gom bài cùng sự kiện."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from .models import Article, Source, Story, normalize_url, url_id

# Thứ tự ưu tiên khi chọn bài gốc trong một sự kiện (số nhỏ đứng trước)
ROLE_RANK = {"origin": 0, "peer_reviewed": 0, "official": 0, "preprint": 1, "press": 2, "expert": 3, "community": 4}


def daily_window(day: date, settings: dict[str, Any]) -> tuple[datetime, datetime]:
    """Khung giờ của bản tin ngày `day`: [day-1 lúc cutoff, day lúc cutoff) theo giờ VN."""
    tz = ZoneInfo(settings["timezone"])
    flt = settings["filter"]
    hh, mm = (int(x) for x in flt.get("cutoff_time", "07:00").split(":"))
    end = datetime.combine(day, time(hh, mm), tzinfo=tz)
    return end - timedelta(hours=flt["window_hours"]), end


def prepare(articles: list[Article], strip_params: list[str]) -> list[Article]:
    """Điền URL chuẩn hóa, mã tin và mã arXiv; bỏ bài trùng URL trong cùng một nguồn."""
    seen: set[tuple[str, str]] = set()
    out: list[Article] = []
    for a in articles:
        a.norm_url = normalize_url(a.url, strip_params)
        a.id = url_id(a.norm_url)
        if a.norm_url.startswith("https://arxiv.org/abs/"):
            a.arxiv_ids.add(a.norm_url.rsplit("/", 1)[-1])
        key = (a.source_id, a.norm_url)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def within(articles: list[Article], sources: dict[str, Source], since: datetime, until: datetime) -> list[Article]:
    """Giữ bài đăng trong [since, until).

    Bài preprint (arXiv) không lọc theo giờ: giờ trong feed arXiv là giờ công bố của
    ngày hôm sau, và feed chỉ chứa đợt công bố mới nhất.
    """
    return [
        a
        for a in articles
        if sources[a.source_id].role == "preprint" or since <= a.published_at < until
    ]


def drop_unconfirmed_preprints(
    articles: list[Article], sources: dict[str, Source], confirmed_by_roles: list[str]
) -> tuple[list[Article], int]:
    """Bỏ bài preprint không được nguồn nào thuộc confirmed_by_roles nhắc tới (qua mã arXiv).

    Làm trước khi gom sự kiện để không phải so tiêu đề của ~1.000 bài arXiv.
    """
    confirmed: set[str] = set()
    for a in articles:
        if sources[a.source_id].role in confirmed_by_roles:
            confirmed |= a.arxiv_ids
    kept = [a for a in articles if sources[a.source_id].role != "preprint" or a.arxiv_ids & confirmed]
    return kept, len(articles) - len(kept)


# ---------------------------------------------------------------- Gom sự kiện

PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
WORD_RE = re.compile(r"\w[\w.+-]*", re.UNICODE)


def title_key(title: str) -> str:
    return " ".join(PUNCT_RE.sub(" ", title.lower()).split())


def similar(a: str, b: str, threshold: float) -> bool:
    """So độ giống hai tiêu đề (đã chuẩn hóa) bằng difflib; kiểm tra nhanh trước cho đỡ tốn."""
    if not a or not b:
        return False
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= threshold and m.quick_ratio() >= threshold and m.ratio() >= threshold


def _stem(word: str) -> str:
    """Rút gọn đuôi tiếng Anh đơn giản: releases/releasing -> releas, weights -> weight."""
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def title_tokens(title: str, stopwords: set[str]) -> tuple[set[str], set[str]]:
    """Trả về (các từ đặc trưng, các từ trong đó là tên riêng — viết hoa hoặc chứa số)."""
    tokens: set[str] = set()
    proper: set[str] = set()
    for raw in WORD_RE.findall(title.replace("’", "'")):
        word = raw.strip(".-+").lower()
        if not word or word in stopwords or (len(word) < 2 and not word.isdigit()):
            continue
        tok = _stem(word)
        tokens.add(tok)
        if raw[0].isupper() or any(c.isdigit() for c in raw):
            proper.add(tok)
    return tokens, proper


class TokenMatcher:
    """So từ đặc trưng chung giữa các tiêu đề, có trọng số theo độ hiếm (IDF)."""

    def __init__(self, titles: list[str], settings: dict[str, Any]) -> None:
        dd = settings["dedup"]
        self.min_overlap = float(dd.get("token_overlap", 1.01))
        self.min_shared = int(dd.get("min_shared_tokens", 2))
        stop = {w.lower() for w in dd.get("stopwords", [])}
        self.tokens = [title_tokens(t, stop) for t in titles]
        df: dict[str, int] = {}
        for toks, _ in self.tokens:
            for t in toks:
                df[t] = df.get(t, 0) + 1
        n = len(titles)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}

    def match(self, i: int, j: int) -> bool:
        (ti, pi), (tj, pj) = self.tokens[i], self.tokens[j]
        shared = ti & tj
        if len(shared) < self.min_shared or not (shared & pi & pj):
            return False
        weight = lambda toks: sum(self.idf[t] for t in toks)  # noqa: E731
        smaller = min(weight(ti), weight(tj))
        return smaller > 0 and weight(shared) / smaller >= self.min_overlap


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        self.parent[self.find(i)] = self.find(j)


def cluster(articles: list[Article], sources: dict[str, Source], settings: dict[str, Any]) -> list[Story]:
    """Gộp các bài cùng sự kiện thành Story.

    Hai bài cùng sự kiện khi: cùng URL chuẩn hóa, cùng nhắc một mã arXiv,
    tiêu đề giống nhau theo difflib, hoặc (khác nguồn) chung đủ từ đặc trưng.
    Chỉ so tiêu đề của bài cùng ngôn ngữ.
    Bài gốc là bài có trọng số nguồn cao nhất, rồi theo vai trò, rồi đăng sớm nhất.
    """
    threshold = float(settings["dedup"]["title_similarity"])
    n = len(articles)
    uf = _UnionFind(n)
    first_by_key: dict[str, int] = {}
    for i, a in enumerate(articles):
        for key in [f"url:{a.norm_url}", *(f"arxiv:{x}" for x in a.arxiv_ids)]:
            if key in first_by_key:
                uf.union(i, first_by_key[key])
            else:
                first_by_key[key] = i

    keys = [title_key(a.title) for a in articles]
    tokens = TokenMatcher([a.title for a in articles], settings)
    for i in range(n):
        for j in range(i + 1, n):
            ai, aj = articles[i], articles[j]
            if ai.lang != aj.lang or uf.find(i) == uf.find(j):
                continue
            if similar(keys[i], keys[j], threshold) or (
                ai.source_id != aj.source_id and tokens.match(i, j)
            ):
                uf.union(i, j)

    groups: dict[int, list[Article]] = {}
    for i, a in enumerate(articles):
        groups.setdefault(uf.find(i), []).append(a)

    def rank(a: Article) -> tuple[float, int, datetime]:
        s = sources[a.source_id]
        return (-s.weight, ROLE_RANK.get(s.role, 9), a.published_at)

    stories = []
    for members in groups.values():
        members.sort(key=rank)
        stories.append(Story(primary=members[0], others=members[1:]))
    stories.sort(key=lambda s: s.primary.published_at, reverse=True)
    return stories


def select_new(
    stories: list[Story],
    sources: dict[str, Source],
    window_start: datetime,
    until: datetime,
    seen: dict[str, str],
    day: date,
) -> tuple[list[Story], int, int]:
    """Giữ sự kiện có ít nhất một bài (không phải preprint) đăng trong khung 24 giờ,
    và chưa có bài nào từng lên bản tin của ngày trước `day`.

    Trả về (danh sách giữ lại, số bị loại vì cũ, số bị loại vì đã đăng).
    """
    kept: list[Story] = []
    old = published_before = 0
    day_str = day.isoformat()
    for s in stories:
        timed = [a for a in s.articles if sources[a.source_id].role != "preprint"]
        if timed and not any(window_start <= a.published_at < until for a in timed):
            old += 1
            continue
        if any(seen.get(a.id, day_str) < day_str for a in s.articles):
            published_before += 1
            continue
        kept.append(s)
    return kept, old, published_before
