"""Plan building and step tracking for the supervisor agent.

The supervisor is the manager. It writes a visible plan, hands each step to
one specialist, and moves to the next step when that specialist reports
back. These are pure functions (no graph, no I/O), so they are easy to test.
"""

from typing import Literal

from src.workflow.state import Plan, PlanStep, SpecialistName


# Statuses that mean a specialist finished its step successfully. Any other
# status (for example "invalid_input") stops the plan early.
SUCCESS_STATUSES: dict[str, frozenset[str]] = {
    "intake": frozenset({"ready_for_eligibility", "searching"}),
    "search": frozenset({"search_results"}),
    "eligibility": frozenset(
        {"eligible", "not_eligible", "need_more_information"}
    ),
}


def build_initial_plan(
    action: Literal["search", "evaluate", "interview"],
    scheme_id: str | None = None,
) -> Plan:
    """Create the first plan for a request, with the first step started.

    Example for an interview about widow pension:
        1. intake       "Learn about you"            (in_progress)
        2. eligibility  "Check the rules for IGNWPS-MH" (pending)
    """

    if action == "search":
        steps = [
            PlanStep(
                step_id="intake",
                specialist="intake",
                goal="Understand your request",
            ),
            PlanStep(
                step_id="search",
                specialist="search",
                goal="Find source-cited schemes",
            ),
        ]
    else:
        # "interview" asks questions; "evaluate" receives a full profile.
        # Both end with the same rule check.
        steps = [
            PlanStep(
                step_id="intake",
                specialist="intake",
                goal=(
                    "Learn about you"
                    if action == "interview"
                    else "Check your answers"
                ),
                scheme_id=scheme_id,
            ),
            PlanStep(
                step_id="eligibility",
                specialist="eligibility",
                goal=f"Check the rules for {scheme_id or 'the chosen scheme'}",
                scheme_id=scheme_id,
            ),
        ]
    # The supervisor starts the first step straight away.
    steps[0].status = "in_progress"
    return Plan(steps=steps)


def advance_plan(
    plan: Plan,
    specialist: SpecialistName,
    status: str,
) -> tuple[Plan, PlanStep | None]:
    """Record a specialist's report and choose the next step.

    Args:
        plan: The current plan (not changed; a new copy is returned).
        specialist: Who just reported back.
        status: The status they reported, e.g. "ready_for_eligibility".

    Returns:
        (updated plan, next step to run) - the next step is None when the
        plan is finished or stopped early.
    """

    # model_copy(deep=True) gives a separate copy, so the caller's plan is
    # never changed by accident.
    plan = plan.model_copy(deep=True)
    current = next(
        step
        for step in plan.steps
        if step.specialist == specialist and step.status == "in_progress"
    )

    if status not in SUCCESS_STATUSES.get(specialist, frozenset()):
        # The step could not finish (e.g. bad input or an information-only
        # scheme). Mark it failed and skip the rest: nothing else can run.
        current.status = "failed"
        for step in plan.steps:
            if step.status == "pending":
                step.status = "skipped"
        return plan, None

    current.status = "done"
    # Start the next step that has not run yet, if there is one.
    for step in plan.steps:
        if step.status == "pending":
            step.status = "in_progress"
            return plan, step
    return plan, None


def plan_summary(plan: Plan) -> str:
    """One-line text version of the plan, e.g. "Plan: Learn about you -> ..."."""

    return "Plan: " + " -> ".join(step.goal for step in plan.steps)
