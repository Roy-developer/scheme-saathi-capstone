"""Verify generic fact validation and data-only scheme evaluation."""

import hashlib
import json
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import date
from pathlib import Path

import pytest
import aiosqlite
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from src.api.app import app
from src.api.scheme_search import SchemePassage
from src.mcp_servers.tools.eligibility import evaluate_registered_profile
from src.mcp_servers.tools import applications, documents
from src.rules.data_provider import RulePackageProvider, _validate_rule
from src.rules.facts import FactDefinition, FactRegistry, FactState, HouseholdProfile
from src.rules.models import Rule, RulePackage
from fake_chat_model import FakeChatModel, ModelDecision
from src.workflow.errors import MCPToolError
from src.workflow.journey import (
    ApplicationTaskError,
    JourneyCorrection,
    JourneyRequest,
    build_journey_graph,
    correct_journey_answer,
    get_journey,
    resume_journey,
    run_application_task,
    run_journey,
)
from src.workflow.questions import (
    parse_registered_answer,
    registered_question_details,
)


_QUESTION_COPY = {
    "en": {"text": "What is the synthetic exam mark and course type?"},
    "hi": {"text": "परीक्षा के अंक और पाठ्यक्रम का प्रकार क्या है?"},
    "mr": {"text": "परीक्षेचे गुण आणि अभ्यासक्रमाचा प्रकार काय आहे?"},
}
_SOURCE_URL = "https://example.test/synthetic-scholarship"


def _fact(
    fact_id: str,
    value_type: str,
    *,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    choices: list[str] | None = None,
) -> dict[str, object]:
    """Build pending-review metadata for a synthetic test-only fact."""

    return {
        "fact_id": fact_id,
        "version": "1.0.0",
        "meaning": f"Synthetic scholarship {fact_id}.",
        "source_refs": [_SOURCE_URL],
        "definition_review_status": "pending",
        "scope": "person",
        "value_type": value_type,
        "unit": "percent" if fact_id == "exam_marks" else None,
        "period": None,
        "minimum": minimum,
        "maximum": maximum,
        "choices": choices or [],
        "choice_labels": (
            {
                "en": {"science": "Science", "arts": "Arts"},
                "hi": {"science": "विज्ञान", "arts": "कला"},
                "mr": {"science": "विज्ञान", "arts": "कला"},
            }
            if choices
            else {}
        ),
        "max_length": None,
        "display_only": False,
        "derived_from": [],
        "derivation": None,
        "questions": _QUESTION_COPY,
        "question_review_status": "pending",
        "privacy": {
            "policy_id": "synthetic-test-only",
            "version": "1.0.0",
            "purpose": "Exercise deterministic validation in offline tests.",
            "sensitivity": "ordinary",
            "review_status": "pending",
        },
    }


