"""Validate E1 controls and summarize measured development-run observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, isfinite
from statistics import median
from typing import Literal


ARM_IDS = ("C0", "C1", "C2")
DEVELOPMENT_CASE_IDS = (
    "IGNWPS-DEV-001",
    "IGNWPS-DEV-003",
    "IGNWPS-DEV-007",
)
DEVELOPMENT_SET_PATH = "eval/development/personas_v1.json"
UsageKind = Literal["actual", "estimated", "unknown"]
OutcomeSource = Literal[
    "deterministic_workflow", "scripted_model", "live_model", "unknown",
]


@dataclass(frozen=True)
class BudgetCeilings:
    """Conversation budget limits shared by all comparison arms."""

    model_calls: int
    agent_tool_calls: int
    domain_calls: int
    agent_steps: int
    total_tokens: int


EVIDENCE_LABEL = "development_only_not_model_quality_evidence"


def shared_budget_ceilings() -> BudgetCeilings:
    """Derive the conversation budget from src/workflow/agent_config.py at call time."""

    from src.workflow import agent_config

    return BudgetCeilings(
        model_calls=agent_config.MAX_CONVERSATION_MODEL_CALLS,
        agent_tool_calls=agent_config.MAX_CONVERSATION_TOOL_CALLS,
        domain_calls=agent_config.MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
        agent_steps=agent_config.MAX_CONVERSATION_AGENT_STEPS,
        total_tokens=agent_config.MAX_CONVERSATION_TOKENS,
    )


def shared_single_agent_capabilities() -> frozenset[str]:
    """Return the C1 tool set from src/workflow/single_agent.py SINGLE_AGENT_TOOLS."""

    from src.workflow import single_agent

    return frozenset(single_agent.SINGLE_AGENT_TOOLS)


@dataclass(frozen=True)
class ArmControls:
    """Comparable model, capability, and safety controls for one arm."""

    arm_id: str
    model_id: str | None
    model_mode: Literal["none", "scripted", "live"]
    capabilities: frozenset[str]
    budget: BudgetCeilings
    eligibility_decider: str
    approval_policy: str


@dataclass(frozen=True)
class DevelopmentSetControls:
    """Provenance flags required before any E1 execution."""

    split: str
    protected: bool
    synthetic_only: bool
    dataset_version: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class TokenPricing:
    """Explicit model-specific token prices, in USD per million tokens."""

    model_id: str
    input_usd_per_million: float
    output_usd_per_million: float


@dataclass(frozen=True)
class CaseObservation:
    """One arm's observed result for one development case."""

    case_id: str
    arm_id: str
    task_success: bool | None
    outcome_source: OutcomeSource
    policy_violations: int | None
    latency_ms: float | None
    model_calls: int | None
    domain_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    usage_kind: UsageKind
    error: bool = False
    timeout: bool = False
    agent_steps: int | None = None
    agent_tool_calls: int | None = None
    reserved_input_tokens: int | None = None
    reserved_output_tokens: int | None = None


