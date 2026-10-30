"""Test dịch: Claude và Google đều được giả lập, không gọi mạng."""

import json
import subprocess

import pytest

from digest import filters, translator
from digest.storage import load_glossary
from digest.translator import GoogleBackend, TranslationCache, read_output

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


def fake_google(text):
    """Google giả: thêm tiền tố [vi] và làm xô lệch khoảng trắng của mã giữ chỗ."""
    return "[vi] " + text.replace("ZZ0ZZ", "zz 0 ZZ")


def claude_runner(write_items, returncode=0, payload=None):
    """Claude giả: ghi out.json do test chỉ định, trả JSON như --output-format json."""
    calls = []

    def run(cmd, cwd, **kwargs):
        calls.append(cmd)
        inputs = json.loads((cwd / "data/translate/in.json").read_text(encoding="utf-8"))
        items = write_items(inputs)
        if items is not None:
            (cwd / "data/translate/out.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        out = payload or {"type": "result", "subtype": "success", "is_error": False, "num_turns": 4,
                          "total_cost_usd": 0.12, "usage": {"input_tokens": 1000, "output_tokens": 800}}
        return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(out), stderr="")

    run.calls = calls
    return run


# ---------------------------------------------------------------- Lệnh Claude


def test_claude_command_is_restricted(settings):
    cmd = translator.claude_command(settings["translation"]["claude"], settings["paths"])
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == "Read,Write"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "Edit(./data/translate/out.json)" in cmd  # luật ghi file của Claude Code
    assert "Read(./data/translate/in.json)" in cmd
    assert "--strict-mcp-config" in cmd and "--max-turns" in cmd
    assert not any("Bash" in c or "WebFetch" in c for c in cmd)


def test_run_claude_parses_usage(settings, tmp_path):
    (tmp_path / "data/translate").mkdir(parents=True)
    (tmp_path / "data/translate/in.json").write_text("[]", encoding="utf-8")
    run = claude_runner(lambda inputs: [])
    log = translator.run_claude(settings["translation"]["claude"], settings["paths"], tmp_path, runner=run)
    assert log["ok"] and log["num_turns"] == 4 and log["total_cost_usd"] == 0.12
    assert log["usage"]["output_tokens"] == 800


