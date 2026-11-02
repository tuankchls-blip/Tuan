"""Dịch tin tiếng Anh sang tiếng Việt bằng thư viện dichviet.

Luồng mỗi ngày:
1. Tin tiếng Việt giữ nguyên; tin đã có trong data/translations_cache.json (cùng nội dung)
   dùng lại bản dịch cũ.
2. Các tin còn lại gửi cho dichviet (cấu hình config/dichviet.yaml): Claude Code CLI dịch chính,
   không công cụ, không MCP; lỗi thì dự phòng Google rồi MyMemory theo translation.fallback_order;
   mọi bản dịch qua 7 phép kiểm tra của dichviet.
3. Tin nào vẫn lỗi thì để tiếng Anh, nhãn "chưa dịch", không lưu để lần sau dịch lại.
4. Lưu bản dịch vào data/translations_cache.json kèm nguồn dịch (claude/google/mymemory).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dichviet import Translator

from .models import Story
from .storage import read_json, write_json

# Tên máy dịch trong dichviet → nguồn dịch ghi trong bản tin
SOURCE_NAMES = {"claude-cli": "claude", "google": "google", "mymemory": "mymemory"}
FIELDS = {"title": "title_vi", "summary": "summary_vi"}


def text_hash(title: str, summary: str) -> str:
    """Mã của nội dung gốc: nội dung đổi thì dịch lại."""
    return hashlib.sha1(f"{title}\n{summary}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- Bộ nhớ đệm


class TranslationCache:
    """data/translations_cache.json = {mã tin: {title_vi, summary_vi, source, hash, translated_at}}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, dict[str, Any]] = read_json(path, default={})

    def get(self, story: Story) -> dict[str, Any] | None:
        entry = self.data.get(story.id)
        if entry and entry.get("hash") == text_hash(story.primary.title, story.summary):
            return entry
        return None

    def put(self, story: Story, title_vi: str, summary_vi: str, source: str) -> None:
        self.data[story.id] = {
            "title_vi": title_vi,
            "summary_vi": summary_vi,
            "source": source,
            "hash": text_hash(story.primary.title, story.summary),
            "translated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        write_json(self.path, dict(sorted(self.data.items())))


# ---------------------------------------------------------------- Chọn máy dịch


def engine_chain(cfg: dict[str, Any], use_claude: bool, use_google: bool, use_mymemory: bool) -> list[str]:
    """Thứ tự máy dịch cho lần chạy này: Claude (nếu bật) rồi dịch máy theo fallback_order."""
    chain: list[str] = []
    if use_claude and cfg.get("claude", {}).get("enabled", True) and not os.environ.get("DIGEST_NO_CLAUDE"):
        chain.append("claude-cli")
    flags = {"google": use_google, "mymemory": use_mymemory}
    for name in cfg.get("fallback_order", ["google", "mymemory"]):
        if flags.get(name, False) and (cfg.get(name) or {}).get("enabled", True):
            chain.append(name)
    return chain


def default_translator(settings: dict[str, Any], root: Path) -> Translator:
    """Translator đọc config/dichviet.yaml; email MyMemory lấy từ project.contact_email."""
    email = settings.get("project", {}).get("contact_email", "")
    if email:
        os.environ.setdefault("MYMEMORY_EMAIL", email)
    return Translator.from_config(root / settings["paths"]["dichviet_config"])


# ---------------------------------------------------------------- Ghép lại


@dataclass
class TranslationReport:
    counts: dict[str, int] = field(default_factory=lambda: {
        "original": 0, "cache": 0, "claude": 0, "google": 0, "mymemory": 0, "untranslated": 0})
    engines: list[str] = field(default_factory=list)
    dichviet: dict[str, Any] = field(default_factory=dict)
    untranslated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "engines": self.engines,
            "dichviet": self.dichviet,
            "untranslated": self.untranslated[:20],
        }


def translate_stories(
    stories: list[Story],
    settings: dict[str, Any],
    root: Path,
    use_claude: bool = True,
    use_google: bool = True,
    use_mymemory: bool = True,
    translator: Translator | None = None,
) -> TranslationReport:
    """Dịch các tin của một ngày; ghi bộ nhớ đệm. Không ném lỗi khi máy dịch hỏng."""
    cfg = settings["translation"]
    source_langs = cfg["source_langs"]
    cache = TranslationCache(root / settings["paths"]["translations_cache"])
    report = TranslationReport(engines=engine_chain(cfg, use_claude, use_google, use_mymemory))

    todo: list[Story] = []
    for s in stories:
        if s.primary.lang not in source_langs:
            s.title_vi, s.summary_vi, s.translated, s.translation_source = s.primary.title, s.summary, True, "original"
            report.counts["original"] += 1
            continue
        entry = cache.get(s)
        if entry:
            s.title_vi, s.summary_vi = entry["title_vi"], entry["summary_vi"]
            s.translated, s.translation_source = True, entry["source"]
            report.counts["cache"] += 1
            continue
        todo.append(s)

    if todo and not report.engines:
        for s in todo:  # mọi máy dịch đều bị tắt
            s.title_vi, s.summary_vi, s.translated, s.translation_source = "", "", False, None
        report.counts["untranslated"] += len(todo)
        report.untranslated.append("không có máy dịch nào được bật")
    elif todo:
        tr = translator or default_translator(settings, root)
        items = [{"id": s.id, "title": s.primary.title, "summary": s.summary} for s in todo]
        result = tr.translate_items(items, fields=FIELDS, id_field="id", engines=report.engines)
        report.dichviet = result.report.to_dict()
        for s, item in zip(todo, result.items):
            info = item["_dich"]
            if info["status"] == "untranslated":
                s.title_vi, s.summary_vi, s.translated, s.translation_source = "", "", False, None
                report.counts["untranslated"] += 1
                reasons = "; ".join(info.get("warnings") or [])
                report.untranslated.append(f"{s.id[:8]}: {reasons}"[:300])
                continue
            source = SOURCE_NAMES.get(info.get("engine") or "", "claude")
            s.title_vi, s.summary_vi = item["title_vi"], item.get("summary_vi", "")
            s.translated, s.translation_source = True, source
            cache.put(s, s.title_vi, s.summary_vi, source)
            report.counts[source] += 1
    cache.save()
    return report
