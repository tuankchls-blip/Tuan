"""Test dịch qua dichviet: các máy dịch đều là máy giả (tests/fake_dichviet.py), không gọi mạng."""

import json
import os

import pytest

from digest import filters, translator
from digest.translator import TranslationCache, engine_chain

from . import fake_dichviet as fd
from .conftest import art


@pytest.fixture
def stories(sources, settings):
    arts = [
        art("lab", "Apple releases an open-weight LLM", summary="It runs on a GPU."),
        art("press", "Startup raises money", summary=""),
        art("press2", "Robots learn to fold laundry", summary="A new dataset helps robots."),
        art("vnexpress-sohoa", "Việt Nam đẩy mạnh AI", summary="Tin tiếng Việt.", lang="vi"),
    ]
    return filters.cluster(arts, sources, settings)


def by_title(stories, title):
    return next(s for s in stories if s.primary.title == title)


def run(stories, settings, tmp_path, **kw):
    kw.setdefault("use_mymemory", False)
    return translator.translate_stories(stories, settings, tmp_path, translator=fd.make_translator(), **kw)


def test_full_flow_claude_then_google_then_untranslated(stories, settings, tmp_path, monkeypatch):
    # Claude dịch được tin của lab; trả rỗng cho tin robots và startup (không qua kiểm tra)
    fakes = fd.install(monkeypatch,
                       claude_cli=lambda t: "" if ("Robots" in t or "robots" in t or "Startup" in t) else "[vi] " + t,
                       google=lambda t: "" if "raises money" in t else "[gg] " + t)
    lab = by_title(stories, "Apple releases an open-weight LLM")
    robots = by_title(stories, "Robots learn to fold laundry")
    startup = by_title(stories, "Startup raises money")

    report = run(stories, settings, tmp_path)
    assert report.engines == ["claude-cli", "google"]
    assert (lab.translation_source, lab.title_vi) == ("claude", "[vi] Apple releases an open-weight LLM")
    assert robots.translation_source == "google" and robots.title_vi.startswith("[gg]")
    assert startup.translated is False and startup.title_vi == ""
    vn = by_title(stories, "Việt Nam đẩy mạnh AI")
    assert vn.translation_source == "original" and vn.title_vi == "Việt Nam đẩy mạnh AI"
    assert report.counts == {"original": 1, "cache": 0, "claude": 1, "google": 1, "mymemory": 0, "untranslated": 1}
    # tin chưa dịch có lý do; nhật ký có số lần gọi của dichviet
    assert report.untranslated and "bản dịch rỗng" in report.untranslated[0]
    assert report.dichviet["engine_calls"] >= 2

    cache = json.loads((tmp_path / "data/translations_cache.json").read_text(encoding="utf-8"))
    assert cache[lab.id]["source"] == "claude" and cache[robots.id]["source"] == "google"
    assert startup.id not in cache

    # Lần chạy sau: chỉ còn tin chưa dịch được gửi đi
    fakes2 = fd.install(monkeypatch)
    report2 = run(stories, settings, tmp_path)
    assert fakes2["claude-cli"].calls == [["Startup raises money"]]
    assert report2.counts == {"original": 1, "cache": 2, "claude": 1, "google": 0, "mymemory": 0, "untranslated": 0}


def test_google_receives_protected_terms(stories, settings, tmp_path, monkeypatch):
    fakes = fd.install(monkeypatch, google=lambda t: "[gg] " + t)
    lab = by_title(stories, "Apple releases an open-weight LLM")
    run(stories, settings, tmp_path, use_claude=False)
    sent = " ".join(t for call in fakes["google"].calls for t in call)
    # thuật ngữ và tên riêng (bảng của dichviet + config/glossary.yaml) được thay bằng mã giữ chỗ
    assert "LLM" not in sent and "Apple" not in sent and "GPU" not in sent
    assert lab.title_vi == "[gg] Apple releases an open-weight LLM"


def test_claude_off_google_takes_over(stories, settings, tmp_path, monkeypatch):
    fakes = fd.install(monkeypatch)
    report = run(stories, settings, tmp_path, use_claude=False)
    assert fakes["claude-cli"].calls == []
    assert report.engines == ["google"]
    assert report.counts["google"] == 3 and report.counts["untranslated"] == 0


def test_claude_off_by_env(stories, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DIGEST_NO_CLAUDE", "1")
    fakes = fd.install(monkeypatch)
    run(stories, settings, tmp_path)
    assert fakes["claude-cli"].calls == []


def test_mymemory_used_when_google_blocked(stories, settings, tmp_path, monkeypatch):
    fakes = fd.install(monkeypatch, google=fd.quota, mymemory=lambda t: "[mm] " + t)
    report = run(stories, settings, tmp_path, use_claude=False, use_mymemory=True)
    assert report.engines == ["google", "mymemory"]
    assert report.counts["mymemory"] == 3 and report.counts["untranslated"] == 0
    assert len(fakes["google"].calls) == 1  # Google bị chặn một lần là bỏ qua cho cả lần chạy
    cache = json.loads((tmp_path / "data/translations_cache.json").read_text(encoding="utf-8"))
    assert {e["source"] for e in cache.values()} == {"mymemory"}


def test_all_engines_off(stories, settings, tmp_path, monkeypatch):
    fakes = fd.install(monkeypatch)
    report = run(stories, settings, tmp_path, use_claude=False, use_google=False)
    assert all(f.calls == [] for f in fakes.values())
    assert report.counts["untranslated"] == 3 and report.counts["original"] == 1


def test_engine_chain_follows_settings(settings, monkeypatch):
    cfg = settings["translation"]
    assert engine_chain(cfg, True, True, True) == ["claude-cli", "google", "mymemory"]
    assert engine_chain(cfg, False, False, True) == ["mymemory"]
    off = {**cfg, "google": {"enabled": False}, "fallback_order": ["mymemory", "google"]}
    assert engine_chain(off, True, True, True) == ["claude-cli", "mymemory"]
    monkeypatch.setenv("DIGEST_NO_CLAUDE", "1")
    assert engine_chain(cfg, True, True, True) == ["google", "mymemory"]


def test_default_translator_reads_config_and_email(settings, monkeypatch):
    monkeypatch.delenv("MYMEMORY_EMAIL", raising=False)
    tr = translator.default_translator(settings, fd.ROOT)
    assert tr.config.style == "tin-cong-nghe" and tr.config.cache["backend"] == "none"
    assert os.environ["MYMEMORY_EMAIL"] == settings["project"]["contact_email"]
    monkeypatch.setenv("MYMEMORY_EMAIL", "khac@example.com")  # biến đặt sẵn từ ngoài được giữ nguyên
    translator.default_translator(settings, fd.ROOT)
    assert os.environ["MYMEMORY_EMAIL"] == "khac@example.com"


def test_cache_invalidated_when_text_changes(stories, tmp_path):
    cache = TranslationCache(tmp_path / "c.json")
    s = stories[0]
    cache.put(s, "a", "b", "google")
    assert cache.get(s) is not None
    s.primary.summary += " (cập nhật)"
    assert cache.get(s) is None
