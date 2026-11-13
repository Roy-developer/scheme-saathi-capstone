"""Verify synthetic forget behavior across live data and backup snapshots."""

import os
import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import src.api.app as api
from src.api.database_backup import DatabaseBackups
from test_red_team_runtime import _draft, _eligible
from test_ui_integration import IntegratedUI, integrated_ui


@pytest.fixture(scope="module", autouse=True)
def isolate_uploads_and_disable_external_backups(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Keep the live fixture away from real uploads and configured shares."""

    directory = tmp_path_factory.mktemp("forget-backup-isolation")
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("SCHEME_SAATHI_BACKUP_DIR", raising=False)
        patch.setenv("SCHEME_SAATHI_UPLOAD_DIR", str(directory / "uploads"))
        patch.setenv("SCHEME_SAATHI_UPLOAD_DB", str(directory / "uploads.sqlite3"))
        yield


def test_forget_refreshes_backup_before_success(
    integrated_ui: IntegratedUI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The successful response follows deletion from the current backup."""

    harness = integrated_ui
    journey = _eligible(harness)
    draft = _draft(harness, journey)
    other_journey = _eligible(harness)
    saved = harness.client.post(
        "/api/v1/household",
        json={"conversation_id": journey, "memory_consent": True},
    )
    assert saved.status_code == 200, saved.text
    code = saved.json()["return_code"]
    live = Path(os.environ["SCHEME_SAATHI_CHECKPOINT_DB"])
    folder = tmp_path / "synthetic-share"
    folder.mkdir()
    backups = DatabaseBackups(
        folder, [live, harness.database, Path(os.environ["SCHEME_SAATHI_UPLOAD_DB"])],
        directories=[Path(os.environ["SCHEME_SAATHI_UPLOAD_DIR"])],
    )
    monkeypatch.setattr(harness.client.app.state, "backups", backups)
    upload = Path(os.environ["SCHEME_SAATHI_UPLOAD_DIR"]) / journey / "synthetic.txt"
    upload.parent.mkdir(parents=True)
    upload.write_text("synthetic", encoding="utf-8")

    def contains(path: Path, table: str, column: str, value: str) -> bool:
        # Table and column names are fixed test literals, not user input.
        connection = sqlite3.connect(path)
        try:
            return bool(connection.execute(
                f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,),
            ).fetchone())
        finally:
            connection.close()

    def present(journey_db: Path, portal_db: Path) -> tuple[bool, bool, bool, bool]:
        return (
            contains(journey_db, "checkpoints", "thread_id", journey),
            contains(journey_db, "store", "key", code),
            contains(portal_db, "application_drafts", "draft_id", draft["draft_id"]),
            contains(journey_db, "checkpoints", "thread_id", other_journey),
        )

    backups.save()
    saved_journey, saved_portal = folder / live.name, folder / harness.database.name
    assert present(saved_journey, saved_portal) == (True, True, True, True)
    assert (folder / "uploads" / journey / "synthetic.txt").is_file()

    forgotten = harness.client.request(
        "DELETE", "/api/v1/forget",
        json={"conversation_id": journey, "return_code": code},
    )
    assert forgotten.status_code == 204, forgotten.text
    assert present(live, harness.database) == (False, False, False, True)
    assert present(saved_journey, saved_portal) == (False, False, False, True)
    assert not (folder / "uploads" / journey).exists()
    assert backups.pending_deletions() == []

    restored = tmp_path / "restored"
    DatabaseBackups(
        folder, [restored / live.name, restored / harness.database.name],
    ).restore()
    assert present(restored / live.name, restored / harness.database.name) == (
        False, False, False, True,
    )


