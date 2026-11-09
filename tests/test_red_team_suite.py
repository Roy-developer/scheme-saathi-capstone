"""Validate the starter red-team suite schema."""

from __future__ import annotations

import json
from pathlib import Path

from eval.schema import RedTeamSuite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = PROJECT_ROOT / "eval" / "red_team" / "attacks_v0.json"


def test_red_team_suite_has_starter_categories() -> None:
    suite = RedTeamSuite.model_validate(
        json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    )

    assert len(suite.attacks) >= 8
    categories = {attack.category for attack in suite.attacks}
    assert {
        "scam_page",
        "scheme_text_injection",
        "inflate_eligibility",
        "cross_household_memory",
        "id_leakage",
    } <= categories
    assert all(attack.status == "stub" for attack in suite.attacks)
