"""Code-validated planning actions for the supervisor specialist."""

from collections.abc import Mapping
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import Field

from src.workflow.agent_runtime import (
    AgentActionError,
    AgentSchema,
    copy_agent_budget,
    observation,
    run_agent,
)
from src.workflow.state import Plan


class PlanProposalArguments(AgentSchema):
    """Step identifiers proposed by the supervisor; no arbitrary goals/tools."""

    step_ids: list[str] = Field(min_length=1, max_length=20)


class PlanProposalObservation(AgentSchema):
    """Code validation result shown back to the next model choice."""

    accepted: bool
    step_ids: list[str]


class FinishPlanArguments(AgentSchema):
    """A model-selected handoff after observing plan validation."""

    confirm: Literal["use_validated_plan"]


class FinishPlanObservation(AgentSchema):
    """The supervisor's typed, terminal action result."""

    finished: Literal[True]


def validate_plan_order(plan: Plan, step_ids: list[str]) -> list[str] | None:
    """Accept only the existing steps with intake dependencies preserved."""

    expected = [step.step_id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)) or set(step_ids) != set(expected):
        return None
    if not expected or step_ids[0] != "intake":
        return None
    by_id = {step.step_id: step for step in plan.steps}
    remaining = [by_id[step_id] for step_id in step_ids[1:]]
    if any(step.specialist not in {"eligibility", "search"} for step in remaining):
        return None
    if any(step.specialist == "search" for step in remaining):
        # Discovery follows intake and is never interleaved with a rule check.
        if [step.specialist for step in remaining] != ["search"]:
            return None
    return step_ids


async def propose_supervisor_plan(
    provider: BaseChatModel | None,
    plan: Plan,
    locale: Literal["en", "hi", "mr"],
    budget: Mapping[str, int] | None,
) -> tuple[Plan, dict[str, int], list[dict[str, object]], str]:
    """Let the model reorder the plan steps; code validates every proposal."""

    if provider is None:
        return plan, copy_agent_budget(budget), [], "deterministic"

    proposed_order: list[str] = []
    proposed_valid = False

    @tool(args_schema=PlanProposalArguments)
    async def propose_plan(step_ids: list[str]) -> str:
        """Propose an ordering of exactly the supplied plan steps."""
        nonlocal proposed_order, proposed_valid
        validated = validate_plan_order(plan, step_ids)
        proposed_order = validated or []
        proposed_valid = validated is not None
        return observation(PlanProposalObservation(accepted=proposed_valid, step_ids=proposed_order))

    @tool(args_schema=FinishPlanArguments, return_direct=True)
    async def finish_plan(confirm: str) -> str:
        """Finish after observing accepted plan validation."""
        if not proposed_valid:
            raise AgentActionError("There is no validated plan to finish.")
        return observation(FinishPlanObservation(finished=True))

    result = await run_agent(
        provider, "supervisor", locale,
        {"valid_step_ids": [step.step_id for step in plan.steps]},
        [propose_plan, finish_plan], budget, max_steps=2,
    )
    if result.status == "completed" and proposed_valid:
        by_id = {step.step_id: step for step in plan.steps}
        plan = plan.model_copy(update={"steps": [by_id[step_id] for step_id in proposed_order]})
        return plan, result.budget, result.trace, "model_validated"
    return plan, result.budget, result.trace, "deterministic_fallback"
