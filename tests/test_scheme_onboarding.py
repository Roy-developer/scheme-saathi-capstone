"""Test `scheme_rules.py onboard` offline, on temporary copies of the project.

The main check rebuilds the state IGNOAPS was in before it was onboarded by
hand, runs the command, and requires exactly the files that were made by hand.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from src.rule_extraction_reflexion import scheme_rules
from src.rules.data_provider import RulePackageProvider
from src.rule_extraction_reflexion.onboarding import (
    OnboardingRefused, ProjectPaths, _json_like, apply_onboarding, plan_onboarding,
)

REAL_ROOT = Path(__file__).parents[1]
SCHEME = "IGNOAPS-MH"
PACKAGE = "ignoaps_mh.v1.json"
SOURCE_URL = "https://sjsa.maharashtra.gov.in/en/scheme/indira-gandhi-national-old-age-pension-scheme/"
CASE_MARKER = '"package": "ignoaps_mh.v1.json", '


@pytest.fixture
def live_copy(tmp_path: Path) -> ProjectPaths:
    """A copy of the project with IGNOAPS live, as it is today."""

    root = tmp_path / "project"
    shutil.copytree(REAL_ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for folder in ("rule_extraction_sources", "document_checklists", "mock_forms"):
        shutil.copytree(REAL_ROOT / "data/schemes" / folder, root / "data/schemes" / folder)
    shutil.copytree(REAL_ROOT / "data/schemes/passages", root / "data/schemes/passages")
    shutil.copy(
        REAL_ROOT / "data/schemes/rule_extraction_cases_dev.json",
        root / "data/schemes/rule_extraction_cases_dev.json",
    )
    (root / "docs").mkdir()
    for review in (REAL_ROOT / "docs").glob("*_RULE_REVIEW_*.md"):
        shutil.copy(review, root / "docs" / review.name)
    return ProjectPaths(root)


@pytest.fixture
def before(live_copy: ProjectPaths) -> ProjectPaths:
    """The same copy, put back to the moment before IGNOAPS was onboarded."""

    paths = live_copy
    paths.staged_packages.mkdir()
    shutil.move(paths.packages / PACKAGE, paths.staged_packages / PACKAGE)

    registry_raw = paths.fact_registry.read_bytes()
    registry = json.loads(registry_raw)
    for fact in registry["definitions"]:
        if fact["fact_id"] in {"age", "application_date", "date_of_birth"}:
            fact["source_refs"].remove(SOURCE_URL)
    earlier = _json_like(registry_raw, registry)
    paths.fact_registry.write_bytes(earlier)
    old_sha, new_sha = hashlib.sha256(earlier).hexdigest(), hashlib.sha256(registry_raw).hexdigest()

    bundles_raw = paths.bundle_registry.read_bytes()
    bundles = json.loads(bundles_raw)
    bundles["bundles"] = [b for b in bundles["bundles"] if b["scheme_id"] != SCHEME]
    for bundle in bundles["bundles"]:
        bundle["registry_sha256"] = old_sha
    paths.bundle_registry.write_bytes(_json_like(bundles_raw, bundles))

    paths.passages_file(SCHEME).unlink()

    cases = paths.cases.read_bytes().decode("utf-8")
    assert cases.count(CASE_MARKER) == 1
    paths.cases.write_bytes(cases.replace(
        CASE_MARKER, CASE_MARKER + '"package_dir": "data/schemes/reflexion_packages", ',
    ).encode("utf-8"))
    return paths


def _review(paths: ProjectPaths) -> Path:
    return paths.docs / "IGNOAPS_MH_RULE_REVIEW_2026-11-08.md"


def _files(paths: ProjectPaths) -> dict[str, bytes]:
    return {
        str(path.relative_to(paths.root)): path.read_bytes()
        for path in paths.root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _real(relative: str) -> bytes:
    return (REAL_ROOT / relative).read_bytes()


def test_onboard_rebuilds_the_hand_made_ignoaps_files_exactly(before: ProjectPaths) -> None:
    plan = plan_onboarding(SCHEME, before)
    apply_onboarding(plan)

    for relative in (
        f"src/rules/packages/{PACKAGE}",
        "src/rules/bundle_registry.json",
        "src/rules/fact_registry.json",
        "src/rules/data_provider.py",
        "data/schemes/rule_extraction_cases_dev.json",
    ):
        assert (before.root / relative).read_bytes() == _real(relative), relative
    # The curated corpus file also holds the second source's passages, so onboarding
    # is checked for the passages it writes from the source file, not byte for byte.
    written = json.loads(before.passages_file(SCHEME).read_bytes())["passages"]
    curated = json.loads(_real("data/schemes/passages/ignoaps_mh_passages.json"))["passages"]
    assert {p["passage_id"] for p in written} <= {p["passage_id"] for p in curated}
    assert not (before.staged_packages / PACKAGE).exists()


def test_onboarded_scheme_passes_the_loader_and_stays_a_reflexion_case(before: ProjectPaths) -> None:
    apply_onboarding(plan_onboarding(SCHEME, before))

    provider = RulePackageProvider(before.packages)
    assert provider.bundles[SCHEME].activation_state == "approved"
    assert SCHEME in provider.packages
    cases = scheme_rules.build_cases(path=before.cases, rules_dir=before.rules)
    assert "IGNOAPS-MH-ELIGIBILITY-01" in {case.case_id for case in cases}


def test_preview_writes_nothing_and_lists_what_people_must_still_do(
    before: ProjectPaths, capsys: pytest.CaptureFixture[str],
) -> None:
    unchanged = _files(before)

    scheme_rules.onboard(SCHEME, yes=False, paths=before, run_tests=False)

    assert _files(before) == unchanged
    shown = capsys.readouterr().out
    assert "Nothing was written" in shown
    assert "Re-check the search thresholds" in shown


def test_apply_runs_the_tests_after_writing(
    before: ProjectPaths, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def fake_tests() -> bool:
        seen.append((before.packages / PACKAGE).exists())
        return True

    monkeypatch.setattr(scheme_rules, "_run_test_suite", fake_tests)

    scheme_rules.onboard(SCHEME, yes=True, paths=before)

    assert seen == [True]


def _different_official_text(paths: ProjectPaths) -> None:
    source = paths.sources / "ignoaps_mh.json"
    source.write_bytes(source.read_bytes().replace(b"aged 65 and above", b"aged 60 and above"))


def _no_passages(paths: ProjectPaths) -> None:
    source = paths.sources / "ignoaps_mh.json"
    data = json.loads(source.read_bytes())
    del data["onboarding"]
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _no_staged_package(paths: ProjectPaths) -> None:
    (paths.staged_packages / PACKAGE).unlink()


def _break_another_live_package(paths: ProjectPaths) -> None:
    other = paths.packages / "ignwps_mh.v1.json"
    other.write_bytes(other.read_bytes() + b"\n")


@pytest.mark.parametrize(
    ("spoil", "message"),
    [
        (_different_official_text, "does not quote the source file"),
        (_no_passages, "no \"onboarding\" block"),
        (_no_staged_package, "No approved package"),
        (_break_another_live_package, "loader would refuse"),
    ],
)
def test_onboard_refuses_and_writes_nothing(before: ProjectPaths, spoil, message: str) -> None:
    spoil(before)
    unchanged = _files(before)

    with pytest.raises(OnboardingRefused, match=message):
        plan_onboarding(SCHEME, before)

    assert _files(before) == unchanged


def _drop_comma(line: str) -> str:
    """Drop the trailing comma, keeping any carriage return the file's line endings add."""

    body = line.rstrip("\r")
    return body.rstrip(",") + line[len(body):]


