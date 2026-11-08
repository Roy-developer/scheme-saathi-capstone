"""Verify strict shared checklist loading and fail-closed trust decisions."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.documents import checklists
from src.documents import publication
from src.documents.forms import MockFormField, MockFormMapping, MockFormSnapshot
from src.mcp_servers.tools.documents import assess_document_metadata
from src.portal import repository as portal_repository
from src.api.applications import document_input_fingerprint
from src.rules.bundles import SchemeBundle
from src.mcp_servers.rule_data import get_active_rule_data as _ORIGINAL_ACTIVE_RULE_DATA


@pytest.fixture(autouse=True)
def _synthetic_document_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicitly authorize the existing synthetic checklist fixture's pilot facts."""

    from src.mcp_servers import rule_data
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    bundle = provider.get_bundle("IGNWPS-MH").model_copy(update={
        "scheme_id": "TEST-SCHEME", "activation_state": "development_only",
    })

    def get_bundle(scheme_id: str) -> SchemeBundle:
        return bundle if scheme_id == "TEST-SCHEME" else provider.get_bundle(scheme_id)

    monkeypatch.setattr(rule_data, "get_active_rule_data", lambda: SimpleNamespace(
        registry=provider.registry, get_bundle=get_bundle,
    ))


@pytest.mark.parametrize("fact_id", ["excluded_government_employee_member", "exam_marks"])
def test_mock_form_rejects_facts_outside_actual_scheme_bundle(fact_id: str) -> None:
    """Global or multi-scheme facts do not authorize a scheme's form mapping."""

    from src.documents.forms import build_form_fields
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    mapping = MockFormMapping.model_validate({
        "schema_version": 1, "scheme_id": "IGNWPS-MH",
        "form_version": "1.0.0", "status": "demo_only",
        "fields": ({
            "field_id": "additional_fact", "fact_id": fact_id,
            "labels": {"en": "Test", "hi": "परीक्षण", "mr": "चाचणी"},
            "value_type": "boolean", "required": True,
        },),
    })
    with pytest.raises(ValueError, match="outside"):
        mapping.validate_registry(provider.registry)
    with pytest.raises(ValueError, match="outside"):
        build_form_fields(
            MockFormSnapshot(
                scheme_id=mapping.scheme_id, mapping=mapping,
                fingerprint="a" * 64, notice="Synthetic only",
            ),
            provider.registry, {fact_id: True},
        )


def test_checklist_rejects_global_fact_and_loader_cannot_bypass_scope() -> None:
    """Read-time validation rejects a valid global ID excluded from the bundle."""

    from src.documents.checklists import DocumentChecklist, _snapshot_from_bytes
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    payload = json.loads((
        Path(__file__).parents[1] / "data" / "schemes" /
        "document_checklists" / "IGNWPS-MH.json"
    ).read_text(encoding="utf-8"))
    payload["requirements"][0]["condition"] = {
        "kind": "registered_fact", "fact_id": "excluded_government_employee_member",
        "operator": "eq", "value": True,
    }
    raw = json.dumps(payload).encode()
    with pytest.raises(ValueError, match="outside"):
        DocumentChecklist.model_validate_json(raw).validate_registry(provider.registry)
    snapshot = _snapshot_from_bytes("IGNWPS-MH", raw, b"{}", 0)
    assert snapshot.checklist is None


def test_additional_fact_mapping_requires_explicit_bundle_membership_and_version() -> None:
    """An explicit development bundle can authorize an extra registered fact."""

    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider(
        Path(__file__).parent / "fixtures" / "phase4" / "packages",
        allow_development=True,
    )
    fact_id = "guardian_consent"
    mapping = MockFormMapping.model_validate({
        "schema_version": 1, "scheme_id": "TEST-SCHOLARSHIP",
        "form_version": "1.0.0", "status": "demo_only",
        "fields": ({
            "field_id": "additional_fact", "fact_id": fact_id,
            "labels": {"en": "Test", "hi": "परीक्षण", "mr": "चाचणी"},
            "value_type": "boolean", "required": True,
        },),
    })
    development = provider.get_bundle("TEST-SCHOLARSHIP")
    mapping.validate_registry(provider.registry, development)
    with pytest.raises(ValueError, match="outside"):
        mapping.validate_registry(provider.registry, development.model_copy(update={
            "fact_ids": tuple(item for item in development.fact_ids if item != fact_id),
        }))
    with pytest.raises(ValueError, match="incompatible"):
        mapping.validate_registry(
            provider.registry,
            development.model_copy(update={"registry_version": "99.0.0"}),
        )
    with pytest.raises(ValueError, match="incompatible"):
        mapping.validate_registry(provider.registry, development.model_copy(update={
            "scheme_id": "OTHER-SCHEME",
        }))


