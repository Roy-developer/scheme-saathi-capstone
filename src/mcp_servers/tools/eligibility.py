"""Register deterministic eligibility tools on the shared MCP server."""

from collections.abc import Mapping

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from src.api.eligibility import (
    EligibilityResponse,
    evaluate_mock_eligibility,
)
from src.mcp_servers.contracts import tool_error
from src.rules.facts import FactRegistry, TypedFactStore
from src.rules.bundles import SchemeBundle
from src.rules.models import HouseholdProfile, RulePackage
from src.mcp_servers.rule_data import get_active_rule_data


def evaluate_registered_profile(
    scheme_id: str,
    profile: HouseholdProfile | TypedFactStore,
    packages: Mapping[str, RulePackage],
    bundles: Mapping[str, SchemeBundle],
    registry: FactRegistry,
) -> EligibilityResponse:
    """Evaluate legacy or registry-based inputs using the active bundle."""

    package = packages.get(scheme_id)
    bundle = bundles.get(scheme_id)
    if package is None or bundle is None:
        raise KeyError(scheme_id)
    if isinstance(profile, TypedFactStore):
        profile = TypedFactStore.from_wire(profile.to_wire(), registry)
    return evaluate_mock_eligibility(
        profile,
        package,
        registry=registry,
        legacy_profile_mapping=bundle.legacy_profile_mapping,
    )


def register_tools(mcp: MCPServer) -> None:
    """Add the eligibility tool to an existing MCP server."""

    # Load every rule package once when the MCP server starts.
    provider = get_active_rule_data()
    rule_packages = provider.packages
    bundles = provider.bundles

    # @mcp.tool() publishes this function so MCP clients can call it by name.
    # The type hints become the tool's input and output schema, so MCP checks
    # the profile against HouseholdProfile before this code runs.
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Evaluate synthetic scheme eligibility",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def evaluate_eligibility(
        scheme_id: str,
        profile: HouseholdProfile | TypedFactStore,
    ) -> EligibilityResponse:
        """Evaluate a synthetic household against any loaded scheme package."""

        if scheme_id not in rule_packages or scheme_id not in bundles:
            raise tool_error("not_found", "Unknown scheme.")
        return evaluate_registered_profile(
            scheme_id,
            profile,
            rule_packages,
            bundles,
            provider.registry,
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List required scheme facts",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def required_facts(scheme_id: str) -> list[str]:
        """Return the versioned rule package's declared facts for a scheme."""

        package = rule_packages.get(scheme_id)
        if package is None:
            raise tool_error("not_found", "Unknown scheme.")
        return list(package.required_facts)
