"""Test the on-demand Reflexion commands offline (fake model, temporary store)."""

import asyncio
import json
from pathlib import Path

import pytest

from src.rule_extraction_reflexion import scheme_rules
from src.rule_extraction_reflexion import extractor, reflexion
from src.rule_extraction_reflexion.models import LessonText, RuleExtractionOutput


def _fake_model_answers(monkeypatch, module, answers, prompts=None) -> None:
    async def fake_invoke(_model, output_schema, _system, user_text):
        if prompts is not None:
            prompts.append(user_text)
        answer = answers.pop(0)
        return answer if isinstance(answer, output_schema) else output_schema.model_validate(answer)

    monkeypatch.setattr(module, "invoke_structured_output", fake_invoke)


def _cases_file(tmp_path: Path, learn_clause: str | None) -> Path:
    data = scheme_rules.load_case_file()
    for entry in data["cases"]:
        entry["split"] = "learn" if entry["clause_id"] == learn_clause else "check"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_every_listed_clause_builds_a_case_from_its_approved_package() -> None:
    cases = scheme_rules.build_cases()

    assert len(cases) == 10
    for case in cases:
        assert case.expected_rules and case.topic_tags
        # The approved line comes last; any headings it sits under come first.
        assert case.clauses[0].text.endswith(case.expected_rules[0].source_text)
    ignwps = next(case for case in cases if case.case_id == "IGNWPS-MH-ELIGIBILITY-01")
    assert len(ignwps.expected_rules) == 4


def test_list_item_is_shown_under_the_headings_it_sits_under() -> None:
    """Income tax is item v) under 4.1 ("shall not be eligible") and 4.1(b)."""
    case = next(
        case for case in scheme_rules.build_cases()
        if case.case_id == "PMKISAN-GUIDELINES-2020-4.1(b)(v)"
    )

    assert case.clauses[0].text.splitlines() == [
        "4.1 The following categories of beneficiaries of higher economic status "
        "shall not be eligible for benefit under the scheme:",
        "(b) Farmer families in which one or more of its members belong to following categories :",
        "All Persons who paid Income Tax in last assessment year.",
    ]


def test_clause_without_context_is_shown_as_approved() -> None:
    case = next(
        case for case in scheme_rules.build_cases()
        if case.case_id == "PMKISAN-GUIDELINES-2020-3"
    )

    assert case.clauses[0].text == case.expected_rules[0].source_text


def test_unknown_context_name_is_reported(tmp_path) -> None:
    data = scheme_rules.load_case_file()
    data["cases"][0]["context"] = ["NO-SUCH-HEADING"]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown context"):
        scheme_rules.build_cases(path=path)


def test_learn_refuses_until_a_learn_split_is_assigned(monkeypatch, tmp_path) -> None:
    """Unassigned and check clauses are never learned from."""
    data = scheme_rules.load_case_file()
    for entry in data["cases"]:
        entry["split"] = None
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(scheme_rules, "CASES_FILE", path)
    monkeypatch.setattr(scheme_rules, "project_model", lambda: pytest.fail("no model call expected"))

    with pytest.raises(SystemExit, match="split"):
        scheme_rules.main(["learn", "--yes"])


def test_paid_commands_send_nothing_without_yes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(scheme_rules, "project_model", lambda: pytest.fail("no model call expected"))

    scheme_rules.main(["evaluate", "--runs", "3"])

    expected = 3 * len(scheme_rules.build_cases())
    assert f"up to {expected} OpenRouter model call(s)" in capsys.readouterr().out


def test_learn_review_freeze_then_evaluate_uses_the_lesson(monkeypatch, tmp_path) -> None:
    """The whole on-demand loop, run through the script's own commands."""
    clause = "PMKISAN-GUIDELINES-2020-4.1(a)"
    cases_path = _cases_file(tmp_path, learn_clause=clause)
    store = tmp_path / "lessons.sqlite3"
    registry = scheme_rules.load_registry()
    (learn_case,) = scheme_rules.build_cases("learn", path=cases_path)
    approved = learn_case.expected_rules[0]

    # A typical exclusion mistake: "institutional landholders are excluded" written as eq True.
    _fake_model_answers(monkeypatch, extractor, [RuleExtractionOutput(
        rules=(approved.model_copy(update={"value": True}),),
    )])
    _fake_model_answers(monkeypatch, reflexion, [LessonText(
        instruction="For an exclusion, write who qualifies: fact eq false.",
        when_to_apply="The clause says a group is not eligible.",
    )])
    (lesson_id,) = asyncio.run(scheme_rules.learn(None, [learn_case], registry, store_path=store))

    with pytest.raises(PermissionError):
        asyncio.run(scheme_rules.review(
            lesson_id, approve=True, reviewer="the model", reason="self-approval",
            authorized=lambda reviewer: reviewer == "Roy-developer", store_path=store,
        ))
    asyncio.run(scheme_rules.review(
        lesson_id, approve=True, reviewer="Roy-developer", reason="Correct and general.",
        authorized=lambda reviewer: reviewer == "Roy-developer", store_path=store,
    ))
    assert asyncio.run(scheme_rules.freeze("1.0.0", store_path=store)) == 1

    check_cases = [
        case for case in scheme_rules.build_cases("check", path=cases_path)
        if "exclusion_clause" in case.topic_tags
    ][:1]
    prompts: list[str] = []
    _fake_model_answers(monkeypatch, extractor, [RuleExtractionOutput(
        rules=check_cases[0].expected_rules,
    )], prompts)
    summary = asyncio.run(scheme_rules.evaluate(
        None, check_cases, registry, runs=1, playbook_version="1.0.0",
        store_path=store, report_dir=tmp_path / "reports",
    ))

    assert summary["exact"] == summary["total"] == 1
    assert "For an exclusion, write who qualifies" in prompts[0]