def comparability_blockers(
    arms: tuple[ArmControls, ...],
    dataset: DevelopmentSetControls,
) -> list[str]:
    """Return prerequisites that prevent a defensible comparison."""

    blockers: list[str] = []
    by_id = {arm.arm_id: arm for arm in arms}
    if len(by_id) != len(arms) or set(by_id) != set(ARM_IDS):
        blockers.append("Exactly one C0, C1, and C2 configuration is required.")
        return blockers

    if dataset.split != "development" or dataset.protected or not dataset.synthetic_only:
        blockers.append("Only unprotected synthetic development cases are allowed.")

    c0, c1, c2 = (by_id[arm_id] for arm_id in ARM_IDS)
    if c0.model_mode != "none" or c0.model_id is not None:
        blockers.append("C0 must identify its model as unused.")
    if c1.model_mode == "none" or c2.model_mode == "none":
        blockers.append("C1 and C2 must both use a model.")
    if not c1.model_id or c1.model_id != c2.model_id:
        blockers.append("C1 and C2 must pin the same nonempty model identifier.")
    if c1.model_mode != c2.model_mode:
        blockers.append("C1 and C2 must use the same live or scripted model mode.")
    if not c0.capabilities or any(not arm.capabilities for arm in (c1, c2)):
        blockers.append("All arms must declare their available domain capabilities.")
    elif not (c0.capabilities == c1.capabilities == c2.capabilities):
        blockers.append("Domain capabilities must be equivalent across all arms.")
    shared_caps = shared_single_agent_capabilities()
    if any(arm.capabilities != shared_caps for arm in arms):
        blockers.append(
            "Declared capabilities differ from the shared SINGLE_AGENT_TOOLS set.",
        )
    if not (c0.budget == c1.budget == c2.budget):
        blockers.append("Model, domain-call, step, and token ceilings must match.")
    shared_budget = shared_budget_ceilings()
    if any(arm.budget != shared_budget for arm in arms):
        blockers.append(
            "Declared budget ceilings differ from the shared agent_config constants.",
        )
    if any(
        ceiling <= 0
        for arm in arms
        for ceiling in (
            arm.budget.model_calls,
            arm.budget.agent_tool_calls,
            arm.budget.domain_calls,
            arm.budget.agent_steps,
            arm.budget.total_tokens,
        )
    ):
        blockers.append("All shared budget ceilings must be positive.")
    if len({arm.eligibility_decider for arm in arms}) != 1 or any(
        arm.eligibility_decider != "rule_engine" for arm in arms
    ):
        blockers.append("Every arm must use the deterministic rule engine.")
    if len({arm.approval_policy for arm in arms}) != 1 or any(
        arm.approval_policy != "separate_exact_human_approval" for arm in arms
    ):
        blockers.append("Every arm must retain separate exact human approval.")
    return blockers


def _accounting_blockers(observations: tuple[CaseObservation, ...]) -> list[str]:
    """Check recorded counters against the shared per-conversation ceilings."""

    from src.workflow import agent_config

    blockers: list[str] = []
    for row in observations:
        if row.arm_id == "C0" and (
            (row.model_calls or 0) > 0
            or (row.input_tokens or 0) > 0
            or (row.output_tokens or 0) > 0
        ):
            blockers.append("C0 is model-free but recorded model calls or tokens.")
        if row.model_calls is not None and row.model_calls > agent_config.MAX_CONVERSATION_MODEL_CALLS:
            blockers.append("Observed model calls exceed the shared model-call ceiling.")
        if row.agent_tool_calls is not None and row.agent_tool_calls > agent_config.MAX_CONVERSATION_TOOL_CALLS:
            blockers.append("Observed agent tool calls exceed the shared tool-call ceiling.")
        if row.domain_calls is not None and row.domain_calls > agent_config.MAX_CONVERSATION_DOMAIN_TOOL_CALLS:
            blockers.append("Observed domain calls exceed the shared domain-call ceiling.")
        if row.agent_steps is not None and row.agent_steps > agent_config.MAX_CONVERSATION_AGENT_STEPS:
            blockers.append("Observed agent steps exceed the shared step ceiling.")
        if (
            row.input_tokens is not None
            and row.output_tokens is not None
            and row.input_tokens + row.output_tokens > agent_config.MAX_CONVERSATION_TOKENS
        ):
            blockers.append("Observed tokens exceed the shared token ceiling.")
    return sorted(set(blockers))


def _p95(values: list[float]) -> float | None:
    """Return nearest-rank p95 for a nonempty sample."""

    if not values:
        return None
    return sorted(values)[ceil(0.95 * len(values)) - 1]


