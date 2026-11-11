"""Verify service isolation, tool discovery, schema checks, and portal boundary."""

import asyncio
import json
from pathlib import Path
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from src.mcp_servers.doc_check_server import mcp as doc_check_server
from src.mcp_servers.mock_portal_server import mcp as mock_portal_server
from src.mcp_servers.rule_engine_server import mcp as rule_engine_server
from src.mcp_servers.schemes_kb_server import mcp as schemes_kb_server
from src.mcp_servers.service_routing import (
    SERVICE_TOOLS,
    ServiceClientRouter,
)
from src.api import portal_service
from src.portal.app import app as portal_app


def test_portal_health_requires_the_startup_identity_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEME_SAATHI_PORTAL_HEALTH_TOKEN", "test-startup-token")

    with TestClient(portal_app) as client:
        unauthorized = client.get("/health")
        authorized = client.get(
            "/health",
            headers={"X-Scheme-Saathi-Startup-Token": "test-startup-token"},
        )

    assert unauthorized.status_code == 404
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "ok"
    assert len(authorized.json()["proof"]) == 64


def test_portal_startup_rejects_an_unrelated_http_health_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self, _exc_type: object, _exc_value: object, _traceback: object
        ) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    process = FakeProcess()
    requests = []

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        requests.append(request)
        return FakeResponse()

    times = iter(
        (0.0, 0.0, portal_service.PORTAL_STARTUP_TIMEOUT_SECONDS + 1)
    )
    monkeypatch.setattr(
        portal_service, "portal_host_port", lambda: ("127.0.0.1", 8765)
    )
    monkeypatch.setattr(
        portal_service.subprocess, "Popen", lambda *args, **kwargs: process
    )
    monkeypatch.setattr(portal_service.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(portal_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(portal_service.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="did not become ready"):
        portal_service.start_portal_service(Path("portal-test.sqlite3"))

    assert requests
    assert requests[0].get_header("X-scheme-saathi-startup-token")


def test_each_mcp_process_discovers_only_its_registered_tools() -> None:
    servers = {
        "rule-engine": rule_engine_server,
        "schemes-kb": schemes_kb_server,
        "doc-check": doc_check_server,
        "mock-portal": mock_portal_server,
    }

    async def discover() -> dict[str, set[str]]:
        discovered: dict[str, set[str]] = {}
        for service_name, server in servers.items():
            async with Client(server) as client:
                listing = await client.list_tools()
                discovered[service_name] = {tool.name for tool in listing.tools}
        return discovered

    inventory = asyncio.run(discover())

    assert inventory == {
        service_name: set(tool_names)
        for service_name, tool_names in SERVICE_TOOLS.items()
    }
    assert inventory["rule-engine"] == {"evaluate_eligibility", "required_facts"}
    assert inventory["doc-check"] == {"check_documents"}


@pytest.mark.parametrize(
    ("scheme_id", "expected_ids"),
    [
        (
            "IGNWPS-MH",
            {"identity_proof", "age_proof", "widow_status_proof", "bpl_proof"},
        ),
        (
            "PM-KISAN-IN",
            {"identity_proof", "land_record", "bank_account_proof"},
        ),
    ],
)
def test_knowledge_tools_share_the_active_document_checklist(
    scheme_id: str, expected_ids: set[str]
) -> None:
    async def read_tools() -> tuple[dict, dict, dict]:
        async with Client(schemes_kb_server) as client:
            scheme = await client.call_tool(
                "get_scheme", {"scheme_id": scheme_id}
            )
            documents = await client.call_tool(
                "get_documents", {"scheme_id": scheme_id}
            )
        async with Client(doc_check_server) as client:
            assessment = await client.call_tool(
                "check_documents", {"scheme_id": scheme_id, "documents": {}}
            )
        return (
            scheme.structured_content,
            documents.structured_content,
            assessment.structured_content,
        )

    scheme, documents, assessment = asyncio.run(read_tools())

    assert scheme["source_ids"]
    assert scheme["scheme_name"]
    assert documents["demo_only"] is True
    assert documents["requirements_status"] == "demo_only_unverified"
    assert documents["checklist_version"] == assessment["checklist_version"]
    assert documents["active_fingerprint"] == assessment["active_fingerprint"]
    assert {
        item["document_id"]
        for group in documents["groups"]
        for item in group["alternatives"]
    } == expected_ids
    assert {
        item["document_id"] for item in assessment["requirements"]
    } == expected_ids


def test_tool_annotations_distinguish_reads_from_portal_writes() -> None:
    async def get_annotations() -> tuple[dict, dict]:
        async with Client(rule_engine_server) as rule_client:
            rules = await rule_client.list_tools()
        async with Client(mock_portal_server) as portal_client:
            portal = await portal_client.list_tools()
        return (
            {tool.name: tool.annotations for tool in rules.tools},
            {tool.name: tool.annotations for tool in portal.tools},
        )

    rules, portal = asyncio.run(get_annotations())

    assert rules["evaluate_eligibility"].read_only_hint is True
    assert portal["get_draft"].read_only_hint is True
    assert portal["create_draft"].read_only_hint is False
    assert portal["submit_draft"].destructive_hint is True


def test_mcp_rejects_invalid_tool_schema_and_returns_typed_error() -> None:
    async def check() -> tuple[bool, bool, str]:
        async with Client(doc_check_server) as client:
            invalid_schema = await client.call_tool(
                "check_documents",
                {"scheme_id": "IGNWPS-MH", "documents": {"age_proof": "no"}},
            )
        async with Client(rule_engine_server) as client:
            unknown_scheme = await client.call_tool(
                "required_facts", {"scheme_id": "UNKNOWN"}
            )
            text = "\n".join(
                item.text for item in unknown_scheme.content if hasattr(item, "text")
            )
            return invalid_schema.is_error, unknown_scheme.is_error, text

    schema_error, service_error, text = asyncio.run(check())

    assert schema_error
    assert service_error
    envelope = json.loads(text.partition(": ")[2])
    assert envelope["error"]["code"] == "not_found"
    assert "input_value" not in envelope["error"]["message"]


def test_tool_router_calls_only_the_service_that_owns_a_tool() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.called: list[str] = []

        async def call_tool(self, name: str, arguments: dict) -> str:
            self.called.append(name)
            return name

    rule_client = FakeClient()
    kb_client = FakeClient()
    clients = {
        "rule-engine": rule_client,
        "schemes-kb": kb_client,
        "doc-check": FakeClient(),
        "mock-portal": FakeClient(),
    }
    router = ServiceClientRouter(clients)

    async def route() -> object:
        return await router.call_tool("required_facts", {"scheme_id": "IGNWPS-MH"})

    assert asyncio.run(route()) == "required_facts"
    assert rule_client.called == ["required_facts"]
    assert kb_client.called == []


def test_portal_http_service_owns_its_database(tmp_path, monkeypatch) -> None:
    database = tmp_path / "portal.sqlite3"
    monkeypatch.setenv("SCHEME_SAATHI_PORTAL_DB", str(database))
    payload = {
        "action": "create_draft",
        "journey_id": "synthetic-journey",
        "scheme_id": "IGNWPS-MH",
        "profile": {
            "date_of_birth": "1986-01-01",
            "is_widow": True,
        },
        "documents": {
            "identity_proof": "available",
            "age_proof": "available",
            "widow_status_proof": "available",
            "bpl_proof": "available",
        },
    }

    with TestClient(portal_app) as client:
        response = client.post("/internal/actions", json=payload)
        invalid = client.post(
            "/internal/actions", json={**payload, "unexpected": "field"}
        )

    assert response.status_code == 200
    assert response.json()["fingerprint"]
    assert invalid.status_code == 422
    assert database.exists()