def _write_synthetic_bundle(
    root: Path,
    *,
    invalid_choice_operator: bool = False,
    wrong_numeric_unit: bool = False,
    activation_state: str = "development_only",
    scheme_id: str = "SYNTHETIC-SCHOLARSHIP-TEST",
    create_only: bool = False,
    package_approved: bool = False,
    definitions_approved: bool = False,
) -> tuple[RulePackageProvider | None, RulePackage]:
    """Write a data-only bundle outside the real scheme catalogue."""

    package_dir = root / "packages"
    package_dir.mkdir()
    registry_data = {
        "schema_version": "1.0",
        "registry_version": "1.0.0",
        "definitions": [
            _fact("exam_marks", "decimal", minimum=0, maximum=100),
            _fact("course_type", "choice", choices=["science", "arts"]),
        ],
    }
    if definitions_approved:
        for definition in registry_data["definitions"]:
            definition.update({
                "definition_review_status": "approved",
                "definition_reviewer": "Offline test reviewer",
                "definition_reviewed_at": "2026-11-08",
            })
    registry_bytes = (
        json.dumps(registry_data, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    (root / "fact_registry.json").write_bytes(registry_bytes)
    package_data = {
        "package_version": "1.0.0",
        "scheme_id": scheme_id,
        "approval_status": (
            "approved_for_mock_portal" if package_approved
            else "mock_baseline_pending_human_rule_approval"
        ),
        "reviewer_name": "Offline synthetic test fixture; no policy review",
        "reviewed_at": "2026-11-04",
        "approval_scope": "synthetic_mock_portal_only",
        "source": {
            "publisher": "Synthetic test fixture",
            "source_url": _SOURCE_URL,
            "collected_at": "2026-11-04",
            "official_eligibility_text": "Synthetic fixture only: marks 75–100 and science.",
            "publication_date_status": "not_confirmed",
        },
        "required_facts": ["exam_marks", "course_type"],
        "documents_status": "not_verified",
        "reasons": {
            "eligible": "Synthetic test conditions are met.",
            "not_eligible": "A synthetic test condition is not met.",
            "need_more_information": "A synthetic test fact is unknown.",
        },
        "rules": [
            {
                "rule_id": "SYNTHETIC-MARKS-MIN",
                "field": "exam_marks",
                "operator": "gte",
                "value": 75,
                "unit": "marks" if wrong_numeric_unit else "percent",
                "source_clause_id": "SYNTHETIC-TEST-CLAUSE",
            },
            {
                "rule_id": "SYNTHETIC-MARKS-MAX",
                "field": "exam_marks",
                "operator": "lte",
                "value": 100,
                "unit": "percent",
                "source_clause_id": "SYNTHETIC-TEST-CLAUSE",
            },
            {
                "rule_id": "SYNTHETIC-COURSE",
                "field": "course_type",
                "operator": "gte" if invalid_choice_operator else "eq",
                "value": "science",
                "source_clause_id": "SYNTHETIC-TEST-CLAUSE",
            },
        ],
    }
    package = RulePackage.model_validate(package_data)
    package_path = package_dir / "synthetic_scholarship.json"
    package_bytes = (
        json.dumps(package_data, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    package_path.write_bytes(package_bytes)
    manifest = {
        "schema_version": "1.0",
        "bundles": [
            {
                "scheme_id": package.scheme_id,
                "bundle_version": "1.0.0",
                "activation_state": activation_state,
                "package_file": package_path.name,
                "package_version": package.package_version,
                "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
                "registry_version": "1.0.0",
                "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
                "fact_ids": ["exam_marks", "course_type"],
                "source_clause_ids": ["SYNTHETIC-TEST-CLAUSE"],
            }
        ],
    }
    (root / "bundle_registry.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    provider = (
        None
        if create_only
        else RulePackageProvider(package_dir, allow_development=True)
    )
    return provider, package


def _store(
    provider: RulePackageProvider,
    *,
    marks: object | None,
    course: str = "science",
    status: str = "known",
) -> HouseholdProfile:
    """Build a test fact store with explicitly versioned values."""

    facts: dict[str, FactState] = {
        "course_type": FactState(
            status="known",
            value=course,
            definition_version="1.0.0",
            provenance="user_reported",
        )
    }
    if marks is not None or status != "known":
        facts["exam_marks"] = FactState(
            status=status,
            value=marks,
            definition_version="1.0.0",
            provenance="user_reported" if status == "known" else None,
        )
    return HouseholdProfile(registry_version="1.0.0", facts=facts)


def test_new_numeric_and_choice_facts_evaluate_through_mcp_core(
    tmp_path: Path,
) -> None:
    """A new synthetic scheme uses data-only rules through the MCP adapter."""

    provider, package = _write_synthetic_bundle(tmp_path)
    bundle = provider.get_bundle(package.scheme_id)

    def evaluate(store: HouseholdProfile):
        return evaluate_registered_profile(
            package.scheme_id,
            store,
            provider.packages,
            provider.bundles,
            provider.registry,
        )

    assert bundle.activation_state == "development_only"
    assert evaluate(_store(provider, marks=75.0)).result == "eligible"
    assert evaluate(_store(provider, marks=100.0)).result == "eligible"
    assert evaluate(_store(provider, marks=74.99)).result == "not_eligible"
    unknown = _store(provider, marks=None)
    assert evaluate(unknown).result == "need_more_information"
    assert evaluate(unknown).missing_fields == ["exam_marks"]
    declined = _store(provider, marks=None, status="declined")
    assert declined.facts["exam_marks"].status == "declined"
    assert evaluate(declined).result == "need_more_information"


@pytest.mark.parametrize(
    ("marks", "message"),
    [
        (True, "must be a finite decimal"),
        (-0.01, "below its minimum"),
        (100.01, "above its maximum"),
        (float("nan"), "must be a finite decimal"),
        (float("inf"), "must be a finite decimal"),
    ],
)
def test_numeric_fact_rejects_malformed_values(
    tmp_path: Path,
    marks: object,
    message: str,
) -> None:
    """Numbers reject booleans, non-finite values, and out-of-range values."""

    provider, _ = _write_synthetic_bundle(tmp_path)
    with pytest.raises(ValueError, match=message):
        _store(provider, marks=marks).validate_against(provider.registry)


def test_decimal_checkpoint_roundtrip_preserves_verdict_boundary(
    tmp_path: Path,
) -> None:
    """Checkpoint/MCP wire encoding preserves exact decimal eligibility."""

    provider, package = _write_synthetic_bundle(tmp_path)
    threshold = Decimal("0.12345678901234566")
    answer = Decimal("0.12345678901234567")
    rules = [
        rule.model_copy(update={"value": threshold})
        if rule.field == "exam_marks" and rule.operator == "gte"
        else rule
        for rule in package.rules
    ]
    precision_package = package.model_copy(update={"rules": rules})
    store = HouseholdProfile(
        registry_version=provider.registry.registry_version,
        facts={
            "exam_marks": FactState(
                status="known",
                value=answer,
                definition_version="1.0.0",
                provenance="user_reported",
            ),
            "course_type": FactState(
                status="known",
                value="science",
                definition_version="1.0.0",
                provenance="user_reported",
            ),
        },
    ).validate_against(provider.registry)

    before = evaluate_registered_profile(
        package.scheme_id,
        store,
        {package.scheme_id: precision_package},
        provider.bundles,
        provider.registry,
    )
    wire = store.to_wire(provider.registry)
    assert wire["facts"]["exam_marks"]["value"] == {
        "$decimal": "0.12345678901234567"
    }
    mcp_decoded = HouseholdProfile.model_validate(wire)
    restored = HouseholdProfile.from_wire(mcp_decoded.model_dump(), provider.registry)
    after = evaluate_registered_profile(
        package.scheme_id,
        restored,
        {package.scheme_id: precision_package},
        provider.bundles,
        provider.registry,
    )

    assert before.result == after.result == "eligible"
    assert restored.value("exam_marks", provider.registry) == answer
    with pytest.raises(ValueError, match="must be a finite decimal"):
        provider.registry.get("exam_marks").validate_value(
            "0.12345678901234567"
        )
    invalid_wire = {
        **wire,
        "facts": {
            **wire["facts"],
            "exam_marks": {
                **wire["facts"]["exam_marks"],
                "value": "0.12345678901234567",
            },
        },
    }
    with pytest.raises(ValueError, match="require a numeric value"):
        HouseholdProfile.from_wire(invalid_wire, provider.registry)


def test_decimal_answer_keeps_precision_through_journey_interrupt_and_checkpoint(
    tmp_path: Path,
) -> None:
    """The actual resume path keeps only validated values in checkpoint writes."""

    provider, package = _write_synthetic_bundle(tmp_path)
    threshold = Decimal("0.12345678901234566")
    answer = "0.12345678901234567"
    precision_package = package.model_copy(update={
        "rules": [
            rule.model_copy(update={"value": threshold})
            if rule.field == "exam_marks" and rule.operator == "gte"
            else rule
            for rule in package.rules
        ]
    })
    packages = {package.scheme_id: precision_package}
    class RecordingSaver(MemorySaver):
        def __init__(self) -> None:
            super().__init__()
            self.captured_writes: list[tuple[str, object]] = []

        async def aput_writes(
            self,
            config,
            writes,
            task_id: str,
            task_path: str = "",
        ) -> None:
            self.captured_writes.extend(writes)
            await super().aput_writes(config, writes, task_id, task_path)

    checkpointer = RecordingSaver()

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id,
            store,
            packages,
            provider.bundles,
            provider.registry,
        )

    async def scenario() -> None:
        graph = build_journey_graph(
            object(),
            packages,
            eligibility_tool=evaluate,
            checkpointer=checkpointer,
            fact_registry=provider.registry,
            rule_bundles=provider.bundles,
        )
        started = await run_journey(
            graph,
            JourneyRequest(action="interview", scheme_id=package.scheme_id),
        )
        assert started.pending_fact == "exam_marks"

        course_question = await resume_journey(
            graph, started.conversation_id, answer
        )
        assert course_question.status == "awaiting_answer"
        assert course_question.pending_fact == "course_type"
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": str(started.conversation_id)}}
        )
        assert snapshot.values["typed_facts"]["facts"]["exam_marks"]["value"] == {
            "$decimal": answer
        }
        def exact_value_paths(
            value: object, path: tuple[str, ...] = ()
        ) -> list[tuple[str, ...]]:
            if isinstance(value, dict):
                return [
                    found
                    for key, nested in value.items()
                    for found in exact_value_paths(nested, (*path, str(key)))
                ]
            if isinstance(value, (list, tuple)):
                return [
                    found
                    for index, nested in enumerate(value)
                    for found in exact_value_paths(nested, (*path, str(index)))
                ]
            return [path] if value == answer else []

        assert exact_value_paths(checkpointer.captured_writes)
        assert all(
            path[-1] == "$decimal"
            for path in exact_value_paths(checkpointer.captured_writes)
        )
        resume_writes = [
            value
            for key, value in checkpointer.captured_writes
            if key == "__resume__"
        ]
        assert resume_writes
        resume_payloads = [
            item
            for value in resume_writes
            for item in (value if isinstance(value, list) else [value])
        ]
        assert all(
            item["safe_text"] == "[REDACTED_ACCOUNT]"
            for item in resume_payloads
        )
        assert all(
            item["answer"]["value"]["$decimal"] == answer
            for item in resume_payloads
        )
        persisted_without_fact = {
            key: value
            for key, value in snapshot.values.items()
            if key != "typed_facts"
        }
        assert answer not in json.dumps(
            persisted_without_fact, ensure_ascii=False
        )
        assert answer not in json.dumps(
            snapshot.values["conversation"], ensure_ascii=False
        )
        assert "[REDACTED_ACCOUNT]" in json.dumps(
            snapshot.values["conversation"], ensure_ascii=False
        )

        verdict = await resume_journey(
            graph, started.conversation_id, "science"
        )
        assert verdict.status == "eligible"
        assert verdict.eligibility_result is not None
        assert verdict.eligibility_result.result == "eligible"

    asyncio.run(scenario())


def test_dont_know_appears_in_the_chat_as_the_person_chose_it(tmp_path: Path) -> None:
    """The answer buttons send "skip"; the conversation must not show that code."""

    provider, package = _write_synthetic_bundle(tmp_path)
    packages = {package.scheme_id: package}

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id, store, packages, provider.bundles, provider.registry,
        )

    async def scenario() -> None:
        graph = build_journey_graph(
            object(),
            packages,
            eligibility_tool=evaluate,
            checkpointer=MemorySaver(),
            fact_registry=provider.registry,
            rule_bundles=provider.bundles,
        )
        started = await run_journey(
            graph, JourneyRequest(action="interview", scheme_id=package.scheme_id),
        )
        reply = await resume_journey(graph, started.conversation_id, "skip")
        said = [turn["content"] for turn in reply.conversation if turn["role"] == "user"]

        assert "I don't know" in said
        assert "skip" not in said

    asyncio.run(scenario())


def test_choice_fact_rejects_values_outside_its_finite_set(
    tmp_path: Path,
) -> None:
    """Choice answers cannot invent unregistered categories."""

    provider, _ = _write_synthetic_bundle(tmp_path)
    store = _store(provider, marks=80, course="medicine")
    with pytest.raises(ValueError, match="not a registered choice"):
        store.validate_against(provider.registry)


def test_choice_labels_cannot_alias_another_choice_code() -> None:
    """Localized aliases cannot silently resolve to a different stable code."""

    ambiguous = _fact("course_type", "choice", choices=["first", "second"])
    ambiguous["choice_labels"] = {
        "en": {"first": "Second!", "second": "The other choice"},
        "hi": {"first": "पहला", "second": "दूसरा"},
        "mr": {"first": "पहिला", "second": "दुसरा"},
    }
    with pytest.raises(
        ValidationError,
        match="unambiguous in every locale",
    ):
        FactDefinition.model_validate(ambiguous)

    valid = _fact("course_type", "choice", choices=["first", "second"])
    valid["choice_labels"] = {
        "en": {"first": "first", "second": "Second"},
        "hi": {"first": "पहला", "second": "दूसरा"},
        "mr": {"first": "पहिला", "second": "दुसरा"},
    }
    assert FactDefinition.model_validate(valid).choices == ("first", "second")


def test_choice_codes_are_unique_after_answer_normalization_without_labels() -> None:
    """Codes colliding after case, spacing, or punctuation normalization fail."""

    ambiguous = _fact(
        "course_type",
        "choice",
        choices=["first", " FIRST! "],
    )
    with pytest.raises(ValidationError, match="Choice facts require unique choices"):
        FactDefinition.model_validate(ambiguous)


def test_provider_rejects_incompatible_rule_operators(
    tmp_path: Path,
) -> None:
    """A syntactically valid rule cannot compare a choice with a number."""

    with pytest.raises(ValueError, match="Unsupported operator or value"):
        _write_synthetic_bundle(tmp_path, invalid_choice_operator=True)


def test_provider_rejects_numeric_rule_with_incompatible_unit(
    tmp_path: Path,
) -> None:
    """Thresholds must use the exact unit declared by the registered fact."""

    with pytest.raises(ValueError, match="Unsupported operator or value"):
        _write_synthetic_bundle(tmp_path, wrong_numeric_unit=True)


def test_development_only_bundle_is_not_activated_by_default(
    tmp_path: Path,
) -> None:
    """Test fixtures cannot accidentally become active catalogue packages."""

    _write_synthetic_bundle(tmp_path)
    with pytest.raises(ValueError, match="Development-only bundles"):
        RulePackageProvider(tmp_path / "packages")



def test_explicit_development_loader_accepts_pending_synthetic_bundle(
    tmp_path: Path,
) -> None:
    """A pending synthetic bundle remains available only to explicit test use."""

    _write_synthetic_bundle(tmp_path)
    with pytest.raises(ValueError, match="Development-only bundles"):
        RulePackageProvider(tmp_path / "packages")
    provider = RulePackageProvider(
        tmp_path / "packages",
        allow_development=True,
    )
    assert "SYNTHETIC-SCHOLARSHIP-TEST" in provider.packages


def test_fact_registry_rejects_duplicate_ids_and_unsupported_types() -> None:
    """Registry IDs, supported types, and code-owned derivations are strict."""

    duplicate = {
        "schema_version": "1.0",
        "registry_version": "1.0.0",
        "definitions": [
            _fact("exam_marks", "integer", minimum=0, maximum=100),
            _fact("exam_marks", "integer", minimum=0, maximum=100),
        ],
    }
    with pytest.raises(ValidationError, match="Fact registry IDs must be unique"):
        FactRegistry.model_validate(duplicate)
    with pytest.raises(ValidationError):
        FactDefinition.model_validate(_fact("exam_marks", "formula"))
    invalid_version = {
        "schema_version": "1.0",
        "registry_version": "latest",
        "definitions": [_fact("exam_marks", "integer", minimum=0, maximum=100)],
    }
    with pytest.raises(ValidationError, match="numeric semver"):
        FactRegistry.model_validate(invalid_version)


def test_wire_values_round_trip_and_reject_malformed_decimals() -> None:
    """Saved answers decode exactly, and only the strict decimal form is accepted."""

    from types import SimpleNamespace

    from src.rules.facts import decode_wire_value, encode_wire_value

    decimal_fact = SimpleNamespace(value_type="decimal")
    date_fact = SimpleNamespace(value_type="date")
    exact = Decimal("0.12345678901234567")
    assert decode_wire_value(decimal_fact, encode_wire_value(exact)) == exact
    assert decode_wire_value(date_fact, encode_wire_value(date(1981, 3, 12))) == date(1981, 3, 12)
    for malformed in ({"$decimal": "1_000"}, {"$decimal": " 1 "}, {"$decimal": "abc"}, 5):
        with pytest.raises(ValueError):
            decode_wire_value(decimal_fact, malformed)
    assert decode_wire_value(decimal_fact, 5, allow_plain_numbers=True) == Decimal("5")


def test_derived_fact_cycle_check_rejects_cycles_and_ignores_unknown_inputs() -> None:
    """The defensive cycle check catches loops; unregistered inputs are skipped."""

    from types import SimpleNamespace

    def graph(**edges: tuple[str, ...]) -> dict[str, SimpleNamespace]:
        return {fact: SimpleNamespace(derived_from=inputs) for fact, inputs in edges.items()}

    FactRegistry._validate_acyclic(graph(age=("dob", "today"), dob=(), today=()))
    FactRegistry._validate_acyclic(graph(age=("not_registered",)))
    for cyclic in (graph(a=("b",), b=("a",)), graph(a=("a",)), graph(a=("b",), b=("c",), c=("a",))):
        with pytest.raises(ValueError, match="Derived fact definitions contain a cycle"):
            FactRegistry._validate_acyclic(cyclic)


def test_provider_rejects_duplicate_json_keys_and_modified_rule_hash(
    tmp_path: Path,
) -> None:
    """Content loading rejects duplicate keys and post-manifest rule edits."""

    _write_synthetic_bundle(tmp_path)
    package_path = tmp_path / "packages" / "synthetic_scholarship.json"
    valid_package = package_path.read_bytes()
    package_path.write_text('{"scheme_id":"A","scheme_id":"B"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        RulePackageProvider(
            tmp_path / "packages",
            allow_development=True,
        )
    package_path.write_bytes(valid_package + b" ")
    with pytest.raises(ValueError, match="Rule package hash mismatch"):
        RulePackageProvider(
            tmp_path / "packages",
            allow_development=True,
        )


def test_registry_question_parser_is_strict_and_localized(
    tmp_path: Path,
) -> None:
    """Data-defined numeric and choice answers use types, bounds, and labels."""

    provider, _ = _write_synthetic_bundle(tmp_path)
    marks = provider.registry.get("exam_marks")
    course = provider.registry.get("course_type")
    enrollment = FactDefinition.model_validate(_fact("is_enrolled", "boolean"))
    score = FactDefinition.model_validate(
        _fact("score", "integer", minimum=0, maximum=100)
    )
    start_date = FactDefinition.model_validate(_fact("start_date", "date"))
    text_data = _fact("display_note", "text")
    text_data["max_length"] = 20
    text_data["display_only"] = True
    display_note = FactDefinition.model_validate(text_data)

    assert parse_registered_answer(marks, "80.25", "en").value == 80.25
    assert parse_registered_answer(marks, "100.01").kind == "invalid"
    assert "न्यूनतम" in parse_registered_answer(marks, "100.01", "hi").error
    assert "अधिकतम" in parse_registered_answer(marks, "-1", "hi").error
    assert "किमान" in parse_registered_answer(marks, "100.01", "mr").error
    assert "कमाल" in parse_registered_answer(marks, "-1", "mr").error
    assert parse_registered_answer(marks, "NaN").kind == "invalid"
    assert parse_registered_answer(marks, "8_0").kind == "invalid"
    assert parse_registered_answer(course, "विज्ञान", "hi").value == "science"
    assert parse_registered_answer(course, "law", "en").kind == "invalid"
    assert parse_registered_answer(course, " ").kind == "invalid"
    assert parse_registered_answer(course, "मुझे नहीं पता", "hi").kind == "unknown"
    assert parse_registered_answer(enrollment, "हाँ", "hi").value is True
    assert parse_registered_answer(enrollment, "maybe").kind == "invalid"
    assert parse_registered_answer(score, "81").value == 81
    assert parse_registered_answer(score, "81.0").kind == "invalid"
    assert parse_registered_answer(
        start_date, "१२/०३/२०२६", "hi"
    ).value.isoformat() == "2026-03-12"
    assert parse_registered_answer(
        display_note, "  Synthetic note!  ", "en"
    ).value == "Synthetic note!"
    assert parse_registered_answer(
        display_note, "मुझे नहीं पता", "hi"
    ).kind == "unknown"
    assert parse_registered_answer(
        display_note, "Synthetic note is too long", "en"
    ).kind == "invalid"
    assert "20" in parse_registered_answer(
        display_note, "Synthetic note is too long", "en"
    ).error
    assert registered_question_details(display_note, "en")["max_length"] == 20


@pytest.mark.parametrize("activation_state", ["development_only", "approved"])
def test_registry_questions_drive_typed_journey_and_resume(
    tmp_path: Path, activation_state: str,
) -> None:
    """A synthetic bundle asks localized registry questions and resumes typed facts.

    Runs for a development bundle and for an "approved" one: approved schemes
    use the registry question path, not the old pilot path.
    """

    approved = activation_state == "approved"
    provider, package = _write_synthetic_bundle(
        tmp_path, activation_state=activation_state,
        package_approved=approved, definitions_approved=approved,
    )
    checkpointer = MemorySaver()

    class Planner(FakeChatModel):
        model_name: str = "offline-planner"

        def __init__(self) -> None:
            super().__init__()
            self.decisions = [
                ModelDecision(
                    action="propose_plan",
                    arguments={"step_ids": ["intake", "eligibility"]},
                ),
                ModelDecision(
                    action="finish_plan",
                    arguments={"confirm": "use_validated_plan"},
                ),
            ]
            self.seen: list[str] = []

        async def choose(self, _agent, _locale, messages, _actions):
            self.seen.append(json.dumps(messages, ensure_ascii=False))
            return self.decisions.pop(0)

    model = Planner()

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id,
            store,
            provider.packages,
            provider.bundles,
            provider.registry,
        )

    async def scenario() -> None:
        graph = build_journey_graph(
            object(),
            provider.packages,
            eligibility_tool=evaluate,
            model_provider=model,
            checkpointer=checkpointer,
            fact_registry=provider.registry,
            rule_bundles=provider.bundles,
        )
        started = await run_journey(
            graph,
            JourneyRequest(
                action="interview",
                scheme_id=package.scheme_id,
                locale="hi",
            ),
        )
        assert started.status == "awaiting_answer"
        assert started.pending_fact == "exam_marks"
        assert started.question_definition is not None
        assert started.question_definition.value_type == "decimal"
        assert started.question_definition.unit == "percent"
        assert started.question_definition.minimum == 0
        assert started.question_definition.maximum == 100

        invalid = await resume_journey(
            graph, started.conversation_id, "100.01"
        )
        assert invalid.status == "awaiting_answer"
        assert invalid.pending_fact == "exam_marks"

        next_question = await resume_journey(
            graph, started.conversation_id, "80.25"
        )
        assert next_question.status == "awaiting_answer"
        assert next_question.pending_fact == "course_type"
        assert next_question.question_definition is not None
        assert [
            choice.model_dump(mode="json")
            for choice in next_question.question_definition.choices
        ] == [
            {"code": "science", "label": "विज्ञान"},
            {"code": "arts", "label": "कला"},
        ]
        refreshed = await get_journey(graph, started.conversation_id)
        assert refreshed is not None
        assert refreshed.pending_fact == "course_type"
        assert refreshed.question_definition == next_question.question_definition

        verdict = await resume_journey(
            graph, started.conversation_id, "विज्ञान"
        )
        assert verdict.status == "eligible"
        assert verdict.eligibility_result is not None
        assert verdict.eligibility_result.result == "eligible"

    asyncio.run(scenario())


