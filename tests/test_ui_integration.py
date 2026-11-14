"""Click the real UI through FastAPI, four MCP children and the local portal.

Only HTTP transport into TestClient and search's paid vector/rerank components
are replaced. Search still ranks the real corpus with BM25 inside schemes-kb.
No journey, rule, document, draft, approval or portal response is fabricated.
"""

from dataclasses import dataclass, field
from contextlib import closing
from collections.abc import Iterator
from http.client import HTTPResponse
from io import BytesIO
import json
import shutil
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import urlsplit
import urllib.request
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from streamlit.testing.v1 import AppTest

import src.api.app as api
from src.config import PORTAL_URL, PROJECT_ROOT
from src.mcp_servers.service_routing import ServiceClientRouter
from src.ui import api_client
from src.api.scheme_search import PassageSource, SchemePassage
from src.documents.publication import publish_checklist_file
from src.documents.forms import publish_mock_form_file
from src.mcp_servers.rule_data import get_active_rule_data
from src.portal.repository import _canonical_fingerprint
from src.workflow.journey import build_journey_graph


UI_PATH = Path(__file__).parents[1] / "src" / "ui" / "app.py"
SCHEME = "IGNWPS-MH"
TIMEOUT = 90
UI_ORIGIN = "http://ui-acceptance.invalid"
DOCUMENT_IDS = (
    "identity_proof", "bank_account_proof", "widow_status_proof",
)
SCHOLARSHIP = "TEST-SCHOLARSHIP"
SCHOLARSHIP_PACKAGE_DIR = (
    Path(__file__).parent / "fixtures" / "phase4" / "packages"
)
SCHOLARSHIP_SCHEME_DIR = SCHOLARSHIP_PACKAGE_DIR.parent / "schemes"

# Run the ordinary server entry point after disabling only paid retrieval.
# Parent monkeypatches cannot change a spawned child's retriever.
OFFLINE_SEARCH_BOOTSTRAP = """
import runpy
import urllib.request
from src.api.scheme_search import HybridSchemeRetriever

def deny_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("Search acceptance must not access the network")

urllib.request.urlopen = deny_network
original_init = HybridSchemeRetriever.__init__

def offline_init(self: HybridSchemeRetriever, passages: object, **kwargs: object) -> None:
    kwargs.update(vector_search=lambda *args: [], rerank=None, use_cross_encoder=False)
    original_init(self, passages, **kwargs)

HybridSchemeRetriever.__init__ = offline_init
runpy.run_module("src.mcp_servers.schemes_kb_server", run_name="__main__")
"""


@dataclass
class IntegratedUI:
    """Keep actual HTTP/tool observations and the isolated portal database."""

    client: TestClient
    database: Path
    requests: list[tuple[str, str, dict, dict]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)


@pytest.fixture(scope="module")
def integrated_ui() -> Iterator[IntegratedUI]:
    """Reuse one real lifespan; shut down children before deleting owned DBs."""

    databases = [
        Path.cwd() / f".pytest-ui-{name}-{uuid4().hex}.sqlite3"
        for name in ("journey", "portal")
    ]
    real_urlopen = urllib.request.urlopen
    real_parameters = api.StdioServerParameters
    real_call_tool = ServiceClientRouter.call_tool
    observations: list[str] = []

    def offline_parameters(
        *args: object, **kwargs: object,
    ) -> api.StdioServerParameters:
        if kwargs.get("args") == ["-m", "src.mcp_servers.schemes_kb_server"]:
            kwargs["args"] = ["-c", OFFLINE_SEARCH_BOOTSTRAP]
        return real_parameters(*args, **kwargs)

    async def record_tool(
        self: ServiceClientRouter, name: str, arguments: dict[str, object],
    ) -> object:
        observations.append(name)
        return await real_call_tool(self, name, arguments)

    harness: IntegratedUI | None = None

    def local_http(
        request: urllib.request.Request | str, *args: object, **kwargs: object,
    ) -> BytesIO | HTTPResponse:
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        address = urlsplit(url)
        if (
            address.scheme == "http"
            and address.netloc == urlsplit(UI_ORIGIN).netloc
            and (
                address.path.startswith("/api/v1/journey")
                or address.path == "/api/v1/forget"
                or address.path.startswith("/api/v1/household")
            )
        ):
            assert harness is not None
            assert isinstance(request, urllib.request.Request)
            body = json.loads(request.data) if request.data else {}
            response = harness.client.request(
                request.get_method(),
                address.path + (f"?{address.query}" if address.query else ""),
                content=request.data, headers=dict(request.header_items()),
            )
            result = response.json() if response.content else {}
            harness.requests.append(
                (request.get_method(), address.path, body, result)
            )
            if response.is_error:
                raise HTTPError(
                    url, response.status_code, response.reason_phrase,
                    response.headers, BytesIO(response.content),
                )
            return BytesIO(response.content)
        # Portal readiness is real loopback HTTP, not a TestClient response.
        if (
            address.scheme == "http"
            and address.netloc == urlsplit(PORTAL_URL).netloc
        ):
            return real_urlopen(request, *args, **kwargs)
        raise AssertionError("Acceptance tests permit only UI API and local portal HTTP")

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(databases[0]))
            patch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(databases[1]))
            patch.delenv("SCHEME_SAATHI_PORTAL_DB", raising=False)
            patch.setenv("SCHEME_SAATHI_API_URL", UI_ORIGIN)
            patch.setattr(api, "StdioServerParameters", offline_parameters)
            patch.setattr(ServiceClientRouter, "call_tool", record_tool)
            patch.setattr(urllib.request, "urlopen", local_http)
            patch.setattr(api_client, "urlopen", local_http)
            with TestClient(api.app) as client:
                harness = IntegratedUI(client, databases[1], tools=observations)
                assert set(client.app.state.mcp_services) == {
                    "rule-engine", "schemes-kb", "doc-check", "mock-portal",
                }
                yield harness
    finally:
        for database in databases:
            for suffix in ("", "-wal", "-shm"):
                database.with_name(database.name + suffix).unlink(missing_ok=True)


