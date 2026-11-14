"""Store uploaded synthetic document files and the person's issue resolutions.

Files are saved on the backend's disk under
``<upload dir>/<conversation id>/<document id>/<random name>.<ext>``. One
conversation holds at most one file per checklist ``document_id``, and every
scheme that asks for that document shares it. Here files are only
size-checked, type-checked by their first bytes, hashed and stored; the
checker never reads them. Only an explicit "read name and date" request sends
a file to a reader (``extraction.py``), and an outside vision model is used
for that only when switched on.
"""

import hashlib
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DOCUMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")

# Extension -> (stored extension, content type, required leading bytes).
_FILE_TYPES: dict[str, tuple[str, str, bytes]] = {
    "pdf": ("pdf", "application/pdf", b"%PDF-"),
    "jpg": ("jpg", "image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("jpg", "image/jpeg", b"\xff\xd8\xff"),
    "png": ("png", "image/png", b"\x89PNG\r\n\x1a\n"),
}
ALLOWED_EXTENSIONS = tuple(sorted(_FILE_TYPES))

ResolutionAction = Literal["acknowledge"]
ActorMode = Literal["citizen", "csc"]


class UploadError(Exception):
    """A rejected upload or lookup, with an HTTP-style status and safe text."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class UploadRecord(BaseModel):
    """Public metadata about one stored file; it never exposes the disk path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: str


class ResolutionRecord(BaseModel):
    """A person's acknowledgment of one checker issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    issue_code: str
    action: ResolutionAction
    reason: str
    actor_mode: ActorMode
    fingerprint: str
    resolved_at: str


def clean_file_name(value: str) -> str:
    """Keep a short, printable base name for display only."""

    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        character
        for character in unicodedata.normalize("NFKC", name)
        if character.isprintable()
    ).strip()
    return name[:120] or "document"


def detect_file_type(file_name: str, content: bytes) -> tuple[str, str]:
    """Return (stored extension, content type) or raise a 415 UploadError."""

    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    expected = _FILE_TYPES.get(extension)
    if expected is None:
        raise UploadError(415, "Only PDF, JPG and PNG files are accepted.")
    stored_extension, content_type, signature = expected
    if not content.startswith(signature):
        raise UploadError(
            415, "The file contents do not match its PDF, JPG or PNG type."
        )
    return stored_extension, content_type


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class UploadStore:
    """Disk files plus SQLite records for uploads and issue resolutions."""

    def __init__(self, directory: Path, database: Path) -> None:
        self.directory = directory
        self.database = database
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    conversation_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, document_id)
                );
                CREATE TABLE IF NOT EXISTS resolutions (
                    conversation_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    issue_code TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor_mode TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    resolved_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, document_id, issue_code)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    conversation_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    reviewer_name TEXT NOT NULL,
                    note TEXT NOT NULL,
                    actor_mode TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, document_id)
                );
                CREATE TABLE IF NOT EXISTS extractions (
                    conversation_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    name TEXT,
                    date_of_birth TEXT,
                    engine TEXT NOT NULL,
                    extracted_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, document_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _check_ids(conversation_id: str, document_id: str | None = None) -> None:
        try:
            uuid.UUID(conversation_id)
        except ValueError as error:
            raise UploadError(422, "conversation_id must be a UUID.") from error
        if document_id is not None and not DOCUMENT_ID_PATTERN.match(document_id):
            raise UploadError(422, "document_id is not valid.")

    def _folder(self, conversation_id: str, document_id: str) -> Path:
        folder = (self.directory / conversation_id / document_id).resolve()
        if self.directory.resolve() not in folder.parents:
            raise UploadError(422, "document_id is not valid.")
        return folder

    @staticmethod
    def _record(row: sqlite3.Row) -> UploadRecord:
        return UploadRecord(
            document_id=row["document_id"],
            original_name=row["original_name"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            uploaded_at=row["uploaded_at"],
        )

    def save(
        self,
        conversation_id: str,
        document_id: str,
        file_name: str,
        content: bytes,
    ) -> UploadRecord:
        """Validate and store one file, replacing any earlier file for the document."""

        self._check_ids(conversation_id, document_id)
        if not content:
            raise UploadError(422, "The file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise UploadError(413, "The file is larger than the 20 MB limit.")
        display_name = clean_file_name(file_name)
        extension, content_type = detect_file_type(display_name, content)
        folder = self._folder(conversation_id, document_id)
        folder.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        target = folder / stored_name
        partial = folder / f"{stored_name}.partial"
        partial.write_bytes(content)
        os.replace(partial, target)
        digest = _sha256(content)
        uploaded_at = _now()
        with closing(self._connect()) as connection, connection:
            previous = connection.execute(
                "SELECT stored_name FROM uploads WHERE conversation_id = ? "
                "AND document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id, document_id, stored_name, display_name,
                    content_type, len(content), digest, uploaded_at,
                ),
            )
        if previous is not None and previous["stored_name"] != stored_name:
            (folder / previous["stored_name"]).unlink(missing_ok=True)
        return UploadRecord(
            document_id=document_id,
            original_name=display_name,
            content_type=content_type,
            size_bytes=len(content),
            sha256=digest,
            uploaded_at=uploaded_at,
        )

    def list_uploads(self, conversation_id: str) -> dict[str, UploadRecord]:
        """Return stored file metadata keyed by document_id."""

        self._check_ids(conversation_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM uploads WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        return {row["document_id"]: self._record(row) for row in rows}

    def is_intact(self, conversation_id: str, document_id: str) -> bool:
        """Return whether the stored file still exists with its saved size and hash."""

        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT stored_name, size_bytes, sha256 FROM uploads "
                "WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
        if row is None:
            return False
        path = self._folder(conversation_id, document_id) / row["stored_name"]
        try:
            if path.stat().st_size != row["size_bytes"]:
                return False
            return _sha256(path.read_bytes()) == row["sha256"]
        except OSError:
            return False

    def read_file(self, conversation_id: str, document_id: str) -> tuple[UploadRecord, bytes]:
        """Return a file's record and bytes, or raise a 404 UploadError."""

        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM uploads WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
        if row is None:
            raise UploadError(404, "No file is stored for this document.")
        path = self._folder(conversation_id, document_id) / row["stored_name"]
        try:
            return self._record(row), path.read_bytes()
        except OSError as error:
            raise UploadError(404, "The stored file is no longer available.") from error

    def delete_upload(self, conversation_id: str, document_id: str) -> bool:
        """Delete one stored file and its resolutions; return whether it existed."""

        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT stored_name FROM uploads WHERE conversation_id = ? "
                "AND document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
            connection.execute(
                "DELETE FROM uploads WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            )
            connection.execute(
                "DELETE FROM resolutions WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            )
            connection.execute(
                "DELETE FROM extractions WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            )
            connection.execute(
                "DELETE FROM reviews WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            )
        folder = self._folder(conversation_id, document_id)
        if row is not None:
            (folder / row["stored_name"]).unlink(missing_ok=True)
        shutil.rmtree(folder, ignore_errors=True)
        return row is not None

    def delete_conversation(self, conversation_id: str) -> None:
        """Forget every file, record and resolution of one conversation."""

        self._check_ids(conversation_id)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM uploads WHERE conversation_id = ?", (conversation_id,)
            )
            connection.execute(
                "DELETE FROM resolutions WHERE conversation_id = ?", (conversation_id,)
            )
            connection.execute(
                "DELETE FROM extractions WHERE conversation_id = ?", (conversation_id,)
            )
            connection.execute(
                "DELETE FROM reviews WHERE conversation_id = ?", (conversation_id,)
            )
        shutil.rmtree(self.directory / conversation_id, ignore_errors=True)

    def save_review(
        self,
        conversation_id: str,
        document_id: str,
        reviewer_name: str,
        note: str,
        actor_mode: str,
    ) -> dict:
        """Record that a person reviewed the file currently stored."""

        self._check_ids(conversation_id, document_id)
        reviewer = " ".join(reviewer_name.split())[:80]
        if len(reviewer) < 2:
            raise UploadError(422, "Enter the reviewer's name.")
        reviewed_at = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT sha256 FROM uploads WHERE conversation_id = ? "
                "AND document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
            if row is None:
                raise UploadError(404, "No file is stored for this document.")
            connection.execute(
                "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id, document_id, row["sha256"], reviewer,
                    note.strip()[:300], actor_mode, reviewed_at,
                ),
            )
        return {
            "reviewer_name": reviewer, "note": note.strip()[:300],
            "actor_mode": actor_mode, "reviewed_at": reviewed_at,
        }

    def list_reviews(self, conversation_id: str) -> dict[str, dict]:
        """Return sign-offs that still belong to the stored file (same hash)."""

        self._check_ids(conversation_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT r.document_id, r.reviewer_name, r.note, r.actor_mode, "
                "r.reviewed_at FROM reviews r JOIN uploads u ON "
                "u.conversation_id = r.conversation_id AND "
                "u.document_id = r.document_id AND u.sha256 = r.sha256 "
                "WHERE r.conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        return {row["document_id"]: dict(row) for row in rows}

    def delete_review(self, conversation_id: str, document_id: str) -> bool:
        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM reviews WHERE conversation_id = ? AND document_id = ?",
                (conversation_id, document_id),
            )
        return cursor.rowcount > 0

    def save_extraction(
        self,
        conversation_id: str,
        document_id: str,
        sha256: str,
        name: str | None,
        date_of_birth: str | None,
        engine: str,
    ) -> dict:
        """Keep one suggestion for the file with this hash."""

        self._check_ids(conversation_id, document_id)
        extracted_at = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id, document_id, sha256, name, date_of_birth,
                    engine, extracted_at,
                ),
            )
        return {
            "name": name, "date_of_birth": date_of_birth,
            "engine": engine, "extracted_at": extracted_at,
        }

    def get_extraction(self, conversation_id: str, document_id: str) -> dict | None:
        """Return the suggestion only if it belongs to the file now stored."""

        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT e.name, e.date_of_birth, e.engine, e.extracted_at "
                "FROM extractions e JOIN uploads u ON u.conversation_id = "
                "e.conversation_id AND u.document_id = e.document_id "
                "AND u.sha256 = e.sha256 "
                "WHERE e.conversation_id = ? AND e.document_id = ?",
                (conversation_id, document_id),
            ).fetchone()
        return dict(row) if row else None

    def save_resolution(
        self,
        conversation_id: str,
        document_id: str,
        issue_code: str,
        reason: str,
        actor_mode: ActorMode,
        fingerprint: str,
    ) -> ResolutionRecord:
        """Record that the person acknowledged one specific issue state."""

        self._check_ids(conversation_id, document_id)
        record = ResolutionRecord(
            document_id=document_id,
            issue_code=issue_code,
            action="acknowledge",
            reason=reason.strip(),
            actor_mode=actor_mode,
            fingerprint=fingerprint,
            resolved_at=_now(),
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id, document_id, issue_code, record.action,
                    record.reason, actor_mode, fingerprint, record.resolved_at,
                ),
            )
        return record

    def list_resolutions(self, conversation_id: str) -> list[ResolutionRecord]:
        self._check_ids(conversation_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM resolutions WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        return [
            ResolutionRecord(
                document_id=row["document_id"],
                issue_code=row["issue_code"],
                action=row["action"],
                reason=row["reason"],
                actor_mode=row["actor_mode"],
                fingerprint=row["fingerprint"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        ]

    def delete_resolution(
        self, conversation_id: str, document_id: str, issue_code: str
    ) -> bool:
        """Reopen an acknowledged issue; return whether one was stored."""

        self._check_ids(conversation_id, document_id)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM resolutions WHERE conversation_id = ? "
                "AND document_id = ? AND issue_code = ?",
                (conversation_id, document_id, issue_code),
            )
        return cursor.rowcount > 0
