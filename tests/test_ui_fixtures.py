import pytest

from src.ui.data_provider import FixtureDataProvider


@pytest.fixture
def provider() -> FixtureDataProvider:
    return FixtureDataProvider()


def test_fixture_pack_has_expected_size(
    provider: FixtureDataProvider,
) -> None:
    assert len(provider.fixtures.scenarios) == 7
    assert len(provider.visible_scenarios()) == 3


def test_fixture_pack_is_draft_and_synthetic(
    provider: FixtureDataProvider,
) -> None:
    assert provider.fixtures.status == "draft_pending_role_review"
    assert provider.fixtures.synthetic_personas is True
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
        ("not-eligible-not-bpl", "not_eligible"),
        ("cant-tell-bpl-unknown", "cant_tell"),
    ],
)
def test_reviewed_draft_boundary_expectations(
    provider: FixtureDataProvider,
    scenario_id: str,
    expected_result: str,
) -> None:
    scenario = provider.get_scenario(scenario_id)

    assert scenario.expected_verdict.result == expected_result


def test_cant_tell_case_names_missing_information(
    provider: FixtureDataProvider,
) -> None:
    scenario = provider.get_scenario("cant-tell-bpl-unknown")

    assert scenario.expected_verdict.missing_fields == ["bpl_status"]


def test_policy_source_is_official_and_dated(
    provider: FixtureDataProvider,
) -> None:
    source = provider.fixtures.policy.source

    assert source.source_url.host == "sjsa.maharashtra.gov.in"
    assert source.collected_at.isoformat() == "2026-10-28"
    assert source.publication_date_status == "not_confirmed"


def test_document_requirements_are_not_invented(
    provider: FixtureDataProvider,
) -> None:
    assert provider.fixtures.policy.documents_status == "not_verified"


def test_unknown_scenario_fails_clearly(
    provider: FixtureDataProvider,
) -> None:
    with pytest.raises(KeyError, match="Unknown development scenario"):
        provider.get_scenario("not-present")
