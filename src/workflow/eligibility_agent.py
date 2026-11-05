"""Observation-driven eligibility handoff without model verdict authority."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from pydantic import Field, ValidationError

from src.api.eligibility import EligibilityResponse
from src.workflow.agent_runtime import (
    AgentAction, AgentActionError, AgentSchema, ToolChoiceProvider,
    recover_authorized_action, run_react_loop,
)
from src.workflow.errors import MCPToolError


class CheckCandidate(AgentSchema):
    """Select only the code-bound candidate."""

    scheme_id: str


class VerdictObservation(AgentSchema):
    """Safe rule-engine metadata; no applicant values or external prose."""

    scheme_id: str
    status: Literal["observed", "unavailable"] = "observed"
    result: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str] = Field(default_factory=list)


class HandoffVerdict(AgentSchema):
    """Return the observed verdict, never a model-written one."""

    confirm: Literal["return_observed_verdict"]


class FinishedHandoff(AgentSchema):
    """Code-validated terminal handoff."""

    finished: Literal[True] = True
    outcome: Literal["verdict", "clarification", "referral"] = "verdict"


class ClarificationRequest(AgentSchema):
    """Request only the missing facts actually reported by the rule engine."""

    confirm: Literal["request_observed_missing_facts"]


class ReferralRequest(AgentSchema):
    """Stop without a verdict when the checked rule tool is unavailable."""

    confirm: Literal["refer_without_verdict"]


async def run_eligibility_specialist(
    provider: ToolChoiceProvider | None,
    scheme_id: str,
    locale: str,
    budget: Mapping[str, int],
    evaluate: Callable[[], Awaitable[EligibilityResponse]],
) -> tuple[EligibilityResponse | None, dict[str, int], list[dict[str, object]], str]:
    """Run a real model tool loop, preserving C0 only when no model is configured."""

    observed: EligibilityResponse | None = None
    attempted = False

    async def check(arguments: AgentSchema) -> AgentSchema:
        nonlocal observed, attempted
        if not isinstance(arguments, CheckCandidate) or arguments.scheme_id != scheme_id:
            raise AgentActionError("Candidate is outside the specialist scope.")
        if attempted:
            raise AgentActionError("Candidate has already been checked.")
        attempted = True
        try:
            observed = EligibilityResponse.model_validate(await evaluate())
        except (MCPToolError, ValidationError, TypeError):
            observed = None
            return VerdictObservation(scheme_id=scheme_id, status="unavailable")
        if observed.scheme_id != scheme_id:
            observed = None
            return VerdictObservation(scheme_id=scheme_id, status="unavailable")
        return VerdictObservation(
            scheme_id=observed.scheme_id, result=observed.result,
            missing_fields=observed.missing_fields,
            deciding_rule_ids=observed.deciding_rule_ids,
        )

    async def handoff(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, HandoffVerdict) or observed is None:
            raise AgentActionError("Observe a rule-engine verdict before handoff.")
        return FinishedHandoff()

    async def clarify(arguments: AgentSchema) -> AgentSchema:
        if (
            not isinstance(arguments, ClarificationRequest)
            or observed is None or not observed.missing_fields
        ):
            raise AgentActionError("Only observed missing facts can be requested.")
        return FinishedHandoff(outcome="clarification")

    async def check_without_model() -> dict[str, object]:
        """Run the same code-bound rule check when no model step is possible."""

        nonlocal observed
        try:
            response = EligibilityResponse.model_validate(await evaluate())
        except (MCPToolError, ValidationError, TypeError):
            return {}
        if response.scheme_id == scheme_id:
            observed = response
        return {}

    async def refer(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, ReferralRequest) or not attempted or observed is not None:
            raise AgentActionError("Referral needs an observed rule-tool failure.")
        return FinishedHandoff(outcome="referral")

    if provider is None:
        try:
            result = EligibilityResponse.model_validate(await evaluate())
        except (MCPToolError, ValidationError, TypeError):
            result = None
        if result is not None and result.scheme_id != scheme_id:
            result = None
        return result, dict(budget), [], "deterministic"
    run = await run_react_loop(
        "eligibility", "eligibility", locale,
        {"scheme_id": scheme_id},
        [
            AgentAction("check_candidate", "Observe the code-bound rule-engine verdict.",
                        "eligibility", CheckCandidate, VerdictObservation, check),
            AgentAction("handoff_verdict", "Hand off only after observing the verdict.",
                        "eligibility", HandoffVerdict, FinishedHandoff, handoff, terminal=True),
            AgentAction("request_clarification", "Hand off the engine's missing facts for clarification.",
                        "eligibility", ClarificationRequest, FinishedHandoff, clarify, terminal=True),
            AgentAction("refer_for_help", "Refer safely after a rule-tool failure; no verdict.",
                        "eligibility", ReferralRequest, FinishedHandoff, refer, terminal=True),
        ],
        provider, budget, max_steps=3,
    )
    # The model could not be asked (allowance used up or unavailable). The
    # verdict always comes from the rule engine, so run that check once
    # without the model; it counts against the conversation's tool budget.
    recovered = run.status in {"budget_exhausted", "model_unavailable"}
    if recovered and not attempted:
        await recover_authorized_action(run, check_without_model)
    return (
        observed if run.status == "completed" or recovered else None,
        run.budget, run.trace,
        "model_assisted" if run.status == "completed" else "deterministic_fallback",
    )
