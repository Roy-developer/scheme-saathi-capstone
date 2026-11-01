"""MCP server exposing the deterministic synthetic eligibility tool."""

# MCPServer creates the object that registers and serves our MCP tools.
from mcp.server import MCPServer
# ToolError marks a failed tool call so the MCP client knows it did not succeed.
from mcp.server.mcpserver.exceptions import ToolError

# Reuse the API's request/response types so the tool speaks the same contract.
from src.api.eligibility import (
    EligibilityRequest,
    EligibilityResponse,
    evaluate_mock_eligibility,
)
# Load the same reviewed, version-controlled rules used by the API.
from src.rules.data_provider import RulePackageProvider

# Create a named MCP server; clients see this identity when connecting.
mcp = MCPServer("scheme-saathi-rule-engine")
# Read and validate all rule packages once when this server process starts.
# The provider exposes a read-only mapping from scheme IDs to rule packages.
rule_packages = RulePackageProvider().packages

# @mcp.tool() publishes this function and derives its input/output schemas
# from the Python type hints below.
@mcp.tool()
def evaluate_eligibility(
    scheme_id: str,
    profile: EligibilityRequest,
) -> EligibilityResponse:
    """Return a rule-based result and source citations for a synthetic profile."""
    # Find the preloaded rules; an unknown scheme must not get guessed at.
    package = rule_packages.get(scheme_id)
    # Raise a tool error instead of returning an error-looking success value.
    if package is None:
        raise ToolError(f"Unknown scheme: {scheme_id}")

    # Call the existing deterministic code; the MCP layer does not decide policy.
    return evaluate_mock_eligibility(profile, package)


@mcp.tool()
def identify_scheme(scheme_id:str) ->str:
    """Confirm which scheme ID the caller asked about."""
    return f"Received scheme ID: {scheme_id}"

if __name__ == "__main__":
    # When launched as `python -m src.mcp_servers.rule_engine`, serve MCP
    # messages over stdio. Imports during tests do not start a server process.
    mcp.run()