def test_unknown_registry_fact_is_not_reasked_and_saved_definitions_fail_closed(
    tmp_path: Path,
) -> None:
    """Unknown stays declined, while a changed registry cannot reinterpret it."""

    provider, package = _write_synthetic_bundle(tmp_path)
    checkpointer = MemorySaver()

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id,
            store,
            provider.packages,
            provider.bundles,
            provider.registry,
        )

    async def scenario() -> None:
        graph = build_journey_graph(
            object(),
            provider.packages,
            eligibility_tool=evaluate,
            checkpointer=checkpointer,
            fact_registry=provider.registry,
            rule_bundles=provider.bundles,
        )
        started = await run_journey(
            graph,
            JourneyRequest(action="interview", scheme_id=package.scheme_id),
        )
        choice = await resume_journey(
            graph, started.conversation_id, "I don't know"
        )
        assert choice.status == "awaiting_answer"
        assert choice.pending_fact == "course_type"
        missing = await resume_journey(graph, started.conversation_id, "science")
        assert missing.status == "need_more_information"
        assert missing.eligibility_result is not None
        assert missing.eligibility_result.missing_fields == ["exam_marks"]

        changed_registry = provider.registry.model_copy(
            update={"registry_version": "2.0.0"}
        )
        changed_graph = build_journey_graph(
            object(),
            provider.packages,
            eligibility_tool=evaluate,
            checkpointer=checkpointer,
            fact_registry=changed_registry,
            rule_bundles=provider.bundles,
        )
        restarted = await run_journey(
            changed_graph,
            JourneyRequest(
                action="interview",
                scheme_id=package.scheme_id,
                conversation_id=started.conversation_id,
            ),
        )
        assert restarted.status == "invalid_input"
        assert "different fact definition" in restarted.message

    asyncio.run(scenario())


