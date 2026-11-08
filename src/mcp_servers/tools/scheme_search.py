"""Register scheme-passage search on the shared MCP server."""

import os

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from src.config import PROJECT_ROOT
from src.documents.checklists import load_checklist_snapshot
from src.mcp_servers.rule_data import get_active_rule_data
from src.api.scheme_search import (
    HOSTED_RERANK_AGREEMENT_MIN_SCORE,
    HOSTED_RERANK_FALLBACK_MIN_SCORE,
    HOSTED_RERANK_MIN_SCORE,
    HybridSchemeRetriever,
    OpenRouterReranker,
    SchemePassage,
    load_passages,
)
from src.mcp_servers.contracts import tool_error


class SchemeSummary(BaseModel):
    """Source-linked scheme identity drawn from the local passage corpus."""

    model_config = ConfigDict(extra="forbid")

    scheme_id: str
    scheme_name: str
    jurisdiction: str
    languages: list[str]
    source_ids: list[str]
    review_statuses: list[str]


class SchemeDocuments(BaseModel):
    """Direct checklist response with citations and explicit trust metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme_id: str
    requirements_status: str
    trust_status: str
    demo_only: bool
    checklist_version: str | None
    checklist_fingerprint: str
    evidence_fingerprint: str
    active_fingerprint: str
    requirements: list[dict[str, object]]
    groups: list[dict[str, object]]
    citations: list[dict[str, object]]
    notice: str


def register_tools(mcp: MCPServer) -> None:
    """Add BM25 retrieval for RAG context to the shared MCP server."""

    passage_file = PROJECT_ROOT / "data" / "schemes" / "passages.json"
    rerank_mode = os.getenv("SCHEME_SAATHI_RERANKER", "").casefold()
    passages = load_passages(passage_file)
    retriever = HybridSchemeRetriever(
        passages,
        rerank=OpenRouterReranker() if rerank_mode == "openrouter" else None,
        use_cross_encoder=(
            rerank_mode != "openrouter"
            and os.getenv("SCHEME_SAATHI_DISABLE_CROSS_ENCODER") != "1"
        ),
    )
    schemes: dict[str, SchemeSummary] = {}
    for passage in passages:
        existing = schemes.get(passage.scheme_id)
        if existing is None:
            schemes[passage.scheme_id] = SchemeSummary(
                scheme_id=passage.scheme_id,
                scheme_name=passage.scheme_name,
                jurisdiction=passage.jurisdiction,
                languages=[passage.language],
                source_ids=[passage.source.source_id or passage.passage_id],
                review_statuses=[passage.review_status],
            )
        else:
            existing.languages = sorted(set(existing.languages) | {passage.language})
            existing.source_ids = sorted(
                set(existing.source_ids)
                | {passage.source.source_id or passage.passage_id}
            )
            existing.review_statuses = sorted(
                set(existing.review_statuses) | {passage.review_status}
            )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search scheme knowledge base",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def search_schemes(
        query: str,
        jurisdiction: str | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[SchemePassage]:
        """Retrieve BM25-ranked passages with citations for downstream RAG."""

        try:
            return list(
                retriever.search(
                    query,
                    jurisdiction=jurisdiction,
                    language=language,
                    limit=limit,
                    min_score=(
                        HOSTED_RERANK_MIN_SCORE
                        if rerank_mode == "openrouter"
                        else None
                    ),
                    fallback_min_score=(
                        HOSTED_RERANK_FALLBACK_MIN_SCORE
                        if rerank_mode == "openrouter"
                        else None
                    ),
                    agreement_min_score=(
                        HOSTED_RERANK_AGREEMENT_MIN_SCORE
                        if rerank_mode == "openrouter"
                        else None
                    ),
                )
            )
        except ValueError as error:
            raise tool_error("invalid_input", str(error)) from error

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get scheme details",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def get_scheme(scheme_id: str) -> SchemeSummary:
        """Return source IDs and corpus metadata for a known scheme."""

        scheme = schemes.get(scheme_id)
        if scheme is None:
            raise tool_error("not_found", "Scheme was not found in the knowledge base.")
        return scheme

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get shared document checklist",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def get_documents(scheme_id: str) -> SchemeDocuments:
        """Return the directly loaded checklist without retrieval ranking."""

        snapshot = load_checklist_snapshot(
            scheme_id, registry=get_active_rule_data().registry
        )
        checklist = snapshot.checklist if snapshot.usable else None
        requirements = (
            [
                {
                    "requirement_id": requirement.requirement_id,
                    "labels": requirement.labels.model_dump(),
                    "condition": requirement.condition.model_dump(),
                    "alternatives": [
                        {
                            "document_id": alternative.document_id,
                            "labels": alternative.labels.model_dump(),
                        }
                        for alternative in requirement.alternatives
                    ],
                    "evidence_passage_ids": requirement.evidence_passage_ids,
                }
                for requirement in checklist.requirements
            ]
            if checklist is not None
            else []
        )
        return SchemeDocuments(
            scheme_id=scheme_id,
            requirements_status=snapshot.trust_status,
            trust_status=snapshot.trust_status,
            demo_only=snapshot.trust_status == "demo_only_unverified",
            checklist_version=snapshot.checklist_version,
            checklist_fingerprint=snapshot.checklist_fingerprint,
            evidence_fingerprint=snapshot.evidence_fingerprint,
            active_fingerprint=snapshot.active_fingerprint,
            requirements=requirements,
            groups=requirements,
            citations=[
                passage.model_dump(mode="json") for passage in snapshot.citations
            ],
            notice=snapshot.notice,
        )
