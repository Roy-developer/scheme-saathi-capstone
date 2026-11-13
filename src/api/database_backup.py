"""Keep saved copies of the live SQLite databases on a network share.

The app scales to zero, which erases the container's disk. The live databases
cannot simply move to the Azure file share: they use SQLite WAL mode, which
does not work over a network filesystem. So they stay on the container's disk,
and this module copies complete files to and from the share:

    start     share -> container disk, when the container has no database
    running   container disk -> share, every few minutes
    shutdown  container disk -> share

SQLite never opens a file on the share. Each save makes a consistent snapshot on
the container's disk with SQLite's backup API, checks it, and only then copies
it across. Set ``SCHEME_SAATHI_BACKUP_DIR`` to turn this on; local development
leaves it unset.
"""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

BACKUP_DIR_VARIABLE = "SCHEME_SAATHI_BACKUP_DIR"
INTERVAL_VARIABLE = "SCHEME_SAATHI_BACKUP_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 300
PENDING_DELETIONS = ".pending-deletions"


def _is_intact(path: Path) -> bool:
    """Return whether SQLite finds this database file undamaged."""

    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        return False
    finally:
        connection.close()


class DatabaseBackups:
    """Restore and save complete copies of a fixed set of SQLite databases."""

    def __init__(
        self,
        folder: Path,
        databases: Iterable[Path],
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        directories: Iterable[Path] = (),
    ) -> None:
        self.folder = folder
        self.databases = tuple(databases)
        # Plain file trees (uploaded documents), copied whole rather than snapshotted.
        self.directories = tuple(directories)
        self.interval_seconds = interval_seconds
        self._save_lock = threading.Lock()
        # Databases that could not be restored. Saving these would replace a
        # good copy on the share with the empty database this run started with.
        self._not_restored: set[Path] = set()

    @classmethod
    def from_environment(
        cls, databases: Iterable[Path], directories: Iterable[Path] = ()
    ) -> "DatabaseBackups | None":
        """Build from the environment, or return None when backups are off."""

        folder = os.getenv(BACKUP_DIR_VARIABLE)
        if not folder:
            return None
        interval = int(os.getenv(INTERVAL_VARIABLE, str(DEFAULT_INTERVAL_SECONDS)))
        if interval < 1:
            raise ValueError(f"{INTERVAL_VARIABLE} must be positive")
        return cls(Path(folder), databases, interval, directories)

    def restore(self) -> None:
        """Bring back saved databases that this container does not have."""

        if not self.folder.is_dir():
            logger.error("Database backup folder is not available; not restoring or saving")
            self._not_restored.update(self.databases)
            self._not_restored.update(self.directories)
            return
        for database in self.databases:
            try:
                self._restore_one(database)
            except (OSError, sqlite3.Error):
                logger.exception("Could not restore database %s", database.name)
                self._not_restored.add(database)
        for directory in self.directories:
            try:
                self._restore_directory(directory)
            except OSError:
                logger.exception("Could not restore folder %s", directory.name)
                self._not_restored.add(directory)

    def _restore_directory(self, directory: Path) -> None:
        saved = self.folder / directory.name
        if directory.exists() and any(directory.iterdir()) or not saved.is_dir():
            return
        shutil.copytree(saved, directory, dirs_exist_ok=True)
        logger.info("Restored folder %s", directory.name)

    def _save_directory(self, directory: Path) -> None:
        """Mirror the folder so a forgotten file is also gone from the share."""

        target = self.folder / directory.name
        target.mkdir(parents=True, exist_ok=True)
        wanted: set[Path] = set()
        for source in directory.rglob("*"):
            if source.is_dir() or source.name.endswith(".partial"):
                continue
            relative = source.relative_to(directory)
            wanted.add(relative)
            copy = target / relative
            if copy.exists() and copy.stat().st_size == source.stat().st_size:
                continue
            copy.parent.mkdir(parents=True, exist_ok=True)
            incoming = copy.with_name(f"{copy.name}.saving")
            shutil.copyfile(source, incoming)
            os.replace(incoming, copy)
        for existing in sorted(target.rglob("*"), reverse=True):
            relative = existing.relative_to(target)
            if existing.is_file() and relative not in wanted:
                existing.unlink()
            elif existing.is_dir() and not any(existing.iterdir()):
                existing.rmdir()

    def _restore_one(self, database: Path) -> None:
        saved = self.folder / database.name
        if database.exists() or not saved.exists():
            return
        database.parent.mkdir(parents=True, exist_ok=True)
        incoming = database.with_name(f"{database.name}.restoring")
        shutil.copyfile(saved, incoming)
        if not _is_intact(incoming):
            incoming.unlink()
            # Keep it for inspection, and let this run save a fresh copy.
            os.replace(saved, saved.with_name(f"{saved.name}.corrupt"))
            logger.error("Saved database %s is damaged; starting empty", database.name)
            return
        os.replace(incoming, database)
        logger.info("Restored database %s", database.name)

    def save(self, *, strict: bool = False) -> None:
        """Copy live data; strict mode raises if any required copy cannot be saved."""

        with self._save_lock:
            if not self.folder.is_dir():
                if strict:
                    raise OSError("Database backup folder is unavailable")
                logger.error("Database backup folder is not available; not saving")
                return
            for database in self.databases:
                if database in self._not_restored or not database.exists():
                    if strict:
                        raise OSError("A required database is unavailable for backup")
                    continue
                try:
                    self._save_one(database)
                except (OSError, sqlite3.Error):
                    if strict:
                        raise
                    logger.exception("Could not save database %s", database.name)
            for directory in self.directories:
                if directory in self._not_restored or not directory.is_dir():
                    if strict:
                        raise OSError("A required directory is unavailable for backup")
                    continue
                try:
                    self._save_directory(directory)
                except OSError:
                    if strict:
                        raise
                    logger.exception("Could not save folder %s", directory.name)

    def begin_deletion(self, payload: dict[str, object]) -> str:
        """Persist a pending deletion before changing any live records."""

        if not self.folder.is_dir():
            raise OSError("Database backup folder is unavailable")
        directory = self.folder / PENDING_DELETIONS
        directory.mkdir(exist_ok=True)
        marker_id = uuid4().hex
        temporary = directory / f"{marker_id}.tmp"
        marker = directory / f"{marker_id}.json"
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)
        return marker_id

    def pending_deletions(self) -> list[tuple[str, dict[str, object]]]:
        """Load pending markers; unreadable or malformed markers stop recovery."""

        if not self.folder.is_dir():
            raise OSError("Database backup folder is unavailable")
        directory = self.folder / PENDING_DELETIONS
        try:
            with os.scandir(directory) as entries:
                markers = sorted(
                    Path(entry.path) for entry in entries if entry.name.endswith(".json")
                )
        except FileNotFoundError:
            return []
        result = []
        for marker in markers:
            if len(marker.stem) != 32 or any(
                c not in "0123456789abcdef" for c in marker.stem
            ):
                raise ValueError("Invalid pending-deletion marker ID")
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid pending-deletion marker")
            result.append((marker.stem, payload))
        return result

    def finish_deletion(self, marker_id: str) -> None:
        """Remove a marker only after every refreshed snapshot succeeds."""

        if len(marker_id) != 32 or any(c not in "0123456789abcdef" for c in marker_id):
            raise ValueError("Invalid pending-deletion marker ID")
        (self.folder / PENDING_DELETIONS / f"{marker_id}.json").unlink()

    def _save_one(self, database: Path) -> None:
        with tempfile.TemporaryDirectory(dir=database.parent) as folder:
            snapshot = Path(folder) / database.name
            source = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=10)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            if not _is_intact(snapshot):
                raise sqlite3.DatabaseError("The snapshot failed its integrity check")
            incoming = self.folder / f"{database.name}.saving"
            shutil.copyfile(snapshot, incoming)
            os.replace(incoming, self.folder / database.name)

    async def save_regularly(self) -> None:
        """Save on a fixed interval until cancelled."""

        while True:
            await asyncio.sleep(self.interval_seconds)
            await asyncio.to_thread(self.save)