def test_registry_question_metadata_flows_through_journey_http_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API exposes dynamic widgets, answer validation, and refresh state."""

    provider, package = _write_synthetic_bundle(tmp_path)

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(
            scheme_id,
            store,
            provider.packages,
            provider.bundles,
            provider.registry,
        )

    graph = build_journey_graph(
        object(),
        provider.packages,
        eligibility_tool=evaluate,
        checkpointer=MemorySaver(),
        fact_registry=provider.registry,
        rule_bundles=provider.bundles,
    )

    @asynccontextmanager
    async def isolated_lifespan(_application):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    monkeypatch.setattr(app.state, "journey_graph", graph, raising=False)
    monkeypatch.setattr(
        app.state, "rule_packages", provider.packages, raising=False
    )
    with TestClient(app) as client:
        started = client.post(
            "/api/v1/journey",
            json={
                "action": "interview",
                "scheme_id": package.scheme_id,
                "locale": "mr",
                "profile_description": "Synthetic marks are 99.",
            },
        )
        assert started.status_code == 200
        first = started.json()
        assert first["pending_fact"] == "exam_marks"
        assert first["question_definition"]["value_type"] == "decimal"
        assert first["question_definition"]["unit"] == "percent"

        invalid = client.post(
            f"/api/v1/journey/{first['conversation_id']}/messages",
            json={"message": "101"},
        )
        assert invalid.status_code == 200
        assert invalid.json()["pending_fact"] == "exam_marks"

        next_question = client.post(
            f"/api/v1/journey/{first['conversation_id']}/messages",
            json={"message": "82.5"},
        )
        assert next_question.status_code == 200
        second = next_question.json()
        assert second["pending_fact"] == "course_type"
        assert second["question_definition"]["choices"][0] == {
            "code": "science",
            "label": "विज्ञान",
        }
        refreshed = client.get(
            f"/api/v1/journey/{first['conversation_id']}"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["question_definition"] == second[
            "question_definition"
        ]

        result = client.post(
            f"/api/v1/journey/{first['conversation_id']}/messages",
            json={"message": "विज्ञान"},
        )
        assert result.status_code == 200
        assert result.json()["status"] == "eligible"


def _write_multischeme_bundle(root: Path) -> RulePackageProvider:
    """Load two synthetic bundles from data, with shared and distinct meanings."""

    _write_synthetic_bundle(root, create_only=True)
    registry_path = root / "fact_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for fact_id, scope, period in (
        ("personal_income_2025", "person", "2025"),
        ("family_income_2026", "family", "2026"),
    ):
        definition = _fact(fact_id, "decimal", minimum=0)
        definition.update({
            "meaning": f"Synthetic {scope} income during {period}.",
            "scope": scope, "period": period, "unit": "INR",
        })
        registry["definitions"].append(definition)
    registry_bytes = json.dumps(registry).encode()
    registry_path.write_bytes(registry_bytes)
    package_path = root / "packages" / "synthetic_scholarship.json"
    first = json.loads(package_path.read_text(encoding="utf-8"))
    second = {
        **first,
        "scheme_id": "SYNTHETIC-FAMILY-TEST",
        "required_facts": ["exam_marks", "family_income_2026"],
        "rules": [first["rules"][0]],
    }
    first["required_facts"].append("personal_income_2025")
    for package, field in (
        (first, "personal_income_2025"), (second, "family_income_2026")
    ):
        package["rules"] = [*package["rules"], {
            "rule_id": f"SYNTHETIC-{field}",
            "field": field, "operator": "lte", "value": 1000, "unit": "INR",
            "source_clause_id": "SYNTHETIC-TEST-CLAUSE",
        }]
    manifest_path = root / "bundle_registry.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template = manifest["bundles"][0]
    bundles = []
    for package, filename in (
        (first, "synthetic_scholarship.json"), (second, "synthetic_family.json")
    ):
        raw = json.dumps(package).encode()
        (root / "packages" / filename).write_bytes(raw)
        bundles.append({
            **template, "scheme_id": package["scheme_id"],
            "package_file": filename, "package_sha256": hashlib.sha256(raw).hexdigest(),
            "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
            "fact_ids": package["required_facts"],
        })
    manifest_path.write_text(json.dumps({"schema_version": "1.0", "bundles": bundles}))
    return RulePackageProvider(root / "packages", allow_development=True)


def test_data_only_multischeme_discovery_sharing_and_typed_correction_through_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected search is retrieval plumbing proof, not a real corpus hit."""

    provider = _write_multischeme_bundle(tmp_path)
    candidates = [
        "SYNTHETIC-SCHOLARSHIP-TEST", "SYNTHETIC-FAMILY-TEST", "SYNTHETIC-NO-RULES"
    ]
    searches: list[str] = []
    evaluations: list[str] = []

    async def search(_client, query):
        searches.append(query)
        return [
            SchemePassage(
                passage_id=f"offline-{scheme_id}", scheme_id=scheme_id,
                scheme_name="Synthetic test only", jurisdiction="IN", language="en",
                section="Synthetic", text="Injected synthetic search result only.",
                source={"publisher": "Offline test", "url": _SOURCE_URL,
                        "collected_at": "2026-11-04"},
                review_status="pending_review",
            )
            for scheme_id in candidates
        ]

    async def evaluate(_client, scheme_id, store):
        evaluations.append(scheme_id)
        assert isinstance(store, HouseholdProfile)
        return evaluate_registered_profile(
            scheme_id, store, provider.packages, provider.bundles, provider.registry
        )

    graph = build_journey_graph(
        object(), provider.packages, eligibility_tool=evaluate, search_tool=search,
        checkpointer=MemorySaver(), fact_registry=provider.registry,
        rule_bundles=provider.bundles,
    )

    @asynccontextmanager
    async def isolated_lifespan(_application):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    monkeypatch.setattr(app.state, "journey_graph", graph, raising=False)
    monkeypatch.setattr(app.state, "rule_packages", provider.packages, raising=False)
    with TestClient(app) as client:
        found = client.post("/api/v1/journey", json={
            "action": "search", "query": "Synthetic scholarship offline fixture",
        }).json()
        assert found["candidate_scheme_ids"] == candidates
        conversation_id = found["conversation_id"]
        response = client.post("/api/v1/journey", json={
            "action": "interview", "candidate_scheme_ids": candidates,
            "conversation_id": conversation_id,
        })
        assert response.status_code == 200
        asked = []
        for expected, answer in (
            ("exam_marks", "80.25"), ("course_type", "science"),
            ("personal_income_2025", "100"), ("family_income_2026", "900"),
        ):
            body = response.json()
            assert body["pending_fact"] == expected
            asked.append(body["pending_fact"])
            response = client.post(
                f"/api/v1/journey/{conversation_id}/messages", json={"message": answer}
            )
            assert response.status_code == 200
        completed = response.json()
        assert completed["status"] == "completed"
        assert asked.count("exam_marks") == 1
        assert completed["candidate_verdicts"][candidates[0]]["result"] == "eligible"
        assert completed["candidate_verdicts"][candidates[1]]["result"] == "eligible"
        assert completed["candidate_verdicts"][candidates[2]]["result"] == "information_only"
        assert completed["correctable_fact_names"] == asked
        assert set(completed["fact_questions"]) == set(asked)
        prior_budget = completed["agent_budget"]
        invalid = client.post(f"/api/v1/journey/{conversation_id}/corrections", json={
            "fact_name": "family_income_2026", "answer": "not a number",
        })
        assert invalid.status_code == 422
        assert client.get(f"/api/v1/journey/{conversation_id}").json()["dependency_version"] == 0

        def correct(fact_id: str, answer: str) -> dict[str, object]:
            result = client.post(f"/api/v1/journey/{conversation_id}/corrections", json={
                "fact_name": fact_id, "answer": answer,
            })
            assert result.status_code == 200, result.text
            return result.json()

        changed = correct("personal_income_2025", "1000.0000000000000000001")
        assert changed["candidate_verdicts"][candidates[0]]["result"] == "not_eligible"
        assert changed["candidate_verdicts"][candidates[1]]["result"] == "eligible"
        assert changed["dependency_version"] == 1
        unknown = correct("personal_income_2025", "don't know")
        assert unknown["candidate_verdicts"][candidates[0]]["result"] == "need_more_information"
        assert unknown["candidate_verdicts"][candidates[1]]["result"] == "eligible"
        restored = correct("personal_income_2025", "100")
        choice = correct("course_type", "arts")
        assert restored["candidate_verdicts"][candidates[0]]["result"] == "eligible"
        assert choice["candidate_verdicts"][candidates[0]]["result"] == "not_eligible"
        assert choice["candidate_verdicts"][candidates[1]]["result"] == "eligible"
        assert searches == ["Synthetic scholarship offline fixture"]
        assert evaluations == candidates[:2] * 5
        for key, value in prior_budget.items():
            assert choice["agent_budget"].get(key, 0) >= value

        # A same-ID restart shares compatible answers, without another search.
        restarted = client.post("/api/v1/journey", json={
            "action": "interview", "candidate_scheme_ids": candidates,
            "conversation_id": conversation_id,
        }).json()
        assert restarted["status"] == "completed"
        assert restarted["agent_budget"]["tool_calls"] >= choice["agent_budget"]["tool_calls"]


