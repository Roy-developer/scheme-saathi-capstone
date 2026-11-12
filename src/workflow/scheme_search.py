"""Backend adapter for scheme-search tools on the shared MCP server."""

from mcp import Client
from pydantic import ValidationError

from src.api.scheme_search import SchemePassage
from src.workflow.errors import MCPToolError
from src.workflow.scam_screen import apply_scam_screen


class ScreenedSearchPassages(list[SchemePassage]):
    """Keep normal list behavior while reporting omitted scam passages."""

    def __init__(self, passages: list[SchemePassage], omitted_count: int) -> None:
        super().__init__(passages)
        self.omitted_count = omitted_count


async def search_scheme_passages(
    client: Client,
    query: str,
    *,
    jurisdiction: str | None = None,
    language: str | None = None,
    limit: int = 10,
) -> ScreenedSearchPassages:
    """Validate search output and omit only passages containing detected scams."""

    arguments: dict[str, str | int] = {"query": query, "limit": limit}
    if jurisdiction is not None:
        arguments["jurisdiction"] = jurisdiction
    if language is not None:
        arguments["language"] = language

    try:
        result = await client.call_tool("search_schemes", arguments)
    except Exception as error:
        raise MCPToolError(
            "Could not call the MCP scheme-search tool."
        ) from error

    if result.is_error or result.structured_content is None:
        raise MCPToolError(
            "The MCP scheme-search tool returned an error."
        )

    try:
        records = result.structured_content["result"]
        if not isinstance(records, list):
            raise TypeError("Search result must be a list.")
        passages = [SchemePassage.model_validate(record) for record in records]
    except (KeyError, TypeError, ValidationError) as error:
        raise MCPToolError(
            "The MCP scheme-search tool returned an invalid response."
        ) from error

    clean = []
    for passage in passages:
        displayed = "\n".join((
            passage.passage_id, passage.scheme_id, passage.scheme_name,
            passage.section, passage.text,
            passage.source.publisher, str(passage.source.url),
            passage.source.locator or "",
        ))
        if not apply_scam_screen(displayed).flagged:
            clean.append(passage)
    return ScreenedSearchPassages(clean, len(passages) - len(clean))
