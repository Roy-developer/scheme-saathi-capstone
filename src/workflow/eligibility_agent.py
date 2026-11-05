"""Observation-driven eligibility handoff without model verdict authority."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import Field, ValidationError

from src.api.eligibility import EligibilityResponse
from src.workflow.agent_runtime import (
    AgentActionError, AgentSchema, observation, recover_authorized_action, run_agent,
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
    provider: BaseChatModel | None,
    scheme_id: str,
    locale: str,
    budget: Mapping[str, int],
    evaluate: Callable[[], Awaitable[EligibilityResponse]],
) -> tuple[EligibilityResponse | None, dict[str, int], list[dict[str, object]], str]:
    """Let the model observe the rule engine's verdict and hand it off.

    The verdict always comes from the rule engine (``evaluate``); the model
    only chooses which observed outcome to hand off. Without a model the
    rule engine runs directly.
    """

    task_scheme_id = scheme_id
    observed: EligibilityResponse | None = None
    attempted = False

    async def run_rule_check() -> EligibilityResponse | None:
        try:
            response = EligibilityResponse.model_validate(await evaluate())
        except (MCPToolError, ValidationError, TypeError):
            return None
        return response if response.scheme_id == task_scheme_id else None

    @tool(args_schema=CheckCandidate)
    async def check_candidate(scheme_id: str) -> str:
        """Observe the code-bound rule-engine verdict."""
        nonlocal observed, attempted
        if scheme_id != task_scheme_id:
            raise AgentActionError("Candidate is outside the specialist scope.")
        if attempted:
            raise AgentActionError("Candidate has already been checked.")
        attempted = True
        observed = await run_rule_check()
        if observed is None:
            return observation(VerdictObservation(scheme_id=task_scheme_id, status="unavailable"))
        return observation(VerdictObservation(
            scheme_id=observed.scheme_id, result=observed.result,
            missing_fields=observed.missing_fields,
            deciding_rule_ids=observed.deciding_rule_ids,
        ))

    @tool(args_schema=HandoffVerdict, return_direct=True)
    async def handoff_verdict(confirm: str) -> str:
        """Hand off only after observing the verdict."""
        if observed is None:
            raise AgentActionError("Observe a rule-engine verdict before handoff.")
        return observation(FinishedHandoff())

    @tool(args_schema=ClarificationRequest, return_direct=True)
    async def request_clarification(confirm: str) -> str:
        """Hand off the engine's missing facts for clarification."""
        if observed is None or not observed.missing_fields:
            raise AgentActionError("Only observed missing facts can be requested.")
        return observation(FinishedHandoff(outcome="clarification"))

    @tool(args_schema=ReferralRequest, return_direct=True)
    async def refer_for_help(confirm: str) -> str:
        """Refer safely after a rule-tool failure; no verdict."""
        if not attempted or observed is not None:
            raise AgentActionError("Referral needs an observed rule-tool failure.")
        return observation(FinishedHandoff(outcome="referral"))

    if provider is None:
        return await run_rule_check(), dict(budget), [], "deterministic"
    run = await run_agent(
        provider, "eligibility", locale, {"scheme_id": task_scheme_id},
        [check_candidate, handoff_verdict, request_clarification, refer_for_help],
        budget, max_steps=3,
    )

    async def check_without_model() -> dict[str, object]:
        nonlocal observed
        observed = await run_rule_check()
        return {}

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
