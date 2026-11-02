"""Register scheme-passage search on the shared MCP server."""

import os

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.config import PROJECT_ROOT
from src.api.scheme_search import (
    HOSTED_RERANK_MIN_SCORE,
    HybridSchemeRetriever,
    OpenRouterReranker,
    SchemePassage,
    load_passages,
)


def register_tools(mcp: MCPServer) -> None:
    """Add BM25 retrieval for RAG context to the shared MCP server."""

    passage_file = PROJECT_ROOT / "data" / "schemes" / "passages.json"
    passages = load_passages(passage_file)
    rerank_mode = os.getenv("SCHEME_SAATHI_RERANKER", "").casefold()
    retriever = HybridSchemeRetriever(
        passages,
        rerank=OpenRouterReranker() if rerank_mode == "openrouter" else None,
        use_cross_encoder=(
            rerank_mode != "openrouter"
            and os.getenv("SCHEME_SAATHI_DISABLE_CROSS_ENCODER") != "1"
        ),
    )

    @mcp.tool()
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
                )
            )
        except ValueError as error:
            raise ToolError(str(error)) from error