@pytest.mark.parametrize("change", ["meaning", "scope", "period", "review", "bundle", "rule", "withdrawn"])
def test_dependency_changes_require_review_without_erasing_answers_or_restoring_a_to_b_to_a(
    tmp_path: Path, change: str,
) -> None:
    """Content and review changes refuse saved results even at the same version."""

    provider, package = _write_synthetic_bundle(tmp_path)
    saver = MemorySaver()
    evaluations = []

    async def evaluate(_client, scheme_id, store):
        evaluations.append(scheme_id)
        return evaluate_registered_profile(
            scheme_id, store, provider.packages, provider.bundles, provider.registry
        )

    def graph_for(registry, bundles, packages):
        return build_journey_graph(
            object(), packages, eligibility_tool=evaluate, checkpointer=saver,
            fact_registry=registry, rule_bundles=bundles,
        )

    async def scenario() -> None:
        original_registry = provider.registry
        if change == "review":
            definition = original_registry.get("exam_marks")
            reviewed = definition.model_copy(update={
                "definition_review_status": "approved",
                "definition_reviewer": "Synthetic metadata reviewer only",
                "definition_reviewed_at": date(2026, 11, 4),
            })
            original_registry = original_registry.model_copy(update={
                "definitions": (reviewed, *original_registry.definitions[1:])
            })
        original = graph_for(original_registry, provider.bundles, provider.packages)
        started = await run_journey(original, JourneyRequest(
            action="interview", scheme_id=package.scheme_id,
        ))
        await resume_journey(original, started.conversation_id, "80")
        completed = await resume_journey(original, started.conversation_id, "science")
        config = {"configurable": {"thread_id": str(started.conversation_id)}}
        before = (await original.aget_state(config)).values
        registry = provider.registry
        bundles = dict(provider.bundles)
        packages = dict(provider.packages)
        definition = registry.get("exam_marks")
        updates = {
            "meaning": {"meaning": "Different synthetic meaning, same ID and version"},
            "scope": {"scope": "family"},
            "period": {"period": "previous academic year"},
        }
        if change == "review":
            registry = provider.registry
        elif change in updates:
            registry = registry.model_copy(update={"definitions": (
                definition.model_copy(update=updates[change]), *registry.definitions[1:]
            )})
        elif change == "bundle":
            bundles[package.scheme_id] = bundles[package.scheme_id].model_copy(
                update={"bundle_version": "1.0.1"}
            )
        elif change == "rule":
            packages[package.scheme_id] = package.model_copy(update={
                "rules": (
                    package.rules[0].model_copy(update={"value": 90}),
                    *package.rules[1:],
                ),
            })
        else:
            packages.pop(package.scheme_id)
            bundles.pop(package.scheme_id)
        changed = graph_for(registry, bundles, packages)
        refused = await get_journey(changed, started.conversation_id)
        assert refused.status == "invalid_input"
        assert "Human review" in refused.message
        assert refused.eligibility_result is None
        assert refused.eligibility_results == refused.candidate_verdicts == {}
        assert refused.agent_budget == completed.agent_budget
        after = (await changed.aget_state(config)).values
        assert after["typed_facts"] == before["typed_facts"]
        assert after["registry_dependencies"] == before["registry_dependencies"]
        assert after["dependency_review_required"] and after["dependency_blocked"]
        assert after["dependency_version"] == 1
        # Returning to the original files is not a migration or reconfirmation.
        restored = graph_for(original_registry, provider.bundles, provider.packages)
        restarted = await run_journey(restored, JourneyRequest(
            action="interview", scheme_id=package.scheme_id,
            conversation_id=started.conversation_id,
        ))
        assert restarted.status == "invalid_input"
        assert restarted.dependency_version == 1
        assert evaluations == [package.scheme_id]
        with pytest.raises(ApplicationTaskError, match="Human review"):
            await run_application_task(
                restored, started.conversation_id, "check_documents",
                {"scheme_id": package.scheme_id, "documents": {}},
            )

    asyncio.run(scenario())


