"""Test toàn luồng `main.py daily` với dữ liệu mẫu: không gọi mạng, Claude và Google đều giả lập."""

import json
from datetime import date, datetime, timezone

import requests

import main
from digest.translator import GoogleBackend
from digest.storage import load_glossary

from .conftest import FIXTURES

NOW = datetime(2026, 10, 30, 0, 5, tzinfo=timezone.utc)  # 07:05 giờ VN
DAY = date(2026, 10, 30)


def fake_get(url, params):
    """Một số nguồn trả dữ liệu mẫu, các nguồn còn lại lỗi 503 (kiểm tra luôn việc chịu lỗi)."""
    routes = {
        "rss.arxiv.org": "arxiv_sample.xml", "huggingface.co/api": "hf_papers.json",
        "hn.algolia.com": "hackernews.json", "cisa.gov": "cisa_kev.json", "crossref.org": "crossref.json",
        "anthropic.com/sitemap": "sitemap.xml", "openai.com": "rss_sample.xml",
        "simonwillison.net": "atom_sample.xml",
    }
    for key, name in routes.items():
        if key in url:
            return (FIXTURES / name).read_bytes()
    resp = requests.Response()
    resp.status_code = 503
    raise requests.HTTPError(response=resp)


def no_claude_runner(*args, **kwargs):
    raise AssertionError("không được gọi Claude")


def run(tmp_path, **kw):
    kw.setdefault("google", GoogleBackend(load_glossary(), translate_fn=lambda t: "[vi] " + t))
    kw.setdefault("use_mymemory", False)  # không gọi mạng
    return main.run_daily(DAY, root=tmp_path, getter=fake_get, now=NOW, use_claude=False,
                          runner=no_claude_runner, log=lambda *a: None, **kw)


def test_daily_end_to_end(tmp_path):
    r = run(tmp_path)
    data = json.loads(r.json_path.read_text(encoding="utf-8"))
    assert r.json_path == tmp_path / "data/2026/2026-10-30.json"
    assert data["date"] == "2026-10-30" and data["generated_at"].endswith("+07:00")
    assert len(data["sources_status"]) == 31
    failed = [s for s in data["sources_status"] if not s["ok"]]
    assert failed and all(s["error"] == "HTTP 503" for s in failed)
    required = {"id", "url", "source_id", "published_at", "lang", "title_orig", "summary_orig", "title_vi",
                "summary_vi", "translated", "also_covered_by", "category", "subcategory", "score", "label",
                "matched_keywords"}
    assert data["stories"] and all(required <= set(s) for s in data["stories"])

    titles = {s["title_orig"] for s in data["stories"]}
    # Model X: lab + HN + HF Papers + arXiv + blog chuyên gia gộp làm một sự kiện
    model_x = next(s for s in data["stories"] if s["source_id"] == "openai" and "Model X" in s["title_orig"])
    covered = {o["source_id"] for o in model_x["also_covered_by"]}
    assert {"hackernews", "hf-papers", "arxiv", "simonwillison"} <= covered
    assert model_x["label"] == "important"
    assert "An Unconfirmed Paper" not in titles          # arXiv chưa xác nhận bị loại
    assert "An old post" not in titles                   # ngoài khung giờ
    assert any(t.startswith("CVE-2026-0001") for t in titles)
    assert "Ask HN: What are you reading?" not in titles  # chỉ có HN, không khớp từ khóa
    # Lần đầu đọc sitemap chỉ ghi nhận, không đăng
    assert not any(s["source_id"] == "anthropic" for s in data["stories"])
    assert (tmp_path / "data/sitemaps/anthropic.json").exists()
    # Mọi tin tiếng Anh có bản dịch (Claude tắt -> Google dịch thay)
    assert all(s["translated"] for s in data["stories"])
    assert {s["translation_source"] for s in data["stories"]} <= {"google", "original"}

    html = r.html_path.read_text(encoding="utf-8")
    assert r.html_path == tmp_path / "docs/daily/2026/2026-10-30.html" and "[vi] " in html
    assert (tmp_path / "docs/index.html").exists() and (tmp_path / "docs/search-index.js").exists()
    usage = json.loads(r.usage_path.read_text(encoding="utf-8"))
    assert usage["runs"][0]["translation"]["counts"]["google"] > 0


def test_rerun_same_day_overwrites_without_duplicates(tmp_path):
    first = json.loads(run(tmp_path).json_path.read_text(encoding="utf-8"))
    second = json.loads(run(tmp_path).json_path.read_text(encoding="utf-8"))
    ids1 = [s["id"] for s in first["stories"]]
    ids2 = [s["id"] for s in second["stories"]]
    assert ids1 == ids2 and len(ids2) == len(set(ids2))
    assert second["translation"]["counts"]["cache"] > 0   # lần 2 dùng lại bản dịch
    assert len(json.loads((tmp_path / "data/usage/2026-10-30.json").read_text())["runs"]) == 2


