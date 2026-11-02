"""Test bản tổng hợp với dữ liệu ngày giả lập hơn một năm (01/12/2025 → 15/01/2027)."""

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from digest import aggregator
from digest.aggregator import Aggregator, due_kinds, last_completed, period_for, sub_periods
from digest.storage import Storage

START, END = date(2025, 12, 1), date(2027, 1, 15)
MISSING = {date(2026, 3, 10), date(2026, 3, 11)}  # hai ngày workflow không chạy
CATS = ["models", "research", "security", "business", "infra"]
KEYWORDS = [["LLM"], ["benchmark"], ["zero-day"], ["GPU"], []]


def make_story(day: date, i: int) -> dict:
    sid = hashlib.sha1(f"{day}-{i}".encode()).hexdigest()
    return {
        "id": sid, "url": f"https://example.com/{sid}", "source_id": ["openai", "deepmind", "krebs"][i % 3],
        "published_at": f"{day}T01:00:00+00:00", "lang": "en",
        "title_orig": f"Report {sid[:12]} on {sid[12:24]}", "summary_orig": "", "title_vi": f"Tin {i} ngày {day}",
        "summary_vi": "", "translated": True, "also_covered_by": [], "category": CATS[i % 5],
        "subcategory": "nlp" if CATS[i % 5] == "research" else None,
        "score": 10 - i + (day.day % 3), "label": "important" if i < 3 else "notable",
        "matched_keywords": KEYWORDS[i % 5],
    }


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    st = Storage(tmp_path_factory.mktemp("data"))
    day = START
    while day <= END:
        if day not in MISSING:
            stories = [make_story(day, i) for i in range(6)]
            st.save_daily(day, {"date": day.isoformat(), "stories": stories, "sources_status": []})
        day += timedelta(days=1)
    # Một sự kiện được đưa tin ba ngày trong tuần 2026-W44
    for d, title in [(date(2026, 10, 27), "Mistral releases Mistral Large 4 open weights"),
                     (date(2026, 10, 28), "Mistral Large 4 tops coding benchmark"),
                     (date(2026, 10, 30), "Developers react to Mistral Large 4 license")]:
        data = st.load_daily(d)
        s = make_story(d, 9)
        s.update(title_orig=title, label="important", score=20)
        data["stories"].append(s)
        st.save_daily(d, data)
    return st


@pytest.fixture
def agg(store, settings):
    return Aggregator(store, settings, now=datetime(2027, 1, 16, tzinfo=timezone.utc))


# ---------------------------------------------------------------- Ranh giới kỳ


def test_iso_week_53_crosses_into_2027():
    w = period_for("weekly", date(2027, 1, 3))
    assert (w.key, w.start, w.end) == ("2026-W53", date(2026, 12, 28), date(2027, 1, 3))
    assert period_for("weekly", date(2026, 12, 28)) == w
    assert period_for("weekly", date(2027, 1, 4)).key == "2027-W01"
    assert period_for("weekly", date(2026, 1, 1)).key == "2026-W01"   # 01/01/2026 là Thứ Năm
    assert period_for("weekly", date(2025, 12, 29)).key == "2026-W01"  # tuần ISO đầu năm bắt đầu từ 2025


def test_month_quarter_year_bounds():
    assert period_for("monthly", date(2026, 2, 14)).end == date(2026, 2, 28)
    assert period_for("monthly", date(2028, 2, 14)).end == date(2028, 2, 29)  # năm nhuận
    assert period_for("monthly", date(2026, 12, 31)).key == "2026-12"
    q = period_for("quarterly", date(2026, 11, 2))
    assert (q.key, q.start, q.end) == ("2026-Q4", date(2026, 10, 1), date(2026, 12, 31))
    assert period_for("yearly", date(2026, 7, 4)).key == "2026"


def test_every_day_belongs_to_exactly_one_period_of_each_kind():
    for kind in aggregator.KINDS:
        periods = sub_periods(period_for("yearly", date(2026, 6, 1)), kind)
        covered = [d for p in periods for d in p.days if d.year == 2026]
        assert covered == period_for("yearly", date(2026, 6, 1)).days
        for a, b in zip(periods, periods[1:]):
            assert b.start == a.end + timedelta(days=1)


def test_month_children_are_overlapping_weeks():
    weeks = period_for("monthly", date(2026, 10, 1)).children()
    assert [w.key for w in weeks] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert weeks[0].start == date(2026, 9, 28) and weeks[-1].end == date(2026, 11, 1)


def test_last_completed_and_due():
    assert last_completed("weekly", date(2026, 11, 2)).key == "2026-W44"
    assert last_completed("weekly", date(2027, 1, 4)).key == "2026-W53"
    assert last_completed("monthly", date(2026, 11, 1)).key == "2026-10"
    assert last_completed("quarterly", date(2027, 1, 1)).key == "2026-Q4"
    assert last_completed("yearly", date(2027, 1, 1)).key == "2026"
    assert due_kinds(date(2026, 11, 2)) == ["weekly"]
    assert due_kinds(date(2026, 11, 3)) == []
    assert due_kinds(date(2027, 1, 1)) == ["monthly", "quarterly", "yearly"]
    assert due_kinds(date(2026, 6, 1)) == ["weekly", "monthly"]  # Thứ Hai và ngày 1


