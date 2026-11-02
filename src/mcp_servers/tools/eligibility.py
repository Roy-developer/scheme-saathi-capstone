"""Register deterministic eligibility tools on the shared MCP server."""

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.api.eligibility import (
    EligibilityResponse,
    evaluate_mock_eligibility,
)
from src.rules.data_provider import RulePackageProvider
from src.rules.models import HouseholdProfile


def register_tools(mcp: MCPServer) -> None:
    """Add the eligibility tool to an existing MCP server."""

    # Load every rule package once when the MCP server starts.
    rule_packages = RulePackageProvider().packages

    # @mcp.tool() publishes this function so MCP clients can call it by name.
    # The type hints become the tool's input and output schema, so MCP checks
    # the profile against HouseholdProfile before this code runs.
    @mcp.tool()
    def evaluate_eligibility(
        scheme_id: str,
        profile: HouseholdProfile,
    ) -> EligibilityResponse:
        """Evaluate a synthetic household against any loaded scheme package."""

        package = rule_packages.get(scheme_id)
        if package is None:
            # ToolError sends a clear error back to the caller.
            raise ToolError(f"Unknown scheme: {scheme_id}")

        # Plain code decides eligibility; no LLM is involved.
        return evaluate_mock_eligibility(profile, package)
