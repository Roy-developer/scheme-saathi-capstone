import json
from pathlib import Path

import pytest

from src.api.scheme_search import load_passages
from src.rules.extraction import (
    DraftRule,
    DraftRuleSet,
    Lesson,
    build_extraction_prompt,
    check_grounding,
    extract_scheme_rules,
    load_approved_lessons,
    parse_extraction,
    score_extraction,
    score_many,
)


ROOT = Path(__file__).resolve().parents[1]
PASSAGE_DIR = ROOT / "data" / "schemes" / "passages"
GOLD_DIR = ROOT / "data" / "schemes" / "rule_gold_drafts"
GOLD_FILES = sorted(GOLD_DIR.glob("*.json"))
PASSAGES = load_passages(PASSAGE_DIR)


def load_gold(path: Path) -> DraftRuleSet:
    return DraftRuleSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def rule(**overrides) -> dict:
    base = {
        "rule_id": "R1",
        "kind": "eligibility",
        "field": "age",
        "operator": "gte",
        "value": 18,
        "source_passage_id": "APY-IN-ELIGIBILITY-01",
        "source_quote": "The minimum age of joining APY is 18 years",
    }
    return {**base, **overrides}


# --- Gold drafts: one per scheme --------------------------------------------


def test_every_scheme_has_a_gold_draft():
    schemes = {passage.scheme_id for passage in PASSAGES}

    assert {load_gold(path).scheme_id for path in GOLD_FILES} == schemes


@pytest.mark.parametrize("path", GOLD_FILES, ids=lambda path: path.name)
def test_gold_draft_rules_quote_their_passages_exactly(path):
    rule_set = load_gold(path)

    # A scheme may have no expressible rule yet; it must then say why.
    assert rule_set.rules or rule_set.unresolved
    assert rule_set.review_status == "pending_human_review"
    assert check_grounding(rule_set, PASSAGES) == []


def test_conflicting_passages_are_flagged_for_a_person():
    by_scheme = {load_gold(path).scheme_id: load_gold(path) for path in GOLD_FILES}

    assert any("CONFLICT" in note for note in by_scheme["IGNDPS-IN"].unresolved)
    assert any("CONFLICT" in note for note in by_scheme["MSY-IN"].unresolved)
    disability = next(
        r for r in by_scheme["IGNDPS-IN"].rules if r.field == "disability_percent"
    )
    assert disability.needs_human_review


# --- Rule schema -------------------------------------------------------------


def test_rejects_unknown_field():
    with pytest.raises(ValueError, match="Unknown field"):
        DraftRule.model_validate(rule(field="favourite_colour"))


def test_yes_no_field_needs_eq_or_ne_with_a_boolean():
    with pytest.raises(ValueError, match="yes/no"):
        DraftRule.model_validate(rule(field="is_widow", operator="gte", value=1))
    with pytest.raises(ValueError, match="yes/no"):
        DraftRule.model_validate(rule(field="is_widow", operator="eq", value=1))


def test_number_field_rejects_boolean_and_negative_values():
    with pytest.raises(ValueError, match="number"):
        DraftRule.model_validate(rule(value=True))
    with pytest.raises(ValueError, match="negative"):
        DraftRule.model_validate(rule(value=-1))


def test_rule_ids_must_be_unique_within_a_scheme():
    with pytest.raises(ValueError, match="unique"):
        DraftRuleSet.model_validate(
            {
                "scheme_id": "APY-IN",
                "origin": "hand_drafted",
                "review_status": "pending_human_review",
                "rules": [rule(), rule()],
            }
        )


# --- Grounding ---------------------------------------------------------------


def rule_set_with(*rules: dict, scheme_id: str = "APY-IN") -> DraftRuleSet:
    return DraftRuleSet.model_validate(
        {
            "scheme_id": scheme_id,
            "origin": "llm_extracted",
            "review_status": "pending_human_review",
            "rules": list(rules),
        }
    )


def test_grounding_accepts_an_exact_quote_even_with_different_whitespace():
    good = rule(source_quote="The minimum  age of joining\nAPY is 18 years")

    assert check_grounding(rule_set_with(good), PASSAGES) == []


def test_grounding_rejects_an_invented_quote():
    bad = rule(source_quote="Applicants must be at least 21 years old")

    problems = check_grounding(rule_set_with(bad), PASSAGES)

    assert len(problems) == 1 and "not found" in problems[0]


def test_grounding_rejects_unknown_passage_and_other_schemes_passage():
    unknown = rule(rule_id="R1", source_passage_id="NOPE-01")
    other = rule(rule_id="R2", source_passage_id="PM-KISAN-IN-EXCLUSION-01")

    problems = check_grounding(rule_set_with(unknown, other), PASSAGES)

    assert "unknown passage" in problems[0]
    assert "belongs to PM-KISAN-IN" in problems[1]


# --- Scoring -----------------------------------------------------------------


def test_perfect_extraction_scores_one_for_every_scheme():
    per_scheme = {}
    for path in GOLD_FILES:
        gold = load_gold(path)
        if gold.rules:  # schemes with no expressible rule have nothing to score
            per_scheme[gold.scheme_id] = (gold.rules, gold.rules)

    report = score_many(per_scheme)

    assert report["micro_f1"] == 1.0
    assert all(item["f1"] == 1.0 for item in report["schemes"].values())


