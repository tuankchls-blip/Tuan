"""Test bước 4: chấm điểm và gắn nhãn."""

from digest import filters, scorer

from .conftest import art


def score(stories_articles, sources, settings):
    stories = filters.cluster(stories_articles, sources, settings)
    for s in stories:
        scorer.score_story(s, sources, settings)
    return stories


def test_acronyms_are_case_sensitive():
    assert scorer.find_terms(["AI"], "Ai cũng biết điều này") == []
    assert scorer.find_terms(["AI"], "New AI model") == ["AI"]
    assert scorer.find_terms(["LLMs"], "Open LLMs today") == ["LLMs"]
    assert scorer.find_terms(["reasoning"], "Better Reasoning") == ["reasoning"]


def test_keywords_match_whole_words_and_regex():
    assert scorer.find_terms(["sale"], "wholesale prices") == []
    assert scorer.find_terms(["re:best .{0,40} to buy"], "The best laptops to buy now") == ["re:best .{0,40} to buy"]
    assert scorer.find_terms(["large language model"], "a large  language model") == ["large language model"]


def test_tier_points():
    tiers = {200: 1, 500: 2, 1000: 3}
    assert [scorer.tier_points(v, tiers) for v in (100, 200, 640, 5000)] == [0, 1, 2, 3]


def test_origin_weight3_always_important(sources, settings):
    (s,) = score([art("lab", "Quarterly update")], sources, settings)
    assert s.label == "important"
    assert any("công bố gốc" in r for r in s.reasons)


def test_excluded_keyword_overrides_always_rule(sources, settings):
    (s,) = score([art("lab", "Our new podcast episode")], sources, settings)
    assert s.label is None and s.score < 0


def test_press_needs_keywords(sources, settings):
    weak, strong = score(
        [art("press", "Company changes office plants"),
         art("press2", "New open-weight LLM tops benchmark")],
        sources, settings,
    )
    by_title = {s.primary.title: s for s in (weak, strong)}
    assert by_title["Company changes office plants"].label is None
    s = by_title["New open-weight LLM tops benchmark"]
    assert s.label == "notable"
    assert "LLM" in s.matched_keywords and "open-weight" in s.matched_keywords


def test_three_independent_sources_important(sources, settings):
    t = "Startup Zeta raises funding for robots"
    (s,) = score([art("press", t), art("press2", t + "!"), art("expert", t + ".")], sources, settings)
    assert s.label == "important"
    assert any("3 nguồn độc lập" in r for r in s.reasons)


def test_hackernews_is_not_independent_source(sources, settings):
    t = "Startup Zeta raises funding for robots"
    (s,) = score([art("press", t), art("press2", t + "!"), art("hackernews", t, hn_points=250)], sources, settings)
    assert not any("nguồn độc lập" in r for r in s.reasons)


def test_community_only_needs_keyword(sources, settings):
    (s,) = score([art("hackernews", "A famous actor has died", hn_points=3000)], sources, settings)
    assert s.label is None
    (s,) = score([art("hackernews", "Running an LLM on a calculator", hn_points=3000)], sources, settings)
    assert s.label in ("notable", "important")


def test_cisa_kev_always_important(sources, settings):
    (s,) = score([art("cisa-kev", "CVE-2026-0001: Router RCE")], sources, settings)
    assert s.label == "important"


def test_ai_law_always_important(sources, settings):
    (s,) = score([art("press", "EU AI Act enters into force for general-purpose models")], sources, settings)
    assert s.label == "important"
    assert any("luật" in r for r in s.reasons)


def test_unconfirmed_preprint_dropped(sources, settings):
    (s,) = score([art("arxiv", "A great LLM reasoning benchmark", url="https://arxiv.org/abs/2610.00002")],
                 sources, settings)
    assert s.label is None


def test_vietnam_group_has_lower_threshold(sources, settings):
    (s,) = score([art("vnexpress-sohoa", "Việt Nam đẩy mạnh trí tuệ nhân tạo", lang="vi")], sources, settings)
    assert s.label == "notable"


def test_score_all_sorts_important_first(sources, settings):
    stories = filters.cluster(
        [art("press2", "New open-weight LLM tops benchmark"), art("lab", "Quarterly update")], sources, settings
    )
    kept, dropped = scorer.score_all(stories, sources, settings)
    assert [s.label for s in kept] == ["important", "notable"]


def test_security_keywords_lift_security_news(sources, settings):
    (s,) = score([art("press", "Hackers exploit zero-day in popular VPN appliance")], sources, settings)
    assert s.label == "notable"
    assert "zero-day" in s.matched_keywords


def test_press_with_single_ai_keyword_is_notable(sources, settings):
    (s,) = score([art("press", "Anthropic is asking Wall Street to believe in AGI and AI")], sources, settings)
    assert s.label == "notable"
    (s,) = score([art("press", "Carmaker recalls trucks over brake issue")], sources, settings)
    assert s.label is None


def test_routine_lab_posts_not_automatically_important(sources, settings):
    (s,) = score([art("lab", "How Acme Corp is using AI for contract review")], sources, settings)
    assert s.label == "notable"
    (s,) = score([art("lab", "Research Focus – Edition #97")], sources, settings)
    assert s.label != "important"
    (s,) = score([art("lab", "How we detect frontier model misalignment")], sources, settings)
    assert s.label == "important"


def test_hf_papers_need_min_upvotes(sources, settings):
    (s,) = score([art("hf-papers", "A new LLM reasoning benchmark", hf_upvotes=2)], sources, settings)
    assert s.label is None and any("tối thiểu" in r for r in s.reasons)
    (s,) = score([art("hf-papers", "A new LLM reasoning benchmark", hf_upvotes=6)], sources, settings)
    assert s.label is not None
