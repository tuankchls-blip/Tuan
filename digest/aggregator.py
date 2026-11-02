"""Bản tổng hợp tuần → tháng → quý → năm.

- Tin nổi bật: mỗi cấp chọn từ cấp ngay dưới (tuần ← tin Quan trọng của các bản ngày,
  tháng ← các bản tuần, quý ← các bản tháng, năm ← các bản quý). Cấp dưới luôn được dựng lại
  từ dữ liệu ngày để không dùng nhầm bản cũ (ví dụ bản tuần tạo khi tuần chưa hết).
- Số liệu thống kê luôn tính lại từ dữ liệu ngày, nên một tuần vắt qua hai tháng không làm lệch số.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .filters import TokenMatcher, similar, title_key
from .storage import Storage

KINDS = ("weekly", "monthly", "quarterly", "yearly")


# ---------------------------------------------------------------- Kỳ (tuần ISO, tháng, quý, năm)


@dataclass(frozen=True)
class Period:
    kind: str
    key: str  # 2026-W44, 2026-10, 2026-Q4, 2026
    start: date
    end: date  # tính cả ngày cuối

    @property
    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def previous(self) -> Period:
        return period_for(self.kind, self.start - timedelta(days=1))

    def children(self) -> list[Period]:
        """Các kỳ cấp ngay dưới có giao với kỳ này (tháng → các tuần chạm vào tháng)."""
        child_kind = {"monthly": "weekly", "quarterly": "monthly", "yearly": "quarterly"}.get(self.kind)
        return sub_periods(self, child_kind) if child_kind else []


def _month_end(year: int, month: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def period_for(kind: str, day: date) -> Period:
    """Kỳ loại `kind` chứa ngày `day`."""
    if kind == "weekly":
        iso = day.isocalendar()  # năm ISO có thể khác năm dương lịch (2027-01-03 thuộc 2026-W53)
        start = date.fromisocalendar(iso.year, iso.week, 1)
        return Period(kind, f"{iso.year}-W{iso.week:02d}", start, start + timedelta(days=6))
    if kind == "monthly":
        return Period(kind, f"{day.year}-{day.month:02d}", date(day.year, day.month, 1),
                      _month_end(day.year, day.month))
    if kind == "quarterly":
        q = (day.month - 1) // 3 + 1
        first_month = 3 * (q - 1) + 1
        return Period(kind, f"{day.year}-Q{q}", date(day.year, first_month, 1),
                      _month_end(day.year, first_month + 2))
    if kind == "yearly":
        return Period(kind, str(day.year), date(day.year, 1, 1), date(day.year, 12, 31))
    raise ValueError(f"loại bản tổng hợp không hợp lệ: {kind}")


def last_completed(kind: str, today: date) -> Period:
    """Kỳ vừa kết thúc trước ngày `today` (dùng cho lịch tự động)."""
    return period_for(kind, period_for(kind, today).start - timedelta(days=1))


def sub_periods(period: Period, kind: str) -> list[Period]:
    """Các kỳ loại `kind` giao với `period`, theo thứ tự thời gian."""
    out: list[Period] = []
    day = period.start
    while day <= period.end:
        p = period_for(kind, day)
        out.append(p)
        day = p.end + timedelta(days=1)
    return out


def due_kinds(today: date) -> list[str]:
    """Các bản tổng hợp đến hạn vào ngày `today` (sáng Thứ Hai, ngày 1, đầu quý, đầu năm)."""
    kinds = []
    if today.weekday() == 0:
        kinds.append("weekly")
    if today.day == 1:
        kinds.append("monthly")
        if today.month in (1, 4, 7, 10):
            kinds.append("quarterly")
        if today.month == 1:
            kinds.append("yearly")
    return kinds


# ---------------------------------------------------------------- Tin trong bản tổng hợp


def make_entry(day: date, s: dict[str, Any]) -> dict[str, Any]:
    """Một tin trong bản tổng hợp: chép những trường cần hiển thị từ tin của bản ngày."""
    others = {o["source_id"] for o in s.get("also_covered_by", [])} - {s["source_id"]}
    return {
        "day": day.isoformat(),
        "id": s["id"],
        "url": s["url"],
        "source_id": s["source_id"],
        "lang": s.get("lang", "en"),
        "title_orig": s["title_orig"],
        "title_vi": s.get("title_vi", ""),
        "summary_vi": s.get("summary_vi", ""),
        "translated": s.get("translated", False),
        "category": s.get("category", "other"),
        "subcategory": s.get("subcategory"),
        "label": s.get("label"),
        "score": s.get("score", 0),
        "n_sources": 1 + len(others),
        "matched_keywords": s.get("matched_keywords", []),
    }


def rank_key(e: dict[str, Any]) -> tuple:
    """Xếp hạng tin nổi bật: Quan trọng trước, điểm cao, nhiều nguồn, rồi theo ngày."""
    return (e["label"] != "important", -e["score"], -e["n_sources"], e["day"], e["id"])


def pick_highlights(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for e in candidates:
        if e["id"] not in best or rank_key(e) < rank_key(best[e["id"]]):
            best[e["id"]] = e
    return sorted(best.values(), key=rank_key)[:limit]


# ---------------------------------------------------------------- Dựng bản tổng hợp


class Aggregator:
    def __init__(self, storage: Storage, settings: dict[str, Any], now: datetime | None = None) -> None:
        self.storage = storage
        self.settings = settings
        self.cfg = settings["summaries"]
        self.tz = ZoneInfo(settings["timezone"])
        self.now = now or datetime.now(timezone.utc)
        self._daily: dict[date, dict[str, Any] | None] = {}
        self._highlights: dict[str, list[dict[str, Any]]] = {}

    # ---- Dữ liệu ngày

    def daily(self, day: date) -> dict[str, Any] | None:
        if day not in self._daily:
            self._daily[day] = self.storage.load_daily(day)
        return self._daily[day]

    def entries(self, period: Period) -> list[dict[str, Any]]:
        """Mọi tin của các bản ngày trong kỳ."""
        out = []
        for day in period.days:
            data = self.daily(day)
            if data:
                out.extend(make_entry(day, s) for s in data.get("stories", []))
        return out

    def days_with_data(self, period: Period) -> list[str]:
        return [d.isoformat() for d in period.days if self.daily(d)]

    def days_expected(self, period: Period) -> list[str]:
        """Các ngày lẽ ra có bản tin: từ ngày có bản tin đầu tiên của dự án đến hôm nay."""
        all_days = self.storage.list_days()
        if not all_days:
            return []
        today = self.now.astimezone(self.tz).date()
        return [d.isoformat() for d in period.days if all_days[0] <= d <= today]

    # ---- Tin nổi bật

    def highlights(self, period: Period) -> list[dict[str, Any]]:
        cache_key = f"{period.kind}:{period.key}"
        if cache_key not in self._highlights:
            self._highlights[cache_key] = self._pick(period)
        return self._highlights[cache_key]

    def _pick(self, period: Period) -> list[dict[str, Any]]:
        limit = self.cfg[period.kind]["max_highlights"]
        if period.kind == "weekly":
            candidates = [e for e in self.entries(period) if e["label"] == "important"]
        else:
            candidates = [
                h for child in period.children() for h in self.highlights(child)
                if period.contains(date.fromisoformat(h["day"]))
            ]
        return pick_highlights(candidates, limit)

    # ---- Số liệu

    def stats(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        top_n = self.cfg.get("top_n", 15)
        order = self.settings["categories"]["order"]
        cats = Counter(e["category"] for e in entries)
        keywords = Counter(k for e in entries for k in dict.fromkeys(e["matched_keywords"]))
        return {
            "stories": len(entries),
            "labels": {"important": sum(e["label"] == "important" for e in entries),
                       "notable": sum(e["label"] == "notable" for e in entries)},
            "categories": {c: cats[c] for c in order if cats[c]},
            "sources": dict(Counter(e["source_id"] for e in entries).most_common(top_n)),
            "keywords": dict(keywords.most_common(top_n)),
        }

    def topic_counts(self, entries: list[dict[str, Any]]) -> Counter:
        """Số tin theo chủ đề = nhóm từ khóa ưu tiên trong settings.yaml."""
        counts: Counter = Counter()
        for group in self.settings["keywords"]["priority"]:
            terms = set(group["terms"])
            counts[group["group"]] = sum(bool(terms & set(e["matched_keywords"])) for e in entries)
        return counts

    def topics(self, entries: list[dict[str, Any]], prev_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Chủ đề tăng/giảm so với kỳ trước, xếp theo mức thay đổi."""
        now, before = self.topic_counts(entries), self.topic_counts(prev_entries)
        rows = [{"topic": t, "count": now[t], "previous": before[t], "delta": now[t] - before[t]}
                for t in now if now[t] or before[t]]
        return sorted(rows, key=lambda r: (-r["delta"], -r["count"], r["topic"]))

    def multi_day_events(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sự kiện được đưa tin nhiều ngày: gộp tin khác ngày có tiêu đề cùng sự kiện."""
        min_days = self.cfg["weekly"].get("multi_day_min_days", 2)
        en = [e for e in entries if e["lang"] == "en"]
        if len(en) < 2:
            return []
        matcher = TokenMatcher([e["title_orig"] for e in en], self.settings)
        keys = [title_key(e["title_orig"]) for e in en]
        threshold = float(self.settings["dedup"]["title_similarity"])
        parent = list(range(len(en)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(en)):
            for j in range(i + 1, len(en)):
                if en[i]["day"] != en[j]["day"] and find(i) != find(j):
                    if similar(keys[i], keys[j], threshold) or matcher.match(i, j):
                        parent[find(i)] = find(j)
        groups: dict[int, list[dict[str, Any]]] = {}
        for i, e in enumerate(en):
            groups.setdefault(find(i), []).append(e)
        events = []
        for members in groups.values():
            days = sorted({e["day"] for e in members})
            if len(days) >= min_days:
                members.sort(key=lambda e: e["day"])
                lead = min(members, key=rank_key)
                events.append({"title_orig": lead["title_orig"], "title_vi": lead["title_vi"],
                               "translated": lead["translated"], "days": days, "stories": members})
        return sorted(events, key=lambda ev: (-len(ev["days"]), ev["days"][0]))

    def series(self, period: Period, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Số tin theo kỳ con (tháng → tuần, quý và năm → tháng) để xem xu hướng."""
        sub_kind = "weekly" if period.kind == "monthly" else "monthly"
        rows = []
        for sub in sub_periods(period, sub_kind):
            part = [e for e in entries if sub.contains(date.fromisoformat(e["day"]))]
            cats = Counter(e["category"] for e in part)
            rows.append({"key": sub.key, "start": sub.start.isoformat(), "end": sub.end.isoformat(),
                         "stories": len(part), "important": sum(e["label"] == "important" for e in part),
                         "categories": dict(cats), "topics": dict(self.topic_counts(part))})
        return rows

    # ---- Ghép lại

    def build(self, period: Period) -> dict[str, Any]:
        entries = self.entries(period)
        prev = period.previous()
        highlights = self.highlights(period)
        summary: dict[str, Any] = {
            "kind": period.kind,
            "key": period.key,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "previous_key": prev.key,
            "generated_at": self.now.astimezone(self.tz).isoformat(timespec="seconds"),
            "days_with_data": self.days_with_data(period),
            "days_expected": self.days_expected(period),
            "days_total": len(period.days),
            "complete": period.end < self.now.astimezone(self.tz).date(),
            "highlights": highlights,
            "stats": self.stats(entries),
            "topics": self.topics(entries, self.entries(prev)),
        }
        if period.kind == "weekly":
            picks = sorted((e for e in entries if e["category"] == "research"), key=rank_key)
            summary["research"] = picks[: self.cfg["weekly"].get("research_picks", 10)]
            summary["multi_day_events"] = self.multi_day_events(entries)
        else:
            summary["series"] = self.series(period, entries)
        if period.kind in ("quarterly", "yearly"):
            summary["major_releases"] = [h for h in highlights if h["category"] == "models"]
        if period.kind == "yearly":
            timeline: dict[str, list[dict[str, Any]]] = {}
            for h in sorted(highlights, key=lambda h: h["day"]):
                timeline.setdefault(h["day"][:7], []).append(h)
            summary["timeline"] = [{"month": m, "highlights": hs} for m, hs in timeline.items()]
        return summary

    def build_and_save(self, period: Period) -> dict[str, Any]:
        summary = self.build(period)
        self.storage.save_summary(period.kind, period.key, summary)
        return summary