def test_typed_corrections_and_changed_definitions_revoke_real_pilot_approval_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit test injection bridges only the pilot's reviewed field mapping."""

    synthetic_root = tmp_path / "synthetic"
    synthetic_root.mkdir()
    synthetic, package = _write_synthetic_bundle(synthetic_root)
    pilots = RulePackageProvider()
    registry = FactRegistry.model_validate({
        **pilots.registry.model_dump(mode="python"),
        "definitions": (*pilots.registry.definitions, *synthetic.registry.definitions),
    })
    # Test-only composition; production activation pins and pilot files stay untouched.
    packages = {**pilots.packages, **synthetic.packages}
    bundles = {**pilots.bundles, **synthetic.bundles}
    checkpoint_path = tmp_path / "checkpoints.sqlite3"
    monkeypatch.setenv("SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "portal.sqlite3"))
    report = {
        "scheme_id": "IGNWPS-MH",
        "documents": {name: "available" for name in (
            "identity_proof", "bank_account_proof", "widow_status_proof",
        )},
    }

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(scheme_id, store, packages, bundles, registry)

    async def search(_client, _query):
        return []

    async def portal(_client, name, arguments):
        try:
            if name == "check_documents":
                return documents.assess_document_metadata(
                    arguments, registry=registry
                )
            return applications._portal_action(arguments)
        except (RuntimeError, ValueError) as error:
            raise MCPToolError("Synthetic portal rejected an unsafe transition") from error

    def graph_for(connection, active_registry=registry):
        return build_journey_graph(
            None, packages, eligibility_tool=evaluate, application_tool=portal,
            search_tool=search,
            checkpointer=AsyncSqliteSaver(connection), fact_registry=active_registry,
            rule_bundles=bundles,
        )

    async def scenario() -> None:
        async with aiosqlite.connect(checkpoint_path) as connection:
            graph = graph_for(connection)
            started = await run_journey(graph, JourneyRequest(
                action="interview", candidate_scheme_ids=["IGNWPS-MH", package.scheme_id],
                profile={
                    "date_of_birth": "1986-01-01", "application_date": "2026-01-01",
                    "is_widow": True, "bpl_card_shown": True,
                },
            ))
            assert started.pending_fact == "exam_marks"
            conversation_id = started.conversation_id
            await resume_journey(graph, conversation_id, "80")
            completed = await resume_journey(graph, conversation_id, "science")
            assert completed.candidate_verdicts["IGNWPS-MH"].result == "eligible"
            assert completed.candidate_verdicts[package.scheme_id].result == "eligible"
            draft = await run_application_task(graph, conversation_id, "create_draft", report)
            identity = {**report, **{key: draft[key] for key in (
                "draft_id", "revision", "fingerprint",
            )}}
            await run_application_task(graph, conversation_id, "approve", identity)

        async with aiosqlite.connect(checkpoint_path) as connection:
            graph = graph_for(connection)
            # A decimal correction stays eligible, but still cancels exact approvals.
            corrected = await correct_journey_answer(graph, conversation_id, JourneyCorrection(
                fact_name="exam_marks", answer="85.1234567890123456789",
            ))
            assert corrected.candidate_verdicts["IGNWPS-MH"].result == "eligible"
            assert corrected.candidate_verdicts[package.scheme_id].result == "eligible"
            old = applications._portal_action({
                "action": "get_draft", "journey_id": str(conversation_id),
                "draft_id": draft["draft_id"],
            })
            assert old["stale"] and not old["approved"]
            dated = await correct_journey_answer(graph, conversation_id, JourneyCorrection(
                fact_name="date_of_birth", answer="1985-01-01",
            ))
            assert dated.candidate_verdicts["IGNWPS-MH"].result == "eligible"
            assert dated.dependency_version == 2
            fresh = await run_application_task(graph, conversation_id, "create_draft", report)
            fresh_identity = {**report, **{key: fresh[key] for key in (
                "draft_id", "revision", "fingerprint",
            )}}
            await run_application_task(graph, conversation_id, "approve", fresh_identity)

        changed_registry = registry.model_copy(update={"definitions": tuple(
            definition.model_copy(update={"scope": "family"})
            if definition.fact_id == "exam_marks" else definition
            for definition in registry.definitions
        )})
        async with aiosqlite.connect(checkpoint_path) as connection:
            changed = graph_for(connection, changed_registry)
            refused = await get_journey(changed, conversation_id)
            assert refused.status == "invalid_input"
            assert refused.dependency_version == 3
            old = applications._portal_action({
                "action": "get_draft", "journey_id": str(conversation_id),
                "draft_id": fresh["draft_id"],
            })
            assert old["stale"] and not old["approved"]
        async with aiosqlite.connect(checkpoint_path) as connection:
            restored = graph_for(connection)
            with pytest.raises(ApplicationTaskError, match="Human review"):
                await run_application_task(restored, conversation_id, "submit", fresh_identity)
            response = await get_journey(restored, conversation_id)
            assert response.status == "invalid_input"
            assert response.dependency_version == 3

    asyncio.run(scenario())


def _write_mapped_development_bundle(root: Path) -> RulePackageProvider:
    """Load a novel flag plus an explicit legacy bridge without compatibility pins."""

    _write_synthetic_bundle(root, create_only=True)
    widow = _fact("is_widow", "boolean")
    registry_bytes = json.dumps({
        "schema_version": "1.0", "registry_version": "1.0.0",
        "definitions": [widow, _fact("synthetic_flag", "boolean")],
    }).encode()
    (root / "fact_registry.json").write_bytes(registry_bytes)
    package_path = root / "packages" / "synthetic_scholarship.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["required_facts"] = ["is_widow", "synthetic_flag"]
    package["rules"] = [{
        "rule_id": f"SYNTHETIC-{field}", "field": field, "operator": "eq",
        "value": True, "source_clause_id": "SYNTHETIC-TEST-CLAUSE",
    } for field in package["required_facts"]]
    package_bytes = json.dumps(package).encode()
    package_path.write_bytes(package_bytes)
    manifest_path = root / "bundle_registry.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundles"][0].update({
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "fact_ids": package["required_facts"],
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return RulePackageProvider(root / "packages", allow_development=True)


def test_development_bundle_with_legacy_bridge_still_asks_and_corrects_novel_fact(
    tmp_path: Path,
) -> None:
    """A mapping is an adapter, not permission to select fixed-profile intake."""

    provider = _write_mapped_development_bundle(tmp_path)
    scheme_id = next(iter(provider.packages))
    seen = []

    async def evaluate(_client, candidate, store):
        assert isinstance(store, HouseholdProfile)
        seen.append(store.to_wire(provider.registry))
        return evaluate_registered_profile(
            candidate, store, provider.packages, provider.bundles, provider.registry
        )

    async def scenario() -> None:
        graph = build_journey_graph(
            object(), provider.packages, eligibility_tool=evaluate,
            checkpointer=MemorySaver(), fact_registry=provider.registry,
            rule_bundles=provider.bundles,
        )
        started = await run_journey(graph, JourneyRequest(
            action="interview", scheme_id=scheme_id,
        ))
        assert started.pending_fact == "is_widow"
        assert started.question_definition.value_type == "boolean"
        flag = await resume_journey(graph, started.conversation_id, "yes")
        assert flag.pending_fact == "synthetic_flag"
        assert flag.question_definition.value_type == "boolean"
        completed = await resume_journey(graph, started.conversation_id, "yes")
        assert completed.status == "eligible"
        changed = await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
            fact_name="synthetic_flag", answer="no",
        ))
        assert changed.status == "not_eligible"
        assert seen[-1]["facts"]["synthetic_flag"]["value"] is False
        restored = await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
            fact_name="synthetic_flag", answer="yes",
        ))
        assert restored.status == "eligible"
        unknown = await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
            fact_name="is_widow", answer="don't know",
        ))
        assert unknown.status == "need_more_information"
        assert unknown.dependency_version == 3

    asyncio.run(scenario())


