"""Passage models, loading, and search for scheme discovery."""

import json
import os
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Literal
import urllib.error
import urllib.request
import uuid

from fastembed.rerank.cross_encoder import TextCrossEncoder
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from openai import OpenAIError
from rank_bm25 import BM25Okapi
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from qdrant_client import models

from src.config import PROJECT_ROOT
from src.llm_client import openrouter_embeddings


class PassageSource(BaseModel):
    """Where this passage came from and when we collected it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str | None = None
    publisher: str = Field(min_length=1)
    url: HttpUrl
    collected_at: date
    publication_date: date | None = None
    locator: str | None = None


class SchemePassage(BaseModel):
    """One source passage, with metadata for multi-scheme search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: str = Field(min_length=1)
    scheme_id: str = Field(min_length=1)
    scheme_name: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=10)
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source: PassageSource
    review_status: Literal["pending_review", "reviewed", "rejected"]
    eligible_for_mock_flow: bool = False


class PassageCorpus(BaseModel):
    """Versioned, validated collection used by the search tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_version: str = Field(min_length=1)
    passages: tuple[SchemePassage, ...]


EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "voyageai/voyage-4")
OPENROUTER_RERANK_URL = "https://openrouter.ai/api/v1/rerank"
OPENROUTER_RERANKER_MODEL = "cohere/rerank-v3.5"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3-int8"
VECTOR_COLLECTION = "scheme_passages"
RETRIEVAL_DEPTH = 20
# Chosen from the 43-query dev set: keeps 94% of relevant passages and
# drops ~90% of the rest. Specific to Cohere rerank scores.
HOSTED_RERANK_MIN_SCORE = 0.3
# If nothing reaches 0.3, the single best passage is still kept when it
# scores at least this. Plain questions such as "small farmer with 1 acre,
# any money support?" score ~0.24 for the right PM-KISAN passage, while
# off-topic questions scored at most 0.145 (PMAY housing) in a live check.
HOSTED_RERANK_FALLBACK_MIN_SCORE = 0.2
# Below 0.2, the best passage is still kept when it scores at least this AND
# keyword search and meaning search both rank its scheme first. Calibrated
# 2026-11-05 on 75 development questions (scripts/calibrate_search_fallback.py):
# right answers missed by the 0.2 line scored 0.186-0.198 and all had both
# searches agreeing; off-topic questions scored at most 0.068. Details and the
# re-calibration procedure: docs/RETRIEVAL_IMPROVEMENT_BACKLOG.md.
HOSTED_RERANK_AGREEMENT_MIN_SCORE = 0.12
RRF_K = 60

_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from",
    "how", "i", "in", "is", "me", "of", "on", "or", "the", "to",
    "what", "when", "where", "which", "who", "with",
}


class OpenRouterReranker:
    """Rerank passages through OpenRouter without loading a local model."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def __call__(
        self,
        query: str,
        passages: Sequence["SchemePassage"],
    ) -> list[float]:
        api_key = self._api_key or free_api_key("hosted reranking")

        documents = [
            HybridSchemeRetriever.document_text(passage)
            for passage in passages
        ]
        payload = json.dumps(
            {
                "model": OPENROUTER_RERANKER_MODEL,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENROUTER_RERANK_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"OpenRouter reranking request failed with HTTP {error.code}."
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError("OpenRouter reranking request failed.") from error
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError(
                "OpenRouter returned an invalid reranking response."
            ) from error

        try:
            results = body["results"]
            scores: list[float | None] = [None] * len(documents)
            for result in results:
                index = result["index"]
                score = float(result["relevance_score"])
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 0 <= index < len(documents)
                    or scores[index] is not None
                ):
                    raise ValueError("Invalid reranking result index.")
                scores[index] = score
            if any(score is None for score in scores):
                raise ValueError("Reranking response omitted documents.")
            return [score for score in scores if score is not None]
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                "OpenRouter returned an invalid reranking response."
            ) from error


def free_api_key(purpose: str) -> str:
    """Return the free OpenRouter key used for search, never the chat key."""

    api_key = os.getenv("OPENROUTER_API_KEY_FREE") or os.getenv("OPEN_ROUTER_FREE")
    if not api_key:
        raise RuntimeError(f"OPENROUTER_API_KEY_FREE is required for {purpose}.")
    return api_key


def load_passages(path: Path) -> tuple[SchemePassage, ...]:
    """Load a versioned passage corpus and reject duplicate passage IDs."""

    data = json.loads(path.read_text(encoding="utf-8"))
    corpus = PassageCorpus.model_validate(data)
    passages = corpus.passages
    passage_ids = [passage.passage_id for passage in passages]
    if len(passage_ids) != len(set(passage_ids)):
        raise ValueError("Passage IDs must be unique.")

    return passages