def test_new_clause_is_added_to_the_cases_file_and_flagged_for_a_split(before: ProjectPaths) -> None:
    text = before.cases.read_bytes().decode("utf-8")
    lines = [line for line in text.split("\n") if CASE_MARKER not in line]
    lines[-4] = _drop_comma(lines[-4])  # the last case line, before "  ]", "}" and the final newline
    before.cases.write_bytes("\n".join(lines).encode("utf-8"))

    plan = plan_onboarding(SCHEME, before)
    apply_onboarding(plan)

    data = json.loads(before.cases.read_bytes())
    entry = next(case for case in data["cases"] if case["clause_id"] == "IGNOAPS-MH-ELIGIBILITY-01")
    assert entry["split"] is None
    assert any("Choose learn or check" in item for item in plan.for_people)


def test_missing_checklist_and_form_are_left_to_people(before: ProjectPaths) -> None:
    (before.schemes / "document_checklists" / f"{SCHEME}.json").unlink()
    (before.schemes / "mock_forms" / f"{SCHEME}.json").unlink()

    plan = plan_onboarding(SCHEME, before)

    assert any("document_checklists" in item for item in plan.for_people)
    assert any("mock_forms" in item for item in plan.for_people)


def test_scheme_already_in_the_app_is_refused_by_the_command(live_copy: ProjectPaths) -> None:
    with pytest.raises(OnboardingRefused, match="already in the app"):
        plan_onboarding(SCHEME, live_copy)

    with pytest.raises(SystemExit, match="Refused: IGNOAPS-MH is already in the app"):
        scheme_rules.main(["onboard", SCHEME])
