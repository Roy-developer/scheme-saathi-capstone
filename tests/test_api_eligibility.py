"""Test deterministic mock eligibility API behavior."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.scheme_search import load_passages
from src.workflow.journey import JourneyResponse


ENDPOINT = "/api/v1/schemes/IGNWPS-MH/evaluate"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Run API startup, including launching and connecting to the MCP server."""

    # TestClient's context manager runs FastAPI's lifespan startup/shutdown.
    with TestClient(app) as test_client:
        # While yielded, the MCP stdio connection is available to API routes.
        yield test_client


def request_payload(
    *,
    date_of_birth: str = "1986-10-30",
    is_widow: bool = True,
    bpl_card_shown: bool | None = True,
) -> dict[str, object]:
    return {
        "date_of_birth": date_of_birth,
        "application_date": "2026-10-30",
        "is_widow": is_widow,
        "bpl_card_shown": bpl_card_shown,
    }


def test_startup_logs_loaded_package_details(caplog: pytest.LogCaptureFixture) -> None:
    # Capture startup logging while TestClient starts the API and MCP process.
    with caplog.at_level(logging.INFO, logger="src.api.app"):
        with TestClient(app):
            pass

    # Startup should report the rules package loaded before serving requests.
    assert "IGNWPS-MH v1.0.0 (4 rules)" in caplog.text
    # The API should also log that its MCP client connected successfully.
    assert "Connected to the local Saathi MCP server" in caplog.text


def test_health_endpoint(client: TestClient) -> None:
    # A running API has already connected to MCP through the fixture above.
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "IGNWPS-MH" in client.app.state.rule_packages


def test_inclusive_age_boundaries_are_eligible(client: TestClient) -> None:
    # Each request crosses FastAPI and MCP before reaching the deterministic rules.
    for date_of_birth, expected_age in (
        ("1986-10-30", 40),
        ("1947-10-30", 79),
    ):
        response = client.post(
            ENDPOINT,
            json=request_payload(date_of_birth=date_of_birth),
        )

        assert response.status_code == 200
        assert response.json()["result"] == "eligible"
        assert response.json()["age_on_application_date"] == expected_age


def test_age_outside_inclusive_boundaries_is_not_eligible(client: TestClient) -> None:
    for date_of_birth in ("1987-10-30", "1946-10-30"):
        response = client.post(
            ENDPOINT,
            json=request_payload(date_of_birth=date_of_birth),
        )

        assert response.status_code == 200
        assert response.json()["result"] == "not_eligible"


def test_missing_bpl_card_needs_more_information(client: TestClient) -> None:
    response = client.post(
        ENDPOINT,
        json=request_payload(bpl_card_shown=False),
    )

    body = response.json()
    assert body["result"] == "need_more_information"
    assert body["missing_fields"] == ["government_bpl_card"]


def test_unknown_bpl_card_answer_needs_more_information(client: TestClient) -> None:
    response = client.post(
        ENDPOINT,
        json=request_payload(bpl_card_shown=None),
    )

    assert response.json()["result"] == "need_more_information"


def test_not_widow_does_not_pass_rule(client: TestClient) -> None:
    response = client.post(
        ENDPOINT,
        json=request_payload(is_widow=False),
    )

    assert response.json()["result"] == "not_eligible"
    assert response.json()["deciding_rule_ids"] == ["IGNWPS-MH-WIDOW-01"]


def test_response_includes_official_source_citation(client: TestClient) -> None:
    response = client.post(ENDPOINT, json=request_payload())

    evidence = response.json()["evidence"]
    assert evidence
    assert evidence[0]["source_url"].startswith(
        "https://sjsa.maharashtra.gov.in/"
    )
    assert "40 to 79 years" in evidence[0]["source_text"]


def test_unknown_scheme_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/schemes/UNKNOWN/evaluate",
        json=request_payload(),
    )

    assert response.status_code == 404


def test_birth_date_after_application_date_is_rejected(client: TestClient) -> None:
    response = client.post(
        ENDPOINT,
        json={
            **request_payload(),
            "date_of_birth": "2026-10-31",
        },
    )

    assert response.status_code == 422


def test_search_endpoint_calls_adapter_with_filters_and_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_search(
        mcp_client,
        query,
        *,
        jurisdiction,
        language,
        limit,
    ):
        calls.append((query, jurisdiction, language, limit))
        return list(
            load_passages(
                Path(__file__).resolve().parents[1]
                / "data"
                / "schemes"
                / "passages.json"
            )[:limit]
        )

    monkeypatch.setattr("src.api.app.search_scheme_passages", fake_search)
    response = client.get(
        "/api/v1/schemes/search",
        params={
            "query": "below poverty line",
            "jurisdiction": "IN-MH",
            "language": "en",
            "limit": 2,
        },
    )

    assert response.status_code == 200
    passages = response.json()
    assert len(passages) == 2
    assert passages[0]["scheme_id"] == "IGNWPS-MH"
    assert passages[0]["review_status"] == "reviewed"
    assert calls == [("below poverty line", "IN-MH", "en", 2)]


def test_search_endpoint_returns_empty_list_for_no_match(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr("src.api.app.search_scheme_passages", fake_search)
    response = client.get(
        "/api/v1/schemes/search",
        params={"query": "widow", "jurisdiction": "IN-KA"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_search_endpoint_rejects_limit_above_maximum(client: TestClient) -> None:
    response = client.get(
        "/api/v1/schemes/search",
        params={"query": "widow", "limit": 101},
    )

    assert response.status_code == 422


def test_search_endpoint_limits_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr("src.api.app.search_scheme_passages", fake_search)
    response = client.get(
        "/api/v1/schemes/search",
        params={"query": "widow", "limit": 2},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_journey_endpoint_returns_orchestrated_search(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = "0e8fa6c3-46a1-44db-b4f3-4f2c9d981af1"
    passage = load_passages(
        Path(__file__).resolve().parents[1]
        / "data"
        / "schemes"
        / "passages.json"
    )[0]
    calls = []

    async def fake_run_journey(graph, journey_request):
        calls.append((graph, journey_request))
        return JourneyResponse(
            conversation_id=journey_request.conversation_id,
            plan="Find a source-cited scheme.",
            status="search_results",
            message="Found one cited passage.",
            passages=[passage],
        )

    monkeypatch.setattr("src.api.app.run_journey", fake_run_journey)
    response = client.post(
        "/api/v1/journey",
        json={
            "action": "search",
            "conversation_id": conversation_id,
            "query": "widow pension",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "search_results"
    assert response.json()["passages"][0]["passage_id"] == passage.passage_id
    assert calls[0][1].query == "widow pension"


def test_forget_journey_rejects_non_uuid_id(client: TestClient) -> None:
    response = client.delete("/api/v1/journey/not-a-uuid")

    assert response.status_code == 422


def test_forget_journey_deletes_checkpoint_thread(client: TestClient) -> None:
    response = client.delete(
        "/api/v1/journey/0e8fa6c3-46a1-44db-b4f3-4f2c9d981af1"
    )

    assert response.status_code == 204
