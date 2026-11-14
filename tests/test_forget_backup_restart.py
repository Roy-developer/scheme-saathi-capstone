"""Verify durable forget recovery after a synthetic scale-to-zero restart."""

import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import src.api.app as api
from src.api.database_backup import DatabaseBackups
from src.workflow.application_gate import application_gate_thread_id
from test_red_team_runtime import _draft, _eligible
from test_ui_integration import IntegratedUI, OFFLINE_SEARCH_BOOTSTRAP


def _has_row(path: Path, table: str, column: str, value: str) -> bool:
    """Read only fixed test tables from a temporary SQLite database."""

    connection = sqlite3.connect(path)
    try:
        return bool(connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,),
        ).fetchone())
    finally:
        connection.close()


def test_malformed_marker_prevents_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable recovery state must not be skipped on startup."""

    share = tmp_path / "share"
    marker_dir = share / ".pending-deletions"
    marker_dir.mkdir(parents=True)
    (marker_dir / "invalid.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SCHEME_SAATHI_BACKUP_DIR", str(share))
    monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(tmp_path / "journey.sqlite3"))
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "portal.sqlite3"))
    monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DB", str(tmp_path / "uploads.sqlite3"))
    monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DIR", str(tmp_path / "uploads"))
    with pytest.raises(ValueError, match="marker ID"):
        with TestClient(api.app):
            pytest.fail("The API must not serve with an invalid marker")


def test_restart_replays_pending_deletion_before_serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale backup and pending marker cannot restore deleted records."""

    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setenv("SCHEME_SAATHI_BACKUP_DIR", str(share))
    monkeypatch.setenv("SCHEME_SAATHI_BACKUP_INTERVAL_SECONDS", "3600")
    original_parameters = api.StdioServerParameters

    def offline_parameters(*args: object, **kwargs: object) -> object:
        if kwargs.get("args") == ["-m", "src.mcp_servers.schemes_kb_server"]:
            kwargs["args"] = ["-c", OFFLINE_SEARCH_BOOTSTRAP]
        return original_parameters(*args, **kwargs)

    monkeypatch.setattr(api, "StdioServerParameters", offline_parameters)

    def configure_instance(folder: Path) -> tuple[Path, Path]:
        journey = folder / "journey.sqlite3"
        portal = folder / "portal.sqlite3"
        monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(journey))
        monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(portal))
        monkeypatch.delenv("SCHEME_SAATHI_PORTAL_DB", raising=False)
        monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DB", str(folder / "uploads.sqlite3"))
        monkeypatch.setenv("SCHEME_SAATHI_UPLOAD_DIR", str(folder / "uploads"))
        return journey, portal

    _, portal = configure_instance(tmp_path / "first-instance")
    with TestClient(api.app) as client:
        harness = IntegratedUI(client, portal)
        journey = _eligible(harness)
        draft = _draft(harness, journey)
        other_journey = _eligible(harness)
        saved = client.post("/api/v1/household", json={
            "conversation_id": journey, "memory_consent": True,
        })
        assert saved.status_code == 200, saved.text
        code = saved.json()["return_code"]
        gate = application_gate_thread_id(journey, draft["draft_id"], draft["revision"])
        backups = client.app.state.backups
        backups.save(strict=True)
        save_one = backups._save_one
        assert _has_row(share / "journey.sqlite3", "checkpoints", "thread_id", gate)
        assert _has_row(share / "portal.sqlite3", "application_drafts", "draft_id", draft["draft_id"])

        def unavailable(_database: Path) -> None:
            raise OSError("synthetic snapshot failure")

        monkeypatch.setattr(backups, "_save_one", unavailable)
        response = client.request("DELETE", "/api/v1/forget", json={
            "conversation_id": journey, "return_code": code,
        })
        assert response.status_code == 503
        markers = backups.pending_deletions()
        assert len(markers) == 1
        assert UUID(gate) in [
            UUID(value) for value in markers[0][1]["gate_threads"]
        ]
        assert _has_row(share / "journey.sqlite3", "store", "key", code)
        # Model a crash after a mixed snapshot: the portal copy is already
        # deleted while the journey copy still contains old approval threads.
        save_one(portal)
        assert not _has_row(
            share / "portal.sqlite3", "application_drafts", "draft_id", draft["draft_id"]
        )

    configure_instance(tmp_path / "failed-recovery")
    with monkeypatch.context() as transient:
        def unavailable(_backups: DatabaseBackups, _database: Path) -> None:
            raise OSError("synthetic recovery snapshot failure")

        transient.setattr(DatabaseBackups, "_save_one", unavailable)
        with pytest.raises(BaseExceptionGroup) as failure:
            with TestClient(api.app):
                pytest.fail("The API must not serve before recovery succeeds")
        assert failure.value.subgroup(
            lambda error: isinstance(error, OSError)
            and str(error) == "synthetic recovery snapshot failure"
        ) is not None
    assert len(DatabaseBackups(share, []).pending_deletions()) == 1

    journey_db, portal_db = configure_instance(tmp_path / "new-instance")
    with TestClient(api.app) as client:
        assert client.get(
            f"/api/v1/household/{code}", params={"memory_consent": True},
        ).status_code == 404
        assert not _has_row(journey_db, "checkpoints", "thread_id", journey)
        assert not _has_row(journey_db, "checkpoints", "thread_id", gate)
        assert not _has_row(portal_db, "application_drafts", "draft_id", draft["draft_id"])
        assert _has_row(journey_db, "checkpoints", "thread_id", other_journey)
        assert not _has_row(share / "journey.sqlite3", "store", "key", code)
        assert not _has_row(share / "journey.sqlite3", "checkpoints", "thread_id", gate)
        assert client.app.state.backups.pending_deletions() == []


def test_schemes_kb_child_receives_the_baked_embedding_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The search child must see the image's model cache, or it falls back to paid embeddings."""

    for name, value in {
        "SCHEME_SAATHI_CHECKPOINT_DB": tmp_path / "journey.sqlite3",
        "SCHEME_SAATHI_APPLICATION_DB": tmp_path / "portal.sqlite3",
        "SCHEME_SAATHI_UPLOAD_DB": tmp_path / "uploads.sqlite3",
        "SCHEME_SAATHI_UPLOAD_DIR": tmp_path / "uploads",
    }.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("SCHEME_SAATHI_PORTAL_DB", raising=False)
    monkeypatch.delenv("SCHEME_SAATHI_BACKUP_DIR", raising=False)
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/opt/fastembed_cache")
    original_parameters = api.StdioServerParameters
    environments: dict[str, dict[str, str]] = {}

    def offline_parameters(*args: object, **kwargs: object) -> object:
        module = str(kwargs["args"][-1])
        environments[module] = dict(kwargs["env"])
        if kwargs.get("args") == ["-m", "src.mcp_servers.schemes_kb_server"]:
            kwargs["args"] = ["-c", OFFLINE_SEARCH_BOOTSTRAP]
        return original_parameters(*args, **kwargs)

    monkeypatch.setattr(api, "StdioServerParameters", offline_parameters)
    with TestClient(api.app):
        pass

    search = environments["src.mcp_servers.schemes_kb_server"]
    assert search["FASTEMBED_CACHE_PATH"] == "/opt/fastembed_cache"
    for module, environment in environments.items():
        if module != "src.mcp_servers.schemes_kb_server":
            assert "FASTEMBED_CACHE_PATH" not in environment
