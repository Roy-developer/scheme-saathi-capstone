"""Verify the shared API exposes only its intended minimal contract."""

from fastapi.testclient import TestClient

from src.api.app import app


client = TestClient(app)


def test_health_endpoint() -> None:
    """The operations endpoint reports a healthy process."""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_service_info_is_safe_for_shared_development(
    monkeypatch,
) -> None:
    """Deployment metadata remains explicit and marks the service synthetic."""

    monkeypatch.setenv("APP_VERSION", "git-abc123")
    monkeypatch.setenv("DEPLOYED_REF", "feature/example")

    response = client.get("/api/v1/info")

    assert response.status_code == 200
    assert response.json() == {
        "name": "scheme-saathi-api",
        "api_version": "0.1.0",
        "app_version": "git-abc123",
        "deployed_ref": "feature/example",
        "synthetic_only": True,
    }


def test_openapi_document_is_available() -> None:
    """FastAPI publishes an OpenAPI document with the expected identity."""

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Scheme Saathi API"
