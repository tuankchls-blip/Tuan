"""Test xuất HTML: thoát ký tự, chặn link nguy hiểm, chia mục, mục lục."""

from datetime import date

from digest import storage
from digest.renderer import Renderer, safe_url
from digest.storage import ROOT, Storage


def make_story(i, **kw):
    s = {
        "id": f"{i:040d}", "url": f"https://example.com/{i}", "source_id": "openai",
        "published_at": "2026-10-29T10:00:00+00:00", "lang": "en",
        "title_orig": f"Title {i}", "summary_orig": "Summary", "title_vi": f"Tiêu đề {i}", "summary_vi": "Tóm tắt",
        "translated": True, "translation_source": "claude", "also_covered_by": [], "category": "models",
        "subcategory": None, "score": 5, "label": "important", "matched_keywords": ["LLM"], "signals": {},
    }
    s.update(kw)
    return s


def make_data(day, stories):
    return {
        "date": day.isoformat(), "generated_at": f"{day.isoformat()}T07:01:00+07:00",
        "window": {"start": "x", "end": f"{day.isoformat()}T07:00:00+07:00"},
        "sources_status": [{"source_id": "openai", "ok": True, "items": 3, "error": None, "note": None},
                           {"source_id": "cacm", "ok": False, "items": 0, "error": "HTTP 403", "note": None}],
        "stories": stories, "translation": {"counts": {"claude": 1, "google": 0, "cache": 0, "untranslated": 1}},
    }


def renderer(tmp_path, settings):
    return Renderer(ROOT / "templates", tmp_path / "docs", settings, storage.load_sources(include_disabled=True))


def test_safe_url():
    assert safe_url("https://a.com/x") == "https://a.com/x"
    assert safe_url("javascript:alert(1)") == "#"
    assert safe_url(None) == "#"


def test_daily_escapes_feed_content(tmp_path, settings):
    evil = make_story(1, title_vi="<script>alert(1)</script>", url="javascript:alert(2)",
                      also_covered_by=[{"source_id": "hackernews", "url": "javascript:x",
                                       "title": "\"><img src=x onerror=alert(3)>"}])
    path = renderer(tmp_path, settings).render_daily(make_data(date(2026, 10, 30), [evil]), None, None)
    html = path.read_text(encoding="utf-8")
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html
    assert 'href="javascript:' not in html
    assert "<img src=x" not in html


def test_daily_content_and_links(tmp_path, settings):
    stories = [
        make_story(1),
        make_story(2, translated=False, title_vi="", summary_vi="", label="notable", category="research",
                   subcategory="cv"),
        make_story(3, category="research", subcategory="nlp",
                   also_covered_by=[{"source_id": "hackernews", "url": "https://news.ycombinator.com/item?id=1", "title": "a"},
                                    {"source_id": "hackernews", "url": "https://news.ycombinator.com/item?id=2", "title": "b"}]),
    ]
    r = renderer(tmp_path, settings)
    html = r.render_daily(make_data(date(2026, 10, 30), stories), date(2026, 10, 29), date(2027, 1, 2)) \
        .read_text(encoding="utf-8")
    assert "Thứ Sáu, 30/10/2026" in html
    assert "Tiêu đề 1" in html and "Title 1" in html            # tiêu đề Việt và tiêu đề gốc
    assert "chưa dịch" in html                                  # tin chưa dịch có nhãn
    assert "Xem bản gốc" in html
    assert "Hacker News #2" in html                             # nguồn lặp được đánh số
    assert 'href="../2026/2026-10-29.html"' in html
    assert 'href="../2027/2027-01-02.html"' in html             # sang năm mới
    assert "HTTP 403" in html and "1/2" in html                 # tình trạng nguồn
    # Mục rỗng bị ẩn; mục Nghiên cứu chia mục con theo thứ tự cấu hình
    assert "Bảo mật</h2>" not in html
    assert html.index("Xử lý ngôn ngữ tự nhiên") < html.index("Thị giác máy tính")
    assert "<link" not in html and "<script src" not in html    # tự chứa, không tải gì bên ngoài