def _healthy(screen: AppTest) -> None:
    """Fail on UI exceptions or safe API-error banners, not just HTTP status."""

    assert not screen.exception
    assert not screen.error, [item.value for item in screen.error]


@pytest.mark.parametrize("all_scam", [False, True])
def test_scam_search_omits_flagged_passages_from_api_and_ui(
    integrated_ui, monkeypatch, all_scam,
):
    """Keep clean matches while ignoring scam passages and warning the citizen."""

    original = ServiceClientRouter.call_tool
    lure = "Visit https://pm-kisan-gov-in-verify.example/otp and enter your OTP."
    calls = []

    async def poisoned_search(self, name, arguments):
        result = await original(self, name, arguments)
        if name == "search_schemes":
            calls.append(name)
            records = result.structured_content["result"]
            assert records
            for record in (records if all_scam else records[:1]):
                record["text"] = lure
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ServiceClientRouter, "call_tool", poisoned_search)
        response = integrated_ui.client.get(
            "/api/v1/schemes/search", params={"query": "widow pension BPL"}
        )
        assert response.status_code == 200
        assert int(response.headers["X-Saathi-Omitted-Scam-Passages"]) >= 1
        assert bool(response.json()) is not all_scam
        assert "verify.example" not in response.text

        screen = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT).run()
        screen.text_input(key="scheme_query").set_value("widow pension BPL")
        next(item for item in screen.button if item.label == "Search schemes").click().run()
        _healthy(screen)
        assert any("flagged and ignored" in item.value for item in screen.warning)
        result = integrated_ui.requests[-1][3]
        assert result["status"] == "search_results"
        assert bool(result["passages"]) is not all_scam
        assert bool(result["candidate_scheme_ids"]) is not all_scam
        assert "verify.example" not in json.dumps(result)
        assert len(calls) == 2, "Filtered search results must not be retried."

    screen = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT).run()
    screen.text_input(key="scheme_query").set_value("widow pension BPL")
    _click(screen, "Search schemes")
    assert integrated_ui.requests[-1][3]["passages"]