@pytest.mark.parametrize(("seed", "pending", "invalid", "valid"), [
    # The application date is no longer asked, so only date of birth can be pending.
    ({"application_date": "2026-01-01"}, "date_of_birth", "1800-01-01", "1986-01-01"),
])
def test_combined_date_answer_reasks_safely_and_invalid_correction_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    seed: dict[str, str], pending: str, invalid: str, valid: str,
) -> None:
    """Invalid cross-fact age must not consume the only usable interview pause."""

    synthetic, package = _write_synthetic_bundle(tmp_path)
    pilots = RulePackageProvider()
    registry = FactRegistry.model_validate({
        **pilots.registry.model_dump(mode="python"),
        "definitions": (*pilots.registry.definitions, *synthetic.registry.definitions),
    })
    packages = {**pilots.packages, **synthetic.packages}
    bundles = {**pilots.bundles, **synthetic.bundles}
    saver = MemorySaver()
    seen = []

    async def evaluate(_client, scheme_id, store):
        seen.append(store.to_wire(registry))
        return evaluate_registered_profile(scheme_id, store, packages, bundles, registry)

    async def search(_client, _query):
        return []

    graph = build_journey_graph(
        object(), packages, eligibility_tool=evaluate, search_tool=search,
        checkpointer=saver, fact_registry=registry, rule_bundles=bundles,
    )

    @asynccontextmanager
    async def isolated_lifespan(_application):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    monkeypatch.setattr(app.state, "journey_graph", graph, raising=False)
    monkeypatch.setattr(app.state, "rule_packages", packages, raising=False)
    with TestClient(app) as client:
        started = client.post("/api/v1/journey", json={
            "action": "interview",
            "candidate_scheme_ids": ["IGNWPS-MH", package.scheme_id],
            "profile": {**seed, "is_widow": True, "bpl_card_shown": True},
        }).json()
        conversation_id = started["conversation_id"]
        assert started["pending_fact"] == pending
        rejected = client.post(
            f"/api/v1/journey/{conversation_id}/messages", json={"message": invalid},
        )
        assert rejected.status_code == 200
        rejected = rejected.json()
        assert rejected["status"] == "awaiting_answer"
        assert rejected["pending_fact"] == pending
        assert rejected["question_definition"]["value_type"] == "date"
        snapshot = graph.get_state({"configurable": {"thread_id": conversation_id}})
        assert snapshot.interrupts
        assert pending not in snapshot.values["typed_facts"]["facts"]
        assert snapshot.values["pending_registered_answer"] is None
        assert rejected["agent_budget"] == started["agent_budget"]
        retried = client.post(
            f"/api/v1/journey/{conversation_id}/messages", json={"message": valid},
        )
        assert retried.status_code == 200
        assert retried.json()["pending_fact"] == "exam_marks"
        client.post(f"/api/v1/journey/{conversation_id}/messages", json={"message": "80"})
        completed = client.post(
            f"/api/v1/journey/{conversation_id}/messages", json={"message": "science"}
        ).json()
        assert completed["status"] == "completed"
        before = graph.get_state({"configurable": {"thread_id": conversation_id}}).values
        bad_correction = client.post(
            f"/api/v1/journey/{conversation_id}/corrections",
            json={"fact_name": pending, "answer": invalid},
        )
        assert bad_correction.status_code == 422
        after = graph.get_state({"configurable": {"thread_id": conversation_id}}).values
        assert after["typed_facts"] == before["typed_facts"]
        assert after["dependency_version"] == before["dependency_version"] == 0
        assert after["agent_budget"] == before["agent_budget"]
        corrected = client.post(
            f"/api/v1/journey/{conversation_id}/corrections",
            json={"fact_name": pending, "answer": valid},
        )
        assert corrected.status_code == 200
        assert corrected.json()["status"] == "completed"
        assert corrected.json()["dependency_version"] == 1
        assert seen


