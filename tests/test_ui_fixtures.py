"""Verify fixture provenance, boundary cases, and approval safety behavior."""

import pytest
from pydantic import ValidationError

from src.ui.approval import approval_matches, draft_fingerprint
from src.ui.data_provider import FixtureDataProvider
from src.rules.data_provider import RulePackageProvider
from src.rules.models import Rule, RulePackage


@pytest.fixture
def provider() -> FixtureDataProvider:
    """Load the packaged fixture set for each test."""

    return FixtureDataProvider()


def test_fixture_pack_has_expected_size(
    provider: FixtureDataProvider,
) -> None:
    """The pack includes all boundary cases but exposes only reviewed demos."""

    assert len(provider.fixtures.scenarios) == 7
    assert len(provider.visible_scenarios()) == 3


def test_fixture_pack_is_draft_and_synthetic(
    provider: FixtureDataProvider,
) -> None:
    """Fixture metadata prevents draft personas from being treated as real data."""

    assert provider.fixtures.status == "draft_pending_technical_review"
    assert provider.fixtures.synthetic_personas is True
    assert provider.rule_package.reviewer_name == "Debadyuti Roy"
    assert provider.rule_package.approval_status == "approved_for_mock_portal"
    assert all(
        scenario.profile.synthetic
        for scenario in provider.fixtures.scenarios
    )


@pytest.mark.parametrize(
    ("scenario_id", "expected_result"),
    [
        ("eligible-age-40", "eligible"),
        ("eligible-age-79", "eligible"),
        ("not-eligible-age-39", "not_eligible"),
        ("not-eligible-age-80", "not_eligible"),
        ("not-eligible-not-widow", "not_eligible"),
        ("eligible-bpl-card-shown", "eligible"),
        ("cant-tell-bpl-card-not-shown", "cant_tell"),
    ],
)
def test_reviewed_draft_boundary_expectations(
    provider: FixtureDataProvider,
    scenario_id: str,
    expected_result: str,
) -> None:
    """Every documented eligibility boundary keeps its reviewed outcome."""

    scenario = provider.get_scenario(scenario_id)

    assert scenario.expected_verdict.result == expected_result


def test_cant_tell_case_names_missing_information(
    provider: FixtureDataProvider,
) -> None:
    """Indeterminate results state which fact must be collected."""

    scenario = provider.get_scenario("cant-tell-bpl-card-not-shown")

    assert scenario.profile.bpl_status == "unknown"
    assert scenario.expected_verdict.missing_fields == ["government_bpl_card"]


@pytest.mark.parametrize(
    ("scenario_id", "expected_age"),
    [
        ("eligible-age-40", 40),
        ("eligible-age-79", 79),
        ("not-eligible-age-39", 39),
        ("not-eligible-age-80", 80),
    ],
)
def test_fixture_age_is_calculated_on_application_date(
    provider: FixtureDataProvider,
    scenario_id: str,
    expected_age: int,
) -> None:
    """The scenario age comes from birth date and application date."""

    profile = provider.get_scenario(scenario_id).profile

    assert profile.age == expected_age
    assert profile.date_of_birth < profile.application_date


def test_no_bpl_card_is_unknown_not_a_verified_negative(
    provider: FixtureDataProvider,
) -> None:
    """Missing mock evidence requests information instead of denying eligibility."""

    scenario = provider.get_scenario("cant-tell-bpl-card-not-shown")

    assert scenario.profile.bpl_card_shown is False
    assert scenario.profile.bpl_status == "unknown"
    assert scenario.expected_verdict.result == "cant_tell"


def test_rule_package_records_mock_approval_source_and_interpretations(
    provider: FixtureDataProvider,
) -> None:
    """Rules, their provenance and mock-only approval live together."""

    package = provider.rule_package

    assert package.package_version == "1.0.0"
    assert package.age_as_of == "application_date"
    assert package.age_boundaries_inclusive is True
    assert package.bpl_confirmation == "government_bpl_card_shown"
    assert package.source.source_url.host == "sjsa.maharashtra.gov.in"
    assert package.approval_scope == "synthetic_mock_portal_only"