def summarize_arm(
    arm: ArmControls,
    observations: tuple[CaseObservation, ...],
    *,
    pricing: TokenPricing | None,
) -> dict[str, object]:
    """Summarize only observed measures; unavailable usage stays unknown."""

    rows = [row for row in observations if row.arm_id == arm.arm_id]
    successes = [row.task_success for row in rows if row.task_success is not None]
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    policy_counts = [
        row.policy_violations for row in rows if row.policy_violations is not None
    ]
    no_model_used = bool(rows) and arm.model_mode == "none" and all(
        row.model_calls == 0 for row in rows
    )
    measured_usage = bool(rows) and (no_model_used or all(
        row.usage_kind == "actual"
        and row.input_tokens is not None
        and row.output_tokens is not None
        for row in rows
    ))
    model_calls = (
        sum(row.model_calls for row in rows if row.model_calls is not None)
        if all(row.model_calls is not None for row in rows)
        else None
    )
    agent_steps = (
        sum(row.agent_steps for row in rows if row.agent_steps is not None)
        if all(row.agent_steps is not None for row in rows)
        else None
    )
    agent_tool_calls = (
        sum(row.agent_tool_calls for row in rows if row.agent_tool_calls is not None)
        if all(row.agent_tool_calls is not None for row in rows)
        else None
    )
    domain_calls = (
        sum(row.domain_calls for row in rows if row.domain_calls is not None)
        if all(row.domain_calls is not None for row in rows)
        else None
    )
    input_tokens = 0 if no_model_used else (
        sum(row.input_tokens for row in rows if row.input_tokens is not None)
        if measured_usage
        else None
    )
    output_tokens = 0 if no_model_used else (
        sum(row.output_tokens for row in rows if row.output_tokens is not None)
        if measured_usage
        else None
    )
    reserved_input_tokens = (
        sum(row.reserved_input_tokens for row in rows if row.reserved_input_tokens is not None)
        if rows and all(row.reserved_input_tokens is not None for row in rows)
        else None
    )
    reserved_output_tokens = (
        sum(row.reserved_output_tokens for row in rows if row.reserved_output_tokens is not None)
        if rows and all(row.reserved_output_tokens is not None for row in rows)
        else None
    )
    cost_usd: float | None = 0.0 if no_model_used else None
    if (
        not no_model_used
        and pricing is not None
        and measured_usage
        and input_tokens is not None
        and output_tokens is not None
    ):
        cost_usd = (
            input_tokens * pricing.input_usd_per_million
            + output_tokens * pricing.output_usd_per_million
        ) / 1_000_000

    return {
        "case_count": len(rows),
        "task_success_count": sum(successes) if successes else None,
        "task_success_rate": (
            sum(successes) / len(successes) if successes else None
        ),
        "outcome_sources": sorted({row.outcome_source for row in rows}),
        "policy_violations": sum(policy_counts) if policy_counts else None,
        "latency_ms": {
            "median": median(latencies) if latencies else None,
            "p95": _p95(latencies),
            "measured_case_count": len(latencies),
        },
        "model_calls": model_calls,
        "agent_steps": agent_steps,
        "agent_tool_calls": agent_tool_calls,
        "domain_calls": domain_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reserved_input_tokens_estimate": reserved_input_tokens,
        "reserved_output_tokens_ceiling": reserved_output_tokens,
        "cost_usd": cost_usd,
        "usage_status": (
            "no_model_provider_in_this_arm"
            if no_model_used
            else "actual_provider_usage"
            if measured_usage and rows
            else "unknown_not_priced_or_not_provider_reported"
        ),
        "errors": sum(row.error for row in rows),
        "timeouts": sum(row.timeout for row in rows),
    }


