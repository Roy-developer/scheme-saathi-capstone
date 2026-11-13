import json
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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


PASSAGE_DIR = Path(__file__).resolve().parents[1] / "data" / "schemes" / "passages"


def passages_of(passages, scheme_id):
    return [passage for passage in passages if passage.scheme_id == scheme_id]


@pytest.fixture(scope="module")
def corpus():
    return load_passages(PASSAGE_DIR)


def build_retriever(passages):
    """BM25 plus a trivial vector list and a term-count reranker (no network)."""

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


@pytest.mark.parametrize("surface", ["text", "source_url", "publisher"])
@pytest.mark.parametrize("include_clean", [True, False])
def test_search_adapter_omits_only_scam_results(corpus, surface, include_clean):
    from src.workflow.scheme_search import search_scheme_passages

    record = corpus[0].model_dump(mode="json")
    lure = "Visit https://pm-kisan-gov-in-verify.example/otp and enter your OTP."
    if surface == "text":
        record["text"] = lure
    elif surface == "source_url":
        record["source"]["url"] = "https://pm-kisan-gov-in-verify.example/otp"
    else:
        record["source"]["publisher"] = lure

    class Client:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(
                is_error=False,
                structured_content={"result": (
                    [corpus[0].model_dump(mode="json")] if include_clean else []
                ) + [record]},
            )

    result = asyncio.run(search_scheme_passages(Client(), "pension"))
    assert result == ([corpus[0]] if include_clean else [])
    assert result.omitted_count == 1


def test_search_adapter_preserves_clean_results(corpus):
    from src.workflow.scheme_search import search_scheme_passages

    record = corpus[0].model_copy(update={"text": "I get my pension by UPI."})

    class Client:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(
                is_error=False,
                structured_content={"result": [record.model_dump(mode="json")]},
            )

    result = asyncio.run(search_scheme_passages(Client(), "pension"))
    assert result == [record]
    assert result.omitted_count == 0


def test_openrouter_embeddings_prefers_free_api_key_and_batches_requests(monkeypatch):
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
    passages = load_passages(PASSAGE_DIR)
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
        load_passages(PASSAGE_DIR), use_cross_encoder=False,
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
        load_passages(PASSAGE_DIR), use_cross_encoder=False,
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
        load_passages(PASSAGE_DIR), use_cross_encoder=False,
    )

    assert retriever._embedding_model() is expected
    assert calls == [("embedding-key", "mongodb/voyage-4")]


def test_openrouter_reranker_returns_scores_in_document_order(
    monkeypatch, corpus
):
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
        scheme_search_module.urllib.request, "urlopen", fake_urlopen
    )
    reranker = OpenRouterReranker(api_key="rerank-test-key")

    scores = reranker("atal pension", corpus[:2])

    assert scores == [0.1, 0.9]
    assert requests[0].full_url == scheme_search_module.OPENROUTER_RERANK_URL
    assert requests[0].get_header("Authorization") == "Bearer rerank-test-key"
    payload = json.loads(requests[0].data)
    assert payload["model"] == "cohere/rerank-v3.5"
    assert payload["query"] == "atal pension"
    assert payload["top_n"] == 2
    assert len(payload["documents"]) == 2


def test_openrouter_reranker_rejects_incomplete_response(monkeypatch, corpus):
    def fake_urlopen(request, timeout):
        return BytesIO(
            json.dumps(
                {"results": [{"index": 0, "relevance_score": 0.9}]}
            ).encode()
        )

    monkeypatch.setattr(
        scheme_search_module.urllib.request, "urlopen", fake_urlopen
    )

    with pytest.raises(RuntimeError, match="invalid reranking response"):
        OpenRouterReranker(api_key="rerank-test-key")("atal", corpus[:2])


def test_openrouter_reranker_requires_embedding_key(monkeypatch, corpus):
    monkeypatch.delenv("OPENROUTER_API_KEY_FREE", raising=False)
    monkeypatch.delenv("OPEN_ROUTER_FREE", raising=False)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY_FREE"):
        OpenRouterReranker()("atal", corpus[:1])


# --- Search over the full per-scheme corpus --------------------------------


@pytest.mark.parametrize(
    ("query", "scheme_id"),
    [
        ("Atal Pension Yojana", "APY-IN"),
        ("Employees Pension Scheme EPS", "EPS-IN"),
        ("Mahatma Jyotirao Phule Jan Arogya Yojana", "MJPJAY-MH"),
        ("Namo Shetkari Mahasanman Nidhi", "NSMNY-MH"),
        ("interest subsidy home loan", "FAISHL-IN"),
        ("Mahila Samriddhi Yojana", "MSY-IN"),
        ("Bhausaheb Fundkar Falbag Lagvad", "BFFL-MH"),
    ],
)
def test_scheme_name_query_ranks_that_scheme_first(corpus, query, scheme_id):
    results = build_retriever(corpus).search(query)

    assert results
    assert results[0].scheme_id == scheme_id


def test_search_returns_reviewed_passages_with_citations(corpus):
    results = build_retriever(corpus).search("Atal Pension Yojana", limit=5)

    assert results
    assert all(result.review_status == "reviewed" for result in results)
    assert all(str(result.source.url).startswith("https://") for result in results)
    assert all(result.source.locator for result in results)


