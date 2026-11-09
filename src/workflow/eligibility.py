"""Backend adapter that calls and validates the rule-engine MCP tool."""

# Client sends MCP protocol requests to a connected MCP server.
from mcp import Client
# Pydantic raises this when returned data does not match our output schema.
from pydantic import ValidationError

# These models define the facts sent to the tool and the response expected.
from src.api.eligibility import EligibilityResponse
from src.rules.facts import TypedFactStore
from src.workflow.errors import MCPToolError


async def evaluate_eligibility(
    client: Client,
    scheme_id: str,
    profile: TypedFactStore,
) -> EligibilityResponse:
    """Call the MCP tool and validate its structured result."""
    # Ask the connected server for the named tool using JSON-compatible inputs.
    try:
        result = await client.call_tool(
            "evaluate_eligibility",
            {
                # Tell the server which versioned scheme rules to use.
                "scheme_id": scheme_id,
                # Convert date values and the Pydantic profile into JSON values.
                "profile": profile.to_wire(),
            },
        )
    # Preserve the original cause for developers while exposing a safe error.
    except Exception as error:
        raise MCPToolError(
            "Could not call the MCP eligibility tool."
        ) from error

    # Do not mistake a failed call or missing structured data for a verdict.
    if result.is_error or result.structured_content is None:
        raise MCPToolError(
            "The MCP eligibility tool returned an error."
        )

    # Validate server output before the API sends it to the UI.
    try:
        return EligibilityResponse.model_validate(result.structured_content)
    # Reject malformed output rather than returning success-shaped data.
    except ValidationError as error:
        raise MCPToolError(
            "The MCP eligibility tool returned an invalid response."
        ) from error
