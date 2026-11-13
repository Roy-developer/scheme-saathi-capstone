"""Generate synthetic DEVELOPMENT personas from the live rule packages.

Output: eval/development/personas_generated_v2.json

These cases are development-only (split="development", protected=false). They
are not independent labels and are not held-out. Inputs are hand-chosen
boundary values; every expected result is computed by the deterministic rule
engine (src/api/eligibility.py evaluate_mock_eligibility), never typed by hand.

Usage:
    .venv/Scripts/python.exe scripts/generate_dev_personas.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.harness.runner import typed_fact_store  # noqa: E402
from src.api.eligibility import evaluate_mock_eligibility  # noqa: E402
from src.rules.data_provider import RulePackageProvider  # noqa: E402

PACKAGE_DIR = REPO_ROOT / "src" / "rules" / "packages"
OUTPUT_PATH = REPO_ROOT / "eval" / "development" / "personas_generated_v2.json"
GENERATOR_PATH = "scripts/generate_dev_personas.py"

# Prefix used in persona IDs -> package file (5 live packages only).
PACKAGE_FILES = {
    "APY": "apy_in.v1.json",
    "IGNDPS": "igndps_mh.v1.json",
    "IGNOAPS": "ignoaps_mh.v1.json",
    "IGNWPS": "ignwps_mh.v1.json",
    "PMKISAN": "pmkisan_in.v1.json",
}

APPLICATION_DATE = "2026-06-01"

# Synthetic dates. With application date 2026-06-01:
#   1986-06-01 -> age 40 (exact lower/upper boundary), 1986-06-02 -> age 39
#   2008-06-01 -> age 18, 2009-06-02 -> age 17
#   1947-06-01 -> age 79, 1946-06-01 -> age 80, 1947-06-02 -> age 78
#   1961-06-01 -> age 65, 1962-06-02 -> age 64
#   1985-06-01 -> age 41, 1990-06-01 -> age 35
DOB = {
    "age39": "1986-06-02",
    "age40": "1986-06-01",
    "age79": "1947-06-01",
    "age80": "1946-06-01",
    "age64": "1962-06-02",
    "age65": "1961-06-01",
    "age17": "2009-06-02",
    "age18": "2008-06-01",
    "age41": "1985-06-01",
    "age35": "1990-06-01",
    "age50": "1976-06-01",
    "age70": "1956-06-01",
}


def _dob_facts(dob_key: str, **extra: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "date_of_birth": DOB[dob_key] if dob_key else None,
        "application_date": APPLICATION_DATE,
    }
    facts.update(extra)
    return facts


# Each case: (prefix, family, intended verdict, description, typed_facts).
# The intended verdict is only a design check: the generator fails if the rule
# engine disagrees, but the stored expected value is always the engine output.
CASES: list[tuple[str, str, str, str, dict[str, object]]] = [
    # IGNWPS-MH: widow, age 40-79 inclusive, BPL card proof.
    ("IGNWPS", "ignwps-age-lower-below", "not_eligible",
     "Widow aged 39 (one day short of 40 on the application date), BPL card shown.",
     _dob_facts("age39", is_widow=True, bpl_card_shown=True)),
    ("IGNWPS", "ignwps-age-lower-exact", "eligible",
     "Widow exactly 40 on the application date, BPL card shown.",
     _dob_facts("age40", is_widow=True, bpl_card_shown=True)),
    ("IGNWPS", "ignwps-age-upper-exact", "eligible",
     "Widow exactly 79 on the application date, BPL card shown.",
     _dob_facts("age79", is_widow=True, bpl_card_shown=True)),
    ("IGNWPS", "ignwps-age-upper-above", "not_eligible",
     "Widow aged 80 on the application date, BPL card shown.",
     _dob_facts("age80", is_widow=True, bpl_card_shown=True)),
    ("IGNWPS", "ignwps-widow-exclusion", "not_eligible",
     "Age 50 applicant who is not a widow, BPL card shown.",
     _dob_facts("age50", is_widow=False, bpl_card_shown=True)),
    ("IGNWPS", "ignwps-bpl-missing", "need_more_information",
     "Widow aged 50 with the BPL card answer left unknown.",
     _dob_facts("age50", is_widow=True, bpl_card_shown=None)),

    # IGNOAPS-MH: age 65 or above, name on BPL list.
    ("IGNOAPS", "ignoaps-age-lower-below", "not_eligible",
     "Applicant aged 64 on the application date, name on BPL list.",
     _dob_facts("age64", name_on_bpl_list=True)),
    ("IGNOAPS", "ignoaps-age-lower-exact", "eligible",
     "Applicant exactly 65 on the application date, name on BPL list.",
     _dob_facts("age65", name_on_bpl_list=True)),
    ("IGNOAPS", "ignoaps-bpl-list-exclusion", "not_eligible",
     "Applicant aged 70, name not on BPL list.",
     _dob_facts("age70", name_on_bpl_list=False)),
    ("IGNOAPS", "ignoaps-bpl-list-missing", "need_more_information",
     "Applicant aged 70, BPL list answer unknown.",
     _dob_facts("age70", name_on_bpl_list=None)),
    ("IGNOAPS", "ignoaps-dob-missing", "need_more_information",
     "Applicant with date of birth unknown, name on BPL list.",
     _dob_facts("", name_on_bpl_list=True)),

    # IGNDPS-MH: age 18-79 inclusive, has disability.
    ("IGNDPS", "igndps-age-lower-below", "not_eligible",
     "Applicant aged 17 on the application date, has disability.",
     _dob_facts("age17", has_disability=True)),
    ("IGNDPS", "igndps-age-lower-exact", "eligible",
     "Applicant exactly 18 on the application date, has disability.",
     _dob_facts("age18", has_disability=True)),
    ("IGNDPS", "igndps-age-upper-exact", "eligible",
     "Applicant exactly 79 on the application date, has disability.",
     _dob_facts("age79", has_disability=True)),
    ("IGNDPS", "igndps-age-upper-above", "not_eligible",
     "Applicant aged 80 on the application date, has disability.",
     _dob_facts("age80", has_disability=True)),
    ("IGNDPS", "igndps-disability-exclusion", "not_eligible",
     "Applicant aged 46 without a disability.",
     _dob_facts("age50", has_disability=False)),
    ("IGNDPS", "igndps-disability-missing", "need_more_information",
     "Applicant aged 50 with disability answer unknown.",
     _dob_facts("age50", has_disability=None)),

    # APY-IN: age 18-40 inclusive, citizen, savings account, not a taxpayer.
    ("APY", "apy-age-lower-below", "not_eligible",
     "Applicant aged 17 on the application date, all other answers clean.",
     _dob_facts("age17", apy_is_citizen_of_india=True,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=False)),
    ("APY", "apy-age-lower-exact", "eligible",
     "Applicant exactly 18 on the application date, all answers clean.",
     _dob_facts("age18", apy_is_citizen_of_india=True,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=False)),
    ("APY", "apy-age-upper-exact", "eligible",
     "Applicant exactly 40 on the application date, all answers clean.",
     _dob_facts("age40", apy_is_citizen_of_india=True,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=False)),
    ("APY", "apy-age-upper-above", "not_eligible",
     "Applicant aged 41 on the application date, all answers clean.",
     _dob_facts("age41", apy_is_citizen_of_india=True,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=False)),
    ("APY", "apy-taxpayer-exclusion", "not_eligible",
     "Age 35 applicant who has been an income tax payer.",
     _dob_facts("age35", apy_is_citizen_of_india=True,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=True)),
    ("APY", "apy-citizenship-missing", "need_more_information",
     "Age 35 applicant with citizenship answer unknown.",
     _dob_facts("age35", apy_is_citizen_of_india=None,
                apy_has_savings_bank_account=True,
                apy_is_or_has_been_income_tax_payer=False)),

    # PM-KISAN-IN: landholding required; each exclusion fact must be False.
    ("PMKISAN", "pmkisan-clean-eligible", "eligible",
     "Family with state-recorded cultivable land and no listed exclusion.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-landholding-false", "not_eligible",
     "Family with no cultivable land in state records; other answers clean.",
     {
         "landholding_family_in_state_records": False,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-institutional-landholder-exclusion", "not_eligible",
     "Family with land, but the landholder is an institution.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": True,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-public-office-exclusion", "not_eligible",
     "Family with land, one member holds a listed public office.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": True,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-government-employee-exclusion", "not_eligible",
     "Family with land, one member is an excluded government employee.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": True,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-pension-exclusion", "not_eligible",
     "Family with land, pension of at least 10000 outside the stated grades.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": True,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-income-tax-exclusion", "not_eligible",
     "Family with land, income tax paid in the last assessment year.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": True,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-professional-exclusion", "not_eligible",
     "Family with land, one member is a registered practising professional.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": True,
         "nri_new_beneficiary": False,
     }),
    ("PMKISAN", "pmkisan-nri-exclusion", "not_eligible",
     "Family with land, applicant is a new NRI beneficiary.",
     {
         "landholding_family_in_state_records": True,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": True,
     }),
    ("PMKISAN", "pmkisan-landholding-missing", "need_more_information",
     "Family with the state-records landholding answer unknown; other answers clean.",
     {
         "landholding_family_in_state_records": None,
         "institutional_landholder": False,
         "listed_public_office_member": False,
         "excluded_government_employee_member": False,
         "pension_at_least_10000_excluding_stated_grades": False,
         "income_tax_paid_last_assessment_year": False,
         "registered_practicing_professional_member": False,
         "nri_new_beneficiary": False,
     }),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_document() -> dict[str, object]:
    """Return the development persona set with rule-engine expected values."""

    provider = RulePackageProvider()
    registry = provider.registry
    packages = {}
    hashes = {}
    for prefix, filename in PACKAGE_FILES.items():
        path = PACKAGE_DIR / filename
        scheme_id = json.loads(path.read_text(encoding="utf-8"))["scheme_id"]
        packages[prefix] = provider.packages[scheme_id]
        hashes[f"{scheme_id} ({filename})"] = _sha256(path)

    counters: dict[str, int] = {}
    personas: list[dict[str, object]] = []
    for prefix, family, intended, description, typed_facts in CASES:
        counters[prefix] = counters.get(prefix, 0) + 1
        package = packages[prefix]
        profile = typed_fact_store(typed_facts, registry)
        actual = evaluate_mock_eligibility(profile, package, registry=registry)
        if actual.result != intended:
            raise SystemExit(
                f"Design check failed for {family}: intended {intended}, "
                f"rule engine returned {actual.result}"
            )
        personas.append({
            "persona_id": f"GEN-{prefix}-{counters[prefix]:03d}",
            "boundary_family": family,
            "split": "development",
            "protected": False,
            "description": description,
            "typed_facts": typed_facts,
            "expected_by_scheme": {
                package.scheme_id: {
                    "result": actual.result,
                    "missing_fields": list(actual.missing_fields),
                    "deciding_rule_ids": list(actual.deciding_rule_ids),
                },
            },
        })

    hash_lines = "; ".join(f"{name} sha256={digest}" for name, digest in hashes.items())
    note = (
        "GENERATED DEVELOPMENT-ONLY SET, NOT HELD-OUT, NOT INDEPENDENT. "
        "Built from the live rule packages in src/rules/packages/ "
        f"({hash_lines}). Generator: {GENERATOR_PATH}. "
        f"Application date fixed at {APPLICATION_DATE}; dates of birth are synthetic. "
        "Every expected_by_scheme value was computed by the deterministic rule engine "
        "(src/api/eligibility.py evaluate_mock_eligibility), not hand-written. "
        "Inputs were chosen at threshold boundaries and exclusion facts; the "
        "intended verdict is checked by the generator only. "
        "Dual labelling by Role 1 is not done. The held-out set still needs "
        "independent authorship."
    )
    return {
        "dataset_version": "2.0.0-dev-generated",
        "split": "development",
        "protected": False,
        "annotation_note": note,
        "personas": personas,
    }


def main() -> None:
    document = build_document()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(document['personas'])} personas to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
