"""Test bước 2–3: khung giờ, chuẩn hóa URL, gom sự kiện, bỏ tin đã đăng."""

from datetime import date, datetime, timezone

from digest import filters
from digest.models import normalize_url

from .conftest import DAY, SINCE, UNTIL, art

# Tiêu đề nhiễu khác hẳn nhau, để tính độ hiếm của từ như một ngày thật
NOISE = [
    "Chipmaker unveils faster memory for data centers",
    "Regulators question streaming merger",
    "Browser update patches password bug",
    "Satellite startup lands defense contract",
    "Researchers map protein folding errors",
    "Electric truck maker delays deliveries",
    "Court rules on encryption backdoor request",
    "Robot vacuum firm cuts staff",
    "Weather model predicts storms earlier",
    "Quantum lab reports stable qubits",
]


def test_daily_window_is_fixed_at_cutoff(settings):
    start, end = filters.daily_window(date(2026, 10, 30), settings)
    assert end.isoformat() == "2026-10-30T07:00:00+07:00"
    assert start.isoformat() == "2026-10-29T07:00:00+07:00"


def test_normalize_url():
    strip = ["utm_source", "ref"]
    assert normalize_url("http://www.Example.com/a/?utm_source=x&id=2#top", strip) == "https://example.com/a?id=2"
    assert normalize_url("https://arxiv.org/pdf/2610.00001v3") == "https://arxiv.org/abs/2610.00001"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_prepare_sets_ids_and_drops_same_source_duplicates():
    a1 = art("lab", "T", url="https://lab.example.com/x?utm_source=rss")
    a2 = art("lab", "T", url="https://lab.example.com/x")
    out = filters.prepare([a1, a2], ["utm_source"])
    assert len(out) == 1 and len(out[0].id) == 40


def test_within_keeps_window_but_not_for_preprints(sources):
    inside = art("lab", "in", published=datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    old = art("lab", "old", published=datetime(2026, 10, 1, tzinfo=timezone.utc))
    paper = art("arxiv", "paper", published=datetime(2026, 10, 30, 4, tzinfo=timezone.utc))
    kept = filters.within([inside, old, paper], sources, SINCE, UNTIL)
    assert [a.title for a in kept] == ["in", "paper"]


def test_drop_unconfirmed_preprints(sources):
    confirmed = art("arxiv", "P1", url="https://arxiv.org/abs/2610.00001")
    lonely = art("arxiv", "P2", url="https://arxiv.org/abs/2610.00002")
    hf = art("hf-papers", "P1", url="https://huggingface.co/papers/2610.00001")
    hf.arxiv_ids = {"2610.00001"}
    kept, n = filters.drop_unconfirmed_preprints([confirmed, lonely, hf], sources, ["community", "expert"])
    assert n == 1 and lonely not in kept


def test_cluster_by_same_url_and_primary_is_highest_weight(sources, settings):
    hn = art("hackernews", "Something", url="https://lab.example.com/post", hn_points=500)
    lab = art("lab", "Our new post", url="https://lab.example.com/post?utm_source=hn")
    lab.id, lab.norm_url = hn.id, hn.norm_url  # cùng URL sau chuẩn hóa
    stories = filters.cluster([hn, lab], sources, settings)
    assert len(stories) == 1
    assert stories[0].primary.source_id == "lab"
    assert [a.source_id for a in stories[0].others] == ["hackernews"]


def test_cluster_by_arxiv_id(sources, settings):
    paper = art("arxiv", "A Paper", url="https://arxiv.org/abs/2610.00001")
    blog = art("expert", "Notes on something", url="https://expert.example.com/notes")
    blog.arxiv_ids = {"2610.00001"}
    stories = filters.cluster([paper, blog], sources, settings)
    assert len(stories) == 1 and stories[0].primary.source_id == "arxiv"


def test_cluster_by_similar_title(sources, settings):
    a = art("press", "OpenAI releases GPT-6 with better reasoning")
    b = art("press2", "OpenAI releases GPT-6, with better reasoning!")
    assert len(filters.cluster([a, b], sources, settings)) == 1


def test_cluster_by_shared_distinctive_words(sources, settings):
    # Tiêu đề viết khác nhau về cùng sự kiện, kèm nhiều tin khác để tính độ hiếm của từ
    noise = [art("press3", t) for t in NOISE]
    a = art("lab", "Welcome Le Chonk: Mistral Large 4 on Hugging Face")
    b = art("hackernews", "We're releasing the weights of Mistral Large 4")
    stories = filters.cluster([a, b, *noise], sources, settings)
    merged = [s for s in stories if s.others]
    assert len(merged) == 1 and merged[0].primary is a


def test_cluster_does_not_merge_common_words_only(sources, settings):
    noise = [art("press3", t) for t in NOISE]
    a = art("expert", "Building a multiplayer game world with autonomous models")
    b = art("hackernews", "A tiny world model running games on a microcontroller")
    stories = filters.cluster([a, b, *noise], sources, settings)
    assert not any(s.others for s in stories)


def test_cluster_never_mixes_languages(sources, settings):
    a = art("press", "Apple ra mắt iPhone 18")
    b = art("vnexpress-sohoa", "Apple ra mắt iPhone 18", lang="vi")
    assert len(filters.cluster([a, b], sources, settings)) == 2


def test_select_new_window_and_seen(sources, settings):
    start, end = filters.daily_window(DAY, settings)
    fresh = art("lab", "Fresh", published=datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    stale = art("press", "Stale", published=datetime(2026, 10, 28, 12, tzinfo=timezone.utc))
    shown = art("press2", "Shown yesterday", published=datetime(2026, 10, 29, 3, tzinfo=timezone.utc))
    stories = filters.cluster([fresh, stale, shown], sources, settings)
    seen = {shown.id: "2026-10-29"}
    kept, old, published = filters.select_new(stories, sources, start, end, seen, DAY)
    assert [s.primary.title for s in kept] == ["Fresh"]
    assert (old, published) == (1, 1)


def test_select_new_same_day_rerun_keeps_story(sources, settings):
    start, end = filters.daily_window(DAY, settings)
    a = art("lab", "Fresh", published=datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    stories = filters.cluster([a], sources, settings)
    kept, _, _ = filters.select_new(stories, sources, start, end, {a.id: DAY.isoformat()}, DAY)
    assert len(kept) == 1
