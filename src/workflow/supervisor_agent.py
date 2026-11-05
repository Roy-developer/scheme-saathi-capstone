"""Code-validated planning actions for the supervisor specialist."""

from collections.abc import Mapping
from typing import Literal

from pydantic import Field
from langchain_core.language_models import BaseChatModel

from src.workflow.agent_runtime import (
    AgentAction,
    AgentActionError,
    AgentSchema,
    copy_agent_budget,
    run_react_loop,
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
    """Run the planner proposal when configured, otherwise keep the C0 plan."""

    if provider is None:
        return plan, copy_agent_budget(budget), [], "deterministic"

    proposed_order: list[str] = []
    proposed_valid = False

    async def propose(arguments: AgentSchema) -> AgentSchema:
        nonlocal proposed_order, proposed_valid
        if not isinstance(arguments, PlanProposalArguments):
            raise AgentActionError("Invalid plan proposal input.")
        validated = validate_plan_order(plan, arguments.step_ids)
        if validated is None:
            proposed_order = []
            proposed_valid = False
            return PlanProposalObservation(accepted=False, step_ids=[])
        proposed_order = validated
        proposed_valid = True
        return PlanProposalObservation(accepted=True, step_ids=validated)

    async def finish(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, FinishPlanArguments) or not proposed_valid:
            raise AgentActionError("There is no validated plan to finish.")
        return FinishPlanObservation(finished=True)

    result = await run_react_loop(
        "supervisor",
        "supervisor",
        locale,
        {"valid_step_ids": [step.step_id for step in plan.steps]},
        [
            AgentAction(
                "propose_plan",
                "Propose an ordering of exactly the supplied plan steps.",
                "supervisor",
                PlanProposalArguments,
                PlanProposalObservation,
                propose,
            ),
            AgentAction(
                "finish_plan",
                "Finish after observing accepted plan validation.",
                "supervisor",
                FinishPlanArguments,
                FinishPlanObservation,
                finish,
                terminal=True,
            ),
        ],
        provider,
        budget,
        max_steps=2,
    )
    if result.status == "completed" and proposed_valid:
        by_id = {step.step_id: step for step in plan.steps}
        plan = plan.model_copy(update={
            "steps": [by_id[step_id] for step_id in proposed_order]
        })
        return plan, result.budget, result.trace, "model_validated"
    return plan, result.budget, result.trace, "deterministic_fallback"