def test_failed_backup_retains_marker_and_retry_clears_it(
    integrated_ui: IntegratedUI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed refresh cannot be reported as a successful durable deletion."""

    harness = integrated_ui
    journey = _eligible(harness)
    folder = tmp_path / "synthetic-share"
    folder.mkdir()
    backups = DatabaseBackups(
        folder,
        [
            Path(os.environ["SCHEME_SAATHI_CHECKPOINT_DB"]), harness.database,
            Path(os.environ["SCHEME_SAATHI_UPLOAD_DB"]),
        ],
        directories=[Path(os.environ["SCHEME_SAATHI_UPLOAD_DIR"])],
    )
    backups.save(strict=True)
    monkeypatch.setattr(harness.client.app.state, "backups", backups)
    original = backups._save_one

    def unavailable(_database: Path) -> None:
        raise OSError("synthetic backup failure")

    monkeypatch.setattr(backups, "_save_one", unavailable)
    first = harness.client.request("DELETE", "/api/v1/forget", json={
        "conversation_id": journey,
    })
    assert first.status_code == 503
    assert len(backups.pending_deletions()) == 1
    monkeypatch.setattr(backups, "_save_one", original)
    retry = harness.client.request("DELETE", "/api/v1/forget", json={
        "conversation_id": journey,
    })
    assert retry.status_code == 204, retry.text
    assert backups.pending_deletions() == []


def test_unavailable_marker_storage_keeps_live_data(
    integrated_ui: IntegratedUI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a durable marker, forget fails before deleting live records."""

    harness = integrated_ui
    journey = _eligible(harness)
    backups = DatabaseBackups(tmp_path / "unavailable", [])
    monkeypatch.setattr(harness.client.app.state, "backups", backups)
    response = harness.client.request("DELETE", "/api/v1/forget", json={
        "conversation_id": journey,
    })
    assert response.status_code == 503
    saved = harness.client.get(f"/api/v1/journey/{journey}")
    assert saved.status_code == 200 and saved.json()["status"] == "eligible"


def test_forget_blocks_concurrent_household_save(
    integrated_ui: IntegratedUI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request cannot save stale journey data during marker capture."""

    harness = integrated_ui
    journey = _eligible(harness)
    folder = tmp_path / "synthetic-share"
    folder.mkdir()
    backups = DatabaseBackups(
        folder,
        [
            Path(os.environ["SCHEME_SAATHI_CHECKPOINT_DB"]), harness.database,
            Path(os.environ["SCHEME_SAATHI_UPLOAD_DB"]),
        ],
        directories=[Path(os.environ["SCHEME_SAATHI_UPLOAD_DIR"])],
    )
    monkeypatch.setattr(harness.client.app.state, "backups", backups)
    captured = threading.Event()
    release = threading.Event()
    original = api._capture_forget_gate_threads

    async def pause_capture(request, conversation_id):
        threads = await original(request, conversation_id)
        captured.set()
        await api.asyncio.to_thread(release.wait)
        return threads

    monkeypatch.setattr(api, "_capture_forget_gate_threads", pause_capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        forget = pool.submit(
            harness.client.request, "DELETE", "/api/v1/forget",
            json={"conversation_id": journey},
        )
        try:
            assert captured.wait(timeout=30)
            save = pool.submit(
                harness.client.post, "/api/v1/household",
                json={"conversation_id": journey, "memory_consent": True},
            )
            with pytest.raises(TimeoutError):
                save.result(timeout=0.5)
        finally:
            release.set()
        assert forget.result(timeout=30).status_code == 204
        assert save.result(timeout=30).status_code == 404
    assert backups.pending_deletions() == []


@pytest.mark.parametrize("target", ["journey", "household"])
def test_individual_forget_routes_refresh_backup(
    target: str, integrated_ui: IntegratedUI, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each individual route removes its records from the current snapshot."""

    harness = integrated_ui
    journey = _eligible(harness)
    saved = harness.client.post(
        "/api/v1/household", json={"conversation_id": journey, "memory_consent": True},
    )
    assert saved.status_code == 200
    code = saved.json()["return_code"]
    live = Path(os.environ["SCHEME_SAATHI_CHECKPOINT_DB"])
    folder = tmp_path / "synthetic-share"
    folder.mkdir()
    backups = DatabaseBackups(
        folder, [live, harness.database, Path(os.environ["SCHEME_SAATHI_UPLOAD_DB"])],
        directories=[Path(os.environ["SCHEME_SAATHI_UPLOAD_DIR"])],
    )
    backups.save(strict=True)
    monkeypatch.setattr(harness.client.app.state, "backups", backups)

    endpoint = (
        f"/api/v1/journey/{journey}" if target == "journey"
        else f"/api/v1/household/{code}"
    )
    assert harness.client.delete(endpoint).status_code == 204
    with sqlite3.connect(folder / live.name) as connection:
        if target == "journey":
            result = connection.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ?", (journey,),
            ).fetchone()
        else:
            result = connection.execute(
                "SELECT 1 FROM store WHERE key = ?", (code,),
            ).fetchone()
    assert result is None
    assert backups.pending_deletions() == []
