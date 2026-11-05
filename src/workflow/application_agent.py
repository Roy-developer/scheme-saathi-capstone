"""Bounded synthetic portal actions for the application specialist."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from pydantic import Field

from src.workflow.agent_runtime import (
    AgentAction,
    AgentActionError,
    AgentRunResult,
    AgentSchema,
    ToolChoiceProvider,
    recover_authorized_action,
    run_react_loop,
)


class ApplicationActionArguments(AgentSchema):
    """Identify the exact backend-selected draft action."""

    operation: Literal["create_draft", "edit_draft", "submit", "get_status"]
    draft_id: str | None = Field(default=None, max_length=80)


class ApplicationActionObservation(AgentSchema):
    """Report a safe portal outcome without applicant-entered values."""

    operation: Literal["create_draft", "edit_draft", "submit", "get_status"]
    status: Literal["draft_ready", "revision_saved", "submitted", "status_read"]
    revision: int | None = Field(default=None, ge=1)
    receipt_recorded: bool = False


class ApplicationHandoffArguments(AgentSchema):
    """End the specialist loop after the code-owned portal observation."""

    confirm: Literal["return_observed_application_status"]


class ApplicationHandoffObservation(AgentSchema):
    """Typed completion handoff to the supervisor."""

    finished: Literal[True] = True


async def run_application_specialist(
    provider: ToolChoiceProvider | None,
    operation: str,
    draft_id: str | None,
    revision: int | None,
    locale: str,
    budget: Mapping[str, int],
    execute: Callable[[], Awaitable[dict[str, object]]],
) -> tuple[dict[str, object] | None, dict[str, int], list[dict[str, object]], str]:
    """Run one authorized portal action and return only its safe observation."""

    selected: dict[str, object] | None = None

    async def execute_action(arguments: AgentSchema) -> AgentSchema:
        nonlocal selected
        if not isinstance(arguments, ApplicationActionArguments):
            raise AgentActionError("Invalid application action.")
        if (
            arguments.operation != operation
            or arguments.draft_id != draft_id
            or selected is not None
        ):
            raise AgentActionError("The action is outside the trusted application task.")
        selected = await execute()
        statuses = {
            "create_draft": "draft_ready",
            "edit_draft": "revision_saved",
            "submit": "submitted",
            "get_status": "status_read",
        }
        return ApplicationActionObservation(
            operation=operation,
            status=statuses[operation],
            revision=(
                selected.get("revision")
                if type(selected.get("revision")) is int
                else revision
            ),
            receipt_recorded=bool(selected.get("receipt_id")),
        )

    async def handoff(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, ApplicationHandoffArguments) or selected is None:
            raise AgentActionError("Observe the portal result before handoff.")
        return ApplicationHandoffObservation()

    if provider is None:
        try:
            result = await execute()
        except Exception:
            return None, dict(budget), [], "deterministic_fallback"
        return result, dict(budget), [], "deterministic"

    action_name = {
        "create_draft": "prepare_draft",
        "edit_draft": "edit_draft",
        "submit": "submit_draft",
        "get_status": "read_application_status",
    }.get(operation)
    if action_name is None:
        return None, dict(budget), [], "deterministic_fallback"
    run: AgentRunResult = await run_react_loop(
        "application",
        "application",
        locale,
        {"operation": operation, "draft_id": draft_id, "revision": revision},
        [
            AgentAction(
                action_name,
                "Perform only the backend-authorized synthetic portal action.",
                "application",
                ApplicationActionArguments,
                ApplicationActionObservation,
                execute_action,
            ),
            AgentAction(
                "handoff_application",
                "Finish after observing the code-owned portal result.",
                "application",
                ApplicationHandoffArguments,
                ApplicationHandoffObservation,
                handoff,
                terminal=True,
            ),
        ],
        provider,
        budget,
        max_steps=2,
    )
    action_observed = selected is not None
    if not action_observed:
        selected = await recover_authorized_action(run, execute)
    # The portal action is already committed before the model's terminal
    # handoff. Preserve its trusted result if that later choice fails.
    return (
        selected,
        run.budget,
        run.trace,
        (
            "model_assisted" if run.status == "completed"
            else "action_completed_handoff_incomplete"
            if action_observed
            else "deterministic_fallback"
        ),
    )