def _use_free_portal(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give one test its own portal port.

    The module fixture already runs a portal on the shared port. A test that
    starts its own app lifespan would otherwise try to bind the same port.
    """

    import socket

    from src import config as app_config
    from src.api import portal_service

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{probe.getsockname()[1]}"
    monkeypatch.setattr(app_config, "PORTAL_URL", url)
    monkeypatch.setattr(portal_service, "PORTAL_URL", url)
    monkeypatch.setattr(api, "PORTAL_URL", url)
    monkeypatch.setitem(globals(), "PORTAL_URL", url)
    monkeypatch.setenv("SCHEME_SAATHI_PORTAL_URL", url)
    return url


def _click(screen: AppTest, label: str | None = None, *, key: str | None = None) -> None:
    """Click a rendered widget, including the reruns it schedules."""

    button = screen.button(key=key) if key else next(
        item for item in screen.button if item.label == label
    )
    assert not button.disabled
    button.click().run()
    _healthy(screen)


def _approve(screen: AppTest, scheme_id: str) -> None:
    """Tick "I have read this exact draft" (ASI09), then approve."""

    approve = screen.button(key=f"draft-approve-{scheme_id}")
    assert approve.disabled, "Approve must wait for the read confirmation"
    read = next(
        item for item in screen.checkbox
        if (item.key or "").startswith(f"draft-read-{scheme_id}-")
    )
    read.check().run()
    _healthy(screen)
    _click(screen, key=f"draft-approve-{scheme_id}")


def _interview(harness: IntegratedUI, *, csc: bool = False) -> AppTest:
    """Search, select the pilot, consent and answer actual graph questions."""

    screen = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT).run()
    _healthy(screen)
    if csc:
        screen.radio(key="interaction_mode").set_value("csc").run()
    screen.text_input(key="scheme_query").set_value("widow pension BPL")
    _click(screen, "Search schemes")
    assert harness.requests[-1][2]["action"] == "search"
    assert harness.requests[-1][3]["status"] == "search_results"
    screen.selectbox(key="selected_search_scheme").set_value(SCHEME).run()
    _click(screen, "Continue to the synthetic eligibility demo")
    start = next(item for item in screen.button if item.label == "Start questions")
    assert start.disabled
    screen.checkbox(key="demo_consent").check().run()
    if csc:
        assert next(item for item in screen.button if item.label == "Start questions").disabled
        screen.checkbox(key="csc_citizen_present").check().run()
    _click(screen, "Start questions")
    start_request = next(
        request for request in reversed(harness.requests)
        if request[2].get("action") == "interview"
    )
    assert start_request[2]["mode"] == ("csc" if csc else "citizen")
    assert start_request[2]["citizen_present"] is True
    if csc:
        assert "CSC" in start_request[3]["mode_acknowledgement"]
    answers = {
        "date_of_birth": "1986-01-01",
        "application_date": "2026-11-04",
        "is_widow": "yes",
        "bpl_card_shown": "yes",
    }
    answered = set()
    for _ in range(len(answers)):
        if screen.session_state.journey_status != "awaiting_answer":
            break
        response = next(
            request[3] for request in reversed(harness.requests)
            if request[3].get("pending_fact")
        )
        fact = response["pending_fact"]
        answered.add(fact)
        screen.chat_input[0].set_value(answers[fact]).run()
        _healthy(screen)
    assert {"date_of_birth", "is_widow", "bpl_card_shown"} <= answered
    assert screen.session_state.journey_status == "eligible"
    assert screen.session_state.interview_result["evidence"]
    assert screen.session_state.journey_agent_budget.get("model_calls", 0) == 0
    assert screen.session_state.journey_react_status == "deterministic"
    return screen


def _correct_birth_date(screen: AppTest, answer: str) -> None:
    """Change a confirmed fact while keeping this synthetic applicant eligible."""

    previous_version = screen.session_state.journey_dependency_version
    screen.selectbox(key="correction_fact_name").set_value("date_of_birth").run()
    screen.text_input(key="correction_answer_value").set_value(answer)
    _click(screen, "Save correction and recheck")
    assert screen.session_state.journey_status == "eligible"
    assert screen.session_state.journey_dependency_version > previous_version
    assert "correction_invalidated" in screen.session_state.journey_discovery_notices


def _documents(screen: AppTest, *, mismatch: bool = False) -> dict:
    """Use real status and metadata widgets to recheck synthetic documents."""

    screen.text_input(key=f"profile-name-{SCHEME}").set_value("Synthetic Example")
    for document_id in DOCUMENT_IDS:
        screen.selectbox(key=f"doc-{SCHEME}-{document_id}").set_value("available")
    screen.text_input(key=f"doc-name-{SCHEME}-identity_proof").set_value(
        "Different Synthetic Example" if mismatch else "Synthetic Example"
    )
    _click(screen, key=f"docs-update-{SCHEME}")
    return screen.session_state.application_flow[SCHEME]["assessment"]


def _refresh(screen: AppTest) -> AppTest:
    """Create a fresh Streamlit session carrying only the actual saved URL."""

    restored = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT)
    restored.query_params.update(dict(screen.query_params))
    restored.run()
    _healthy(restored)
    assert restored.session_state.conversation_id == screen.session_state.conversation_id
    return restored


def test_development_scholarship_reaches_exact_mock_receipt_through_real_ui(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    """Inject one data-only test bundle while keeping the ordinary catalogue untouched."""

    scheme_id = SCHOLARSHIP
    # Work on a private copy so other tests in this worker never see the bundle
    # while it is being published and restored.
    # The app only accepts test rule data under tests/fixtures, so the copy lives there.
    run_root = SCHOLARSHIP_PACKAGE_DIR.parent.parent / f"phase4-run-{uuid4().hex}"
    shutil.copytree(SCHOLARSHIP_PACKAGE_DIR.parent, run_root)
    request.addfinalizer(lambda: shutil.rmtree(run_root, ignore_errors=True))
    fixture_root = run_root
    package_dir = (fixture_root / "packages").resolve()
    scheme_data = (fixture_root / "schemes").resolve()
    checklist_path = (
        scheme_data / "document_checklists" / f"{scheme_id}.json"
    )
    form_path = scheme_data / "mock_forms" / f"{scheme_id}.json"
    original_checklist = checklist_path.read_bytes()
    original_form = form_path.read_bytes()
    databases = [
        PROJECT_ROOT / f".pytest-ui-scholarship-{name}-{uuid4().hex}.sqlite3"
        for name in ("journey", "portal")
    ]
    ui_origin = "http://ui-scholarship.invalid"
    real_urlopen = urllib.request.urlopen
    real_parameters = api.StdioServerParameters
    harness: IntegratedUI | None = None

    def offline_parameters(
        *args: object, **kwargs: object,
    ) -> api.StdioServerParameters:
        if kwargs.get("args") == ["-m", "src.mcp_servers.schemes_kb_server"]:
            kwargs["args"] = ["-c", OFFLINE_SEARCH_BOOTSTRAP]
        return real_parameters(*args, **kwargs)

    def local_http(
        request: urllib.request.Request | str, *args: object, **kwargs: object,
    ) -> BytesIO | HTTPResponse:
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        address = urlsplit(url)
        if (
            address.scheme == "http"
            and address.netloc == urlsplit(ui_origin).netloc
            and address.path.startswith("/api/v1/journey")
        ):
            assert harness is not None
            assert isinstance(request, urllib.request.Request)
            body = json.loads(request.data) if request.data else {}
            response = harness.client.request(
                request.get_method(), address.path,
                content=request.data, headers=dict(request.header_items()),
            )
            result = response.json() if response.content else {}
            harness.requests.append(
                (request.get_method(), address.path, body, result)
            )
            if response.is_error:
                raise HTTPError(
                    url, response.status_code, response.reason_phrase,
                    response.headers, BytesIO(response.content),
                )
            return BytesIO(response.content)
        if (
            address.scheme == "http"
            and address.netloc == urlsplit(PORTAL_URL).netloc
        ):
            return real_urlopen(request, *args, **kwargs)
        raise AssertionError("Only UI API and private portal HTTP are permitted.")

    monkeypatch.setenv("SCHEME_SAATHI_TEST_RULE_PACKAGE_DIR", str(package_dir))
    monkeypatch.setenv("SCHEME_SAATHI_CHECKPOINT_DB", str(databases[0]))
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(databases[1]))
    monkeypatch.setenv("SCHEME_SAATHI_API_URL", ui_origin)
    monkeypatch.delenv("SCHEME_SAATHI_PORTAL_DB", raising=False)
    monkeypatch.setattr(api, "StdioServerParameters", offline_parameters)
    monkeypatch.setattr(urllib.request, "urlopen", local_http)
    monkeypatch.setattr(api_client, "urlopen", local_http)
    _use_free_portal(monkeypatch)
    # This test starts its own lifespan on the shared app. Its clients and
    # connections are shut down at the end, so restore the module fixture's state.
    saved_app_state = dict(api.app.state._state)

    try:
        with TestClient(api.app) as client:
            provider = client.app.state.mcp_client
            rules = get_active_rule_data()
            passage = SchemePassage(
                passage_id="SYNTH-SCHOLARSHIP-INTRO",
                scheme_id=scheme_id,
                scheme_name="Synthetic test scholarship",
                jurisdiction="TEST-ONLY",
                language="en",
                section="overview",
                text="Synthetic development fixture; not a government scheme.",
                source=PassageSource(
                    publisher="Synthetic test data",
                    url="https://example.test/synthetic-scholarship",
                    collected_at="2026-11-04",
                    locator="fixture",
                ),
                review_status="pending_review",
            )

            async def fixture_search(_client, _query: str) -> list[SchemePassage]:
                return [passage]

            client.app.state.journey_graph = build_journey_graph(
                provider,
                rules.packages,
                search_tool=fixture_search,
                checkpointer=client.app.state.journey_checkpointer,
                fact_registry=rules.registry,
                rule_bundles=rules.bundles,
            )
            harness = IntegratedUI(client, databases[1])

            screen = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT).run()
            _healthy(screen)
            screen.text_input(key="scheme_query").set_value("synthetic scholarship")
            _click(screen, "Search schemes")
            screen.selectbox(key="selected_search_scheme").set_value(scheme_id).run()
            _click(screen, "Continue to the synthetic eligibility demo")
            assert next(item for item in screen.button if item.label == "Start questions").disabled
            screen.checkbox(key="demo_consent").check().run()
            _click(screen, "Start questions")

            answers = {
                "exam_marks": "80",
                "exam_ratio": "0.12345678901234567",
                "exam_stream": "science",
                "guardian_consent": "I don't know",
            }
            answered: set[str] = set()
            for _ in range(len(answers)):
                if screen.session_state.journey_status != "awaiting_answer":
                    break
                response = next(
                    item[3] for item in reversed(harness.requests)
                    if item[3].get("pending_fact")
                )
                fact_id = response["pending_fact"]
                answered.add(fact_id)
                answer_key = (
                    f"registered_answer_{screen.session_state.conversation_id}_"
                    f"{fact_id}"
                )
                if fact_id == "exam_marks":
                    screen.number_input(key=answer_key).set_value(80)
                elif fact_id == "exam_ratio":
                    screen.text_input(key=answer_key).set_value(answers[fact_id])
                elif fact_id == "exam_stream":
                    screen.selectbox(key=answer_key).set_value("Science")
                else:
                    # Yes/no questions are answered by typing.
                    screen.chat_input[0].set_value(answers[fact_id]).run()
                    _healthy(screen)
                    continue
                _click(screen, "Send answer")
                _healthy(screen)
            assert answered == set(answers), (
                screen.session_state.journey_status,
                harness.requests[-5:],
            )
            assert screen.session_state.journey_status == "eligible"
            assert screen.session_state.journey_agent_budget.get("model_calls", 0) == 0
            assert screen.query_params.get("conversation") == (
                screen.session_state.conversation_id
            )
            saved_state = client.portal.call(
                client.app.state.journey_graph.aget_state,
                {"configurable": {
                    "thread_id": screen.session_state.conversation_id
                }},
            ).values
            assert saved_state["typed_facts"]["facts"]["exam_marks"]["value"] == 80
            assert saved_state["typed_facts"]["facts"]["exam_ratio"]["value"] == {
                "$decimal": answers["exam_ratio"],
            }

            _click(screen, key=f"docs-load-{scheme_id}")
            checklist_groups = screen.session_state.application_flow[
                scheme_id
            ]["assessment"]["groups"]
            assert checklist_groups[0]["applicable"] is True
            assert checklist_groups[0]["condition"]["value"] == answers["exam_ratio"]
            assert checklist_groups[1]["applicable"] is True
            assert checklist_groups[2]["applicable"] is None
            for document_id in (
                "student_card", "school_letter", "exam_record",
            ):
                screen.selectbox(key=f"doc-{scheme_id}-{document_id}").set_value(
                    "available" if document_id == "student_card" else "unknown"
                )
            _click(screen, key=f"docs-update-{scheme_id}")
            assessment = screen.session_state.application_flow[scheme_id]["assessment"]
            assert assessment["status"] == "unknown_items"
            assert assessment["groups"][2]["status"] == "unknown"
            assert not any(
                item.key == f"draft-create-{scheme_id}" for item in screen.button
            )

            screen.selectbox(key="correction_fact_name").set_value(
                "guardian_consent"
            ).run()
            screen.text_input(key="correction_answer_value").set_value("yes")
            _click(screen, "Save correction and recheck")
            assert screen.session_state.journey_status == "eligible"
            _click(screen, key=f"docs-load-{scheme_id}")
            screen.selectbox(
                key=f"doc-{scheme_id}-student_card"
            ).set_value("available")
            screen.selectbox(
                key=f"doc-{scheme_id}-exam_record"
            ).set_value("available")
            screen.selectbox(
                key=f"doc-{scheme_id}-guardian_confirmation"
            ).set_value("available")
            screen.text_input(
                key=f"form-{scheme_id}-student_identifier"
            ).set_value("SYNTH-STUDENT-01")
            _click(screen, key=f"docs-update-{scheme_id}")
            assessment = screen.session_state.application_flow[scheme_id]["assessment"]
            assert assessment["status"] == "checklist_complete"
            preview = next(
                item for item in assessment["form_preview"]["fields"]
                if item["field_id"] == "exam_ratio"
            )
            assert preview["value"] == answers["exam_ratio"]
            assert preview["value_type"] == "decimal"
            _click(screen, key=f"draft-create-{scheme_id}")
            first_draft = screen.session_state.application_drafts[scheme_id]
            assert first_draft["draft"]["form_fields"] == {
                "exam_marks": 80,
                "exam_stream": "science",
                "student_identifier": "SYNTH-STUDENT-01",
                "exam_ratio": answers["exam_ratio"],
            }
            assert first_draft["draft"]["form_field_types"]["exam_marks"] == "integer"
            assert first_draft["draft"]["form_field_types"]["exam_ratio"] == "decimal"
            assert first_draft["fingerprint"] == _canonical_fingerprint(first_draft["draft"])
            assert first_draft["draft"]["form_version"] == "1.0.0"
            assert first_draft["draft"]["form_status"] == "demo_only"
            assert not first_draft["approved"]
            _approve(screen, scheme_id)
            approved = screen.session_state.application_drafts[scheme_id]
            assert approved["approved"]
            assert approved["fingerprint"] == first_draft["fingerprint"]
            assert approved["draft"]["form_fields"]["exam_ratio"] == answers["exam_ratio"]

            screen.selectbox(key="correction_fact_name").set_value("exam_ratio").run()
            corrected_ratio = "0.12345678901234568"
            screen.text_input(key="correction_answer_value").set_value(corrected_ratio)
            _click(screen, "Save correction and recheck")
            assert screen.session_state.journey_status == "eligible"
            old_submit = client.post(
                f"/api/v1/journey/{screen.session_state.conversation_id}/drafts/"
                f"{approved['draft_id']}/approval",
                json={
                    "action": "submit", "revision": approved["revision"],
                    "fingerprint": approved["fingerprint"],
                },
            )
            assert old_submit.status_code == 409
            saved = client.get(
                f"/api/v1/journey/{screen.session_state.conversation_id}/drafts"
            ).json()["drafts"]
            stale = next(item for item in saved if item["draft_id"] == approved["draft_id"])
            assert stale["stale"] and not stale["approved"]
            screen = _refresh(screen)
            stale = screen.session_state.application_drafts[scheme_id]
            assert stale["stale"] and not stale["approved"]
            assert not any(item.key == f"draft-submit-{scheme_id}" for item in screen.button)
            _click(screen, key=f"docs-reload-{scheme_id}")
            for document_id in (
                "student_card", "exam_record", "guardian_confirmation",
            ):
                screen.selectbox(key=f"doc-{scheme_id}-{document_id}").set_value("available")
            screen.text_input(key=f"form-{scheme_id}-student_identifier").set_value(
                "SYNTH-STUDENT-01"
            )
            _click(screen, key=f"docs-correct-{scheme_id}")
            corrected = screen.session_state.application_drafts[scheme_id]
            assert corrected["draft_id"] != approved["draft_id"]
            assert corrected["fingerprint"] != approved["fingerprint"]
            assert corrected["draft"]["form_fields"]["exam_ratio"] == corrected_ratio
            assert not corrected["approved"] and not corrected["stale"]
            _approve(screen, scheme_id)
            approved = screen.session_state.application_drafts[scheme_id]
            assert approved["approved"]

            changed_form = json.loads(original_form)
            changed_form["fields"][2]["max_length"] = 23
            changed_checklist = json.loads(original_checklist)
            changed_checklist["checklist_version"] = "v2"
            changed_checklist["approval"]["checklist_version"] = "v2"
            changed_checklist["requirements"][1]["condition"]["value"] = 75
            publish_mock_form_file(
                form_path.name,
                json.dumps(changed_form, ensure_ascii=False).encode("utf-8"),
                form_directory=form_path.parent,
            )
            publish_checklist_file(
                checklist_path.name,
                json.dumps(changed_checklist, ensure_ascii=False).encode("utf-8"),
                checklist_directory=checklist_path.parent,
                evidence_file=scheme_data / "document_evidence.json",
            )
            old_submit = client.post(
                f"/api/v1/journey/{screen.session_state.conversation_id}/drafts/"
                f"{approved['draft_id']}/approval",
                json={
                    "action": "submit",
                    "revision": approved["revision"],
                    "fingerprint": approved["fingerprint"],
                },
            )
            assert old_submit.status_code == 409
            saved = client.get(
                f"/api/v1/journey/{screen.session_state.conversation_id}/drafts"
            ).json()["drafts"]
            stale = next(item for item in saved if item["draft_id"] == approved["draft_id"])
            assert stale["stale"] and not stale["approved"]

            refreshed = _refresh(screen)
            refreshed.selectbox(key="correction_fact_name").set_value("exam_ratio").run()
            refreshed.text_input(key="correction_answer_value").set_value(
                answers["exam_ratio"]
            )
            _click(refreshed, "Save correction and recheck")
            assert refreshed.session_state.journey_status == "eligible"
            saved = client.get(
                f"/api/v1/journey/{screen.session_state.conversation_id}/drafts"
            ).json()["drafts"]
            for old_draft in (first_draft, approved):
                stale = next(
                    item for item in saved if item["draft_id"] == old_draft["draft_id"]
                )
                assert stale["stale"] and not stale["approved"]
                old_submit = client.post(
                    f"/api/v1/journey/{screen.session_state.conversation_id}/drafts/"
                    f"{old_draft['draft_id']}/approval",
                    json={
                        "action": "submit", "revision": old_draft["revision"],
                        "fingerprint": old_draft["fingerprint"],
                    },
                )
                assert old_submit.status_code == 409
            _click(refreshed, key=f"docs-reload-{scheme_id}")
            for document_id in (
                "student_card", "exam_record", "guardian_confirmation",
            ):
                refreshed.selectbox(
                    key=f"doc-{scheme_id}-{document_id}"
                ).set_value("available")
            refreshed.text_input(
                key=f"form-{scheme_id}-student_identifier"
            ).set_value("SYNTH-STUDENT-01")
            _click(refreshed, key=f"docs-correct-{scheme_id}")
            fresh = refreshed.session_state.application_drafts[scheme_id]
            assert fresh["draft_id"] != approved["draft_id"]
            assert fresh["draft"]["checklist_version"] == "v2"
            assert fresh["draft"]["form_mapping_fingerprint"] != (
                approved["draft"]["form_mapping_fingerprint"]
            )
            assert not fresh["approved"] and not fresh["stale"]
            assert fresh["draft"]["form_fields"]["exam_ratio"] == answers["exam_ratio"]
            assert fresh["fingerprint"] == _canonical_fingerprint(fresh["draft"])
            _approve(refreshed, scheme_id)
            _click(refreshed, key=f"draft-submit-{scheme_id}")
            submitted = refreshed.session_state.application_drafts[scheme_id]
            assert submitted["receipt_id"]
            assert submitted["draft"]["form_fields"]["exam_ratio"] == answers["exam_ratio"]
            retry = api_client.decide_application_draft(
                screen.session_state.conversation_id, submitted, "submit"
            )
            assert retry["receipt_id"] == submitted["receipt_id"]
            assert retry["fingerprint"] == submitted["fingerprint"]
            assert retry["draft"]["form_fields"]["exam_ratio"] == answers["exam_ratio"]
            with closing(sqlite3.connect(databases[1])) as connection:
                assert connection.execute(
                    "SELECT COUNT(*), COUNT(submitted_receipt) "
                    "FROM application_drafts WHERE journey_id=?",
                    (screen.session_state.conversation_id,),
                ).fetchone() == (3, 1)
    finally:
        api.app.state._state.clear()
        api.app.state._state.update(saved_app_state)
        publish_mock_form_file(
            form_path.name, original_form, form_directory=form_path.parent
        )
        publish_checklist_file(
            checklist_path.name,
            original_checklist,
            checklist_directory=checklist_path.parent,
            evidence_file=scheme_data / "document_evidence.json",
        )
        for artifact in (
            scheme_data / ".document_checklists.lock",
            scheme_data / ".document_checklists.revision",
        ):
            artifact.unlink(missing_ok=True)
        for database in databases:
            for suffix in ("", "-wal", "-shm"):
                database.with_name(database.name + suffix).unlink(missing_ok=True)


def test_phases_one_to_four_ui_receipt_retry_and_scoped_forget(
    integrated_ui: IntegratedUI,
) -> None:
    """Real widget clicks reach one durable receipt, refresh and scoped deletion."""

    harness = integrated_ui
    screen = _interview(harness)
    conversation_id = screen.session_state.conversation_id
    _correct_birth_date(screen, "1985-01-01")
    assert screen.session_state.application_flow[SCHEME]["assessment"] is None
    _click(screen, key=f"docs-load-{SCHEME}")
    mismatch = _documents(screen, mismatch=True)
    assert mismatch["status"] == "mismatch"
    assert mismatch["discrepancies"] == [{
        "document_id": "identity_proof", "code": "name_mismatch",
    }]
    assert not any(item.key == f"draft-create-{SCHEME}" for item in screen.button)
    checked = _documents(screen)
    assert checked["status"] == "checklist_complete"
    assert checked["demo_only"] is False
    _click(screen, key=f"draft-create-{SCHEME}")
    draft = screen.session_state.application_drafts[SCHEME]
    assert not draft["approved"]
    assert not any(item.key == f"draft-submit-{SCHEME}" for item in screen.button)
    _approve(screen, SCHEME)
    approved = screen.session_state.application_drafts[SCHEME]
    assert approved["approved"]
    assert approved["fingerprint"] == draft["fingerprint"]
    _click(screen, key=f"draft-submit-{SCHEME}")
    submitted = screen.session_state.application_drafts[SCHEME]
    assert submitted["receipt_id"]
    assert any(submitted["receipt_id"] in item.value for item in screen.success)
    restored = _refresh(screen)
    recovered = restored.session_state.application_drafts[SCHEME]
    assert recovered["draft_id"] == submitted["draft_id"]
    assert recovered["receipt_id"] == submitted["receipt_id"]
    assert recovered["stale"] == submitted["stale"]
    assert not any(item.key == f"draft-submit-{SCHEME}" for item in restored.button)
    # A transport retry uses the real serializer/approval endpoint, not a fake receipt.
    retry = api_client.decide_application_draft(conversation_id, recovered, "submit")
    assert retry["receipt_id"] == submitted["receipt_id"]
    with closing(sqlite3.connect(harness.database)) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COUNT(submitted_receipt) FROM application_drafts "
            "WHERE journey_id=?", (conversation_id,),
        ).fetchone() == (1, 1)
    paths = {(method, path) for method, path, _, _ in harness.requests}
    root = f"/api/v1/journey/{conversation_id}"
    assert {
        ("POST", "/api/v1/journey"), ("POST", f"{root}/messages"),
        ("POST", f"{root}/corrections"), ("POST", f"{root}/documents"),
        ("POST", f"{root}/drafts"),
        ("POST", f"{root}/drafts/{draft['draft_id']}/approval"),
        ("GET", root),
    } <= paths
    assert {
        "search_schemes", "evaluate_eligibility",
        "check_documents", "mock_portal",
    } <= set(harness.tools)
    # Keep a second real conversation to prove forget is not a global wipe.
    retained = harness.client.post("/api/v1/journey", json={
        "action": "evaluate", "scheme_id": SCHEME,
        "profile": {
            "date_of_birth": "1986-01-01", "application_date": "2026-11-04",
            "is_widow": True, "bpl_card_shown": True,
        },
    })
    assert retained.status_code == 200
    retained_id = retained.json()["conversation_id"]
    next(
        checkbox for checkbox in restored.checkbox
        if checkbox.key == "memory_consent"
    ).check().run()
    _click(restored, "Forget my demonstration data")
    assert ("DELETE", "/api/v1/forget") in {
        (method, path) for method, path, _, _ in harness.requests
    }
    assert not restored.query_params
    assert not restored.session_state.get("memory_consent", False)
    assert harness.client.get(root).status_code == 404
    assert harness.client.get(f"{root}/drafts").json() == {"drafts": []}
    assert harness.client.get(f"/api/v1/journey/{retained_id}").status_code == 200
    with closing(sqlite3.connect(harness.database)) as connection:
        for table in (
            "application_drafts", "journey_dependencies",
            "document_dependencies", "rule_dependencies",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE journey_id=?",
                (conversation_id,),
            ).fetchone()[0] == 0
    assert harness.client.delete(f"/api/v1/journey/{retained_id}").status_code == 204


def test_corrected_return_code_answer_can_be_resaved_from_the_ui(
    integrated_ui: IntegratedUI,
) -> None:
    """A user can correct a loaded answer and explicitly update that code."""

    harness = integrated_ui
    initial = harness.client.post("/api/v1/journey", json={
        "action": "evaluate",
        "scheme_id": SCHEME,
        "profile": {
            "date_of_birth": "1986-01-01",
            "application_date": "2026-11-04",
            "is_widow": True,
            "bpl_card_shown": True,
            "income_tax_paid_last_assessment_year": False,
        },
    })
    assert initial.status_code == 200
    conversation_id = initial.json()["conversation_id"]
    saved = harness.client.post("/api/v1/household", json={
        "conversation_id": conversation_id,
        "memory_consent": True,
    })
    assert saved.status_code == 200
    return_code = saved.json()["return_code"]

    screen = AppTest.from_file(UI_PATH, default_timeout=TIMEOUT).run()
    _healthy(screen)
    screen.text_input(key="scheme_query").set_value("widow pension BPL")
    _click(screen, "Search schemes")
    screen.selectbox(key="selected_search_scheme").set_value(SCHEME).run()
    _click(screen, "Continue to the synthetic eligibility demo")
    screen.checkbox(key="demo_consent").check().run()
    screen.checkbox(key="memory_consent").check().run()
    screen.text_input(key=f"return_code_input_{SCHEME}").set_value(return_code)
    _click(screen, key=f"load_code_{SCHEME}")
    assert screen.session_state.household_return_code == return_code
    _click(screen, "Start questions")

    answers = {
        "date_of_birth": "1986-01-01",
        "application_date": "2026-11-04",
        "is_widow": "yes",
        "bpl_card_shown": "yes",
    }
    for _ in range(8):
        if screen.session_state.journey_status != "awaiting_answer":
            break
        pending = next(
            request[3] for request in reversed(harness.requests)
            if request[3].get("pending_fact")
        )
        fact = pending["pending_fact"]
        screen.chat_input[0].set_value(answers.get(fact, "no")).run()
        _healthy(screen)
    assert screen.session_state.journey_status == "eligible"
    assert return_code in screen.session_state.journey_return_code

    screen.selectbox(key="correction_fact_name").set_value("bpl_card_shown").run()
    screen.text_input(key="correction_answer_value").set_value("no")
    _click(screen, "Save correction and recheck")
    _click(screen, "Save my answers")

    loaded = harness.client.get(
        f"/api/v1/household/{return_code}?memory_consent=true"
    )
    assert loaded.status_code == 200
    assert (
        loaded.json()["typed_facts"]["facts"]["bpl_card_shown"]["value"]
        is False
    )


def test_approved_ui_correction_refresh_requires_fresh_report_draft_and_review(
    integrated_ui: IntegratedUI,
) -> None:
    """CSC fact correction cannot retain approval even when still eligible."""

    harness = integrated_ui
    screen = _interview(harness, csc=True)
    conversation_id = screen.session_state.conversation_id
    _click(screen, key=f"docs-load-{SCHEME}")
    assert _documents(screen)["status"] == "checklist_complete"
    _click(screen, key=f"draft-create-{SCHEME}")
    _approve(screen, SCHEME)
    old = screen.session_state.application_drafts[SCHEME]
    assert old["approved"]
    _correct_birth_date(screen, "1984-01-01")
    stale = screen.session_state.application_drafts[SCHEME]
    assert stale["stale"]
    assert not stale["approved"]
    assert not any(item.key == f"draft-submit-{SCHEME}" for item in screen.button)
    restored = _refresh(screen)
    stale = restored.session_state.application_drafts[SCHEME]
    assert stale["draft_id"] == old["draft_id"]
    assert stale["stale"] and not stale["approved"]
    assert not any(item.key == f"draft-submit-{SCHEME}" for item in restored.button)
    decision_url = (
        f"/api/v1/journey/{conversation_id}/drafts/{old['draft_id']}/approval"
    )
    refused = harness.client.post(decision_url, json={
        "action": "submit", "revision": old["revision"],
        "fingerprint": old["fingerprint"],
    })
    assert refused.status_code == 409
    _click(restored, key=f"docs-reload-{SCHEME}")
    restored.text_input(key=f"profile-name-{SCHEME}").set_value("Synthetic Example")
    for document_id in DOCUMENT_IDS:
        restored.selectbox(key=f"doc-{SCHEME}-{document_id}").set_value("available")
    restored.text_input(key=f"doc-name-{SCHEME}-identity_proof").set_value(
        "Synthetic Example"
    )
    _click(restored, key=f"docs-correct-{SCHEME}")
    fresh = restored.session_state.application_drafts[SCHEME]
    assert fresh["draft_id"] != old["draft_id"]
    assert fresh["draft"]["profile"]["date_of_birth"] == "1984-01-01"
    assert not fresh["stale"] and not fresh["approved"]
    assert not any(item.key == f"draft-submit-{SCHEME}" for item in restored.button)
    _approve(restored, SCHEME)
    _click(restored, key=f"draft-submit-{SCHEME}")
    assert restored.session_state.application_drafts[SCHEME]["receipt_id"]
    with closing(sqlite3.connect(harness.database)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM application_drafts "
            "WHERE journey_id=? AND submitted_receipt IS NOT NULL",
            (conversation_id,),
        ).fetchone()[0] == 1
    _click(restored, "Forget my demonstration data")
