"""Test saved copies of the live SQLite databases, offline and on temporary folders."""

import asyncio
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import database_backup
from src.api.app import app
from src.api.database_backup import DatabaseBackups


def _make_database(path: Path, value: str, *, wal: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT)")
    connection.execute("INSERT INTO marker VALUES (?)", (value,))
    connection.commit()
    connection.close()


def _values(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT value FROM marker")]
    finally:
        connection.close()


@pytest.fixture
def share(tmp_path: Path) -> Path:
    folder = tmp_path / "share"
    folder.mkdir()
    return folder


@pytest.fixture
def live(tmp_path: Path) -> Path:
    return tmp_path / "live" / "journey.sqlite3"


def test_saved_database_comes_back_on_a_new_container(share: Path, live: Path) -> None:
    _make_database(share / live.name, "saved conversation")

    DatabaseBackups(share, [live]).restore()

    assert _values(live) == ["saved conversation"]


def test_restore_never_replaces_a_database_the_container_already_has(share: Path, live: Path) -> None:
    _make_database(live, "newer")
    _make_database(share / live.name, "older")

    DatabaseBackups(share, [live]).restore()

    assert _values(live) == ["newer"]


def test_save_includes_changes_still_in_the_wal_file(share: Path, live: Path) -> None:
    _make_database(live, "first", wal=True)
    writer = sqlite3.connect(live)
    writer.execute("INSERT INTO marker VALUES ('second')")
    writer.commit()
    try:
        DatabaseBackups(share, [live]).save()
        assert _values(share / live.name) == ["first", "second"]
    finally:
        writer.close()


def test_a_new_save_replaces_the_last_copy_and_leaves_nothing_else(share: Path, live: Path) -> None:
    backups = DatabaseBackups(share, [live])
    _make_database(live, "first")
    backups.save()
    _make_database(live, "second")
    backups.save()

    assert _values(share / live.name) == ["first", "second"]
    assert [path.name for path in share.iterdir()] == [live.name]


def test_sqlite_never_opens_a_file_on_the_share(share: Path, live: Path, monkeypatch) -> None:
    """The share cannot host SQLite locks or WAL; it only stores finished files."""

    _make_database(live, "data", wal=True)
    backups = DatabaseBackups(share, [live])
    backups.save()
    live.unlink()
    opened: list[str] = []
    real_connect = sqlite3.connect

    def recording_connect(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(database_backup.sqlite3, "connect", recording_connect)
    backups.restore()
    backups.save()

    assert opened
    assert not any("share" in name for name in opened)


def test_damaged_copy_is_set_aside_and_the_app_starts_empty(share: Path, live: Path) -> None:
    (share / live.name).write_bytes(b"this is not a database" * 500)
    backups = DatabaseBackups(share, [live])

    backups.restore()

    assert not live.exists()
    assert (share / f"{live.name}.corrupt").exists()
    _make_database(live, "fresh")
    backups.save()
    assert _values(share / live.name) == ["fresh"]


def test_failed_restore_never_overwrites_the_good_copy(share: Path, live: Path, monkeypatch) -> None:
    """A brief share problem must not replace real data with an empty database."""

    _make_database(share / live.name, "precious")
    backups = DatabaseBackups(share, [live])

    def broken_copy(*_args, **_kwargs):
        raise OSError("share unavailable")

    monkeypatch.setattr(database_backup.shutil, "copyfile", broken_copy)
    backups.restore()
    monkeypatch.undo()
    _make_database(live, "empty start")
    backups.save()

    assert _values(share / live.name) == ["precious"]


def test_unmounted_share_is_not_created_or_written(tmp_path: Path, live: Path) -> None:
    missing = tmp_path / "not-mounted"
    backups = DatabaseBackups(missing, [live])
    _make_database(live, "data")

    backups.restore()
    backups.save()

    assert not missing.exists()


def test_failed_save_keeps_the_previous_copy(share: Path, live: Path, monkeypatch) -> None:
    backups = DatabaseBackups(share, [live])
    _make_database(live, "first")
    backups.save()
    _make_database(live, "second")

    def broken_copy(*_args, **_kwargs):
        raise OSError("share unavailable")

    monkeypatch.setattr(database_backup.shutil, "copyfile", broken_copy)
    backups.save()

    assert _values(share / live.name) == ["first"]


def test_database_not_created_yet_is_skipped(share: Path, live: Path) -> None:
    DatabaseBackups(share, [live]).save()

    assert list(share.iterdir()) == []


def test_saves_repeat_on_the_interval(share: Path, live: Path) -> None:
    _make_database(live, "data")
    backups = DatabaseBackups(share, [live], interval_seconds=0)

    async def run_briefly() -> None:
        task = asyncio.create_task(backups.save_regularly())
        for _ in range(500):
            await asyncio.sleep(0.01)
            if (share / live.name).exists():
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_briefly())

    assert _values(share / live.name) == ["data"]


def test_backups_are_off_unless_configured(monkeypatch, live: Path) -> None:
    monkeypatch.delenv(database_backup.BACKUP_DIR_VARIABLE, raising=False)

    assert DatabaseBackups.from_environment([live]) is None


def test_interval_comes_from_the_environment(monkeypatch, share: Path, live: Path) -> None:
    monkeypatch.setenv(database_backup.BACKUP_DIR_VARIABLE, str(share))
    monkeypatch.setenv(database_backup.INTERVAL_VARIABLE, "60")

    assert DatabaseBackups.from_environment([live]).interval_seconds == 60

    monkeypatch.setenv(database_backup.INTERVAL_VARIABLE, "0")
    with pytest.raises(ValueError, match="must be positive"):
        DatabaseBackups.from_environment([live])


def test_backend_restores_both_databases_at_start_and_saves_them_at_shutdown(
    share: Path, tmp_path: Path, monkeypatch,
) -> None:
    """The real startup and shutdown, as after scaling to zero and waking up."""

    journey = tmp_path / "container" / "journey.sqlite3"
    portal = tmp_path / "container" / "portal.sqlite3"
    _make_database(share / journey.name, "saved conversation")
    _make_database(share / portal.name, "saved draft")
    monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(journey))
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(portal))
    monkeypatch.setenv(database_backup.BACKUP_DIR_VARIABLE, str(share))

    with TestClient(app):
        assert _values(journey) == ["saved conversation"]
        assert _values(portal) == ["saved draft"]
        _make_database(portal, "new draft")

    assert _values(share / portal.name) == ["saved draft", "new draft"]
    connection = sqlite3.connect(share / journey.name)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    finally:
        connection.close()
    assert {"marker", "checkpoints", "store"} <= tables
    shutil.rmtree(journey.parent)
