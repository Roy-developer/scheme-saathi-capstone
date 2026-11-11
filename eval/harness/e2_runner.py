"""E2: defences off vs on for offline-checkable red-team attacks."""

from __future__ import annotations

from typing import Any

from eval.schema import RedTeamCase, RedTeamSuite
from src.workflow.agent_runtime import mask_sensitive_text
from src.workflow.injection_guard import screen_free_text
from src.workflow.scam_screen import screen_scam_text


def _injection_flagged(text: str, *, defences_on: bool) -> bool:
    if not defences_on:
        return False
    return screen_free_text(text).flagged


def _scam_flagged(text: str, *, defences_on: bool) -> bool:
    if not defences_on:
        return False
    return screen_scam_text(text).flagged


def _evaluate_attack(
    attack: RedTeamCase,
    *,
    defences_on: bool,
) -> dict[str, Any] | None:
    """Return a result dict for offline-checkable categories; else None."""

    if attack.category == "scheme_text_injection" or (
        attack.category == "other"
        and attack.check
        and attack.check.kind == "injection_screen"
    ):
        flagged = _injection_flagged(attack.attack_input, defences_on=defences_on)
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "defences_on": defences_on,
            "attack_would_succeed": not flagged,
            "defence_held": flagged if defences_on else None,
            "detail": f"flagged={flagged}",
        }

    if attack.category == "id_leakage" and attack.check and attack.check.kind == "id_mask":
        if defences_on:
            masked = mask_sensitive_text(attack.attack_input)
            leaks = [token for token in attack.check.must_not_contain if token in masked]
            return {
                "attack_id": attack.attack_id,
                "category": attack.category,
                "defences_on": True,
                "attack_would_succeed": bool(leaks),
                "defence_held": not leaks,
                "detail": f"leaks={leaks!r}",
            }
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "defences_on": False,
            "attack_would_succeed": True,
            "defence_held": None,
            "detail": "masking disabled",
        }

    if attack.category == "scam_page":
        flagged = _scam_flagged(attack.attack_input, defences_on=defences_on)
        return {
            "attack_id": attack.attack_id,
            "category": attack.category,
            "defences_on": defences_on,
            "attack_would_succeed": not flagged,
            "defence_held": flagged if defences_on else None,
            "detail": f"scam_flagged={flagged}",
        }

    return None


def run_e2_defences(suite: RedTeamSuite) -> dict[str, Any]:
    """Compare attack success with defences off and on (offline subset)."""

    off_results: list[dict[str, Any]] = []
    on_results: list[dict[str, Any]] = []
    for attack in suite.attacks:
        off = _evaluate_attack(attack, defences_on=False)
        on = _evaluate_attack(attack, defences_on=True)
        if off is not None:
            off_results.append(off)
        if on is not None:
            on_results.append(on)

    def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
        if not rows:
            return None
        return sum(1 for row in rows if row.get(key)) / len(rows)

    return {
        "experiment_id": "E2",
        "suite_version": suite.suite_version,
        "mode": "offline_injection_id_scam",
        "defences_off": {
            "case_count": len(off_results),
            "attack_success_rate": _rate(off_results, "attack_would_succeed"),
            "per_attack": off_results,
        },
        "defences_on": {
            "case_count": len(on_results),
            "attack_success_rate": _rate(on_results, "attack_would_succeed"),
            "defence_hold_rate": _rate(on_results, "defence_held"),
            "per_attack": on_results,
        },
        "note": (
            "Offline E2 for injection, ID mask, and scam screens. "
            "scam_screen is eval/tests-only today — the live journey does not "
            "call it; bare UPI/WhatsApp patterns would false-positive if wired "
            "without tightening. Memory/approval-gate attacks still need live "
            "journey runs."
        ),
    }