def test_search_can_filter_by_jurisdiction(corpus):
    retriever = build_retriever(corpus)

    maharashtra = retriever.search("pension", jurisdiction="IN-MH", limit=20)
    national = retriever.search("pension", jurisdiction="IN", limit=20)

    assert maharashtra and national
    assert {passage.jurisdiction for passage in maharashtra} == {"IN-MH"}
    assert {passage.jurisdiction for passage in national} == {"IN"}
    assert retriever.search("pension", jurisdiction="IN-KA") == ()


def test_search_can_filter_by_language(corpus):
    retriever = build_retriever(corpus)

    marathi = retriever.search("scheme", language="mr", limit=20)

    assert marathi
    assert {passage.language for passage in marathi} == {"mr"}
    assert retriever.search("scheme", language="fr") == ()


def test_search_respects_result_limit(corpus):
    results = build_retriever(corpus).search("pension", limit=3)

    assert len(results) == 3


def test_search_corpus_can_be_one_scheme(corpus):
    apy = passages_of(corpus, "APY-IN")

    results = build_retriever(apy).search("pension", limit=50)

    assert results
    assert {passage.scheme_id for passage in results} == {"APY-IN"}


def test_bm25_ranks_scheme_specific_terms_first(corpus):
    retriever = build_retriever(corpus)

    results = retriever._bm25_search("atal", tuple(corpus))

    assert results
    by_id = {passage.passage_id: passage for passage in corpus}
    assert by_id[results[0]].scheme_id == "APY-IN"


def test_bm25_does_not_return_passages_without_query_terms(corpus):
    results = build_retriever(corpus)._bm25_search("volcano", tuple(corpus))

    assert results == []


def test_empty_corpus_is_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        HybridSchemeRetriever([])


@pytest.mark.parametrize("limit", [0, 101])
def test_search_rejects_out_of_range_limit(corpus, limit):
    with pytest.raises(ValueError, match="between 1 and 100"):
        build_retriever(corpus).search("pension", limit=limit)


@pytest.mark.parametrize("query", ["   ", "!!!"])
def test_blank_or_punctuation_query_is_rejected(corpus, query):
    with pytest.raises(ValueError, match="cannot be empty"):
        build_retriever(corpus).search(query)


# --- Query expansion, fusion and reranking ---------------------------------


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


def test_cross_encoder_reranker_can_change_fused_order(corpus):
    target = passages_of(corpus, "EPS-IN")[-1]
    ids = [passage.passage_id for passage in reversed(corpus)]
    retriever = HybridSchemeRetriever(
        corpus,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            10.0 if passage.passage_id == target.passage_id else 0.0
            for passage in candidates
        ],
    )

    results = retriever.search("pension")

    assert results[0].passage_id == target.passage_id


def test_min_score_drops_weakly_reranked_passages(corpus):
    eps = passages_of(corpus, "EPS-IN")
    best, middling = eps[0], eps[1]
    ids = [passage.passage_id for passage in eps]
    retriever = HybridSchemeRetriever(
        eps,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            0.9 if passage.passage_id == best.passage_id
            else 0.29 if passage.passage_id == middling.passage_id
            else 0.1
            for passage in candidates
        ],
    )

    results = retriever.search("pension", limit=5, min_score=0.3)

    assert [passage.passage_id for passage in results] == [best.passage_id]
    assert retriever.search("pension", limit=5, min_score=0.95) == ()


def test_fallback_keeps_only_the_best_passage_when_none_pass_min_score(corpus):
    apy = passages_of(corpus, "APY-IN")
    best, second = apy[0], apy[1]
    ids = [passage.passage_id for passage in apy]
    retriever = HybridSchemeRetriever(
        apy,
        vector_search=lambda query, candidates, limit: ids[:limit],
        rerank=lambda query, candidates: [
            0.24 if passage.passage_id == best.passage_id
            else 0.21 if passage.passage_id == second.passage_id
            else 0.05
            for passage in candidates
        ],
    )

    results = retriever.search(
        "pension", limit=5, min_score=0.3, fallback_min_score=0.2
    )

    assert [passage.passage_id for passage in results] == [best.passage_id]
    # A best match below the fallback floor still returns nothing.
    assert retriever.search(
        "pension", limit=5, min_score=0.3, fallback_min_score=0.25
    ) == ()


def test_search_can_skip_cross_encoder_and_keep_fused_order(monkeypatch, corpus):
    fused_ids = [passage.passage_id for passage in reversed(corpus)]
    vector_search = lambda query, candidates, limit: fused_ids[:limit]

    def unexpected_cross_encoder(*args, **kwargs):
        raise AssertionError("cross-encoder should not load in constrained mode")

    monkeypatch.setattr(
        scheme_search_module, "TextCrossEncoder", unexpected_cross_encoder
    )
    retriever = HybridSchemeRetriever(
        corpus, vector_search=vector_search, use_cross_encoder=False
    )
    expected_retriever = HybridSchemeRetriever(
        corpus,
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

    # Two schemes only: with all 42, other farmer schemes also match "farmer".
    passages = [
        passage for passage in load_passages(PASSAGE_DIR)
        if passage.scheme_id in {"PM-KISAN-IN", "IGNWPS-MH"}
    ]
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