def test_rejected_answer_report_shows_exactly_what_the_model_wrote(monkeypatch, tmp_path) -> None:
    """The pension clause was rejected, but the shortened message hid the answer."""
    (case,) = [
        case for case in scheme_rules.build_cases()
        if case.case_id == "PMKISAN-GUIDELINES-2020-4.1(b)(iv)"
    ]
    model_rule = {
        "rule_id": "not_eligible_pensioners",
        "field": "pension_at_least_10000_excluding_stated_grades",
        "operator": "gte", "value": 10000, "unit": "INR",
        "source_clause_id": case.case_id,
    }
    _fake_model_answers(monkeypatch, extractor, [{"rules": [model_rule]}])

    summary = asyncio.run(scheme_rules.evaluate(
        None, [case], scheme_rules.load_registry(), runs=1, playbook_version=None,
        report_dir=tmp_path,
    ))

    (row,) = summary["rows"]
    assert row["status"] == "rejected"
    assert '"operator": "gte"' in row["detail"] and '"value": 10000' in row["detail"]



IGNOAPS_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "data" / "schemes" / "rule_extraction_sources" / "ignoaps_mh.json"
)


def test_new_scheme_source_builds_cases_without_an_answer_key() -> None:
    _source, (case,) = scheme_rules.build_source_cases(IGNOAPS_SOURCE)

    assert case.expected_rules == ()
    assert case.allowed_fact_ids == ("age", "name_on_bpl_list")
    assert case.clauses[0].text.startswith("Eligible elderly individuals aged 65 and above")


def test_extract_saves_a_draft_marked_not_policy(monkeypatch, tmp_path) -> None:
    """A new scheme: the model drafts rules, nothing is compared or approved."""
    source, cases = scheme_rules.build_source_cases(IGNOAPS_SOURCE)
    rules = [
        {"rule_id": "r1", "field": "age", "operator": "gte", "value": 65, "unit": "years",
         "source_clause_id": "IGNOAPS-MH-ELIGIBILITY-01"},
        {"rule_id": "r2", "field": "name_on_bpl_list", "operator": "eq", "value": True,
         "source_clause_id": "IGNOAPS-MH-ELIGIBILITY-01"},
    ]
    _fake_model_answers(monkeypatch, extractor, [{"rules": rules}])

    record = asyncio.run(scheme_rules.extract(
        None, source, cases, scheme_rules.load_registry(), playbook_version=None,
        draft_dir=tmp_path,
    ))

    assert record["status"] == "draft_for_human_review_not_policy"
    (clause,) = record["clauses"]
    assert clause["status"] == "drafted"
    assert {(r["field"], r["operator"], r["value"]) for r in clause["draft_rules"]} == {
        ("age", "gte", 65), ("name_on_bpl_list", "eq", True),
    }
    saved = json.loads(next(tmp_path.glob("ignoaps-mh_*.json")).read_text(encoding="utf-8"))
    assert saved == record


def test_extract_only_reads_new_scheme_files_with_declared_tags(tmp_path) -> None:
    data = json.loads(IGNOAPS_SOURCE.read_text(encoding="utf-8"))
    data["cases"][0]["topic_tags"] = ["made_up_tag"]
    path = tmp_path / "source.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Undeclared topic tags"):
        scheme_rules.build_source_cases(path)


def test_ignoaps_answer_key_comes_from_the_live_package_and_is_hash_checked(tmp_path) -> None:
    """The cases file pins IGNOAPS's package hash, so an edited package is refused."""
    (case,) = [c for c in scheme_rules.build_cases() if c.case_id == "IGNOAPS-MH-ELIGIBILITY-01"]
    assert {(r.field, r.operator, r.value) for r in case.expected_rules} == {
        ("age", "gte", 65), ("name_on_bpl_list", "eq", True),
    }

    data = scheme_rules.load_case_file()
    entry = next(e for e in data["cases"] if e["clause_id"] == "IGNOAPS-MH-ELIGIBILITY-01")
    entry["package_sha256"] = "0" * 64
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Package hash mismatch"):
        scheme_rules.build_cases(path=path)

