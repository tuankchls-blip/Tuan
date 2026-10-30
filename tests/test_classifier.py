"""Test bước 5: phân mục."""

from digest import classifier, filters

from .conftest import art


def classify(a, sources, settings):
    (s,) = filters.cluster([a], sources, settings)
    classifier.classify(s, sources, settings)
    return s


def test_by_source(sources, settings):
    assert classify(art("vnexpress-sohoa", "Bất kỳ tin nào", lang="vi"), sources, settings).category == "vietnam"
    assert classify(art("cisa-kev", "CVE-2026-1: Something"), sources, settings).category == "security"


def test_by_keywords(sources, settings):
    s = classify(art("press", "Ransomware gang exploits zero-day vulnerability"), sources, settings)
    assert s.category == "security"
    s = classify(art("press", "Startup raises $50M in funding, valuation doubles"), sources, settings)
    assert s.category == "business"


def test_default_by_group(sources, settings):
    s = classify(art("lab2", "Something unusual happened"), sources, settings)
    assert s.category == "infra"
    s = classify(art("press", "Something unusual happened"), sources, settings)
    assert s.category == "other"


def test_research_subcategory_uses_tags(sources, settings):
    a = art("hf-papers", "A Paper About Things")
    a.extra["tags"] = ["cs.CV"]
    s = classify(a, sources, settings)
    assert (s.category, s.subcategory) == ("research", "cv")
    s = classify(art("hf-papers", "Untitled thoughts"), sources, settings)
    assert (s.category, s.subcategory) == ("research", "other")