def build_report(
    arms: tuple[ArmControls, ...],
    dataset: DevelopmentSetControls,
    observations: tuple[CaseObservation, ...],
    *,
    expected_case_ids: tuple[str, ...],
    pricing: TokenPricing | None = None,
) -> dict[str, object]:
    """Build a fail-closed report with no unsupported usage or cost claims."""

    blockers = comparability_blockers(arms, dataset)
    if not expected_case_ids or len(set(expected_case_ids)) != len(expected_case_ids):
        blockers.append("Expected development case IDs must be unique and nonempty.")
    if pricing is not None and (
        not pricing.model_id
        or not isfinite(pricing.input_usd_per_million)
        or not isfinite(pricing.output_usd_per_million)
        or pricing.input_usd_per_million < 0
        or pricing.output_usd_per_million < 0
    ):
        blockers.append("Model-specific token prices must be valid and nonnegative.")
    allowed_arms = {arm.arm_id for arm in arms}
    if any(row.arm_id not in allowed_arms for row in observations):
        blockers.append("An observation refers to an undeclared comparison arm.")
    if any(
        not row.case_id
        or (row.latency_ms is not None and (
            not isfinite(row.latency_ms) or row.latency_ms < 0
        ))
        or any(
            value is not None and value < 0
            for value in (
                row.policy_violations,
                row.model_calls,
                row.agent_steps,
                row.agent_tool_calls,
                row.domain_calls,
                row.input_tokens,
                row.output_tokens,
                row.reserved_input_tokens,
                row.reserved_output_tokens,
            )
        )
        for row in observations
    ):
        blockers.append("Observed counters and latency must be nonnegative and finite.")
    blockers.extend(_accounting_blockers(observations))
    observations_by_key = [
        (row.arm_id, row.case_id) for row in observations
    ]
    if len(set(observations_by_key)) != len(observations_by_key):
        blockers.append("Each arm may record only one result per case.")
    expected_pairs = {
        (arm_id, case_id)
        for arm_id in ARM_IDS
        for case_id in expected_case_ids
    }
    if set(observations_by_key) != expected_pairs:
        blockers.append("Every arm must have exactly one observation for each case.")

    pricing_by_arm = {
        arm.arm_id: (
            pricing
            if pricing is not None and arm.model_id == pricing.model_id
            else None
        )
        for arm in arms
    }
    return {
        "experiment_id": "E1",
        "evidence_label": EVIDENCE_LABEL,
        "shared_constants": {
            "budget_ceilings": asdict(shared_budget_ceilings()),
            "c1_capabilities": sorted(shared_single_agent_capabilities()),
        },
        "status": "blocked" if blockers else "observed",
        "complete": not blockers,
        "comparable": not blockers,
        "blockers": blockers,
        "expected_case_ids": list(expected_case_ids),
        "recorded_observation_count": len(observations),
        "dataset": {
            "split": dataset.split,
            "protected": dataset.protected,
            "synthetic_only": dataset.synthetic_only,
            "dataset_version": dataset.dataset_version,
            "source": dataset.source,
        },
        "configurations": {
            arm.arm_id: {
                "model_id": arm.model_id,
                "model_mode": arm.model_mode,
                "capabilities": sorted(arm.capabilities),
                "budget_ceilings": asdict(arm.budget),
                "eligibility_decider": arm.eligibility_decider,
                "approval_policy": arm.approval_policy,
            }
            for arm in arms
        },
        "arms": {
            arm.arm_id: summarize_arm(
                arm,
                observations,
                pricing=pricing_by_arm[arm.arm_id],
            )
            for arm in arms
        },
        "per_observation": [asdict(row) for row in observations],
        "model_quality_claim": (
            "not_measured_scripted_outputs_are_functional_tests_only"
            if any(arm.model_mode == "scripted" for arm in arms)
            else
            "development_outcome_observations_only_not_generalizable"
            if any(arm.model_mode == "live" for arm in arms)
            else "model_quality_not_applicable_to_model_free_arms"
        ),
        "cost_claim": (
            "provider_usage_and_model_specific_price_required"
            if pricing is None or not observations or any(
                row.usage_kind != "actual" for row in observations
                if row.arm_id != "C0"
            ) or any(
                row.input_tokens is None or row.output_tokens is None
                for row in observations if row.arm_id != "C0"
            ) or any(
                arm.model_id != pricing.model_id
                for arm in arms if arm.arm_id != "C0"
            )
            else "computed_from_provider_reported_tokens_and_pinned_price"
        ),
    }
