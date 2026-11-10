"""Guard the recorded human sign-off for the PM-KISAN mock rules."""

import hashlib
from pathlib import Path

from src.documents.checklists import load_checklist_snapshot
from src.rules.data_provider import RulePackageProvider

ROOT = Path(__file__).parents[1]


def test_pmkisan_is_signed_off_for_the_mock_with_the_cutoff_still_open() -> None:
    package = RulePackageProvider().packages["PM-KISAN-IN"]

    assert package.approval_status == "approved_for_mock_portal"
    assert package.approval_scope == "synthetic_mock_portal_only"
    assert package.reviewer_name == "Roy-developer"
    assert any("cutoff" in check for check in package.unresolved_checks)


def test_pmkisan_review_records_approval_of_these_exact_package_bytes() -> None:
    raw = (ROOT / "src/rules/packages/pmkisan_in.v1.json").read_bytes()
    review = (ROOT / "docs/PMKISAN_RULE_REVIEW_2026-11-02.md").read_text(encoding="utf-8")

    assert (
        "App approval: `PM-KISAN-IN` approved by `Roy-developer` on 2026-11-09 "
        f"for package SHA-256 `{hashlib.sha256(raw).hexdigest()}`"
    ) in review
    assert "Earlier condition not met" in review


def test_every_scheme_checklist_cites_reviewed_official_text() -> None:
    pmkisan = load_checklist_snapshot("PM-KISAN-IN")

    assert pmkisan.trust_status == "approved_source_backed"
    assert {citation.passage_id for citation in pmkisan.citations} == {
        "PMKISAN-DOC-DATABASE-01", "PMKISAN-DOC-ATTRIBUTES-01",
        "PMKISAN-DOC-LAND-01", "PMKISAN-DOC-DECLARATION-01",
    }
    assert all(citation.review_status == "reviewed" for citation in pmkisan.citations)
    for scheme in ("IGNWPS-MH", "IGNOAPS-MH"):
        snapshot = load_checklist_snapshot(scheme)
        assert snapshot.trust_status == "approved_source_backed"
        assert snapshot.citations
