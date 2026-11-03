import json
from io import BytesIO
from pathlib import Path

import pytest

from src.api import scheme_search as scheme_search_module
from src.api.scheme_search import (
    HybridSchemeRetriever,
    OpenRouterEmbeddings,
    OpenRouterReranker,
    decompose_query,
    load_passages,
    reciprocal_rank_fusion,
)


PASSAGE_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "schemes"
    / "passages.json"
)


def build_retriever(passages):
    return HybridSchemeRetriever(
        passages,
        vector_search=lambda query, candidates, limit: [
            passage.passage_id for passage in candidates[:limit]
        ],
        rerank=lambda query, candidates: [
            sum(
                term in HybridSchemeRetriever.document_text(passage).casefold()
                for term in query.casefold().split()
            )
            for passage in candidates
        ],
    )


def test_openrouter_embeddings_prefers_free_api_key(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return BytesIO(
            json.dumps(
                {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
            ).encode()
        )

    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "free-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "default-key")
    monkeypatch.setattr(
        scheme_search_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    vectors = OpenRouterEmbeddings().embed(["test passage"])

    assert vectors == [[0.1, 0.2]]
    assert requests[0].get_header("Authorization") == 'Bearer free-key'


def test_embeddings_do_not_fall_back_to_chat_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY_FREE", raising=False)
    monkeypatch.delenv("OPEN_ROUTER_FREE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-key")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY_FREE"):
        OpenRouterEmbeddings()


def test_openrouter_reranker_returns_scores_in_document_order(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return BytesIO(
            json.dumps(
                {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(
        scheme_search_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    passages = load_passages(PASSAGE_FILE)[:2]
    reranker = OpenRouterReranker(api_key="rerank-test-key")

    scores = reranker("widow pension", passages)

    assert scores == [0.1, 0.9]
    assert requests[0].full_url == scheme_search_module.OPENROUTER_RERANK_URL
    assert requests[0].get_header("Authorization") == 'Bearer rerank-test-key'
    payload = json.loads(requests[0].data)
    assert payload["model"] == "cohere/rerank-v3.5"
    assert payload["query"] == "widow pension"
    assert payload["top_n"] == 2
    assert len(payload["documents"]) == 2


def test_openrouter_reranker_rejects_incomplete_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return BytesIO(
            json.dumps(
                {"results": [{"index": 0, "relevance_score": 0.9}]}
            ).encode()
        )

    monkeypatch.setattr(
        scheme_search_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )
    passages = load_passages(PASSAGE_FILE)[:2]

    with pytest.raises(RuntimeError, match="invalid reranking response"):
        OpenRouterReranker(api_key="rerank-test-key")(
            "widow pension",
            passages,
        )


def test_openrouter_reranker_requires_embedding_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY_FREE", raising=False)
    monkeypatch.delenv("OPEN_ROUTER_FREE", raising=False)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY_FREE"):
        OpenRouterReranker()("widow pension", load_passages(PASSAGE_FILE)[:1])


def test_reviewed_passage_can_be_found_and_is_marked_reviewed():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages).search("below poverty line")

    assert results[0].passage_id == "IGNWPS-MH-ELIGIBILITY-01"
    assert all(result.review_status == "reviewed" for result in results)


def test_search_uses_both_retrieval_lists_and_returns_citations():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages).search("widow pension")

    assert results
    assert results[0].scheme_id == "IGNWPS-MH"
    assert any(
        result.passage_id == "IGNWPS-MH-ELIGIBILITY-01"
        for result in results
    )
    assert all(str(result.source.url).startswith("https://") for result in results)


def test_search_ranks_pm_kisan_for_farmer_support_query():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages).search(
        "farmer land records direct benefit transfer"
    )

    assert results
    assert results[0].scheme_id == "PM-KISAN-IN"
    assert results[0].source.source_id == "SRC-PMKISAN-IN-002"
    assert results[0].source.locator


def test_bm25_ranks_specific_passage_above_shared_scheme_metadata():
    passages = load_passages(PASSAGE_FILE)
    retriever = build_retriever(passages)

    results = retriever._bm25_search("below poverty line", tuple(passages))

    assert results == ["IGNWPS-MH-ELIGIBILITY-01"]


def test_bm25_does_not_return_passages_without_query_terms():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages)._bm25_search("volcano", tuple(passages))

    assert results == []


def test_search_finds_benefit_passage_by_content():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages).search("1500 month")

    assert results
    assert results[0].passage_id == "IGNWPS-MH-BENEFIT-01"


def test_reviewed_passage_can_be_found():
    passages = load_passages(PASSAGE_FILE)

    # Make a reviewed copy for this test; the source JSON stays pending review.
    reviewed_passage = passages[0].model_copy(
        update={"review_status": "reviewed"}
    )

    results = build_retriever([reviewed_passage]).search("below poverty line")

    assert len(results) == 1
    assert results[0].passage_id == "IGNWPS-MH-ELIGIBILITY-01"


def test_search_can_filter_by_jurisdiction():
    passages = load_passages(PASSAGE_FILE)
    reviewed_passage = passages[0].model_copy(
        update={"review_status": "reviewed"}
    )

    results = build_retriever([reviewed_passage]).search(
        "widow",
        jurisdiction="IN-KA",
    )

    assert results == ()


def test_search_respects_result_limit():
    passages = load_passages(PASSAGE_FILE)
    duplicate = passages[0].model_copy(
        update={"passage_id": "IGNWPS-MH-ELIGIBILITY-02"}
    )

    results = build_retriever([*passages, duplicate]).search("widow", limit=1)

    assert len(results) == 1
    assert results[0].passage_id == passages[0].passage_id


@pytest.mark.parametrize("limit", [0, 101])
def test_search_rejects_out_of_range_limit(limit):
    passages = load_passages(PASSAGE_FILE)

    with pytest.raises(ValueError, match="between 1 and 100"):
        build_retriever(passages).search("widow", limit=limit)


def test_empty_search_query_is_rejected():
    passages = load_passages(PASSAGE_FILE)

    with pytest.raises(ValueError, match="cannot be empty"):
        build_retriever(passages).search("   ")


def test_punctuation_only_search_query_is_rejected():
    passages = load_passages(PASSAGE_FILE)

    with pytest.raises(ValueError, match="cannot be empty"):
        build_retriever(passages).search("!!!")


def test_query_decomposition_keeps_original_and_simplifies_words():
    assert decompose_query("What documents are required for widow pension") == (
        "what documents are required for widow pension",
        "documents required widow pension",
    )


def test_reciprocal_rank_fusion_combines_bm25_and_vector_positions():
    fused = reciprocal_rank_fusion(
        [
            ["eligibility", "benefit", "application"],
            ["benefit", "application", "eligibility"],
            ["benefit", "eligibility", "application"],
        ]
    )

    assert fused[0] == "benefit"


def test_cross_encoder_reranker_can_change_fused_order():
    passages = load_passages(PASSAGE_FILE)
    ids = [passage.passage_id for passage in reversed(passages)]
    retriever = HybridSchemeRetriever(
        passages,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            10.0 if passage.passage_id == "IGNWPS-MH-APPLICATION-01" else 0.0
            for passage in candidates
        ],
    )

    results = retriever.search("where do I apply")

    assert results[0].passage_id == "IGNWPS-MH-APPLICATION-01"


def test_min_score_drops_weakly_reranked_passages():
    passages = load_passages(PASSAGE_FILE)
    ids = [passage.passage_id for passage in passages]
    retriever = HybridSchemeRetriever(
        passages,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            0.9 if passage.passage_id == "IGNWPS-MH-APPLICATION-01"
            else 0.29 if passage.passage_id == "IGNWPS-MH-BENEFIT-01"
            else 0.1
            for passage in candidates
        ],
    )

    results = retriever.search("where do I apply", limit=5, min_score=0.3)

    assert [passage.passage_id for passage in results] == [
        "IGNWPS-MH-APPLICATION-01"
    ]
    assert retriever.search("where do I apply", limit=5, min_score=0.95) == ()


def test_fallback_keeps_only_the_best_passage_when_none_pass_min_score():
    passages = load_passages(PASSAGE_FILE)
    ids = [passage.passage_id for passage in passages]
    retriever = HybridSchemeRetriever(
        passages,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            0.24 if passage.passage_id == "PM-KISAN-IN-BENEFIT-01"
            else 0.21 if passage.passage_id == "PM-KISAN-IN-ELIGIBILITY-LAND-01"
            else 0.05
            for passage in candidates
        ],
    )

    results = retriever.search(
        "small farmer money support",
        limit=5,
        min_score=0.3,
        fallback_min_score=0.2,
    )
    assert [passage.passage_id for passage in results] == [
        "PM-KISAN-IN-BENEFIT-01"
    ]
    # A best match below the fallback floor still returns nothing.
    assert retriever.search(
        "small farmer money support",
        limit=5,
        min_score=0.3,
        fallback_min_score=0.25,
    ) == ()


def test_search_can_skip_cross_encoder_and_keep_fused_order(monkeypatch):
    passages = load_passages(PASSAGE_FILE)
    fused_ids = [passage.passage_id for passage in reversed(passages)]
    vector_search = lambda query, candidates, limit: fused_ids[:limit]

    def unexpected_cross_encoder(*args, **kwargs):
        raise AssertionError("cross-encoder should not load in constrained mode")

    monkeypatch.setattr(
        scheme_search_module,
        "TextCrossEncoder",
        unexpected_cross_encoder,
    )
    retriever = HybridSchemeRetriever(
        passages,
        vector_search=vector_search,
        use_cross_encoder=False,
    )
    expected_retriever = HybridSchemeRetriever(
        passages,
        vector_search=vector_search,
        rerank=lambda query, candidates: [
            -index for index in range(len(candidates))
        ],
    )

    results = retriever.search("where do I apply")
    expected = expected_retriever.search("where do I apply")

    assert results == expected
