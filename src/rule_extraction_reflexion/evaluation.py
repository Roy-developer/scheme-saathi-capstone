"""Score extraction cases against supplied gold rules without changing a playbook."""

from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel

from src.rules.facts import FactRegistry
from src.rule_extraction_reflexion.extraction_checker import compare_rules
from src.rule_extraction_reflexion.extractor import extract_rules
from src.rule_extraction_reflexion.models import (
    EvaluationCaseResult,
    PlaybookEvaluation,
    PlaybookSnapshot,
    RuleDifference,
    RuleExtractionCase,
)
from src.rule_extraction_reflexion.playbook import verify_playbook


MAX_EVALUATION_CASES = 60


async def evaluate_cases(
    model: BaseChatModel,
    cases: Sequence[RuleExtractionCase],
    registry: FactRegistry,
    *,
    playbook: PlaybookSnapshot | None = None,
) -> PlaybookEvaluation:
    """Run one extraction per supplied case and report exact rule matches.

    The caller supplies cases explicitly. This function never opens evaluation
    files or modifies the frozen playbook. Use only development cases until an
    independent evaluation owner authorizes a protected held-out run.
    """
    if not cases:
        raise ValueError("At least one evaluation case is required")
    if len(cases) > MAX_EVALUATION_CASES:
        raise ValueError("Evaluation case limit exceeded")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case IDs must be unique")
    if playbook is not None:
        verify_playbook(playbook)

    results: list[EvaluationCaseResult] = []
    exact_match_count = 0
    for case in cases:
        proposed = await extract_rules(
            model,
            case,
            registry,
            playbook=playbook,
        )
        differences = compare_rules(
            case.expected_rules,
            proposed,
            boolean_exclusion_rule_ids=case.boolean_exclusion_rule_ids,
        )
        case_differences = tuple(
            RuleDifference(rule_id=rule_id, attributes=tuple(attributes))
            for rule_id, attributes in sorted(differences.items())
        )
        exact_match = not differences
        exact_match_count += int(exact_match)
        results.append(EvaluationCaseResult(
            case_id=case.case_id,
            exact_match=exact_match,
            differences=case_differences,
        ))

    return PlaybookEvaluation(
        playbook_version=playbook.version if playbook else None,
        playbook_hash=playbook.content_hash if playbook else None,
        case_count=len(cases),
        exact_match_count=exact_match_count,
        model_call_count=len(cases),
        results=tuple(results),
    )
