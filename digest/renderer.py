"""Xuất HTML: bản ngày, trang mục lục và chỉ mục tìm kiếm (tất cả nằm trong docs/)."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Source
from .storage import Storage

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
LABEL_NAMES = {"important": "Quan trọng", "notable": "Đáng chú ý"}
# Các cấp tổng hợp (giai đoạn 3); trang mục lục tự liệt kê nếu thư mục đã có file
SUMMARY_LEVELS = [("yearly", "Bản năm"), ("quarterly", "Bản quý"), ("monthly", "Bản tháng"), ("weekly", "Bản tuần")]


def safe_url(url: str | None) -> str:
    """Chỉ cho phép link http/https (chặn javascript:… cài trong feed)."""
    if url and urlsplit(url).scheme in ("http", "https"):
        return url
    return "#"


def lower_first(text: str) -> str:
    """Viết thường chữ cái đầu ("Quý IV/2026" -> "quý IV/2026"), giữ nguyên phần còn lại."""
    return text[:1].lower() + text[1:]


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


class Renderer:
    def __init__(self, templates_dir: Path, docs_dir: Path, settings: dict[str, Any], sources: list[Source]) -> None:
        self.docs_dir = Path(docs_dir)
        self.settings = settings
        self.tz = ZoneInfo(settings["timezone"])
        self.source_names = {s.id: s.name for s in sources}
        self.n_sources = len([s for s in sources if s.enabled])
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),  # nội dung feed luôn được thoát ký tự HTML
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters.update(
            safe_url=safe_url,
            vn_time=self.vn_time,
            vn_long_date=lambda d: self.vn_long_date(_as_date(d)),
            vn_short_date=lambda d: _as_date(d).strftime("%d/%m/%Y"),
        )
        cat_labels = settings["categories"]["labels"]
        self.env.filters.update(
            category_row=lambda kv: (cat_labels.get(kv[0], kv[0]), kv[1]),
            source_row=lambda kv: (self.source_names.get(kv[0], kv[0]), kv[1]),
        )
        self.env.globals.update(
            source_name=lambda sid: self.source_names.get(sid, sid),
            category_label=lambda c: cat_labels.get(c, c),
            series_label=self.series_label,
            label_names=LABEL_NAMES,
            repo_url=settings["project"]["repo_url"],
        )

    # ---------------------------------------------------------------- Định dạng

    def vn_time(self, value: str | datetime) -> str:
        dt = datetime.fromisoformat(value) if isinstance(value, str) else value
        return dt.astimezone(self.tz).strftime("%H:%M %d/%m")

    @staticmethod
    def vn_long_date(d: date) -> str:
        return f"{WEEKDAYS[d.weekday()]}, {d.day:02d}/{d.month:02d}/{d.year}"

    # ---------------------------------------------------------------- Đường dẫn

    def daily_rel(self, day: date) -> str:
        """Đường dẫn bản ngày, tính từ docs/."""
        return f"daily/{day.year}/{day.isoformat()}.html"

    def daily_path(self, day: date) -> Path:
        return self.docs_dir / self.daily_rel(day)

    # ---------------------------------------------------------------- Bản ngày

    def group_stories(self, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Chia tin theo mục (và mục con của Nghiên cứu) đúng thứ tự cấu hình; mục rỗng bị ẩn."""
        cats = self.settings["categories"]
        rs = cats["research_subcategories"]
        groups = []
        for key in cats["order"]:
            items = [s for s in stories if s["category"] == key]
            if not items:
                continue
            g: dict[str, Any] = {"key": key, "label": cats["labels"].get(key, key), "count": len(items),
                                 "stories": items, "subgroups": None}
            if key == "research":
                g["subgroups"] = [
                    {"key": sk, "label": rs["labels"].get(sk, sk),
                     "stories": [s for s in items if (s.get("subcategory") or "other") == sk]}
                    for sk in rs["order"]
                ]
                g["subgroups"] = [sg for sg in g["subgroups"] if sg["stories"]]
            groups.append(g)
        return groups

    def render_daily(self, data: dict[str, Any], prev_day: date | None, next_day: date | None) -> Path:
        day = _as_date(data["date"])
        stories = data["stories"]
        used = []
        for s in stories:
            for sid in [s["source_id"], *(o["source_id"] for o in s["also_covered_by"])]:
                if sid not in used:
                    used.append(sid)
        # Tên hiển thị cho "Cùng đưa tin": nguồn lặp lại thì đánh số (Hacker News, Hacker News #2)
        for s in stories:
            seen: dict[str, int] = {}
            for o in s["also_covered_by"]:
                seen[o["source_id"]] = seen.get(o["source_id"], 0) + 1
                n = seen[o["source_id"]]
                o["display"] = self.source_names.get(o["source_id"], o["source_id"]) + (f" #{n}" if n > 1 else "")
        status = data["sources_status"]
        html = self.env.get_template("daily.html").render(
            root="../../",
            day=day,
            window_end=data["window"]["end"],
            generated_at=data["generated_at"],
            groups=self.group_stories(stories),
            n_important=sum(s["label"] == "important" for s in stories),
            n_notable=sum(s["label"] == "notable" for s in stories),
            n_sources=len(status),
            n_sources_ok=sum(st["ok"] for st in status),
            sources_status=status,
            used_sources=sorted(used, key=lambda sid: self.source_names.get(sid, sid).lower()),
            translation=(data.get("translation") or {}).get("counts"),
            prev_day=prev_day,
            next_day=next_day,
            prev_href=f"../{prev_day.year}/{prev_day.isoformat()}.html" if prev_day else None,
            next_href=f"../{next_day.year}/{next_day.isoformat()}.html" if next_day else None,
        )
        return self._write(self.daily_path(day), html)

    # ---------------------------------------------------------------- Bản tổng hợp

    @staticmethod
    def summary_title(kind: str, key: str) -> str:
        """Tên kỳ: 2026-W44 -> "Tuần 44/2026", 2026-10 -> "Tháng 10/2026", 2026-Q4 -> "Quý IV/2026"."""
        if kind == "weekly":
            year, week = key.split("-W")
            return f"Tuần {int(week)}/{year}"
        if kind == "monthly":
            year, month = key.split("-")
            return f"Tháng {int(month)}/{year}"
        if kind == "quarterly":
            year, q = key.split("-Q")
            return f"Quý {['I', 'II', 'III', 'IV'][int(q) - 1]}/{year}"
        return f"Năm {key}"

    def series_label(self, row: dict[str, Any]) -> str:
        key = row["key"]
        if "-W" in key:
            start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
            return f"{self.summary_title('weekly', key)} ({start:%d/%m}–{end:%d/%m})"
        return self.summary_title("monthly", key)

    def render_summary(self, summary: dict[str, Any], prev_key: str | None, next_key: str | None) -> Path:
        kind, key = summary["kind"], summary["key"]
        html = self.env.get_template(f"{kind}.html").render(
            root="../",
            s=summary,
            title=f"Bản tin {lower_first(self.summary_title(kind, key))}",
            prev_period_name=lower_first(self.summary_title(kind, summary["previous_key"])),
            series_unit="tuần" if kind == "monthly" else "tháng",
            prev_title=self.summary_title(kind, prev_key) if prev_key else None,
            next_title=self.summary_title(kind, next_key) if next_key else None,
            prev_href=f"{prev_key}.html" if prev_key else None,
            next_href=f"{next_key}.html" if next_key else None,
        )
        return self._write(self.docs_dir / kind / f"{key}.html", html)

    def render_summary_and_neighbors(self, storage: Storage, kind: str, key: str) -> Path:
        """Dựng bản tổng hợp đã lưu và vẽ lại hai kỳ lân cận để cập nhật link trước/sau."""
        keys = storage.list_summaries(kind)
        i = keys.index(key)
        path = Path()
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(keys):
                data = storage.load_summary(kind, keys[j])
                out = self.render_summary(data, keys[j - 1] if j > 0 else None,
                                          keys[j + 1] if j + 1 < len(keys) else None)
                if j == i:
                    path = out
        return path

    # ---------------------------------------------------------------- Mục lục và tìm kiếm

    def render_index(self, storage: Storage) -> Path:
        days = storage.list_days()
        summaries = []
        for level, label in SUMMARY_LEVELS:
            folder = self.docs_dir / level
            files = sorted(folder.glob("*.html"), reverse=True) if folder.exists() else []
            summaries.append({"label": label, "entries": [
                {"name": self.summary_title(level, f.stem), "href": f"{level}/{f.name}"} for f in files]})

        months: dict[str, list[dict[str, Any]]] = {}
        latest = None
        for d in sorted(days, reverse=True):
            data = storage.load_daily(d) or {"stories": []}
            st = data["stories"]
            entry = {"day": d, "href": self.daily_rel(d),
                     "n_important": sum(s["label"] == "important" for s in st),
                     "n_notable": sum(s["label"] == "notable" for s in st)}
            months.setdefault(f"{d.month:02d}/{d.year}", []).append(entry)
            if latest is None:
                latest = {**entry, "top": [s for s in st if s["label"] == "important"][:10]}

        html = self.env.get_template("index.html").render(
            root="",
            latest=latest,
            summaries=summaries,
            months=[{"label": k, "days": v} for k, v in months.items()],
            n_sources=self.n_sources,
        )
        return self._write(self.docs_dir / "index.html", html)

    def write_search_index(self, storage: Storage) -> Path:
        """docs/search-index.js: [ngày, tiêu đề Việt, tiêu đề gốc, link, nhãn, link bản ngày], mới nhất trước."""
        rows = []
        for d in sorted(storage.list_days(), reverse=True):
            data = storage.load_daily(d) or {"stories": []}
            for s in data["stories"]:
                title_vi = s["title_vi"] if s.get("translated") else ""
                rows.append([d.isoformat(), title_vi, s["title_orig"], safe_url(s["url"]), s["label"],
                             f"{self.daily_rel(d)}#s-{s['id'][:10]}"])
        js = "window.DIGEST_SEARCH=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ";\n"
        return self._write(self.docs_dir / "search-index.js", js)

    # ----------------------------------------------------------------

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return path
