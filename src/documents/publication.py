"""Coordinate supported checklist publication with portal transactions."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Iterator

from src.documents.checklists import (
    CHECKLIST_DIRECTORY,
    EVIDENCE_FILE,
    EvidenceCorpus,
    _reject_duplicate_json_keys,
    _snapshot_from_bytes,
)


LOCK_FILENAME = ".document_checklists.lock"
REVISION_FILENAME = ".document_checklists.revision"
SCHEME_FILENAME_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,79}\.json$")
LOCK_WAIT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 0.05
_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCK_STATE = threading.local()


def _local_lock(lock_path: Path) -> threading.Lock:
    """Return one in-process mutex paired with the shared OS file lock."""

    key = str(lock_path.resolve())
    with _LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.Lock())


def _acquire_file_lock(stream) -> None:
    """Acquire one byte-range lock on Windows or flock on POSIX."""

    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(LOCK_RETRY_SECONDS)


def _release_file_lock(stream) -> None:
    """Release the platform-specific publication lock."""

    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def checklist_publication_lock(
    checklist_directory: Path = CHECKLIST_DIRECTORY,
) -> Iterator[None]:
    """Hold the shared cross-process lock through one portal transaction.

    Args:
        checklist_directory: Data directory whose parent contains the lock file.
    """

    lock_path = checklist_directory.parent / LOCK_FILENAME
    key = str(lock_path.resolve())
    active = getattr(_THREAD_LOCK_STATE, "active", set())
    if key in active:
        yield
        return
    process_lock = _local_lock(lock_path)
    if not process_lock.acquire(timeout=LOCK_WAIT_SECONDS):
        raise RuntimeError(
            "The document checklist publication lock is unavailable."
        )
    stream = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+b")
        _acquire_file_lock(stream)
    except Exception as error:
        try:
            if stream is not None:
                stream.close()
        finally:
            process_lock.release()
        raise RuntimeError(
            "The document checklist publication lock is unavailable."
        ) from error
    active = set(active)
    active.add(key)
    _THREAD_LOCK_STATE.active = active
    try:
        yield
    finally:
        active.remove(key)
        _THREAD_LOCK_STATE.active = active
        try:
            _release_file_lock(stream)
        finally:
            stream.close()
            process_lock.release()


def _read_revision(path: Path) -> int:
    """Read the persistent monotonic revision, treating a new install as zero."""

    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 0
    try:
        value = raw.decode("ascii")
        if not value.isdigit():
            raise ValueError
        return int(value)
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("The checklist publication revision is invalid.") from error


def _atomic_replace(path: Path, content: bytes) -> None:
    """Replace one file atomically from a flushed sibling file."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_publication(
    filename: str,
    content: bytes,
    checklist_directory: Path,
    evidence_file: Path,
    revision: int,
) -> Path:
    """Validate one bounded evidence or scheme-checklist file update."""

    from src.mcp_servers.rule_data import get_active_rule_data

    registry = get_active_rule_data().registry
    if filename == evidence_file.name:
        try:
            _reject_duplicate_json_keys(content)
            corpus = EvidenceCorpus.model_validate_json(content)
        except (ValueError, TypeError) as error:
            raise ValueError("The evidence corpus does not match its schema.") from error
        for checklist_path in checklist_directory.glob("*.json"):
            if not SCHEME_FILENAME_PATTERN.fullmatch(checklist_path.name):
                continue
            scheme_id = checklist_path.stem
            snapshot = _snapshot_from_bytes(
                scheme_id, checklist_path.read_bytes(), content, revision, registry
            )
            if snapshot.checklist is None:
                raise ValueError(
                    f"Evidence update would break checklist {scheme_id}."
                )
        return evidence_file

    if not SCHEME_FILENAME_PATTERN.fullmatch(filename):
        raise ValueError("Publish exactly one named checklist or evidence file.")
    scheme_id = filename[:-5]
    target = checklist_directory / filename
    evidence = evidence_file.read_bytes() if evidence_file.exists() else None
    _reject_duplicate_json_keys(content)
    snapshot = _snapshot_from_bytes(
        scheme_id, content, evidence, revision, registry
    )
    if snapshot.checklist is None:
        raise ValueError("The checklist is invalid or its evidence links are broken.")
    if (
        snapshot.checklist.approval.status == "approved"
        and snapshot.trust_status != "approved_source_backed"
    ):
        raise ValueError(
            "An approved checklist must bind the exact current evidence bytes."
        )
    return target


def publish_checklist_file(
    filename: str,
    content: bytes,
    *,
    checklist_directory: Path = CHECKLIST_DIRECTORY,
    evidence_file: Path = EVIDENCE_FILE,
) -> int:
    """Validate and atomically publish one file under the portal's shared lock.

    Every supported update increments a persistent revision before replacing
    content, so publishing A→B→A still invalidates saved reports and approvals.

    Args:
        filename: One checklist basename or the configured evidence basename.
        content: Complete candidate JSON file bytes.
        checklist_directory: Directory containing scheme checklist JSON files.
        evidence_file: Shared evidence corpus file paired with the checklists.
    """

    if not isinstance(content, bytes):
        raise TypeError("Published checklist data must be encoded bytes.")
    checklist_directory = checklist_directory.resolve()
    evidence_file = evidence_file.resolve()
    if evidence_file.parent != checklist_directory.parent:
        raise ValueError("Checklist and evidence files must share a data directory.")
    revision_path = checklist_directory.parent / REVISION_FILENAME
    with checklist_publication_lock(checklist_directory):
        revision = _read_revision(revision_path)
        target = _validate_publication(
            filename, content, checklist_directory, evidence_file, revision
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        next_revision = revision + 1
        _atomic_replace(revision_path, str(next_revision).encode("ascii"))
        _atomic_replace(target, content)
        return next_revision
