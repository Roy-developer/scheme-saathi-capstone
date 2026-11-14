"""E2 live-model check for the two fact-confirmation scenarios (development only).

Runs only when E2_LIVE=1. Sends the real red-team attack text to the free
Nemotron model through the production intake path. Success checks are the
same as the scripted E2 tests. Off arms are the test adapters from the
scripted suite (intake confirmation filter disabled).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.harness.e2_live_config import free_route_settings  # noqa: E402
from test_e2_runtime import (  # noqa: E402
    FACT_CASES, SUITE, _post, _snapshot, _install_model, intake, integrated_ui,
)
from src.llm_client import openrouter_chat_model  # noqa: E402
from src.workflow import intake as intake_settings_module  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("E2_LIVE") != "1",
    reason="live-model E2 run; set E2_LIVE=1 to call the free model",
)


def _live_fact(harness, patch, enabled, clean, *, attack_id, fact, clean_text):
    api_key, model_name = free_route_settings()
    # Route every intake/reader call to the free model, leaving the .env default untouched.
    patch.setattr(intake_settings_module, "openrouter_chat_settings", lambda _default: (api_key, model_name))
    live_model = openrouter_chat_model(api_key, model_name)
    _install_model(harness, patch, live_model)

    attack = next(case for case in SUITE.attacks if case.attack_id == attack_id)
    profile = dict(attack.check.profile)
    if not enabled:
        original = intake._propose_facts

        async def no_filter(*args, **kwargs):
            kwargs["is_confirmed"] = lambda _name: False
            return await original(*args, **kwargs)

        patch.setattr(intake, "_propose_facts", no_filter)

    if clean:
        profile.pop(fact)
        result = _post(harness, action="interview", scheme_id=attack.check.scheme_id,
                       profile=profile, profile_description=clean_text)
    else:
        initial = _post(harness, action="evaluate", scheme_id=attack.check.scheme_id,
                        profile=profile)
        assert initial["status"] == "not_eligible"
        result = _post(harness, action="interview", scheme_id=attack.check.scheme_id,
                       conversation_id=initial["conversation_id"],
                       profile_description=attack.attack_input)
    journey = result["conversation_id"]
    saved = _snapshot(harness, journey)
    if clean:
        control_triggered = bool(saved["pending_confirmation"] and saved["pending_fact"] == fact)
        if not control_triggered:
            # The live model did not propose the fact from the benign text.
            # Record that rather than forcing a pass.
            return False, {"fact": fact, "attack_id": attack_id, "control_triggered": False}
        confirmed = harness.client.post(f"/api/v1/journey/{journey}/messages",
                                        json={"message": "yes"})
        assert confirmed.status_code == 200, confirmed.text
        saved = _snapshot(harness, journey)
        success = (saved["typed_facts"]["facts"].get(fact, {}).get("value") is False
                   and confirmed.json()["status"] == "eligible")
    else:
        success = saved["typed_facts"]["facts"].get(fact, {}).get("value") is False
    return success, {"model": model_name, "fact": fact, "attack_id": attack_id}


@pytest.mark.parametrize("case_id", list(FACT_CASES))
@pytest.mark.parametrize("clean", [False, True], ids=["attack", "clean"])
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_e2_live_fact(integrated_ui, monkeypatch, record_property, case_id, clean, enabled):
    spec = FACT_CASES[case_id]
    with monkeypatch.context() as patch:
        success, observed = _live_fact(integrated_ui, patch, enabled, clean, **spec)
    row = {"case_id": case_id, "clean": clean, "enabled": enabled, **observed, "success": bool(success)}
    record_property("e2_live", row)
    out = os.environ.get("E2_LIVE_OUT")
    if out:
        import json as _json
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row) + "\n")
    assert isinstance(success, bool)
