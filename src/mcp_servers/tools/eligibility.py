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

    rule_packages = RulePackageProvider().packages

    @mcp.tool()
    def evaluate_eligibility(
        scheme_id: str,
        profile: HouseholdProfile,
    ) -> EligibilityResponse:
        """Evaluate a synthetic household against any loaded scheme package."""

        package = rule_packages.get(scheme_id)
        if package is None:
            raise ToolError(f"Unknown scheme: {scheme_id}")

        return evaluate_mock_eligibility(profile, package)