class HybridSchemeRetriever:
    """Combine BM25 and Qdrant vectors with RRF, then rerank candidates."""

    def __init__(
        self,
        passages: Iterable[SchemePassage],
        *,
        vector_search: Callable[
            [str, tuple[SchemePassage, ...], int], Sequence[str]
        ]
        | None = None,
        rerank: Callable[[str, Sequence[SchemePassage]], Sequence[float]]
        | None = None,
        embeddings: Embeddings | None = None,
        use_cross_encoder: bool = True,
    ) -> None:
        self.passages = tuple(passages)
        if not self.passages:
            raise ValueError("Scheme search corpus cannot be empty.")

        self._passage_by_id = {
            passage.passage_id: passage for passage in self.passages
        }
        documents = [
            tokenize(self.document_text(passage)) for passage in self.passages
        ]
        self._bm25 = BM25Okapi(documents)
        self._vector_search_override = vector_search
        self._rerank_override = rerank
        self._embeddings = embeddings
        self._use_cross_encoder = use_cross_encoder
        self._vector_store: QdrantVectorStore | None = None
        self._reranker: TextCrossEncoder | None = None

    def search(
        self,
        query: str,
        *,
        jurisdiction: str | None = None,
        language: str | None = None,
        limit: int = 10,
        min_score: float | None = None,
        fallback_min_score: float | None = None,
        agreement_min_score: float | None = None,
    ) -> tuple[SchemePassage, ...]:
        """Expand the query, retrieve with both methods, fuse, then rerank.

        ``min_score`` drops passages whose rerank score is lower; it has no
        effect when reranking is disabled. If that leaves nothing, the single
        best passage is still returned when it scores at least
        ``fallback_min_score``, so a plainly worded but relevant question
        is not answered with "no results". It is also returned when it scores
        at least ``agreement_min_score`` **and** keyword search and meaning
        (vector) search both rank its scheme first: two independent methods
        agreeing is strong evidence even when the reranker is unsure.
        """

        if not tokenize(query):
            raise ValueError("Search query cannot be empty.")
        if not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100.")

        candidates = tuple(
            passage
            for passage in self.passages
            if (jurisdiction is None or passage.jurisdiction == jurisdiction)
            and (language is None or passage.language == language)
        )
        if not candidates:
            return ()

        variants = decompose_query(query)
        keyword_rankings = [
            self._bm25_search(variant, candidates) for variant in variants
        ]
        vector_rankings = list(self._vector_search_many(variants, candidates))
        rankings: list[Sequence[str]] = [*keyword_rankings, *vector_rankings]

        fused_ids = reciprocal_rank_fusion(rankings)[: max(limit * 5, RETRIEVAL_DEPTH)]
        fused_passages = [
            self._passage_by_id[passage_id]
            for passage_id in fused_ids
            if passage_id in self._passage_by_id
        ]
        if not fused_passages:
            return ()

        if self._rerank_override is None and not self._use_cross_encoder:
            return tuple(fused_passages[:limit])

        scores = self._rerank(query, fused_passages)
        if len(scores) != len(fused_passages):
            raise RuntimeError("Reranker returned an unexpected number of scores.")
        reranked = sorted(
            enumerate(zip(scores, fused_passages)),
            key=lambda item: (-float(item[1][0]), item[0]),
        )
        kept = tuple(
            passage
            for _, (score, passage) in reranked
            if min_score is None or float(score) >= min_score
        )[:limit]
        if not kept:
            best_score, best_passage = reranked[0][1]
            if fallback_min_score is not None and float(best_score) >= fallback_min_score:
                return (best_passage,)
            if (
                agreement_min_score is not None
                and float(best_score) >= agreement_min_score
                and best_passage.scheme_id
                == self._top_scheme(keyword_rankings)
                == self._top_scheme(vector_rankings)
            ):
                return (best_passage,)
        return kept

    def _top_scheme(self, rankings: Sequence[Sequence[str]]) -> str | None:
        """The scheme of the passage one retrieval method ranks first overall."""

        fused = reciprocal_rank_fusion(rankings)
        return self._passage_by_id[fused[0]].scheme_id if fused else None

    def _bm25_search(
        self,
        query: str,
        candidates: tuple[SchemePassage, ...],
    ) -> list[str]:
        terms = tokenize(query)
        scores = self._bm25.get_scores(terms)
        allowed_ids = {passage.passage_id for passage in candidates}
        ranked = sorted(
            (
                (float(score), position, passage.passage_id)
                for position, (score, passage) in enumerate(
                    zip(scores, self.passages)
                )
                if passage.passage_id in allowed_ids
                and set(terms).intersection(tokenize(self.document_text(passage)))
            ),
            key=lambda item: (-item[0], item[1]),
        )
        return [passage_id for _, _, passage_id in ranked[:RETRIEVAL_DEPTH]]

    def _vector_search(
        self,
        query: str,
        candidates: tuple[SchemePassage, ...],
    ) -> Sequence[str]:
        if self._vector_search_override is not None:
            return self._vector_search_override(query, candidates, RETRIEVAL_DEPTH)

        return self._vector_search_many((query,), candidates)[0]

    def _vector_search_many(
        self,
        queries: Sequence[str],
        candidates: tuple[SchemePassage, ...],
    ) -> list[Sequence[str]]:
        if self._vector_search_override is not None:
            return [
                self._vector_search_override(query, candidates, RETRIEVAL_DEPTH)
                for query in queries
            ]

        store = self._get_vector_store()
        must_filters = []
        jurisdictions = {passage.jurisdiction for passage in candidates}
        languages = {passage.language for passage in candidates}
        if len(jurisdictions) == 1:
            must_filters.append(models.FieldCondition(
                key="metadata.jurisdiction",
                match=models.MatchValue(value=next(iter(jurisdictions))),
            ))
        if len(languages) == 1:
            must_filters.append(models.FieldCondition(
                key="metadata.language",
                match=models.MatchValue(value=next(iter(languages))),
            ))
        query_filter = models.Filter(must=must_filters) if must_filters else None
        # One embeddings request for all query variants, then one lookup each.
        return [
            [
                document.metadata["passage_id"]
                for document in store.similarity_search_by_vector(
                    vector, k=min(RETRIEVAL_DEPTH, len(candidates)), filter=query_filter,
                )
            ]
            for vector in self._embed_queries(queries)
        ]

    def _embedding_model(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = openrouter_embeddings(
                free_api_key("vector search"), EMBEDDING_MODEL,
            )
        return self._embeddings

    def _embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        try:
            return self._embedding_model().embed_documents(list(queries))
        except OpenAIError as error:
            # Never echo the provider's error text, which may quote the input.
            raise RuntimeError("OpenRouter embeddings request failed.") from error

    def _get_vector_store(self) -> QdrantVectorStore:
        """Index every passage once in an in-memory Qdrant collection."""

        if self._vector_store is None:
            try:
                self._vector_store = QdrantVectorStore.from_documents(
                    [
                        Document(
                            page_content=self.document_text(passage),
                            metadata={
                                "passage_id": passage.passage_id,
                                "jurisdiction": passage.jurisdiction,
                                "language": passage.language,
                            },
                        )
                        for passage in self.passages
                    ],
                    self._embedding_model(),
                    ids=[
                        str(uuid.uuid5(uuid.NAMESPACE_URL, passage.passage_id))
                        for passage in self.passages
                    ],
                    location=":memory:",
                    collection_name=VECTOR_COLLECTION,
                )
            except OpenAIError as error:
                raise RuntimeError("OpenRouter embeddings request failed.") from error
        return self._vector_store

    def _rerank(
        self,
        query: str,
        passages: Sequence[SchemePassage],
    ) -> Sequence[float]:
        if self._rerank_override is not None:
            return self._rerank_override(query, passages)

        if self._reranker is None:
            self._reranker = TextCrossEncoder(model_name=RERANKER_MODEL)
        return list(
            self._reranker.rerank(
                query,
                [self.document_text(passage) for passage in passages],
            )
        )

    @staticmethod
    def document_text(passage: SchemePassage) -> str:
        return " ".join(
            (passage.scheme_id, passage.scheme_name, passage.section, passage.text)
        )


def decompose_query(query: str) -> tuple[str, ...]:
    """Add a content-word query alongside the user's original wording."""

    original = " ".join(tokenize(query))
    content_terms = [
        term for term in tokenize(query) if term not in _QUERY_STOPWORDS
    ]
    decomposed = " ".join(content_terms)
    if decomposed and decomposed != original:
        return original, decomposed
    return (original,)


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[str]],
    *,
    k: int = RRF_K,
) -> list[str]:
    """Combine independent result lists using rank, not incompatible scores."""

    if k <= 0:
        raise ValueError("RRF k must be positive.")

    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    position = 0
    for ranking in rankings:
        for rank, passage_id in enumerate(ranking, start=1):
            scores[passage_id] = scores.get(passage_id, 0.0) + 1 / (k + rank)
            if passage_id not in first_seen:
                first_seen[passage_id] = position
                position += 1

    return sorted(
        scores,
        key=lambda passage_id: (-scores[passage_id], first_seen[passage_id]),
    )


def tokenize(text: str) -> list[str]:
    """Split searchable text into normalized word tokens."""

    return re.findall(r"\w+", text.casefold())