def test_out_of_bundle_form_is_rejected_by_loader_and_publication(tmp_path: Path) -> None:
    """Neither a file load nor supported publication can grant another scheme's fact."""

    from src.documents.forms import load_mock_form_snapshot, publish_mock_form_file
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    mapping = MockFormMapping.model_validate({
        "schema_version": 1, "scheme_id": "IGNWPS-MH",
        "form_version": "1.0.0", "status": "demo_only",
        "fields": ({
            "field_id": "additional_fact",
            "fact_id": "excluded_government_employee_member",
            "labels": {"en": "Test", "hi": "परीक्षण", "mr": "चाचणी"},
            "value_type": "boolean", "required": True,
        },),
    })
    content = mapping.model_dump_json().encode()
    forms = tmp_path / "mock_forms"
    forms.mkdir()
    target = forms / "IGNWPS-MH.json"
    target.write_bytes(content)
    assert load_mock_form_snapshot(
        "IGNWPS-MH", provider.registry, form_directory=forms,
    ).mapping is None
    with pytest.raises(ValueError, match="schema"):
        publish_mock_form_file(target.name, content, form_directory=forms)
    assert not (tmp_path / publication.REVISION_FILENAME).exists()


def test_forged_checklist_cannot_bypass_mcp_portal_or_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Snapshots and multi-scheme facts remain subject to the actual pilot allowlist."""

    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    original = checklists.load_checklist_snapshot("IGNWPS-MH")
    payload = original.checklist.model_dump(mode="json")
    payload["requirements"][0]["condition"] = {
        "kind": "registered_fact", "fact_id": "excluded_government_employee_member",
        "operator": "eq", "value": True,
    }
    forged = original.model_copy(update={
        "checklist": checklists.DocumentChecklist.model_validate(payload),
    })
    with pytest.raises(ValueError, match="outside"):
        assess_document_metadata({
            "scheme_id": "IGNWPS-MH",
            "profile_facts": {"excluded_government_employee_member": True},
        }, snapshot=forged, registry=provider.registry)
    monkeypatch.setattr(portal_repository, "load_checklist_snapshot", lambda _: forged)
    current = portal_repository._load_current_checklist("IGNWPS-MH")
    assert current.checklist is None
    assert current.trust_status == "requirements_unverified"
    with pytest.raises(ValueError, match="invalid"):
        publication.publish_checklist_file(
            "IGNWPS-MH.json", _encoded(payload),
            checklist_directory=tmp_path / "document_checklists",
            evidence_file=tmp_path / "document_evidence.json",
        )
    assert not (tmp_path / publication.REVISION_FILENAME).exists()


@pytest.mark.parametrize("document_kind", ["mock_forms", "document_checklists"])
def test_startup_rejects_out_of_bundle_document_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, document_kind: str,
) -> None:
    """A configured document mapping fails readiness rather than entering a catalogue."""

    from src.mcp_servers import rule_data
    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    directory = tmp_path / document_kind
    directory.mkdir()
    payload = json.loads((
        Path(__file__).parents[1] / "data" / "schemes" /
        document_kind / "IGNWPS-MH.json"
    ).read_text(encoding="utf-8"))
    if document_kind == "mock_forms":
        payload["fields"][0].update({
            "fact_id": "excluded_government_employee_member", "value_type": "boolean",
            "extra_input": False, "max_length": None,
        })
    else:
        payload["requirements"][0]["condition"] = {
            "kind": "registered_fact", "fact_id": "excluded_government_employee_member",
            "operator": "eq", "value": True,
        }
    (directory / "IGNWPS-MH.json").write_bytes(_encoded(payload))
    monkeypatch.setattr(rule_data, "test_scheme_data_directory", lambda: tmp_path)
    monkeypatch.setattr(rule_data, "test_rule_package_directory", lambda: None)
    monkeypatch.setattr(rule_data, "RulePackageProvider", lambda: provider)
    # The autouse synthetic provider is only for fixtures; exercise real startup.
    startup = _ORIGINAL_ACTIVE_RULE_DATA.__wrapped__
    with pytest.raises(ValueError, match="incompatible"):
        startup()


def test_caller_registry_cannot_replace_active_bundle_fact_definitions() -> None:
    """Keeping the registry version does not authorize a changed fact definition."""

    from src.rules.data_provider import RulePackageProvider

    provider = RulePackageProvider()
    bundle = provider.get_bundle("IGNWPS-MH")
    definition = next(
        item for item in provider.registry.definitions
        if item.value_type == "boolean" and item.fact_id in bundle.fact_ids
    )
    mapping = MockFormMapping.model_validate({
        "schema_version": 1, "scheme_id": bundle.scheme_id,
        "form_version": "1.0.0", "status": "demo_only",
        "fields": ({
            "field_id": "confirmed_fact", "fact_id": definition.fact_id,
            "labels": {"en": "Test", "hi": "परीक्षण", "mr": "चाचणी"},
            "value_type": "boolean", "required": True,
        },),
    })
    registry = provider.registry.model_copy(update={
        "definitions": tuple(
            item.model_copy(update={"version": "99.0.0"})
            if item.fact_id == definition.fact_id else item
            for item in provider.registry.definitions
        ),
    })
    with pytest.raises(ValueError, match="incompatible.*definition"):
        mapping.validate_registry(registry)


@pytest.mark.parametrize(
    ("application_date", "expected_age", "applicable"),
    [("2026-11-04", 55, False), ("2026-11-05", 56, True), (None, None, None)],
)
def test_derived_age_condition_and_form_use_confirmed_date_inputs(
    application_date: str | None, expected_age: int | None, applicable: bool | None,
) -> None:
    """Date boundaries and missing dependencies agree across document and form paths."""

    from src.api.app import _confirmed_form_values
    from src.documents.forms import build_form_fields
    from src.rules.data_provider import RulePackageProvider
    from src.rules.facts import TypedFactStore
    from starlette.requests import Request

    provider = RulePackageProvider()
    registry = provider.registry
    bundle = provider.get_bundle("IGNWPS-MH")
    raw = {"date_of_birth": "1970-11-05"}
    if application_date is not None:
        raw["application_date"] = application_date
    wire = {
        "registry_version": registry.registry_version,
        "facts": {
            fact_id: {
                "status": "known", "value": value,
                "definition_version": registry.get(fact_id).version,
                "provenance": "user_reported",
            }
            for fact_id, value in raw.items()
        },
    }
    store = TypedFactStore.from_wire(wire, registry)
    assert store.value("age", registry) == expected_age
    original = checklists.load_checklist_snapshot("IGNWPS-MH")
    payload = original.checklist.model_dump(mode="json")
    payload["requirements"][0]["condition"] = {
        "kind": "registered_fact", "fact_id": "age", "operator": "gte", "value": 56,
    }
    snapshot = original.model_copy(update={
        "checklist": checklists.DocumentChecklist.model_validate(payload),
    })
    report = assess_document_metadata(
        {"scheme_id": bundle.scheme_id, "typed_facts": wire},
        snapshot=snapshot, registry=registry, bundle=bundle,
    )
    assert report["groups"][0]["applicable"] is applicable
    if expected_age is None:
        assert report["groups"][0]["status"] == "unknown"

    mapping = MockFormMapping.model_validate({
        "schema_version": 1, "scheme_id": bundle.scheme_id,
        "form_version": "1.0.0", "status": "demo_only",
        "fields": ({
            "field_id": "confirmed_age", "fact_id": "age",
            "labels": {"en": "Age", "hi": "आयु", "mr": "वय"},
            "value_type": "integer", "required": True,
        },),
    })
    form = MockFormSnapshot(
        scheme_id=bundle.scheme_id, mapping=mapping, fingerprint="a" * 64,
        notice="Synthetic only",
    )
    fields, missing = build_form_fields(
        form, registry, {}, bundle=bundle, typed_store=store,
    )
    assert fields == ({} if expected_age is None else {"confirmed_age": expected_age})
    assert missing == (["confirmed_age"] if expected_age is None else [])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("src.api.app.load_mock_form_snapshot", lambda *a, **k: form)
        request = Request({
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(
                fact_registry=registry, rule_bundles={bundle.scheme_id: bundle},
            )),
        })
        _, preview = _confirmed_form_values(request, bundle.scheme_id, wire)
        assert preview["missing_fields"] == missing
        assert preview["fields"][0]["value"] == expected_age
    with pytest.raises(ValueError, match="confirmed typed"):
        build_form_fields(form, registry, {"age": 56}, bundle=bundle)
    injected = copy.deepcopy(wire)
    injected["facts"]["age"] = {
        "status": "known", "value": 56, "definition_version": registry.get("age").version,
        "provenance": "user_reported",
    }
    with pytest.raises(ValueError, match="cannot be supplied"):
        assess_document_metadata(
            {"scheme_id": bundle.scheme_id, "typed_facts": injected},
            snapshot=snapshot, registry=registry, bundle=bundle,
        )
    with pytest.raises(ValueError, match="directly"):
        assess_document_metadata(
            {"scheme_id": bundle.scheme_id, "profile_facts": {"age": 56}},
            snapshot=snapshot, registry=registry, bundle=bundle,
        )


def test_derived_document_fact_requires_authorized_dependency_closure() -> None:
    """Derivation cannot reach a globally registered dependency excluded by the bundle."""

    from src.rules.bundles import document_fact_values
    from src.rules.data_provider import RulePackageProvider
    from src.rules.facts import TypedFactStore

    provider = RulePackageProvider()
    bundle = provider.get_bundle("IGNWPS-MH")
    store = TypedFactStore.from_wire({
        "registry_version": provider.registry.registry_version,
        "facts": {
            fact_id: {
                "status": "known", "value": value,
                "definition_version": provider.registry.get(fact_id).version,
                "provenance": "user_reported",
            }
            for fact_id, value in {
                "date_of_birth": "1970-11-05", "application_date": "2026-11-05",
                "excluded_government_employee_member": True,
            }.items()
        },
    }, provider.registry)
    values = document_fact_values(bundle.scheme_id, provider.registry, store, bundle)
    assert values["age"] == 56
    assert "excluded_government_employee_member" not in values
    incomplete = bundle.model_copy(update={
        "fact_ids": tuple(fact_id for fact_id in bundle.fact_ids
                          if fact_id != "application_date"),
    })
    with pytest.raises(ValueError, match="dependencies.*outside"):
        document_fact_values(bundle.scheme_id, provider.registry, store, incomplete)


def _encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _approved_fixture() -> tuple[dict, dict]:
    """Build synthetic source records; these are not scheme evidence."""

    evidence = {
        "schema_version": 1,
        "passages": [
            {
                "passage_id": "SYNTH-IDENTITY",
                "scheme_id": "TEST-SCHEME",
                "section": "documents",
                "exact_quote": "Synthetic identity evidence wording.",
                "source_url": "https://example.test/synthetic",
                "source_locator": "Synthetic page, heading 1",
                "language": "en",
                "collected_on": "2026-11-04",
                "publication_date": None,
                "review_status": "reviewed",
            },
            {
                "passage_id": "SYNTH-CONDITION",
                "scheme_id": "TEST-SCHEME",
                "section": "documents",
                "exact_quote": "Synthetic conditional evidence wording.",
                "source_url": "https://example.test/synthetic",
                "source_locator": "Synthetic page, heading 2",
                "language": "en",
                "collected_on": "2026-11-04",
                "publication_date": None,
                "review_status": "reviewed",
            },
        ],
    }
    checklist = {
        "schema_version": 1,
        "scheme_id": "TEST-SCHEME",
        "checklist_version": "v1",
        "requirements": [
            {
                "requirement_id": "identity_group",
                "labels": {"en": "Identity", "hi": "पहचान", "mr": "ओळख"},
                "alternatives": [
                    {
                        "document_id": "identity_a",
                        "labels": {"en": "Identity A", "hi": "पहचान A", "mr": "ओळख A"},
                    },
                    {
                        "document_id": "identity_b",
                        "labels": {"en": "Identity B", "hi": "पहचान B", "mr": "ओळख B"},
                    },
                ],
                "condition": {"kind": "unconditional"},
                "evidence_passage_ids": ["SYNTH-IDENTITY"],
            },
            {
                "requirement_id": "conditional_group",
                "labels": {"en": "Conditional", "hi": "शर्त", "mr": "अट"},
                "alternatives": [
                    {
                        "document_id": "conditional_doc",
                        "labels": {"en": "Conditional item", "hi": "शर्त मद", "mr": "अट बाब"},
                    },
                ],
                "condition": {
                    "kind": "profile_boolean",
                    "field": "is_widow",
                    "equals": True,
                },
                "evidence_passage_ids": ["SYNTH-CONDITION"],
            },
        ],
        "approval": {
            "status": "approved",
            "checklist_version": "v1",
            "reviewer_role": "synthetic human reviewer",
            "review_reference": "SYNTHETIC-REVIEW-1",
            "reviewed_on": "2026-11-04",
        },
    }
    checklist["approval"]["checklist_content_sha256"] = checklists._canonical_digest(
        {key: value for key, value in checklist.items() if key != "approval"}
    )
    checklist["approval"]["evidence_content_sha256"] = hashlib.sha256(
        _encoded(evidence)
    ).hexdigest()
    return checklist, evidence


def _install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    checklist: dict | None,
    evidence: dict | None,
):
    """Serve synthetic JSON bytes to the real file loader without filesystem writes."""

    content = {}
    if checklist is not None:
        content["TEST-SCHEME.json"] = _encoded(checklist)
    if evidence is not None:
        content["document_evidence.json"] = _encoded(evidence)

    def read_bytes(path: Path) -> bytes | None:
        return content.get(path.name)

    monkeypatch.setattr(checklists, "_load_bytes", read_bytes)
    return checklists.load_checklist_snapshot(
        "TEST-SCHEME",
        checklist_directory=checklists.CHECKLIST_DIRECTORY,
        evidence_file=checklists.EVIDENCE_FILE,
    )


def test_approved_shared_checklist_preserves_any_one_and_condition_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checklist, evidence = _approved_fixture()
    snapshot = _install_fixture(monkeypatch, checklist, evidence)

    result = assess_document_metadata(
        {
            "scheme_id": "TEST-SCHEME",
            "documents": {
                "identity_a": "missing",
                "identity_b": "available",
            },
            "profile_conditions": {"is_widow": False},
        },
        snapshot=snapshot,
    )

    assert snapshot.trust_status == "approved_source_backed"
    assert result["status"] == "checklist_complete"
    assert result["trust_status"] == "approved_source_backed"
    assert result["groups"][0]["status"] == "available"
    assert result["groups"][0]["alternatives"][0]["status"] == "missing"
    assert result["groups"][0]["alternatives"][1]["status"] == "available"
    assert result["groups"][1]["status"] == "not_applicable"
    assert [item["passage_id"] for item in result["citations"]] == [
        "SYNTH-CONDITION",
        "SYNTH-IDENTITY",
    ]


def test_each_applicable_group_is_required_and_unknown_condition_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checklist, evidence = _approved_fixture()
    snapshot = _install_fixture(monkeypatch, checklist, evidence)

    missing_group = assess_document_metadata(
        {
            "scheme_id": "TEST-SCHEME",
            "documents": {
                "identity_a": "available",
                "conditional_doc": "missing",
            },
            "profile_conditions": {"is_widow": True},
        },
        snapshot=snapshot,
    )
    unknown_condition = assess_document_metadata(
        {
            "scheme_id": "TEST-SCHEME",
            "documents": {"identity_a": "available"},
        },
        snapshot=snapshot,
    )
    unknown_condition_with_document = assess_document_metadata(
        {
            "scheme_id": "TEST-SCHEME",
            "documents": {
                "identity_a": "available",
                "conditional_doc": "available",
            },
        },
        snapshot=snapshot,
    )

    assert missing_group["status"] == "missing_items"
    assert missing_group["groups"][1]["status"] == "missing"
    assert unknown_condition["status"] == "unknown_items"
    assert unknown_condition_with_document["status"] == "unknown_items"
    assert unknown_condition_with_document["groups"][1]["status"] == "unknown"


@pytest.mark.parametrize(
    ("approval_status", "passage_status", "expected"),
    [
        ("pending_review", "reviewed", "requirements_unverified"),
        ("approved", "rejected", "requirements_unverified"),
        ("conflict", "reviewed", "conflict"),
        ("superseded", "reviewed", "superseded"),
    ],
)
def test_checklist_approval_and_evidence_status_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    approval_status: str,
    passage_status: str,
    expected: str,
) -> None:
    checklist, evidence = _approved_fixture()
    checklist["approval"]["status"] = approval_status
    evidence["passages"][0]["review_status"] = passage_status
    if approval_status == "approved":
        checklist["approval"]["evidence_content_sha256"] = hashlib.sha256(
            _encoded(evidence)
        ).hexdigest()

    snapshot = _install_fixture(monkeypatch, checklist, evidence)

    assert snapshot.trust_status == expected
    assert snapshot.checklist is None or not snapshot.usable
    assert not snapshot.citations


@pytest.mark.parametrize("broken_link", ["missing", "other_scheme", "rejected"])
def test_broken_or_rejected_evidence_never_becomes_a_verified_list(
    monkeypatch: pytest.MonkeyPatch, broken_link: str
) -> None:
    checklist, evidence = _approved_fixture()
    if broken_link == "missing":
        checklist["requirements"][0]["evidence_passage_ids"] = ["ABSENT"]
    elif broken_link == "other_scheme":
        evidence["passages"][0]["scheme_id"] = "OTHER-SCHEME"
    else:
        evidence["passages"][0]["review_status"] = "rejected"
        checklist["approval"]["evidence_content_sha256"] = hashlib.sha256(
            _encoded(evidence)
        ).hexdigest()

    snapshot = _install_fixture(monkeypatch, checklist, evidence)

    assert snapshot.trust_status == "requirements_unverified"
    assert not snapshot.usable


def test_invalid_schema_duplicate_ids_and_wrong_scheme_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checklist, evidence = _approved_fixture()
    duplicate = copy.deepcopy(checklist)
    duplicate["requirements"][1]["requirement_id"] = "identity_group"
    assert _install_fixture(monkeypatch, duplicate, evidence).trust_status == (
        "requirements_unverified"
    )

    wrong_scheme = copy.deepcopy(checklist)
    wrong_scheme["scheme_id"] = "OTHER-SCHEME"
    assert _install_fixture(monkeypatch, wrong_scheme, evidence).trust_status == (
        "requirements_unverified"
    )

    checklist["unsupported_expression"] = "not accepted"
    assert _install_fixture(monkeypatch, checklist, evidence).trust_status == (
        "requirements_unverified"
    )

    invalid_id, evidence = _approved_fixture()
    invalid_id["requirements"][0]["alternatives"][0]["document_id"] = "Bad ID"
    assert _install_fixture(monkeypatch, invalid_id, evidence).trust_status == (
        "requirements_unverified"
    )


def test_duplicate_json_keys_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checklist, evidence = _approved_fixture()
    encoded_checklist = _encoded(checklist).replace(
        b'"scheme_id": "TEST-SCHEME"',
        b'"scheme_id": "TEST-SCHEME", "scheme_id": "TEST-SCHEME"',
        1,
    )
    content = {
        "TEST-SCHEME.json": encoded_checklist,
        "document_evidence.json": _encoded(evidence),
    }
    monkeypatch.setattr(
        checklists,
        "_load_bytes",
        lambda path: content.get(path.name),
    )

    snapshot = checklists.load_checklist_snapshot(
        "TEST-SCHEME",
        checklist_directory=checklists.CHECKLIST_DIRECTORY,
        evidence_file=checklists.EVIDENCE_FILE,
    )

    assert snapshot.trust_status == "requirements_unverified"
    assert snapshot.checklist is None


def test_supported_publication_is_atomic_and_tracks_restore_revision(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "document_checklists"
    directory.mkdir()
    evidence_file = tmp_path / "document_evidence.json"
    checklist, evidence = _approved_fixture()
    encoded_evidence = _encoded(evidence)
    encoded_checklist = _encoded(checklist)

    assert publication.publish_checklist_file(
        evidence_file.name,
        encoded_evidence,
        checklist_directory=directory,
        evidence_file=evidence_file,
    ) == 1
    assert publication.publish_checklist_file(
        "TEST-SCHEME.json",
        encoded_checklist,
        checklist_directory=directory,
        evidence_file=evidence_file,
    ) == 2
    original = checklists.load_checklist_snapshot(
        "TEST-SCHEME",
        checklist_directory=directory,
        evidence_file=evidence_file,
    )
    assert original.trust_status == "approved_source_backed"

    changed = copy.deepcopy(checklist)
    changed["requirements"][0]["labels"]["en"] = "Changed synthetic label"
    changed["approval"]["checklist_content_sha256"] = checklists._canonical_digest(
        {key: value for key, value in changed.items() if key != "approval"}
    )
    assert publication.publish_checklist_file(
        "TEST-SCHEME.json",
        _encoded(changed),
        checklist_directory=directory,
        evidence_file=evidence_file,
    ) == 3
    assert publication.publish_checklist_file(
        "TEST-SCHEME.json",
        encoded_checklist,
        checklist_directory=directory,
        evidence_file=evidence_file,
    ) == 4
    restored = checklists.load_checklist_snapshot(
        "TEST-SCHEME",
        checklist_directory=directory,
        evidence_file=evidence_file,
    )

    assert restored.checklist_fingerprint == original.checklist_fingerprint
    assert restored.publication_revision == original.publication_revision + 2
    assert restored.active_fingerprint != original.active_fingerprint

    invalid_approval = copy.deepcopy(checklist)
    invalid_approval["requirements"][0]["labels"]["en"] = "Unreviewed change"
    with pytest.raises(ValueError, match="exact current evidence"):
        publication.publish_checklist_file(
            "TEST-SCHEME.json",
            _encoded(invalid_approval),
            checklist_directory=directory,
            evidence_file=evidence_file,
        )
    assert (directory / "TEST-SCHEME.json").read_bytes() == encoded_checklist
    assert (tmp_path / publication.REVISION_FILENAME).read_bytes() == b"4"

    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["passages"][0]["exact_quote"] = "Updated synthetic wording."
    assert publication.publish_checklist_file(
        evidence_file.name,
        _encoded(changed_evidence),
        checklist_directory=directory,
        evidence_file=evidence_file,
    ) == 5
    evidence_changed = checklists.load_checklist_snapshot(
        "TEST-SCHEME",
        checklist_directory=directory,
        evidence_file=evidence_file,
    )
    assert evidence_changed.trust_status == "requirements_unverified"


def test_failed_publication_lock_prevents_portal_action_and_file_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "document_checklists"
    directory.mkdir()
    evidence_file = tmp_path / "document_evidence.json"
    encoded_evidence = _encoded({"schema_version": 1, "passages": []})
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "portal.sqlite3")
    )

    class FailingLock:
        def acquire(self) -> None:
            raise OSError("synthetic lock failure")

    monkeypatch.setattr(publication, "_publication_lock", lambda _path: FailingLock())
    with pytest.raises(RuntimeError, match="publication lock"):
        publication.publish_checklist_file(
            evidence_file.name,
            encoded_evidence,
            checklist_directory=directory,
            evidence_file=evidence_file,
        )
    with pytest.raises(RuntimeError, match="publication lock"):
        portal_repository._portal_action({
            "action": "dependency_status", "journey_id": "synthetic-journey"
        })

    assert not evidence_file.exists()
    assert not (tmp_path / publication.REVISION_FILENAME).exists()


def test_same_version_checklist_or_evidence_mutation_invalidates_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checklist, evidence = _approved_fixture()
    first = _install_fixture(monkeypatch, checklist, evidence)

    changed_checklist = copy.deepcopy(checklist)
    changed_checklist["requirements"][0]["labels"]["en"] = "Changed synthetic label"
    second = _install_fixture(monkeypatch, changed_checklist, evidence)
    assert second.checklist_version == first.checklist_version
    assert second.active_fingerprint != first.active_fingerprint
    assert second.trust_status == "requirements_unverified"

    changed_evidence = copy.deepcopy(evidence)
    changed_evidence["passages"][0]["exact_quote"] = "Changed synthetic wording."
    third = _install_fixture(monkeypatch, checklist, changed_evidence)
    assert third.checklist_version == first.checklist_version
    assert third.active_fingerprint != first.active_fingerprint
    assert third.trust_status == "requirements_unverified"


def test_missing_checklist_is_not_an_empty_verified_requirement_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _install_fixture(monkeypatch, None, {"schema_version": 1, "passages": []})
    result = assess_document_metadata(
        {"scheme_id": "TEST-SCHEME", "documents": {}}, snapshot=snapshot
    )

    assert result["status"] == "requirements_unverified"
    assert result["requirements"] == []
    assert result["demo_only"] is False
    assert "not verified" in result["message"].lower()


@pytest.mark.parametrize(
    ("scheme_id", "document_ids"),
    [
        (
            "IGNWPS-MH",
            {
                "identity_proof", "age_proof", "widow_status_proof", "bpl_proof",
            },
        ),
        (
            "PM-KISAN-IN",
            {"identity_proof", "land_record", "bank_account_proof"},
        ),
    ],
)
def test_pilot_demo_files_keep_existing_ids_and_are_not_official(
    scheme_id: str, document_ids: set[str]
) -> None:
    snapshot = checklists.load_checklist_snapshot(scheme_id)
    result = assess_document_metadata({
        "scheme_id": scheme_id,
        "documents": {},
    }, snapshot=snapshot)

    assert snapshot.checklist_version == "v1"
    assert snapshot.trust_status == "demo_only_unverified"
    assert result["status"] == "unknown_items"
    assert result["demo_only"] is True
    assert {item["document_id"] for item in result["requirements"]} == document_ids
    assert all(
        set(item["labels"]) == {"en", "hi", "mr"}
        for item in result["requirements"]
    )


def test_portal_accepts_only_a_fresh_approved_source_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checklist, evidence = _approved_fixture()
    snapshot = _install_fixture(monkeypatch, checklist, evidence)
    monkeypatch.setattr(
        portal_repository, "load_checklist_snapshot", lambda _scheme_id: snapshot
    )
    active_provider = portal_repository.get_active_rule_data()
    test_bundle = active_provider.get_bundle("IGNWPS-MH").model_copy(
        update={"scheme_id": "TEST-SCHEME"}
    )
    monkeypatch.setattr(
        portal_repository,
        "get_active_rule_data",
        lambda: SimpleNamespace(
            registry=active_provider.registry,
            get_bundle=lambda _scheme_id: test_bundle,
        ),
    )
    test_form = MockFormMapping.model_validate({
        "schema_version": 1,
        "scheme_id": "TEST-SCHEME",
        "form_version": "1.0.0",
        "status": "demo_only",
        "fields": ({
            "field_id": "test_reference",
            "labels": {"en": "Reference", "hi": "संदर्भ", "mr": "संदर्भ"},
            "value_type": "text",
            "required": False,
            "extra_input": True,
            "max_length": 80,
        },),
    })
    monkeypatch.setattr(
        portal_repository,
        "load_mock_form_snapshot",
        lambda _scheme_id, _registry, **_context: MockFormSnapshot(
            scheme_id="TEST-SCHEME",
            mapping=test_form,
            fingerprint="a" * 64,
            notice="Synthetic fixture only.",
        ),
    )
    monkeypatch.setenv(
        "SCHEME_SAATHI_APPLICATION_DB", str(tmp_path / "portal.sqlite3")
    )
    documents = {"identity_a": "missing", "identity_b": "available"}
    conditions = {"is_widow": False}
    assessment = assess_document_metadata(
        {
            "scheme_id": "TEST-SCHEME",
            "documents": documents,
            "profile_conditions": conditions,
        },
        snapshot=snapshot,
    )
    report_input = {
        "input_fingerprint": document_input_fingerprint(
            "TEST-SCHEME",
            documents,
            None,
            None,
            {},
            snapshot.checklist_fingerprint,
            snapshot.evidence_fingerprint,
            snapshot.active_fingerprint,
            conditions,
        ),
        "assessment": assessment,
    }
    report_fingerprint = hashlib.sha256(
        json.dumps(
            report_input, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    identity = {
        "journey_id": "synthetic-approved-journey",
        "scheme_id": "TEST-SCHEME",
        "documents": documents,
        "document_report_fingerprint": report_fingerprint,
        "checklist_fingerprint": snapshot.checklist_fingerprint,
        "evidence_fingerprint": snapshot.evidence_fingerprint,
        "active_checklist_fingerprint": snapshot.active_fingerprint,
    }
    portal_repository._portal_action({
        "action": "bind_documents",
        **identity,
    })
    draft = portal_repository._portal_action({
        "action": "create_draft",
        **identity,
        "profile": {"is_widow": False},
        "applicant_reference": "Synthetic applicant",
        "district": "Synthetic district",
    })

    assert draft["draft"]["requirements_status"] == "approved_source_backed"
    assert draft["draft"]["checklist_version"] == "v1"
    assert draft["draft"]["document_citations"]

    checklist["approval"]["status"] = "pending_review"
    unapproved = _install_fixture(monkeypatch, checklist, evidence)
    monkeypatch.setattr(
        portal_repository, "load_checklist_snapshot", lambda _scheme_id: unapproved
    )
    with pytest.raises(RuntimeError, match="not verified"):
        portal_repository._portal_action({
            "action": "create_draft",
            **identity,
            "profile": {"is_widow": False},
            "applicant_reference": "Synthetic applicant",
            "district": "Synthetic district",
        })