def test_run_claude_reports_errors(settings, tmp_path):
    def broken(cmd, cwd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="not json", stderr="rate limit")

    log = translator.run_claude(settings["translation"]["claude"], settings["paths"], tmp_path, runner=broken)
    assert not log["ok"] and "rate limit" in log["error"]

    def slow(cmd, cwd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    log = translator.run_claude(settings["translation"]["claude"], settings["paths"], tmp_path, runner=slow)
    assert log["error"] == "quá thời gian chờ"


# ---------------------------------------------------------------- Kiểm tra out.json


def test_read_output_validates(tmp_path):
    inputs = [{"id": "a", "title": "T1", "summary": "S1"},
              {"id": "b", "title": "T2", "summary": "S2"},
              {"id": "c", "title": "T3", "summary": ""},
              {"id": "d", "title": "T4", "summary": "S4"}]
    out = tmp_path / "out.json"
    out.write_text(json.dumps([
        {"id": "a", "title_vi": "Tiêu đề 1", "summary_vi": "Tóm tắt 1"},
        {"id": "b", "title_vi": "", "summary_vi": "x"},          # thiếu tiêu đề
        {"id": "c", "title_vi": "Tiêu đề 3", "summary_vi": ""},  # gốc rỗng thì được rỗng
        {"id": "d", "title_vi": "Tiêu đề 4", "summary_vi": ""},  # gốc có tóm tắt mà dịch rỗng
        {"id": "zzz", "title_vi": "lạ", "summary_vi": ""},       # mã không có trong in.json
    ]), encoding="utf-8")
    valid, problems = read_output(out, inputs)
    assert set(valid) == {"a", "c"}
    assert any("2 tin thiếu" in p for p in problems)


def test_read_output_bad_files(tmp_path):
    inputs = [{"id": "a", "title": "T", "summary": ""}]
    assert read_output(tmp_path / "none.json", inputs) == ({}, ["không có out.json"])
    bad = tmp_path / "bad.json"
    bad.write_text("Here is your translation: [", encoding="utf-8")
    valid, problems = read_output(bad, inputs)
    assert valid == {} and "JSON" in problems[0]


# ---------------------------------------------------------------- Google


def test_google_keeps_glossary_terms():
    g = GoogleBackend(load_glossary(), translate_fn=fake_google)
    protected, kept = g.protect("Apple ships an open-weight LLM on NVIDIA GPU; apple pie is unrelated.")
    assert "Apple" not in protected and "apple pie" in protected
    assert set(kept) == {"Apple", "open-weight", "LLM", "NVIDIA", "GPU"}
    out = g.translate("Apple ships an open-weight LLM on NVIDIA GPU.")
    assert out.startswith("[vi] ")
    for term in ("Apple", "open-weight", "LLM", "NVIDIA", "GPU"):
        assert term in out


def test_google_detects_lost_terms():
    g = GoogleBackend(load_glossary(), translate_fn=lambda text: "bản dịch làm rơi mã")
    with pytest.raises(ValueError):
        g.translate("Claude is here")


def test_google_prefers_longer_phrase():
    g = GoogleBackend(load_glossary(), translate_fn=lambda t: t)
    _, kept = g.protect("Google DeepMind and Google")
    assert kept == ["Google DeepMind", "Google"]


# ---------------------------------------------------------------- Toàn luồng


def test_full_flow_claude_then_google_then_untranslated(stories, settings, tmp_path):
    lab = by_title(stories, "Apple releases an open-weight LLM")
    robots = by_title(stories, "Robots learn to fold laundry")
    startup = by_title(stories, "Startup raises money")

    # Claude chỉ dịch được tin của lab, và dịch sai tin robots (thiếu tiêu đề)
    run = claude_runner(lambda inputs: [
        {"id": lab.id, "title_vi": "Apple phát hành LLM open-weight", "summary_vi": "Chạy trên GPU."},
        {"id": robots.id, "title_vi": "", "summary_vi": "x"},
    ])

    def google_fn(text):
        if "Startup" in text:
            raise ConnectionError("Google lỗi")
        return "[vi] " + text

    report = translator.translate_stories(stories, settings, load_glossary(), tmp_path, runner=run,
                                          google=GoogleBackend(load_glossary(), translate_fn=google_fn))
    assert len(run.calls) == 1
    assert (lab.translation_source, lab.title_vi) == ("claude", "Apple phát hành LLM open-weight")
    assert robots.translation_source == "google" and robots.title_vi.startswith("[vi]")
    assert startup.translated is False and startup.title_vi == ""
    vn = by_title(stories, "Việt Nam đẩy mạnh AI")
    assert vn.translation_source == "original" and vn.title_vi == "Việt Nam đẩy mạnh AI"
    assert report.counts == {"original": 1, "cache": 0, "claude": 1, "google": 1, "untranslated": 1}
    assert report.claude["ok"] and report.claude["translated"] == 1
    assert report.claude_problems and report.google_errors

    # Bộ nhớ đệm ghi nguồn dịch; tin chưa dịch không được lưu để lần sau dịch lại
    cache = json.loads((tmp_path / "data/translations_cache.json").read_text(encoding="utf-8"))
    assert cache[lab.id]["source"] == "claude" and cache[robots.id]["source"] == "google"
    assert startup.id not in cache

    # Lần chạy sau: chỉ còn tin chưa dịch được gửi cho Claude
    run2 = claude_runner(lambda inputs: [{"id": i["id"], "title_vi": "Khởi nghiệp gọi vốn", "summary_vi": ""}
                                         for i in inputs])
    report2 = translator.translate_stories(stories, settings, load_glossary(), tmp_path, runner=run2,
                                           google=GoogleBackend(load_glossary(), translate_fn=google_fn))
    sent = json.loads((tmp_path / "data/translate/in.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in sent] == [startup.id]
    assert report2.counts == {"original": 1, "cache": 2, "claude": 1, "google": 0, "untranslated": 0}


def test_claude_off_google_takes_over(stories, settings, tmp_path):
    run = claude_runner(lambda inputs: [])
    report = translator.translate_stories(stories, settings, load_glossary(), tmp_path, use_claude=False,
                                          runner=run, google=GoogleBackend(load_glossary(), translate_fn=fake_google))
    assert run.calls == []
    assert report.counts["google"] == 3 and report.counts["untranslated"] == 0
    assert "đã tắt" in report.claude["error"]


def test_claude_off_by_env(stories, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DIGEST_NO_CLAUDE", "1")
    run = claude_runner(lambda inputs: [])
    translator.translate_stories(stories, settings, load_glossary(), tmp_path, runner=run,
                                 google=GoogleBackend(load_glossary(), translate_fn=fake_google))
    assert run.calls == []


def test_claude_fails_google_takes_over(stories, settings, tmp_path):
    run = claude_runner(lambda inputs: None, returncode=1,
                        payload={"type": "result", "subtype": "error_max_turns", "is_error": True})
    report = translator.translate_stories(stories, settings, load_glossary(), tmp_path, runner=run,
                                          google=GoogleBackend(load_glossary(), translate_fn=fake_google))
    assert report.claude["ran"] and not report.claude["ok"]
    assert report.counts["google"] == 3


def test_stale_out_json_is_removed(stories, settings, tmp_path):
    out = tmp_path / "data/translate/out.json"
    out.parent.mkdir(parents=True)
    lab = by_title(stories, "Apple releases an open-weight LLM")
    out.write_text(json.dumps([{"id": lab.id, "title_vi": "cũ", "summary_vi": "cũ"}]), encoding="utf-8")
    report = translator.translate_stories(stories, settings, load_glossary(), tmp_path, use_claude=False,
                                          google=GoogleBackend(load_glossary(), translate_fn=fake_google))
    assert lab.translation_source == "google" and not out.exists()
    assert report.counts["claude"] == 0


def test_cache_invalidated_when_text_changes(stories, tmp_path):
    cache = TranslationCache(tmp_path / "c.json")
    s = stories[0]
    cache.put(s, "a", "b", "google")
    assert cache.get(s) is not None
    s.primary.summary += " (cập nhật)"
    assert cache.get(s) is None


def test_google_stops_after_repeated_errors():
    calls = []

    def blocked(text):
        calls.append(text)
        raise ConnectionError("CAPTCHA")

    g = GoogleBackend(load_glossary(), translate_fn=blocked)
    for _ in range(5):
        with pytest.raises(Exception):
            g.translate("hello")
    assert len(calls) == GoogleBackend.MAX_CONSECUTIVE_ERRORS and g.disabled


def test_run_claude_logs_permission_denials(settings, tmp_path):
    (tmp_path / "data/translate").mkdir(parents=True)
    (tmp_path / "data/translate/in.json").write_text("[]", encoding="utf-8")
    payload = {"type": "result", "subtype": "success", "is_error": False, "result": "Tôi không ghi được file.",
               "permission_denials": [{"tool_name": "Write", "tool_input": {"file_path": "data/translate/out.json"}}]}
    log = translator.run_claude(settings["translation"]["claude"], settings["paths"], tmp_path,
                                runner=claude_runner(lambda i: None, payload=payload))
    assert log["permission_denials"][0]["tool"] == "Write"
    assert "không ghi được" in log["result_tail"]
