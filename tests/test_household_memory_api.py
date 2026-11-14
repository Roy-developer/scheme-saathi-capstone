"""Memory API consent gates fail closed before accessing stored data."""

import asyncio
import sqlite3
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from langgraph.store.memory import InMemoryStore

import src.api.app as api
from src.workflow.household_memory import HOUSEHOLD_NAMESPACE


client = TestClient(api.app)


def test_load_household_requires_memory_consent() -> None:
    response = client.get("/api/v1/household/SAATHI-AB12CD34EF")

    assert response.status_code == 403
    assert "Explicit memory consent" in response.json()["detail"]


@pytest.mark.parametrize(
    "failure",
    [
        sqlite3.OperationalError("temporary failure"),
        api.ApplicationTaskError(503, "temporary failure"),
    ],
)
def test_combined_forget_attempts_both_stores_when_journey_delete_fails(
    monkeypatch,
    failure: Exception,
) -> None:
    attempted: list[str] = []

    async def fail_journey(request, conversation_uuid: UUID) -> None:
        attempted.append("journey")
        raise failure

    async def delete_household(store, return_code: str) -> None:
        attempted.append(f"household:{return_code}")

    monkeypatch.setattr(api, "_forget_journey_data", fail_journey)
    monkeypatch.setattr(api, "delete_household", delete_household)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(journey_store=object()))
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.forget_personal_data(
                {
                    "conversation_id": "00000000-0000-0000-0000-000000000001",
                    "return_code": "SAATHI-AB12CD34EF",
                },
                request,
            )
        )

    assert error.value.status_code == 503
    assert attempted == ["journey", "household:SAATHI-AB12CD34EF"]


def test_combined_forget_deletes_household_after_journey_succeeds(
    monkeypatch,
) -> None:
    attempted: list[str] = []
    store = InMemoryStore()

    async def forget_journey(request, conversation_uuid: UUID) -> None:
        attempted.append("journey")

    async def run() -> None:
        await store.aput(
            HOUSEHOLD_NAMESPACE,
            "SAATHI-AB12CD34EF",
            {"synthetic": True},
        )
        monkeypatch.setattr(api, "_forget_journey_data", forget_journey)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(journey_store=store))
        )
        await api.forget_personal_data(
            {
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "return_code": "SAATHI-AB12CD34EF",
            },
            request,
        )
        assert await store.aget(HOUSEHOLD_NAMESPACE, "SAATHI-AB12CD34EF") is None

    asyncio.run(run())
    assert attempted == ["journey"]


def test_save_household_requires_memory_consent() -> None:
    response = client.post(
        "/api/v1/household",
        json={"conversation_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 403
    assert "Explicit memory consent" in response.json()["detail"]
