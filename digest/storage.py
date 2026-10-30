"""Đọc cấu hình và đọc/ghi dữ liệu JSON: bản ngày, lịch sử tin đã đăng, trạng thái sitemap."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import Source

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- Cấu hình


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings(config_dir: Path = ROOT / "config") -> dict[str, Any]:
    return load_yaml(config_dir / "settings.yaml")


def load_sources(config_dir: Path = ROOT / "config", include_disabled: bool = False) -> list[Source]:
    raw = load_yaml(config_dir / "sources.yaml")["sources"]
    sources = [Source.from_dict(d) for d in raw]
    return sources if include_disabled else [s for s in sources if s.enabled]


def load_glossary(config_dir: Path = ROOT / "config") -> dict[str, Any]:
    return load_yaml(config_dir / "glossary.yaml")


def user_agent(settings: dict[str, Any]) -> str:
    p = settings["project"]
    return p["user_agent"].format(**p)


# ---------------------------------------------------------------- Đọc/ghi JSON


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """Ghi JSON an toàn: ghi ra file tạm rồi đổi tên, tránh hỏng file khi bị ngắt giữa chừng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o644)  # mkstemp tạo file chỉ chủ sở hữu đọc được
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Storage:
    """Quản lý thư mục data/ (mặc định ở gốc repo; test dùng thư mục tạm)."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    # ---- Bản ngày: data/YYYY/YYYY-MM-DD.json

    def daily_path(self, day: date) -> Path:
        return self.data_dir / f"{day.year}" / f"{day.isoformat()}.json"

    def save_daily(self, day: date, data: dict[str, Any]) -> Path:
        path = self.daily_path(day)
        write_json(path, data)
        return path

    def load_daily(self, day: date) -> dict[str, Any] | None:
        return read_json(self.daily_path(day))

    def list_days(self) -> list[date]:
        """Mọi ngày đã có dữ liệu, tăng dần."""
        days = []
        for path in self.data_dir.glob("[0-9][0-9][0-9][0-9]/*.json"):
            try:
                days.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return sorted(days)

    def neighbors(self, day: date) -> tuple[date | None, date | None]:
        """Ngày có dữ liệu ngay trước và ngay sau `day`."""
        days = self.list_days()
        before = [d for d in days if d < day]
        after = [d for d in days if d > day]
        return (before[-1] if before else None, after[0] if after else None)

    # ---- Tin đã đăng: data/seen.json = {"<mã tin>": "<ngày bản tin>"}

    @property
    def seen_path(self) -> Path:
        return self.data_dir / "seen.json"

    def load_seen(self) -> dict[str, str]:
        return read_json(self.seen_path, default={})

    def update_seen(self, day: date, article_ids: list[str]) -> None:
        """Ghi các mã tin của bản ngày `day`.

        Chạy lại cùng ngày: xóa mã cũ của ngày đó rồi ghi lại, để bản mới thay thế bản cũ.
        """
        seen = {k: v for k, v in self.load_seen().items() if v != day.isoformat()}
        for aid in article_ids:
            seen.setdefault(aid, day.isoformat())
        write_json(self.seen_path, dict(sorted(seen.items())))

    # ---- Nhật ký lượng dùng: data/usage/YYYY-MM-DD.json = {"runs": [mỗi lần chạy]}

    def usage_path(self, day: date) -> Path:
        return self.data_dir / "usage" / f"{day.isoformat()}.json"

    def append_usage(self, day: date, record: dict[str, Any]) -> Path:
        path = self.usage_path(day)
        data = read_json(path, default={"date": day.isoformat(), "runs": []})
        data["runs"].append(record)
        write_json(path, data)
        return path

    # ---- Sitemap: data/sitemaps/<source_id>.json = {url: ngày thấy lần đầu}
    # Lần chạy đầu ghi ngày BASELINE cho mọi URL hiện có (không đăng).
    # Lưu ngày để chạy lại cùng ngày vẫn đăng lại đúng các URL mới của ngày đó.

    BASELINE = "0000-00-00"

    def sitemap_path(self, source_id: str) -> Path:
        return self.data_dir / "sitemaps" / f"{source_id}.json"

    def load_sitemap_state(self, source_id: str) -> dict[str, str] | None:
        """Trả về None nếu chưa từng đọc nguồn này (lần chạy đầu)."""
        return read_json(self.sitemap_path(source_id))

    def sitemap_known_before(self, source_id: str, day: date) -> set[str] | None:
        """Các URL đã thấy trước ngày `day` (None nếu chưa từng đọc)."""
        state = self.load_sitemap_state(source_id)
        if state is None:
            return None
        return {url for url, first in state.items() if first < day.isoformat()}

    def update_sitemap_state(self, source_id: str, day: date, urls: set[str], baseline: bool) -> None:
        state = self.load_sitemap_state(source_id) or {}
        mark = self.BASELINE if baseline else day.isoformat()
        for url in urls:
            state.setdefault(url, mark)
        write_json(self.sitemap_path(source_id), dict(sorted(state.items())))