def test_next_day_skips_published_stories(tmp_path):
    run(tmp_path)
    r2 = main.run_daily(date(2026, 10, 31), root=tmp_path, getter=fake_get,
                        now=datetime(2026, 10, 31, 0, 5, tzinfo=timezone.utc), use_claude=False,
                        google=GoogleBackend(load_glossary(), translate_fn=lambda t: t), use_mymemory=False,
                        log=lambda *a: None)
    first_ids = set(json.loads((tmp_path / "data/2026/2026-10-30.json").read_text())["stories"][0]["article_ids"])
    second = json.loads(r2.json_path.read_text(encoding="utf-8"))
    assert not any(set(s["article_ids"]) & first_ids for s in second["stories"])
    # link hai chiều giữa hai ngày
    assert 'href="../2026/2026-10-31.html"' in (tmp_path / "docs/daily/2026/2026-10-30.html").read_text()
    assert 'href="../2026/2026-10-30.html"' in r2.html_path.read_text()


def test_untranslated_when_both_translators_fail(tmp_path):
    def broken(text):
        raise ConnectionError("blocked")

    r = run(tmp_path, google=GoogleBackend(load_glossary(), translate_fn=broken))
    data = json.loads(r.json_path.read_text(encoding="utf-8"))
    en = [s for s in data["stories"] if s["lang"] == "en"]
    assert en and all(not s["translated"] for s in en)
    assert "chưa dịch" in r.html_path.read_text(encoding="utf-8")


def test_cli_retranslate_needs_date():
    assert main.main(["retranslate"]) == 2


# ---------------------------------------------------------------- Bản tổng hợp và dịch bù


def test_summary_due_and_index(tmp_path):
    run(tmp_path)  # bản ngày 30/10/2026 (tuần 2026-W44, tháng 10)
    quiet = {"root": tmp_path, "now": NOW, "log": lambda *a: None}
    html = main.run_summary("weekly", date(2026, 10, 30), **quiet)
    assert html == tmp_path / "docs/weekly/2026-W44.html"
    summary = json.loads((tmp_path / "data/weekly/2026-W44.json").read_text(encoding="utf-8"))
    assert summary["days_with_data"] == ["2026-10-30"] and summary["highlights"]
    assert "Model X" in html.read_text(encoding="utf-8")

    # Không có --date: kỳ vừa kết thúc tính theo "hôm nay" (30/10 → tuần trước là W43)
    assert main.run_summary("weekly", **quiet).name == "2026-W43.html"

    # Thứ Hai 02/11: đến hạn bản tuần W44; Chủ Nhật 01/11 là ngày 1: bản tháng 10
    assert [p.name for p in main.run_due(date(2026, 11, 2), **quiet)] == ["2026-W44.html"]
    assert [p.name for p in main.run_due(date(2026, 11, 1), **quiet)] == ["2026-10.html"]
    assert main.run_due(date(2026, 11, 3), **quiet) == []
    # 01/01/2027: tháng 12, quý IV và năm 2026 (dù chưa có dữ liệu cho các kỳ này vẫn chạy được)
    assert [p.name for p in main.run_due(date(2027, 1, 1), **quiet)] == ["2026-12.html", "2026-Q4.html", "2026.html"]

    index = (tmp_path / "docs/index.html").read_text(encoding="utf-8")
    for href in ("weekly/2026-W44.html", "monthly/2026-10.html", "quarterly/2026-Q4.html", "yearly/2026.html",
                 "daily/2026/2026-10-30.html"):
        assert f'href="{href}"' in index


def test_retranslate_fills_untranslated_and_updates_summaries(tmp_path):
    def broken(text):
        raise ConnectionError("blocked")

    run(tmp_path, google=GoogleBackend(load_glossary(), translate_fn=broken))
    quiet = {"root": tmp_path, "now": NOW, "log": lambda *a: None}
    main.run_summary("weekly", date(2026, 10, 30), **quiet)
    assert 'class="badge untranslated"' in (tmp_path / "docs/weekly/2026-W44.html").read_text(encoding="utf-8")

    from digest.translator import MyMemoryBackend

    main.run_retranslate(date(2026, 10, 30), root=tmp_path, log=lambda *a: None, use_claude=False,
                         use_google=False, mymemory=MyMemoryBackend(load_glossary(), translate_fn=lambda t: "[mm] " + t))
    data = json.loads((tmp_path / "data/2026/2026-10-30.json").read_text(encoding="utf-8"))
    en = [s for s in data["stories"] if s["lang"] == "en"]
    assert en and all(s["translated"] and s["translation_source"] == "mymemory" for s in en)
    assert data["translation"]["counts"]["untranslated"] == 0
    assert data["translation"]["counts"]["mymemory"] == len(en)
    assert 'class="badge untranslated"' not in (tmp_path / "docs/daily/2026/2026-10-30.html").read_text(encoding="utf-8")
    weekly = (tmp_path / "docs/weekly/2026-W44.html").read_text(encoding="utf-8")
    assert "[mm] " in weekly and 'class="badge untranslated"' not in weekly
    runs = json.loads((tmp_path / "data/usage/2026-10-30.json").read_text(encoding="utf-8"))["runs"]
    assert runs[-1]["retranslate"] is True