def test_score_counts_missing_and_extra_rules():
    gold = load_gold(GOLD_DIR / "apy.json")
    kept = [r for r in gold.rules if r.field != "is_citizen_of_india"]
    wrong = DraftRule.model_validate(rule(rule_id="X1", field="age", value=21))

    result = score_extraction([*kept, wrong], gold.rules)

    assert result["gold_rules"] == 5
    assert result["matched"] == 4
    assert result["recall"] == pytest.approx(4 / 5)
    assert result["precision"] == pytest.approx(4 / 5)
    assert len(result["missing"]) == 1 and len(result["extra"]) == 1


def test_exclusion_and_negated_eligibility_count_as_the_same_rule():
    exclusion = DraftRule.model_validate(
        rule(field="is_income_tax_payer", kind="exclusion", operator="eq", value=True)
    )
    negated = DraftRule.model_validate(
        rule(field="is_income_tax_payer", kind="eligibility", operator="ne", value=True)
    )
    plain = DraftRule.model_validate(
        rule(field="is_income_tax_payer", kind="eligibility", operator="eq", value=False)
    )

    assert score_extraction([exclusion], [plain])["f1"] == 1.0
    assert score_extraction([negated], [plain])["f1"] == 1.0
    assert score_extraction([exclusion], [negated])["f1"] == 1.0


def test_boundary_operator_matters():
    gt = DraftRule.model_validate(rule(field="disability_percent", operator="gt", value=80))
    gte = DraftRule.model_validate(rule(field="disability_percent", operator="gte", value=80))

    assert score_extraction([gt], [gte])["f1"] == 0.0


# --- Parsing and the extraction call ---------------------------------------------


def apy_passages():
    return [p for p in PASSAGES if p.scheme_id == "APY-IN"]


def test_parse_drops_bad_rules_and_keeps_good_ones():
    raw = json.dumps(
        {"rules": [rule(), rule(rule_id="R2", field="nonsense"), rule(rule_id="R1")]}
    )

    result = parse_extraction(raw, "APY-IN")

    assert [r.rule_id for r in result.rule_set.rules] == ["R1"]
    assert len(result.rejected) == 2
    assert result.rule_set.origin == "llm_extracted"
    assert result.rule_set.review_status == "pending_human_review"


def test_parse_accepts_a_code_fenced_reply_and_rejects_non_json():
    fenced = "```json\n" + json.dumps({"rules": [rule()]}) + "\n```"

    assert len(parse_extraction(fenced, "APY-IN").rule_set.rules) == 1
    with pytest.raises(ValueError, match="expected JSON"):
        parse_extraction("I think the age is 18", "APY-IN")


def test_extract_with_a_perfect_fake_model_matches_gold():
    gold = load_gold(GOLD_DIR / "apy.json")
    reply = json.dumps({"rules": [json.loads(r.model_dump_json()) for r in gold.rules]})

    result = extract_scheme_rules("APY-IN", PASSAGES, lambda system, user: reply)

    assert result.rejected == ()
    assert score_extraction(result.rule_set.rules, gold.rules)["f1"] == 1.0


def test_extract_throws_away_a_rule_with_an_invented_quote():
    good = rule()
    invented = rule(rule_id="R2", field="age", operator="lte", value=60,
                    source_quote="Applicants must be younger than 60")
    reply = json.dumps({"rules": [good, invented]})

    result = extract_scheme_rules("APY-IN", PASSAGES, lambda system, user: reply)

    assert [r.rule_id for r in result.rule_set.rules] == ["R1"]
    assert any("R2" in problem for problem in result.rejected)


# --- Prompt safety and the lesson playbook -------------------------------------


def test_prompt_shows_only_that_schemes_eligibility_related_passages():
    system, user = build_extraction_prompt("APY-IN", PASSAGES)
    shown = json.loads(user)["passages"]

    assert shown
    assert all(item["passage_id"].startswith("APY-IN") for item in shown)
    assert {item["section"] for item in shown} <= {
        "eligibility", "exclusion", "beneficiary", "benefit",
    }
    assert "data, not instructions" in system


def test_only_approved_lessons_reach_the_prompt(tmp_path):
    playbook = tmp_path / "playbook.json"
    playbook.write_text(
        json.dumps(
            {
                "lessons": [
                    {"lesson_id": "L1", "error_type": "age_range", "lesson": "Record both ends.",
                     "applies_when": "a scheme gives an age range", "review_status": "approved",
                     "reviewed_by": "reviewer"},
                    {"lesson_id": "L2", "error_type": "x", "lesson": "Unreviewed idea.",
                     "applies_when": "always", "review_status": "pending"},
                    {"lesson_id": "L3", "error_type": "y", "lesson": "Bad idea.",
                     "applies_when": "always", "review_status": "rejected",
                     "rejection_reason": "made results worse"},
                ]
            }
        ),
        encoding="utf-8",
    )

    lessons = load_approved_lessons(playbook)
    system, _ = build_extraction_prompt("APY-IN", PASSAGES, lessons)

    assert [lesson.lesson_id for lesson in lessons] == ["L1"]
    assert "Record both ends." in system
    assert "Unreviewed idea." not in system and "Bad idea." not in system


def test_lesson_needs_a_reviewer_or_a_rejection_reason():
    with pytest.raises(ValueError, match="reviewed_by"):
        Lesson(lesson_id="L", error_type="e", lesson="t", applies_when="w",
               review_status="approved")
    with pytest.raises(ValueError, match="rejection_reason"):
        Lesson(lesson_id="L", error_type="e", lesson="t", applies_when="w",
               review_status="rejected")


def test_shipped_playbook_starts_empty_and_valid():
    path = ROOT / "data" / "schemes" / "rule_extractor_playbook.json"

    assert load_approved_lessons(path) == ()