@pytest.mark.parametrize("registry_candidate", ["absent", "initial", "discovered"])
def test_registry_and_legacy_intake_share_bounded_confirmed_fact_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry_candidate: str,
) -> None:
    """Adding a typed bundle cannot skip discovery or invent retrieval filters."""

    synthetic, package = _write_synthetic_bundle(tmp_path)
    pilots = RulePackageProvider()
    registry = FactRegistry.model_validate({
        **pilots.registry.model_dump(mode="python"),
        "definitions": (*pilots.registry.definitions, *synthetic.registry.definitions),
    })
    packages = {**pilots.packages, **synthetic.packages}
    bundles = {**pilots.bundles, **synthetic.bundles}
    saver = MemorySaver()
    searches = []
    profile = {
        "date_of_birth": "1986-01-01", "application_date": "2026-01-01",
        "is_widow": True, "bpl_card_shown": True,
    }

    async def search(_client, query, **arguments):
        searches.append((query, arguments))
        ids = ["SYNTHETIC-INFORMATION-ONLY"]
        if registry_candidate == "discovered":
            ids.insert(0, package.scheme_id)
        return [SchemePassage(
            passage_id=f"injected-{scheme_id}", scheme_id=scheme_id,
            scheme_name="Injected offline synthetic result", jurisdiction="IN",
            language="en", section="Synthetic", text="Fake search result only.",
            source={"publisher": "Offline fixture", "url": _SOURCE_URL,
                    "collected_at": "2026-11-04"},
            review_status="pending_review",
        ) for scheme_id in ids]

    async def evaluate(_client, scheme_id, store):
        return evaluate_registered_profile(scheme_id, store, packages, bundles, registry)

    monkeypatch.setattr("src.workflow.journey.search_scheme_passages", search)

    def graph_for():
        return build_journey_graph(
            object(), packages, eligibility_tool=evaluate, checkpointer=saver,
            fact_registry=registry, rule_bundles=bundles,
        )

    async def scenario() -> None:
        graph = graph_for()
        candidates = ["IGNWPS-MH"]
        if registry_candidate == "initial":
            candidates.append(package.scheme_id)
        started = await run_journey(graph, JourneyRequest(
            action="interview", candidate_scheme_ids=candidates, profile=profile,
            locale="mr", profile_description="Synthetic household seeking support.",
        ))
        assert searches == [("widow pension age 40", {"language": "mr", "limit": 20})]
        assert started.search_calls == 1
        assert "SYNTHETIC-INFORMATION-ONLY" in started.candidate_scheme_ids
        if registry_candidate != "absent":
            assert started.pending_fact == "exam_marks"
            assert package.scheme_id in started.candidate_scheme_ids
            await resume_journey(graph, started.conversation_id, "80")
            completed = await resume_journey(graph, started.conversation_id, "science")
        else:
            completed = started
        assert completed.candidate_verdicts["SYNTHETIC-INFORMATION-ONLY"].result == "information_only"
        assert completed.status == "completed"
        assert len(searches) == 1
        # A fact unrelated to supported retrieval hints must not trigger a call.
        unrelated = "course_type" if registry_candidate != "absent" else "bpl_card_shown"
        await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
            fact_name=unrelated, answer="science" if unrelated == "course_type" else "yes",
        ))
        assert len(searches) == 1
        for year in (1985, 1984, 1983):
            corrected = await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
                fact_name="date_of_birth", answer=f"{year}-01-01",
            ))
        assert len(searches) == corrected.search_calls == 4
        assert searches[-1] == ("widow pension age 43", {"language": "mr", "limit": 20})
        # Rebuild the graph and restart the request without refunding attempts.
        graph = graph_for()
        snapshot = await graph.aget_state({
            "configurable": {"thread_id": str(started.conversation_id)}
        })
        restarted = await run_journey(graph, JourneyRequest(
            action="interview", candidate_scheme_ids=corrected.candidate_scheme_ids,
            conversation_id=started.conversation_id,
            profile=snapshot.values["profile"], locale="mr",
        ))
        assert restarted.search_calls == 4
        exhausted = await correct_journey_answer(graph, started.conversation_id, JourneyCorrection(
            fact_name="date_of_birth", answer="1982-01-01",
        ))
        assert exhausted.status == "completed"
        assert exhausted.search_calls == len(searches) == 4
        assert "budget_exhausted" in exhausted.discovery_notices
        assert exhausted.candidate_verdicts["IGNWPS-MH"].result == "eligible"

    asyncio.run(scenario())


def test_every_registry_question_is_readable_in_every_language():
    """Broken encoding once saved Hindi and Marathi questions as "???"."""

    registry = json.loads(
        (Path(__file__).resolve().parents[1] / "src" / "rules" / "fact_registry.json")
        .read_text(encoding="utf-8")
    )
    for fact in registry["definitions"]:
        for locale, question in fact.get("questions", {}).items():
            assert "??" not in question["text"], (fact["fact_id"], locale)


def test_pmkmdy_historical_land_record_fact_is_separate_and_mock_scoped():
    root = Path(__file__).resolve().parents[1]
    registry = FactRegistry.model_validate_json(
        (root / "src" / "rules" / "fact_registry.json").read_bytes()
    )
    fact = registry.get("applicant_name_in_land_records_on_2019_08_01")
    gold = json.loads(
        (
            root / "data" / "schemes" / "rule_gold_evaluation" / "pmkmdy.json"
        ).read_text(encoding="utf-8")
    )
    rule = next(item for item in gold["rules"] if item["rule_id"] == "PMKMDY-IN-R09")

    assert fact.scope == "person"
    assert fact.value_type == "boolean"
    assert fact.period == "as_of:2019-08-01"
    assert fact.privacy.policy_id == "synthetic-mock-minimum-data"
    assert fact.privacy.sensitivity == "sensitive"
    assert rule["field"] == fact.fact_id
    assert rule["source_passage_id"] == "PMKMDY-IN-ELIGIBILITY-04"
    _validate_rule(
        Rule(
            rule_id=rule["rule_id"],
            field=rule["field"],
            operator=rule["operator"],
            value=rule["value"],
            source_clause_id=rule["source_passage_id"],
        ),
        registry,
    )


def test_every_packaged_rule_carries_its_exact_source_clause():
    """Every rule records its official text, where it is, and the fact's unit.

    IGNWPS once kept its one eligibility sentence only at package level, while
    PM-KISAN kept text on each rule; the evidence panel then showed an internal
    clause ID as the location. Rule-extraction cases are also built per rule.
    """

    package_dir = Path(__file__).resolve().parents[1] / "src" / "rules" / "packages"
    registry = FactRegistry.model_validate_json(
        (package_dir.parent / "fact_registry.json").read_bytes()
    )
    packages = sorted(package_dir.glob("*.json"))
    assert packages
    for path in packages:
        package = RulePackage.model_validate_json(path.read_bytes())
        for rule in package.rules:
            assert rule.source_text and rule.source_text.strip(), (path.name, rule.rule_id)
            assert rule.source_location and rule.source_location.strip(), (path.name, rule.rule_id)
            # IGNWPS age rules once had no unit and relied on a legacy exception.
            # As in the loader, units count only for number facts; a yes/no
            # fact may describe an amount ("pension of at least Rs 10,000").
            definition = registry.get(rule.field)
            numeric = definition.value_type in {"integer", "decimal"}
            expected_unit = definition.unit if numeric else None
            assert rule.unit == expected_unit, (path.name, rule.rule_id)


# --- "approved" activation: a reviewed new scheme goes live through its records ---


def test_approved_bundle_goes_live_when_package_and_definitions_are_approved(
    tmp_path: Path,
) -> None:
    """The default (live) loader accepts it; questions and privacy may be pending."""
    _write_synthetic_bundle(
        tmp_path, activation_state="approved", create_only=True,
        package_approved=True, definitions_approved=True,
    )

    provider = RulePackageProvider(tmp_path / "packages")

    assert "SYNTHETIC-SCHOLARSHIP-TEST" in provider.packages
    assert provider.bundles["SYNTHETIC-SCHOLARSHIP-TEST"].activation_state == "approved"




def test_development_only_bundle_is_still_refused_even_when_approved_records_exist(
    tmp_path: Path,
) -> None:
    """Approved records do not turn a development bundle on; only the state does."""
    _write_synthetic_bundle(
        tmp_path, activation_state="development_only", create_only=True,
        package_approved=True, definitions_approved=True,
    )

    with pytest.raises(ValueError, match="Development-only bundles"):
        RulePackageProvider(tmp_path / "packages")