def test_invalid_kind():
    with pytest.raises(ValueError):
        period_for("daily", date(2026, 1, 1))


# ---------------------------------------------------------------- Bản tổng hợp


def test_weekly_w53_spans_two_years(agg):
    s = agg.build(period_for("weekly", date(2027, 1, 1)))
    assert s["key"] == "2026-W53" and s["start"] == "2026-12-28" and s["end"] == "2027-01-03"
    assert s["days_total"] == 7 and len(s["days_with_data"]) == 7
    days = {h["day"] for h in s["highlights"]}
    assert any(d.startswith("2026") for d in days) and any(d.startswith("2027") for d in days)
    assert all(h["label"] == "important" for h in s["highlights"])
    assert s["stats"]["stories"] == 7 * 6
    assert len(s["highlights"]) <= agg.cfg["weekly"]["max_highlights"]


def test_stats_come_from_daily_data_not_weeks(agg):
    jan = agg.build(period_for("monthly", date(2027, 1, 10)))
    # Tháng 1/2027 có dữ liệu 01–15/01, dù tuần W53 bắt đầu từ năm 2026
    assert jan["stats"]["stories"] == 15 * 6
    assert all(h["day"].startswith("2027-01") for h in jan["highlights"])
    mar = agg.build(period_for("monthly", date(2026, 3, 1)))
    assert mar["stats"]["stories"] == (31 - 2) * 6 and len(mar["days_with_data"]) == 29


def test_highlights_follow_hierarchy(agg):
    year = period_for("yearly", date(2026, 1, 1))
    ids = lambda hs: {h["id"] for h in hs}  # noqa: E731
    y = agg.highlights(year)
    quarters = set().union(*(ids(agg.highlights(q)) for q in year.children()))
    assert ids(y) <= quarters
    for q in year.children():
        months = set().union(*(ids(agg.highlights(m)) for m in q.children()))
        assert ids(agg.highlights(q)) <= months
        for m in q.children():
            weeks = set().union(*(ids(agg.highlights(w)) for w in m.children()))
            assert ids(agg.highlights(m)) <= weeks
    assert len(y) == agg.cfg["yearly"]["max_highlights"]
    keys = [aggregator.rank_key(h) for h in y]
    assert keys == sorted(keys)


def test_topics_compare_with_previous_period(agg):
    s = agg.build(period_for("weekly", date(2026, 10, 28)))
    topics = {t["topic"]: t for t in s["topics"]}
    llm = topics["Mô hình ngôn ngữ"]
    assert llm["count"] == 7 * 2 and llm["previous"] == 7 * 2 and llm["delta"] == 0
    assert s["previous_key"] == "2026-W43"


def test_multi_day_event_detected(agg):
    s = agg.build(period_for("weekly", date(2026, 10, 28)))
    events = s["multi_day_events"]
    assert len(events) == 1
    assert events[0]["days"] == ["2026-10-27", "2026-10-28", "2026-10-30"]
    assert len(s["research"]) <= agg.cfg["weekly"]["research_picks"]
    assert all(r["category"] == "research" for r in s["research"])


def test_quarter_and_year_extras(agg):
    q = agg.build(period_for("quarterly", date(2026, 11, 2)))
    assert [r["key"] for r in q["series"]] == ["2026-10", "2026-11", "2026-12"]
    assert all(h["category"] == "models" for h in q["major_releases"])
    y = agg.build(period_for("yearly", date(2026, 5, 5)))
    assert len(y["series"]) == 12
    months = [t["month"] for t in y["timeline"]]
    assert months == sorted(months) and all(m.startswith("2026-") for m in months)
    assert sum(len(t["highlights"]) for t in y["timeline"]) == len(y["highlights"])
    assert y["stats"]["stories"] == (365 - 2) * 6 + 3


def test_empty_period(agg):
    s = agg.build(period_for("weekly", date(2030, 1, 1)))
    assert s["highlights"] == [] and s["stats"]["stories"] == 0 and s["days_with_data"] == []


def test_build_and_save(agg, store):
    agg.build_and_save(period_for("weekly", date(2027, 1, 1)))
    assert store.load_summary("weekly", "2026-W53")["end"] == "2027-01-03"
    assert "2026-W53" in store.list_summaries("weekly")


def test_days_expected_ignores_days_before_project_and_future(store, settings):
    # Dữ liệu giả bắt đầu 01/12/2025; "hôm nay" là 05/01/2027
    agg = Aggregator(store, settings, now=datetime(2027, 1, 5, 3, tzinfo=timezone.utc))
    nov = agg.build(period_for("monthly", date(2025, 11, 20)))
    assert nov["days_expected"] == [] and nov["complete"]
    mar = agg.build(period_for("monthly", date(2026, 3, 1)))
    assert len(mar["days_expected"]) - len(mar["days_with_data"]) == 2   # hai ngày thiếu thật
    jan = agg.build(period_for("monthly", date(2027, 1, 1)))
    assert not jan["complete"] and jan["days_expected"][-1] == "2027-01-05"
