"""Test bước 1: đọc từng loại nguồn bằng dữ liệu mẫu, không gọi mạng."""

from datetime import datetime, timezone

import requests

from digest import fetcher
from digest.fetcher import clean_text, fetch_all, fetch_source, slug_to_title

from .conftest import NOW, fixture_getter


def test_clean_text_strips_html_and_truncates():
    assert clean_text("<p>A &amp; <b>B</b>\n\n C</p>") == "A & B C"
    assert clean_text("one two three four", max_chars=9) == "one two…"
    assert clean_text(None) == ""


def test_rss_parses_entries(sources, ctx):
    arts, note = fetcher.fetch_rss(sources["lab"], ctx, fixture_getter("rss_sample.xml"))
    titles = [a.title for a in arts]
    assert "Introducing Model X: an open-weight LLM" in titles
    assert "A post without a date" not in titles
    assert "bỏ 1 mục không có ngày" in note
    x = arts[0]
    assert x.summary.startswith("We release Model X")
    assert "<" not in x.summary
    assert x.arxiv_ids == {"2610.00001"}
    assert x.published_at == datetime(2026, 10, 29, 10, tzinfo=timezone.utc)


def test_rss_future_date_is_clamped(sources, ctx):
    arts, _ = fetcher.fetch_rss(sources["lab"], ctx, fixture_getter("rss_sample.xml"))
    future = next(a for a in arts if a.title == "Future dated post")
    assert future.published_at == NOW


def test_arxiv_skips_replacements_and_cleans_prefix(sources, ctx):
    arts, note = fetcher.fetch_rss(sources["arxiv"], ctx, fixture_getter("arxiv_sample.xml"))
    assert [a.title for a in arts] == ["Model X: Scaling Open-Weight Language Models", "An Unconfirmed Paper"]
    assert arts[0].summary == "We present Model X, a large language model."
    assert arts[0].extra["tags"] == ["cs.CL"]
    assert "bỏ 1 mục cập nhật bài cũ" in note


def test_atom_finds_arxiv_link_in_content(sources, ctx):
    arts, _ = fetcher.fetch_rss(sources["expert"], ctx, fixture_getter("atom_sample.xml"))
    assert arts[0].arxiv_ids == {"2610.00001"}


def test_hf_papers_queries_each_day(sources, ctx):
    get = fixture_getter("hf_papers.json")
    arts, _ = fetcher.fetch_hf_papers(sources["hf-papers"], ctx, get)
    # khung 28/10 -> 30/10 (UTC) = 3 ngày, mỗi ngày một lần gọi
    assert [p["date"] for _, p in get.calls] == ["2026-10-28", "2026-10-29", "2026-10-30"]
    first = arts[0]
    assert first.url == "https://huggingface.co/papers/2610.00001"
    assert first.extra["hf_upvotes"] == 25
    assert first.arxiv_ids == {"2610.00001"}
    assert first.published_at == datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_hackernews_params_and_fields(sources, ctx):
    get = fixture_getter("hackernews.json")
    arts, _ = fetcher.fetch_hackernews(sources["hackernews"], ctx, get)
    params = get.calls[0][1]
    assert "points>=200" in params["numericFilters"]
    assert f"created_at_i>={int(ctx.since.timestamp())}" in params["numericFilters"]
    assert arts[0].extra["hn_points"] == 640
    # bài không có url thì dùng trang thảo luận HN
    assert arts[1].url == "https://news.ycombinator.com/item?id=101"


def test_cisa_kev_keeps_recent_only(sources, ctx):
    arts, _ = fetcher.fetch_cisa_kev(sources["cisa-kev"], ctx, fixture_getter("cisa_kev.json"))
    assert len(arts) == 1
    a = arts[0]
    assert a.title.startswith("CVE-2026-0001:")
    assert a.url == "https://nvd.nist.gov/vuln/detail/CVE-2026-0001"
    assert "ransomware" in a.summary
    assert a.published_at == datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def test_crossref_strips_jats_and_skips_untitled(sources, ctx):
    arts, _ = fetcher.fetch_crossref(sources["cacm"], ctx, fixture_getter("crossref.json"))
    assert len(arts) == 1
    assert arts[0].summary == "We argue that agency is a new abstraction."
    assert arts[0].url == "https://doi.org/10.1145/0000001"


def test_sitemap_first_run_only_records(sources, ctx):
    ctx.sitemap_known = {"anthropic": None}
    arts, note, urls = fetcher.fetch_sitemap(sources["anthropic"], ctx, fixture_getter("sitemap.xml"))
    assert arts == []
    assert "khởi tạo" in note
    assert urls == {
        "https://lab.example.com/news/old-announcement",
        "https://lab.example.com/news/claude-new-model-launch",
        "https://lab.example.com/news/edited-old-post",
    }


def test_sitemap_reports_only_new_urls(sources, ctx):
    ctx.sitemap_known = {"anthropic": {"https://lab.example.com/news/old-announcement",
                                       "https://lab.example.com/news/edited-old-post"}}
    arts, note, urls = fetcher.fetch_sitemap(sources["anthropic"], ctx, fixture_getter("sitemap.xml"))
    assert [a.title for a in arts] == ["Claude new model launch"]
    assert arts[0].published_at == datetime(2026, 10, 29, 15, tzinfo=timezone.utc)
    assert len(urls) == 3


def test_slug_to_title():
    assert slug_to_title("https://x.com/news/expanding-partnership_gsa/") == "Expanding partnership gsa"


def test_one_failing_source_does_not_stop_others(sources, ctx):
    def get(url, params):
        if "press" in url:
            resp = requests.Response()
            resp.status_code = 403
            raise requests.HTTPError(response=resp)
        return fixture_getter("rss_sample.xml")(url, params)

    results = fetch_all([sources["press"], sources["lab"]], ctx, get, max_workers=2)
    assert [r.source_id for r in results] == ["press", "lab"]
    assert results[0].ok is False and results[0].error == "HTTP 403"
    assert results[1].ok is True and results[1].articles


def test_unknown_type_is_reported(sources, ctx):
    src = sources["lab"]
    src.type = "gopher"
    r = fetch_source(src, ctx, fixture_getter("rss_sample.xml"))
    assert not r.ok and "gopher" in r.error


def test_wordpress_boilerplate_removed():
    from digest.fetcher import BOILERPLATE_RE

    text = ("We share results. Our paper fully details [...] Read More... "
            "The post Catching Bugs appeared first on Engineering at Meta .")
    for _ in range(2):
        text = BOILERPLATE_RE.sub("", text)
    assert text == "We share results. Our paper fully details"


def test_hf_papers_tolerates_one_bad_day(sources, ctx):
    good = fixture_getter("hf_papers.json")

    def get(url, params):
        if params["date"] == "2026-10-28":
            resp = requests.Response()
            resp.status_code = 400
            raise requests.HTTPError(response=resp)
        return good(url, params)

    arts, note = fetcher.fetch_hf_papers(sources["hf-papers"], ctx, get)
    assert arts and note == "1 ngày đọc lỗi"


def test_hf_papers_does_not_ask_future_dates(sources, ctx):
    ctx.now = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)  # chạy sớm hơn mốc chốt
    get = fixture_getter("hf_papers.json")
    fetcher.fetch_hf_papers(sources["hf-papers"], ctx, get)
    assert [p["date"] for _, p in get.calls] == ["2026-10-28", "2026-10-29"]
