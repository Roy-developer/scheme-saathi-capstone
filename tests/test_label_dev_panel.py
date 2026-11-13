"""Offline tests for synthetic development panel controls and aggregation."""

import json
from io import BytesIO
from pathlib import Path

import pytest

from scripts import label_dev_panel as panel


def _row(labels: list[str | None], expected: str = "eligible") -> dict:
    return {
        "source_file": "synthetic.json", "persona_id": "test", "scheme_id": "TEST",
        "boundary_family": "test-age-exclusion", "rule_expected": expected,
        "labels": dict(zip(panel.MODELS, labels)),
    }


def test_majority_and_full_panel_unanimity_are_distinct() -> None:
    rows = [
        _row(["eligible", "eligible", "eligible", "not_eligible"]),
        _row(["eligible", "not_eligible", None, None]),
        _row(["eligible", None, None, None]),
        _row(["eligible"] * 4),
    ]
    report = panel.summarize(rows)
    assert [row["majority"] for row in rows] == [
        "eligible", "no_majority", "eligible", "eligible",
    ]
    assert report["complete_four_model_cases"] == 2
    assert report["unanimous_four_model_cases"] == 1
    assert report["majority_vs_rule"] == {
        "compared": 3, "agree": 3, "disagree": 0, "no_majority": 1,
    }
    assert len(report["boundary_exclusion_disagreements"]) == 2


def test_rule_alias_is_normalized_before_scoring() -> None:
    rows = [_row(["need_more_information"] * 4, "cant_tell")]
    report = panel.summarize(rows)
    assert rows[0]["rule_expected"] == "need_more_information"
    assert report["majority_vs_rule"]["agree"] == 1


def test_response_cost_limit_precedes_invalid_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel.urllib.request, "urlopen", lambda *args, **kwargs: BytesIO(
        b'{"usage":{"cost":0.51},"choices":[{"message":{"content":null}}]}'
    ))
    with pytest.raises(panel.PanelStop) as error:
        panel.call_model(panel.MODELS[0], "synthetic-key", "synthetic prompt")
    assert error.value.reason == "cost_above_limit"
    assert error.value.cost == 0.51


def test_invalid_label_retains_provider_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel.urllib.request, "urlopen", lambda *args, **kwargs: BytesIO(
        b'{"usage":{"cost":0.1},"choices":[{"message":{"content":null}}]}'
    ))
    with pytest.raises(panel.PanelFailure) as error:
        panel.call_model(panel.MODELS[0], "synthetic-key", "synthetic prompt")
    assert error.value.cost == 0.1


def test_stops_each_model_after_five_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    cases = [{
        "source_file": "synthetic.json", "persona_id": str(index),
        "scheme_id": "TEST", "boundary_family": "age", "rule_expected": "eligible",
        "facts": {},
    } for index in range(5)]
    monkeypatch.setattr(panel, "load_cases", lambda: cases)
    monkeypatch.setattr(panel, "load_passages", lambda: {"TEST": "Synthetic."})
    monkeypatch.setattr(panel, "OUTPUT", tmp_path / "report.json")
    monkeypatch.setattr(panel.time, "sleep", lambda _: None)
    monkeypatch.setenv(panel.KEY_NAME, "synthetic-key")
    monkeypatch.setattr(panel.sys, "argv", ["panel", "--live"])

    def fail(model, key, prompt):
        raise panel.PanelFailure("http_404")

    monkeypatch.setattr(panel, "call_model", fail)
    assert panel.main() == 0
    report = json.loads(panel.OUTPUT.read_text(encoding="utf-8"))
    assert report["calls"] == 20
    assert all(arm["calls"] == 5 and arm["failures"] == 5
               and arm["stop_reason"] == "five_consecutive_failures"
               for arm in report["models"].values())
    assert report["agreement"]["majority_vs_rule"]["no_majority"] == 5


