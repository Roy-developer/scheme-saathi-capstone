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
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_DIR_VARIABLE = "SCHEME_SAATHI_BACKUP_DIR"
INTERVAL_VARIABLE = "SCHEME_SAATHI_BACKUP_INTERVAL_SECONDS"
DEFAULT_INTERVAL_SECONDS = 300


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
    ) -> None:
        self.folder = folder
        self.databases = tuple(databases)
        self.interval_seconds = interval_seconds
        self._save_lock = threading.Lock()
        # Databases that could not be restored. Saving these would replace a
        # good copy on the share with the empty database this run started with.
        self._not_restored: set[Path] = set()

    @classmethod
    def from_environment(cls, databases: Iterable[Path]) -> "DatabaseBackups | None":
        """Build from the environment, or return None when backups are off."""

        folder = os.getenv(BACKUP_DIR_VARIABLE)
        if not folder:
            return None
        interval = int(os.getenv(INTERVAL_VARIABLE, str(DEFAULT_INTERVAL_SECONDS)))
        if interval < 1:
            raise ValueError(f"{INTERVAL_VARIABLE} must be positive")
        return cls(Path(folder), databases, interval)

    def restore(self) -> None:
        """Bring back saved databases that this container does not have."""

        if not self.folder.is_dir():
            logger.error("Database backup folder is not available; not restoring or saving")
            self._not_restored.update(self.databases)
            return
        for database in self.databases:
            try:
                self._restore_one(database)
            except (OSError, sqlite3.Error):
                logger.exception("Could not restore database %s", database.name)
                self._not_restored.add(database)

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

    def save(self) -> None:
        """Copy each live database to the share; a failure keeps the last copy."""

        with self._save_lock:
            if not self.folder.is_dir():
                logger.error("Database backup folder is not available; not saving")
                return
            for database in self.databases:
                if database in self._not_restored or not database.exists():
                    continue
                try:
                    self._save_one(database)
                except (OSError, sqlite3.Error):
                    logger.exception("Could not save database %s", database.name)

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