def test_empty_day(tmp_path, settings):
    html = renderer(tmp_path, settings).render_daily(make_data(date(2026, 10, 30), []), None, None) \
        .read_text(encoding="utf-8")
    assert "Không có tin nào" in html


def test_index_and_search(tmp_path, settings):
    st = Storage(tmp_path / "data")
    st.save_daily(date(2026, 10, 29), make_data(date(2026, 10, 29), [make_story(1)]))
    st.save_daily(date(2026, 10, 30), make_data(date(2026, 10, 30), [make_story(2), make_story(3, label="notable")]))
    r = renderer(tmp_path, settings)
    (tmp_path / "docs/weekly").mkdir(parents=True)
    (tmp_path / "docs/weekly/2026-W44.html").write_text("x", encoding="utf-8")
    html = r.render_index(st).read_text(encoding="utf-8")
    assert "Bản mới nhất" in html and "daily/2026/2026-10-30.html" in html
    assert "daily/2026/2026-10-29.html" in html
    assert "weekly/2026-W44.html" in html
    js = r.write_search_index(st).read_text(encoding="utf-8")
    assert js.startswith("window.DIGEST_SEARCH=") and js.index("Tiêu đề 2") < js.index("Tiêu đề 1")


# ---------------------------------------------------------------- Bản tổng hợp


def test_summary_titles():
    t = Renderer.summary_title
    assert t("weekly", "2026-W53") == "Tuần 53/2026"
    assert t("monthly", "2026-01") == "Tháng 1/2026"
    assert t("quarterly", "2026-Q4") == "Quý IV/2026"
    assert t("yearly", "2026") == "Năm 2026"


def test_summary_pages_render(tmp_path, settings):
    from datetime import datetime, timezone

    from digest.aggregator import Aggregator, period_for

    st = Storage(tmp_path / "data")
    for d in (date(2026, 12, 30), date(2027, 1, 2)):
        evil = make_story(9, title_vi="<script>x</script>", url="javascript:alert(1)", score=9)
        st.save_daily(d, make_data(d, [make_story(d.day, score=8, category="models"), evil]))
    agg = Aggregator(st, settings, now=datetime(2027, 1, 10, tzinfo=timezone.utc))
    r = renderer(tmp_path, settings)
    pages = {}
    for kind in ("weekly", "monthly", "quarterly", "yearly"):
        p = period_for(kind, date(2026, 12, 30))
        agg.build_and_save(p)
        pages[kind] = r.render_summary_and_neighbors(st, kind, p.key).read_text(encoding="utf-8")

    w = pages["weekly"]
    assert "Bản tin tuần 53/2026" in w and "28/12/2026 – 03/01/2027" in w
    assert 'href="../daily/2027/2027-01-02.html#s-' in w      # link về bản ngày năm sau
    assert "&lt;script&gt;" in w and 'href="javascript:' not in w
    assert "Chủ đề so với tuần 52/2026" in w
    assert "Kỳ chưa kết thúc" not in w
    assert "Dòng thời gian" in pages["yearly"] and "Tháng 12/2026" in pages["yearly"]
    assert "Xu hướng theo tháng" in pages["quarterly"] and "Bản tin quý IV/2026" in pages["quarterly"]
    assert "Xu hướng theo tuần" in pages["monthly"] and "Tuần 53/2026 (28/12–03/01)" in pages["monthly"]

    # Kỳ sau được tạo thì kỳ trước có link "kỳ sau"
    agg.build_and_save(period_for("weekly", date(2027, 1, 5)))
    r.render_summary_and_neighbors(st, "weekly", "2027-W01")
    assert 'href="2027-W01.html"' in (tmp_path / "docs/weekly/2026-W53.html").read_text(encoding="utf-8")

    index = r.render_index(st).read_text(encoding="utf-8")
    for text in ("Tuần 53/2026", "Tháng 12/2026", "Quý IV/2026", "Năm 2026", 'href="weekly/2026-W53.html"'):
        assert text in index
