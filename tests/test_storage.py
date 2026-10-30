"""Test đọc/ghi dữ liệu."""

from datetime import date

from digest import storage
from digest.storage import Storage


def test_config_loads():
    sources = storage.load_sources()
    assert len(storage.load_sources(include_disabled=True)) == 31
    assert len({s.id for s in sources}) == len(sources)
    settings = storage.load_settings()
    assert "mailto:" in storage.user_agent(settings)
    assert all(isinstance(w, str) for w in settings["dedup"]["stopwords"])


def test_daily_roundtrip(tmp_path):
    st = Storage(tmp_path)
    data = {"date": "2026-10-30", "stories": [{"title_orig": "Tiếng Việt có dấu"}]}
    path = st.save_daily(date(2026, 10, 30), data)
    assert path == tmp_path / "2026" / "2026-10-30.json"
    assert "Tiếng Việt" in path.read_text(encoding="utf-8")
    assert st.load_daily(date(2026, 10, 30)) == data
    assert st.load_daily(date(2026, 10, 31)) is None


def test_seen_rerun_same_day_replaces(tmp_path):
    st = Storage(tmp_path)
    st.update_seen(date(2026, 10, 29), ["a", "b"])
    st.update_seen(date(2026, 10, 30), ["c", "d"])
    st.update_seen(date(2026, 10, 30), ["c", "e"])  # chạy lại ngày 30
    assert st.load_seen() == {"a": "2026-10-29", "b": "2026-10-29", "c": "2026-10-30", "e": "2026-10-30"}


def test_seen_keeps_earliest_day(tmp_path):
    st = Storage(tmp_path)
    st.update_seen(date(2026, 10, 29), ["a"])
    st.update_seen(date(2026, 10, 30), ["a"])
    assert st.load_seen()["a"] == "2026-10-29"


def test_sitemap_state(tmp_path):
    st = Storage(tmp_path)
    assert st.load_sitemap_urls("anthropic") is None
    st.save_sitemap_urls("anthropic", {"https://x/news/b", "https://x/news/a"})
    assert st.load_sitemap_urls("anthropic") == {"https://x/news/a", "https://x/news/b"}


def test_usage_log_appends_runs(tmp_path):
    st = Storage(tmp_path)
    st.append_usage(date(2026, 10, 30), {"duration_seconds": 10})
    path = st.append_usage(date(2026, 10, 30), {"duration_seconds": 12})
    assert path == tmp_path / "usage" / "2026-10-30.json"
    data = storage.read_json(path)
    assert data["date"] == "2026-10-30" and len(data["runs"]) == 2
