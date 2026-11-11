"""Verify trusted dispatch permissions and direct success of every MCP tool."""

import asyncio
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from src.api.scheme_search import HybridSchemeRetriever, load_passages
from src.config import PROJECT_ROOT
from src.mcp_servers.doc_check_server import mcp as documents_server
from src.mcp_servers.mock_portal_server import mcp as portal_server
from src.mcp_servers.rule_engine_server import mcp as rules_server
from src.mcp_servers.schemes_kb_server import mcp as kb_server
from src.mcp_servers.service_routing import SERVICE_TOOLS, ServiceClientRouter
from src.mcp_servers.tools import applications
from src.portal.app import app as portal_app
from src.workflow.errors import MCPToolError


@pytest.mark.parametrize(
    "actor,tool,arguments,bound_journey",
    [
        ("intake", "search_schemes", {"query": "pension"}, None),
        ("eligibility", "check_documents", {"scheme_id": "IGNWPS-MH"}, None),
        ("documents", "create_draft", {"journey_id": "synthetic-a"}, "synthetic-a"),
        ("application", "mock_portal", {"action": "approve", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("application", "mock_portal", {"action": "reject", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("application", "mock_portal", {"action": "delete_journey", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("application", "mock_portal", {"action": ["approve"], "journey_id": "synthetic-a"}, "synthetic-a"),
        ("api_read", "mock_portal", {"action": "edit_draft", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("api_read", "mock_portal", {"action": "approve", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("api_read", "mock_portal", {"action": "submit", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("api_read", "mock_portal", {"action": "delete_journey", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("human_approval", "submit_draft", {"journey_id": "synthetic-a"}, "synthetic-a"),
        ("session_cleanup", "mock_portal", {"action": "approve", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("application", "get_draft", {"journey_id": "synthetic-b"}, "synthetic-a"),
        ("application", "create_draft", {"journey_id": "synthetic-a"}, None),
        ("eligibility", "required_facts", {"actor": "human_approval"}, None),
        ("application", "mock_portal", {"action": "begin_profile_change", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("eligibility", "mock_portal", {"action": "bind_rules", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("documents", "mock_portal", {"action": "bind_documents", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("human_approval", "mock_portal", {"action": "reconcile_profile", "journey_id": "synthetic-a"}, "synthetic-a"),
        ("dependency_control", "mock_portal", {"action": "approve", "journey_id": "synthetic-a"}, "synthetic-a"),
    ],
)
def test_denied_calls_never_execute(actor, tool, arguments, bound_journey) -> None:
    """Reject cross-specialist, privileged action, and context spoofing calls."""

    class RecordingClient:
        """Record any service execution so denial cannot hide a side effect."""

        calls = 0

        async def call_tool(self, name: str, arguments: dict) -> object:
            self.calls += 1
            return {}

    service = RecordingClient()
    router = ServiceClientRouter(
        {name: service for name in SERVICE_TOOLS}
    ).for_actor(actor, bound_journey)

    with pytest.raises(MCPToolError):
        asyncio.run(router.call_tool(tool, arguments))
    assert service.calls == 0


@pytest.mark.parametrize(
    "actor,action",
    [
        ("api_read", "get_draft"),
        ("application", "create_draft"),
        ("application", "edit_draft"),
        ("application", "submit"),
        ("human_approval", "approve"),
        ("human_approval", "reject"),
        ("session_cleanup", "delete_journey"),
        ("dependency_control", "begin_profile_change"),
        ("dependency_control", "reconcile_profile"),
        ("dependency_control", "bind_documents"),
        ("dependency_control", "bind_rules"),
        ("dependency_control", "dependency_status"),
    ],
)
def test_trusted_actors_execute_only_their_allowed_portal_actions(actor, action) -> None:
    """Keep human decisions, application writes, and cleanup as separate capabilities."""

    class RecordingClient:
        """Record the action delivered to the owning service."""

        received: dict[str, object] | None = None

        async def call_tool(self, name: str, arguments: dict) -> object:
            self.received = arguments
            return {"action": arguments["action"]}

    service = RecordingClient()
    router = ServiceClientRouter(
        {"mock-portal": service}
    ).for_actor(actor, "synthetic-a")
    arguments = {"action": action, "journey_id": "synthetic-a"}
    assert asyncio.run(router.call_tool("mock_portal", arguments)) == {"action": action}
    assert service.received == arguments


def test_every_inventory_tool_succeeds_via_mcp_and_http_portal(monkeypatch) -> None:
    """Invoke each published tool offline, including specialized portal actions."""

    database = Path.cwd() / f".phase1-tool-test-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("SCHEME_SAATHI_PORTAL_DB", str(database))
    passages = load_passages(PROJECT_ROOT / "data" / "schemes" / "passages" / "ignwps_mh_passages.json")
    monkeypatch.setattr(
        HybridSchemeRetriever, "search",
        lambda _self, *_args, **_kwargs: passages[:1],
    )
    called: set[str] = set()
    with TestClient(portal_app) as http_client:
        def offline_http(request, timeout: int):
            """Deliver adapter HTTP requests in-process without opening a socket."""

            response = http_client.post(
                "/internal/actions", json=json.loads(request.data)
            )
            assert response.status_code == 200, response.text
            return io.BytesIO(response.content)

        monkeypatch.setattr(applications.urllib.request, "urlopen", offline_http)

        async def scenario() -> None:
            servers = {
                "rule-engine": rules_server,
                "schemes-kb": kb_server,
                "doc-check": documents_server,
                "mock-portal": portal_server,
            }
            profile = {
                "date_of_birth": "1986-01-01",
                "application_date": "2026-01-01",
                "is_widow": True, "bpl_card_shown": True,
            }
            documents = {
                "identity_proof": "available", "age_proof": "available",
                "widow_status_proof": "available", "bpl_proof": "available",
            }
            for service_name, server in servers.items():
                async with Client(server) as client:
                    async def invoke(name: str, arguments: dict) -> dict:
                        result = await client.call_tool(name, arguments)
                        assert not result.is_error, result.content
                        assert result.structured_content is not None
                        called.add(name)
                        return result.structured_content

                    if service_name == "rule-engine":
                        verdict = await invoke("evaluate_eligibility", {
                            "scheme_id": "IGNWPS-MH", "profile": profile,
                        })
                        assert verdict["result"] == "eligible"
                        await invoke("required_facts", {"scheme_id": "IGNWPS-MH"})
                    elif service_name == "schemes-kb":
                        await invoke("search_schemes", {"query": "widow pension"})
                        await invoke("get_scheme", {"scheme_id": "IGNWPS-MH"})
                        await invoke("get_documents", {"scheme_id": "IGNWPS-MH"})
                    elif service_name == "doc-check":
                        report = await invoke("check_documents", {
                            "scheme_id": "IGNWPS-MH", "documents": documents,
                        })
                        assert report["status"] == "checklist_complete"
                    else:
                        draft = await invoke("create_draft", {
                            "journey_id": "synthetic-tools",
                            "scheme_id": "IGNWPS-MH",
                            "profile": profile, "documents": documents,
                        })
                        identity = {
                            "journey_id": "synthetic-tools",
                            "draft_id": draft["draft_id"],
                        }
                        await invoke("get_draft", identity)
                        status = await invoke("get_status", identity)
                        assert status["status"] == "draft"
                        exact = {
                            **identity, "revision": draft["revision"],
                            "fingerprint": draft["fingerprint"],
                        }
                        approved = await invoke(
                            "mock_portal", {"action": "approve", **exact}
                        )
                        exact["approval_token"] = approved["approval_token"]
                        submitted = await invoke("submit_draft", exact)
                        assert submitted["receipt_id"]

        try:
            asyncio.run(scenario())
            assert called == set().union(*SERVICE_TOOLS.values())
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(database) + suffix).unlink(missing_ok=True)
