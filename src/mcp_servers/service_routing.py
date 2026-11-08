"""Route MCP calls only to the independently discovered service that owns them."""

from dataclasses import dataclass
from typing import Literal, Protocol

from src.workflow.errors import MCPToolError

ToolActor = Literal[
    "api_read", "intake", "eligibility", "documents",
    "application", "human_approval", "session_cleanup",
    "dependency_control",
]

ACTOR_TOOLS: dict[ToolActor, frozenset[str]] = {
    "api_read": frozenset({
        "evaluate_eligibility", "required_facts", "search_schemes",
        "get_scheme", "get_documents", "get_draft", "get_status", "mock_portal",
    }),
    "intake": frozenset({"required_facts", "evaluate_eligibility"}),
    "eligibility": frozenset({
        "evaluate_eligibility", "search_schemes", "get_scheme",
    }),
    "documents": frozenset({"get_documents", "check_documents"}),
    "application": frozenset({
        "create_draft", "get_draft", "get_status", "submit_draft", "mock_portal",
    }),
    "human_approval": frozenset({"mock_portal"}),
    "session_cleanup": frozenset({"mock_portal"}),
    "dependency_control": frozenset({"mock_portal"}),
}
PORTAL_ACTIONS: dict[ToolActor, frozenset[str]] = {
    "api_read": frozenset({"list_drafts", "get_draft", "get_status"}),
    "application": frozenset({
        "list_drafts", "get_draft", "get_status",
        "create_draft", "edit_draft", "submit",
    }),
    "human_approval": frozenset({"get_draft", "approve", "reject"}),
    "session_cleanup": frozenset({"delete_journey"}),
    "dependency_control": frozenset({
        "begin_profile_change", "reconcile_profile", "bind_documents", "bind_rules",
        "dependency_status",
    }),
}

SERVICE_TOOLS: dict[str, frozenset[str]] = {
    "rule-engine": frozenset({"evaluate_eligibility", "required_facts"}),
    "schemes-kb": frozenset(
        {"search_schemes", "get_scheme", "get_documents"}
    ),
    "doc-check": frozenset({"check_documents"}),
    "mock-portal": frozenset(
        {
            "create_draft",
            "get_draft",
            "get_status",
            "submit_draft",
            "mock_portal",
        }
    ),
}


class ToolClient(Protocol):
    """The small client interface used by workflow adapters and tests."""

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> object:
        """Call a discovered tool by name."""


@dataclass
class ServiceClientRouter:
    """Dispatch a tool call to one MCP process based on its discovered owner."""

    clients: dict[str, ToolClient]
    actor: ToolActor = "api_read"
    journey_id: str | None = None

    def for_actor(
        self, actor: ToolActor, journey_id: str | None = None
    ) -> "ServiceClientRouter":
        """Bind identity in trusted Python code, never from tool arguments."""

        if actor not in ACTOR_TOOLS:
            raise MCPToolError("Unknown tool caller.")
        return ServiceClientRouter(self.clients, actor, journey_id)

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> object:
        """Authorize caller and action before executing any service request."""

        if name not in ACTOR_TOOLS[self.actor]:
            raise MCPToolError("This caller is not allowed to use this tool.")
        if name in SERVICE_TOOLS["mock-portal"]:
            action = (
                arguments.get("action")
                if name == "mock_portal"
                else "submit" if name == "submit_draft" else name
            )
            if (
                not isinstance(action, str)
                or action not in PORTAL_ACTIONS.get(self.actor, frozenset())
            ):
                raise MCPToolError("This caller is not allowed to use this portal action.")
            if self.journey_id is None or arguments.get("journey_id") != self.journey_id:
                raise MCPToolError("Portal calls require the bound journey context.")
        if any(key in arguments for key in ("actor", "caller", "trusted_actor")):
            raise MCPToolError("Tool arguments cannot set caller identity.")

        owners = [
            service
            for service, tools in SERVICE_TOOLS.items()
            if name in tools
        ]
        if len(owners) != 1 or owners[0] not in self.clients:
            raise ValueError(f"No unique MCP service owns tool {name!r}.")
        return await self.clients[owners[0]].call_tool(name, arguments)
