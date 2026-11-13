"""Keep integration startup offline and away from saved demonstration databases."""

import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Must run before any src module reads the portal URL. Under pytest-xdist each
# worker (gw0, gw1, ...) gets its own portal port, so parallel runs don't collide.
_XDIST_WORKER = os.getenv("PYTEST_XDIST_WORKER", "")
if (
    _XDIST_WORKER.startswith("gw")
    and _XDIST_WORKER[2:].isdigit()
    and "SCHEME_SAATHI_PORTAL_URL" not in os.environ
):
    os.environ["SCHEME_SAATHI_PORTAL_URL"] = f"http://127.0.0.1:{8900 + int(_XDIST_WORKER[2:])}"

import httpx
import pytest


# This must precede application imports during collection, not just test setup.
os.environ["SCHEME_SAATHI_DISABLE_DOTENV"] = "1"
os.environ["SCHEME_SAATHI_DISABLE_CROSS_ENCODER"] = "1"
for credential in (
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_FREE", "OPEN_ROUTER_FREE",
    "OPENROUTER_EMBEDDING_API_KEY",
):
    os.environ.pop(credential, None)

_DATABASES = [
    Path.cwd() / f".pytest-{name}-{uuid4().hex}.sqlite3"
    for name in ("journey", "portal")
]
os.environ["SCHEME_SAATHI_CHECKPOINT_DB"] = str(_DATABASES[0])
# Leave PORTAL_DB unset so individual tests can override APPLICATION_DB.
os.environ.pop("SCHEME_SAATHI_PORTAL_DB", None)
os.environ["SCHEME_SAATHI_APPLICATION_DB"] = str(_DATABASES[1])


class FakeOpenRouter:
    """Answer chat requests in-process and remember what was sent.

    Call ``answer(...)`` for a normal reply, or set ``reply`` to an
    ``httpx.Response`` (for example an HTTP 503) or an exception to raise.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: object = self.chat_completion(content="{}")

    @staticmethod
    def chat_completion(
        *, content: str | None = None, tool_call: tuple[str, str] | None = None,
    ) -> dict:
        """Build a minimal OpenAI-format chat reply.

        Args:
            content: Text the model "wrote".
            tool_call: ``(function_name, arguments_json)`` the model "chose".
        """

        message: dict = {"role": "assistant", "content": content}
        if tool_call is not None:
            name, arguments = tool_call
            message["tool_calls"] = [{
                "id": "call-1", "type": "function",
                "function": {"name": name, "arguments": arguments},
            }]
        return {
            "id": "fake", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        }

    def answer(
        self, *, content: str | None = None, tool_call: tuple[str, str] | None = None,
    ) -> None:
        """Make the fake model reply with this text or tool choice."""

        self.reply = self.chat_completion(content=content, tool_call=tool_call)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, BaseException):
            raise self.reply
        if isinstance(self.reply, httpx.Response):
            return self.reply
        return httpx.Response(200, json=self.reply)

    def sent_json(self, index: int = 0) -> dict:
        """Return the JSON body of one recorded request."""

        return json.loads(self.requests[index].content)


@pytest.fixture
def fake_openrouter(monkeypatch: pytest.MonkeyPatch) -> FakeOpenRouter:
    """Route every ``src.llm_client`` request to an in-process fake."""

    from src import llm_client

    fake = FakeOpenRouter()
    monkeypatch.setattr(
        llm_client, "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


@pytest.fixture(scope="session", autouse=True)
def remove_test_databases():
    """Remove only this run's project-local SQLite artifacts after child shutdown."""

    yield
    for database in _DATABASES:
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def _worker_scheme_data(tmp_path_factory) -> Path:
    """Give each xdist worker its own copy of the document data.

    The app takes a publication lock on this data even to read it, so parallel
    workers sharing the repository's files queue on one lock and time out.
    """

    source = PROJECT_ROOT / "data" / "schemes"
    worker = os.getenv("PYTEST_XDIST_WORKER", "main")
    destination = tmp_path_factory.mktemp(f"schemes-{worker}") / "schemes"
    destination.mkdir(parents=True)
    shutil.copytree(source / "document_checklists", destination / "document_checklists")
    shutil.copytree(source / "mock_forms", destination / "mock_forms")
    shutil.copy(source / "document_evidence.json", destination / "document_evidence.json")
    return destination


@pytest.fixture(autouse=True)
def _isolated_document_data(monkeypatch: pytest.MonkeyPatch, _worker_scheme_data: Path) -> None:
    from src.documents import checklists, forms, publication

    destination = _worker_scheme_data
    checklist_directory = destination / "document_checklists"
    evidence_file = destination / "document_evidence.json"
    form_directory = destination / "mock_forms"
    monkeypatch.setattr(checklists, "CHECKLIST_DIRECTORY", checklist_directory)
    monkeypatch.setattr(checklists, "EVIDENCE_FILE", evidence_file)
    monkeypatch.setattr(publication, "CHECKLIST_DIRECTORY", checklist_directory)
    monkeypatch.setattr(publication, "EVIDENCE_FILE", evidence_file)
    monkeypatch.setattr(forms, "FORM_DIRECTORY", form_directory)
    monkeypatch.setattr(forms, "test_scheme_data_directory", lambda: destination)
