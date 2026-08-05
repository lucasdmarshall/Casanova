"""Query normalization and relevance ranking."""

from __future__ import annotations

import pytest

from hiraraweb.search import (
    SearchResult,
    normalize_query,
    rank_by_relevance,
    relevance_score,
)


def r(title="", snippet="", url="https://example.com/") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


# --- normalization ---------------------------------------------------------

@pytest.mark.parametrize(
    "a,b",
    [
        ("bitcoin price", "Bitcoin Price"),
        ("bitcoin price", "  bitcoin   price  "),
        ("bitcoin price", "bitcoin price?"),
        ("bitcoin price", "BITCOIN PRICE!!"),
        ("bitcoin price", "bitcoin\tprice\n"),
    ],
)
def test_equivalent_queries_share_a_cache_key(a, b):
    assert normalize_query(a) == normalize_query(b)


@pytest.mark.parametrize(
    "a,b",
    [
        # Word order changes the search — sorting tokens here would serve the
        # wrong cached answer.
        ("dog bites man", "man bites dog"),
        ("bitcoin price", "ethereum price"),
        # A trailing full stop is left alone because it is load-bearing
        # elsewhere; these are simply different strings.
        ("node.js streams", "node js streams"),
    ],
)
def test_distinct_queries_keep_distinct_cache_keys(a, b):
    assert normalize_query(a) != normalize_query(b)


def test_normalization_does_not_reorder_or_drop_words():
    assert normalize_query("How to fix the borrow checker") == "how to fix the borrow checker"


# --- relevance scoring -----------------------------------------------------

def test_full_coverage_scores_one():
    result = r(title="Server Side Request Forgery Prevention Cheat Sheet")
    assert relevance_score("server side request forgery prevention", result) == 1.0


def test_the_bing_failure_scores_low():
    """The real case: one word matched, subject entirely different."""
    result = r(title="Server (computing) - Wikipedia", snippet="A server is hardware.")
    score = relevance_score("server-side request forgery prevention", result)
    assert score < 0.35


def test_scoring_reads_title_snippet_and_url():
    assert relevance_score("forgery", r(title="Forgery guide")) == 1.0
    assert relevance_score("forgery", r(snippet="about forgery")) == 1.0
    assert relevance_score("forgery", r(url="https://x.example/forgery")) == 1.0


def test_stopwords_do_not_dominate_the_score():
    """Without stopword removal, matching only 'the'/'of' would look relevant."""
    result = r(title="The Story of the Thing")
    assert relevance_score("what is the capital of france", result) < 0.5


def test_query_with_no_content_words_scores_everything_equally():
    assert relevance_score("?? !!", r(title="anything")) == 1.0


# --- ranking ---------------------------------------------------------------

def test_irrelevant_results_sink_but_are_not_dropped():
    good = r(title="Server Side Request Forgery Prevention")
    bad = r(title="Server (computing)", url="https://example.com/server")
    ranked = rank_by_relevance("server side request forgery prevention", [bad, good])

    assert ranked[0] is good
    # Demotion, not deletion — the point of the design.
    assert len(ranked) == 2
    assert bad in ranked


def test_ranking_is_stable_within_equal_scores():
    """Equal relevance must preserve the backend's own ordering."""
    first = r(title="forgery one")
    second = r(title="forgery two", url="https://example.com/2")
    ranked = rank_by_relevance("forgery", [first, second])
    assert [x.title for x in ranked] == ["forgery one", "forgery two"]


def test_scores_are_exposed_on_results():
    ranked = rank_by_relevance("forgery", [r(title="forgery")])
    assert ranked[0].relevance == 1.0
    assert ranked[0].as_dict()["relevance"] == 1.0


def test_an_acronym_result_is_demoted_not_removed():
    """Why the floor defaults to 0: this result is relevant and scores zero."""
    acronym = r(title="SSRF explained", url="https://example.com/ssrf")
    ranked = rank_by_relevance("server side request forgery", [acronym])
    assert ranked[0].relevance == 0.0
    assert len(ranked) == 1