def test_dry_run_never_calls_model(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(panel, "load_cases", lambda: [{
        "scheme_id": "TEST",
    }])
    monkeypatch.setattr(panel, "load_passages", lambda: {"TEST": "Synthetic."})
    monkeypatch.setattr(panel.sys, "argv", ["panel", "--dry-run"])
    monkeypatch.setattr(panel, "call_model", lambda *args: pytest.fail("network call"))
    assert panel.main() == 0
    assert "planned_calls=4" in capsys.readouterr().out


def test_cumulative_reported_cost_stops_entire_panel(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    cases = [{
        "source_file": "synthetic.json", "persona_id": str(index),
        "scheme_id": "TEST", "boundary_family": "age", "rule_expected": "eligible",
        "facts": {},
    } for index in range(3)]
    monkeypatch.setattr(panel, "load_cases", lambda: cases)
    monkeypatch.setattr(panel, "load_passages", lambda: {"TEST": "Synthetic."})
    monkeypatch.setattr(panel, "OUTPUT", tmp_path / "report.json")
    monkeypatch.setenv(panel.KEY_NAME, "synthetic-key")
    monkeypatch.setattr(panel.sys, "argv", ["panel", "--live"])
    monkeypatch.setattr(panel, "call_model", lambda *args: ("eligible", 0.30))
    assert panel.main() == 1
    report = json.loads(panel.OUTPUT.read_text(encoding="utf-8"))
    assert report["calls"] == 2
    assert report["reported_cost_usd"] == 0.60
    assert report["stop_reason"] == "cost_above_limit"
    assert report["models"][panel.MODELS[1]]["calls"] == 0


def test_resume_preserves_old_answers_and_respects_new_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    cases = [{
        "source_file": "synthetic.json", "persona_id": str(index),
        "scheme_id": "TEST", "boundary_family": "age", "rule_expected": "eligible",
        "facts": {},
    } for index in range(12)]
    rows = [{
        **{key: case[key] for key in ("source_file", "persona_id", "scheme_id", "boundary_family", "rule_expected")},
        "labels": {model: ("eligible" if model == panel.MODELS[0] and index < 10 else None)
                   for model in panel.MODELS},
    } for index, case in enumerate(cases)]
    metrics = {model: {
        "calls": 10 if model == panel.MODELS[0] else 0,
        "successes": 10 if model == panel.MODELS[0] else 0,
        "failures": 0, "stop_reason": "not_started",
        "reported_cost_usd": 0.0, "cost_unreported_calls": 0, "failure_reasons": {},
    } for model in panel.MODELS}
    report = {
        "disclaimer": panel.DISCLAIMER, "model_ids": list(panel.MODELS),
        "models": metrics, "calls": 10, "reported_cost_usd": 0.0,
        "cost_unreported_calls": 0, "cases": rows,
    }
    output = tmp_path / "report.json"
    output.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(panel, "OUTPUT", output)
    monkeypatch.setattr(panel, "load_cases", lambda: cases)
    monkeypatch.setattr(panel, "load_passages", lambda: {"TEST": "Synthetic."})
    monkeypatch.setattr(panel, "RESUME_MAX_CALLS", 38)
    monkeypatch.setenv(panel.KEY_NAME, "synthetic-key")
    monkeypatch.setattr(panel.sys, "argv", ["panel", "--live", "--resume"])
    calls = []

    def respond(model, key, prompt):
        calls.append(model)
        return "eligible", 0.0

    monkeypatch.setattr(panel, "call_model", respond)
    assert panel.main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["new_calls"] == 38
    assert calls[:36] == [model for model in panel.MODELS[1:] for _ in range(12)]
    assert calls[36:] == [panel.MODELS[0]] * 2
    assert all(row["labels"][panel.MODELS[0]] == "eligible" for row in result["cases"])


def test_save_report_uses_new_fallback_after_primary_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    output = tmp_path / "report.json"
    monkeypatch.setattr(panel, "OUTPUT", output)
    monkeypatch.setattr(panel.time, "sleep", lambda _: None)
    original_replace = Path.replace

    def replace(path, target):
        if target == output:
            raise PermissionError("locked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    report = {}
    panel.save_report(report, [_row(["eligible"] * 4)])
    fallback = tmp_path / "llm_panel_dev_retry.json"
    assert Path(report["output_path"]) == fallback
    assert json.loads(fallback.read_text(encoding="utf-8"))["cases"][0]["majority"] == "eligible"


def test_finish_lightning_only_calls_unanswered_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    cases = [{
        "source_file": "synthetic.json", "persona_id": str(index),
        "scheme_id": "TEST", "boundary_family": "age", "rule_expected": "eligible",
        "facts": {},
    } for index in range(24)]
    rows = [{
        **{key: case[key] for key in ("source_file", "persona_id", "scheme_id", "boundary_family", "rule_expected")},
        "labels": {model: ("eligible" if model != panel.MODELS[0] or index < 22 else None)
                   for model in panel.MODELS},
    } for index, case in enumerate(cases)]
    metrics = {model: {
        "calls": 22 if model == panel.MODELS[0] else 24,
        "successes": 22 if model == panel.MODELS[0] else 24,
        "failures": 0, "stop_reason": "completed", "reported_cost_usd": 0.0,
        "cost_unreported_calls": 0, "failure_reasons": {},
    } for model in panel.MODELS}
    report = {
        "disclaimer": panel.DISCLAIMER, "model_ids": list(panel.MODELS),
        "models": metrics, "calls": 94, "reported_cost_usd": 0.0,
        "cost_unreported_calls": 0, "cases": rows,
    }
    output = tmp_path / "report.json"
    output.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(panel, "OUTPUT", output)
    monkeypatch.setattr(panel, "load_cases", lambda: cases)
    monkeypatch.setattr(panel, "load_passages", lambda: {"TEST": "Synthetic."})
    monkeypatch.setenv(panel.KEY_NAME, "synthetic-key")
    monkeypatch.setattr(panel.sys, "argv", ["panel", "--live", "--finish-lightning"])
    calls = []

    def respond(model, key, prompt):
        calls.append(model)
        return "eligible", 0.0

    monkeypatch.setattr(panel, "call_model", respond)
    assert panel.main() == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert calls == [panel.MODELS[0]] * 2
    assert result["finish_new_calls"] == 2
    assert result["lightning_missing"] == 0
    assert result["agreement"]["complete_four_model_cases"] == 24
