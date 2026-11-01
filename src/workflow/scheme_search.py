"""Backend adapter for scheme-search tools on the shared MCP server."""

from mcp import Client
from pydantic import ValidationError

from src.api.scheme_search import SchemePassage
from src.workflow.errors import MCPToolError


async def search_scheme_passages(
    client: Client,
    query: str,
    *,
    jurisdiction: str | None = None,
    language: str | None = None,
    limit: int = 10,
) -> list[SchemePassage]:
    """Call the MCP search tool and validate every returned passage."""

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
        return [SchemePassage.model_validate(record) for record in records]
    except (KeyError, TypeError, ValidationError) as error:
        raise MCPToolError(
            "The MCP scheme-search tool returned an invalid response."
        ) from error
