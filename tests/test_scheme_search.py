import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from src.api import scheme_search as scheme_search_module
from src.llm_client import openrouter_embeddings
from src.api.scheme_search import (
    HybridSchemeRetriever,
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


def test_openrouter_embeddings_helper_batches_injected_requests(monkeypatch):
    """Keep the OpenRouter embedding helper's explicit injection behavior covered."""

    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        # Same 2-D vector for every text: enough for Qdrant to return results.
        return httpx.Response(200, json={
            "object": "list", "model": "fake",
            "data": [
                {"object": "embedding", "index": index, "embedding": [1.0, 0.0]}
                for index, _ in enumerate(texts)
            ],
        })

    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "free-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "default-key")
    passages = load_passages(PASSAGE_FILE)
    embeddings = openrouter_embeddings(
        "free-key", "voyageai/voyage-4",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    retriever = HybridSchemeRetriever(
        passages, embeddings=embeddings, use_cross_encoder=False,
    )

    rankings = retriever._vector_search_many(
        ("widow pension", "widow"), passages,
    )

    assert len(rankings) == 2
    assert set(rankings[0]) <= {passage.passage_id for passage in passages}
    assert rankings[0]
    assert requests[-1].url == "https://openrouter.ai/api/v1/embeddings"
    assert requests[-1].headers["Authorization"] == "Bearer free-key"
    assert json.loads(requests[-1].content) == {
        "model": "voyageai/voyage-4", "input": ["widow pension", "widow"],
        "encoding_format": "float",
    }
    before = len(requests)
    retriever._vector_search_many(("widow",), passages)
    assert len(requests) == before + 1, "the passage index is built only once"


def test_vector_search_uses_local_fastembed_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY_FREE", raising=False)
    monkeypatch.delenv("OPEN_ROUTER_FREE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "chat-key")

    class FakeVector(list):
        def tolist(self):
            return list(self)

    class FakeTextEmbedding:
        @staticmethod
        def list_supported_models():
            return [{
                "model": (
                    "sentence-transformers/"
                    "paraphrase-multilingual-MiniLM-L12-v2"
                )
            }]

        def __init__(self, *, model_name, local_files_only):
            assert model_name == (
                "sentence-transformers/"
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
            assert local_files_only is True

        def embed(self, texts):
            return (FakeVector([1.0, 0.0]) for _ in texts)

        def query_embed(self, text):
            return iter([FakeVector([1.0, 0.0])])

    monkeypatch.setattr(scheme_search_module, "TextEmbedding", FakeTextEmbedding)
    retriever = HybridSchemeRetriever(
        load_passages(PASSAGE_FILE), use_cross_encoder=False,
    )

    rankings = retriever._vector_search_many(("widow pension",), retriever.passages)

    assert rankings[0]
    assert retriever._embedding_model() is retriever._embedding_model()


def test_openrouter_embedding_backend_uses_configured_free_key_and_model(monkeypatch):
    monkeypatch.setattr(scheme_search_module, "EMBEDDING_BACKEND", "openrouter")
    monkeypatch.setattr(
        scheme_search_module,
        "OPENROUTER_EMBEDDING_MODEL",
        "mongodb/voyage-4",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-key")
    calls = []
    expected = object()

    def build_embeddings(api_key, model):
        calls.append((api_key, model))
        return expected

    monkeypatch.setattr(
        scheme_search_module,
        "openrouter_embeddings",
        build_embeddings,
    )
    retriever = HybridSchemeRetriever(
        load_passages(PASSAGE_FILE), use_cross_encoder=False,
    )

    assert retriever._embedding_model() is expected
    assert calls == [("embedding-key", "mongodb/voyage-4")]


def test_missing_local_embedding_model_falls_back_to_openrouter(monkeypatch):
    class MissingTextEmbedding:
        @staticmethod
        def list_supported_models():
            return [{
                "model": (
                    "sentence-transformers/"
                    "paraphrase-multilingual-MiniLM-L12-v2"
                )
            }]

        def __init__(self, *, model_name, local_files_only):
            assert model_name == (
                "sentence-transformers/"
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
            assert local_files_only is True
            raise ValueError(
                "Could not load model with local_files_only=True"
            )

    monkeypatch.setattr(scheme_search_module, "TextEmbedding", MissingTextEmbedding)
    monkeypatch.setenv("OPENROUTER_API_KEY_FREE", "embedding-key")
    calls = []
    expected = object()

    def build_embeddings(api_key, model):
        calls.append((api_key, model))
        return expected

    monkeypatch.setattr(
        scheme_search_module,
        "openrouter_embeddings",
        build_embeddings,
    )
    retriever = HybridSchemeRetriever(
        load_passages(PASSAGE_FILE), use_cross_encoder=False,
    )

    assert retriever._embedding_model() is expected
    assert calls == [("embedding-key", "mongodb/voyage-4")]


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
    benefit = next(
        result for result in results
        if result.passage_id == "PM-KISAN-IN-BENEFIT-01"
    )
    assert benefit.source.source_id == "SRC-PMKISAN-IN-002"
    assert benefit.source.locator


def test_bm25_ranks_specific_passage_above_shared_scheme_metadata():
    passages = load_passages(PASSAGE_FILE)
    retriever = build_retriever(passages)

    specific_passages = tuple(
        passage for passage in passages
        if passage.passage_id in {
            "IGNWPS-MH-ELIGIBILITY-01",
            "IGNOAPS-MH-ELIGIBILITY-01",
        }
    )
    results = retriever._bm25_search("below poverty line", specific_passages)

    # Both BPL eligibility clauses match; no shared scheme metadata does.
    assert results == ["IGNWPS-MH-ELIGIBILITY-01", "IGNOAPS-MH-ELIGIBILITY-01"]


def test_bm25_finds_the_old_age_pension_scheme():
    passages = load_passages(PASSAGE_FILE)

    results = build_retriever(passages)._bm25_search("old age pension", tuple(passages))

    assert results and results[0].startswith("IGNOAPS-MH-")


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


def _agreement_retriever(vector_first_scheme: str):
    """Reranker unsure (0.19); keyword search ranks PM-KISAN first for 'farmer';
    meaning search ranks ``vector_first_scheme`` first."""

    passages = tuple(
        passage for passage in load_passages(PASSAGE_FILE)
        if passage.scheme_id in {"PM-KISAN-IN", "IGNWPS-MH"}
    )
    ordered = sorted(passages, key=lambda passage: passage.scheme_id != vector_first_scheme)
    ids = [passage.passage_id for passage in ordered]
    return HybridSchemeRetriever(
        passages,
        vector_search=lambda query, candidates, limit: [
            passage_id for passage_id in ids
            if any(passage.passage_id == passage_id for passage in candidates)
        ][:limit],
        rerank=lambda query, candidates: [
            0.19 if passage.passage_id == "PM-KISAN-IN-BENEFIT-01" else 0.05
            for passage in candidates
        ],
    )


def test_agreement_keeps_a_near_miss_when_both_searches_rank_its_scheme_first():
    retriever = _agreement_retriever("PM-KISAN-IN")
    arguments = dict(limit=5, min_score=0.3, fallback_min_score=0.2)

    # Today's rule alone: 0.19 is under the 0.2 fallback, so nothing is shown.
    assert retriever.search("small farmer money support", **arguments) == ()
    # Both searches rank PM-KISAN first and 0.19 >= 0.12: the passage is shown.
    results = retriever.search(
        "small farmer money support", **arguments, agreement_min_score=0.12,
    )
    assert [passage.passage_id for passage in results] == ["PM-KISAN-IN-BENEFIT-01"]
    # Below the agreement floor, agreement alone is not enough.
    assert retriever.search(
        "small farmer money support", **arguments, agreement_min_score=0.195,
    ) == ()


def test_agreement_needs_both_searches_to_rank_the_same_scheme_first():
    retriever = _agreement_retriever("IGNWPS-MH")
    assert retriever.search(
        "small farmer money support",
        limit=5, min_score=0.3, fallback_min_score=0.2, agreement_min_score=0.12,
    ) == ()