@pytest.mark.parametrize(
    ("field", "operator", "value"),
    [
        ("age", "gte", "confirmed"),
        ("age", "gte", True),
        ("is_widow", "gte", True),
        ("bpl_status", "eq", "unknown"),
    ],
)
def test_rule_rejects_unsupported_combinations(
    field: str,
    operator: str,
    value: bool | int | str,
) -> None:
    """Rule fields cannot use incompatible operators or value types."""

    with pytest.raises(ValidationError, match="Invalid operator or value"):
        Rule(
            rule_id="INVALID-RULE",
            field=field,
            operator=operator,
            value=value,
            source_clause_id="TEST-SOURCE",
        )


def test_rule_package_rejects_duplicate_rule_ids(
    provider: FixtureDataProvider,
) -> None:
    """Duplicate identifiers cannot make evidence ambiguous."""

    payload = provider.rule_package.model_dump(mode="json")
    payload["rules"][1]["rule_id"] = payload["rules"][0]["rule_id"]

    with pytest.raises(ValidationError, match="Policy rule IDs must be unique"):
        RulePackage.model_validate(payload)


def test_rule_package_rejects_incomplete_or_inconsistent_age_bounds(
    provider: FixtureDataProvider,
) -> None:
    """The mock policy requires both ordered age limits."""

    payload = provider.rule_package.model_dump(mode="json")
    payload["rules"] = [
        rule for rule in payload["rules"]
        if rule["rule_id"] != "IGNWPS-MH-AGE-MAX-01"
    ]
    with pytest.raises(ValidationError):
        RulePackage.model_validate(payload)

    payload = provider.rule_package.model_dump(mode="json")
    minimum_rule = next(
        rule for rule in payload["rules"] if rule["operator"] == "gte"
    )
    minimum_rule["value"] = 80
    with pytest.raises(ValidationError, match="Minimum age cannot exceed"):
        RulePackage.model_validate(payload)


def test_rule_package_source_is_official_and_dated(
    provider: FixtureDataProvider,
) -> None:
    """Policy evidence retains its official host and collection metadata."""

    source = provider.rule_package.source

    assert source.source_url.host == "sjsa.maharashtra.gov.in"
    assert source.collected_at.isoformat() == "2026-10-28"
    assert source.publication_date_status == "not_confirmed"


def test_document_requirements_are_not_invented(
    provider: FixtureDataProvider,
) -> None:
    """Unverified document requirements remain explicitly absent."""

    assert provider.rule_package.documents_status == "not_verified"


def test_rule_package_provider_rejects_duplicate_scheme_packages(
    provider: FixtureDataProvider,
    tmp_path,
) -> None:
    """One scheme ID must resolve to exactly one package in the registry."""

    package_json = provider.rule_package.model_dump_json()
    (tmp_path / "first.json").write_text(package_json, encoding="utf-8")
    (tmp_path / "second.json").write_text(package_json, encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate rule package"):
        RulePackageProvider(tmp_path)

def test_eligible_demo_has_matching_application_draft(
    provider: FixtureDataProvider,
) -> None:
    """Only the eligible demo carries a draft matching its source profile."""

    scenario = provider.get_scenario("eligible-age-40")
    draft = scenario.application_draft

    assert draft is not None
    assert draft.scheme_id == provider.fixtures.policy.scheme_id
    assert draft.date_of_birth == scenario.profile.date_of_birth
    assert draft.application_date == scenario.profile.application_date
    assert draft.bpl_status == scenario.profile.bpl_status


def test_draft_fingerprint_is_stable_and_changes_after_edit(
    provider: FixtureDataProvider,
) -> None:
    """A draft edit changes its fingerprint and invalidates prior approval."""

    draft = provider.get_scenario("eligible-age-40").application_draft
    assert draft is not None

    original = draft_fingerprint(draft)
    repeated = draft_fingerprint(draft)
    edited = draft_fingerprint(
        draft.model_copy(update={"district": "Mumbai"})
    )

    assert original == repeated
    assert original != edited
    assert approval_matches(original, draft)
    assert not approval_matches(
        original,
        draft.model_copy(update={"district": "Mumbai"}),
    )


def test_unknown_scenario_fails_clearly(
    provider: FixtureDataProvider,
) -> None:
    """Unknown scenario IDs fail with a useful lookup error."""

    with pytest.raises(KeyError, match="Unknown development scenario"):
        provider.get_scenario("not-present")
