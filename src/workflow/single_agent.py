"""Single-agent baseline (E1, configuration C1).

One agent holds the eligibility and document tools that the team splits
across specialists. It runs under the same ``run_agent`` middleware, so it
gets the same PII masking, durable budget, tool allow-listing and trace as
the team. It has no portal-write tool: approval-gated drafting is identical
in every configuration, so it is outside this comparison.

The verdicts still come only from the rule engine. The model chooses which
candidate to check and when to stop; it can never write a verdict.
"""

from collections.abc import Awaitable, Callable, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import Field, ValidationError

from src.api.eligibility import EligibilityResponse
from src.workflow.agent_runtime import (
    AgentActionError, AgentSchema, observation, run_agent,
)
from src.workflow.errors import MCPToolError

# Same ceiling as the team's per-conversation model calls, so C1 and C2 match.
BASELINE_MAX_STEPS = 8


class CheckCandidateArguments(AgentSchema):
    """Select one code-bound candidate scheme."""

    scheme_id: str = Field(min_length=1, max_length=80)


class InspectDocumentsArguments(AgentSchema):
    """Select one eligible candidate for the metadata comparison."""

    scheme_id: str = Field(min_length=1, max_length=80)


class FinishBaselineArguments(AgentSchema):
    """End the run once every candidate has been handled."""

    done: bool = True


class VerdictObserved(AgentSchema):
    """Safe rule-engine metadata shown to the model."""

    scheme_id: str
    status: str
    result: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    deciding_rule_ids: list[str] = Field(default_factory=list)


class DocumentsObserved(AgentSchema):
    """Machine-readable checklist status only."""

    scheme_id: str
    status: str


class Finished(AgentSchema):
    finished: bool = True


class BaselineOutcome:
    """Code-observed results of one baseline run (never model-written)."""

    def __init__(self) -> None:
        self.verdicts: dict[str, EligibilityResponse | None] = {}
        self.documents: dict[str, dict[str, object] | None] = {}
        self.finished = False


async def run_single_agent_baseline(
    provider: BaseChatModel,
    scheme_ids: list[str],
    locale: str,
    budget: Mapping[str, int],
    evaluate: Callable[[str], Awaitable[EligibilityResponse]],
    inspect: Callable[[str], Awaitable[dict[str, object]]],
    *,
    max_steps: int = BASELINE_MAX_STEPS,
) -> tuple[BaselineOutcome, dict[str, int], list[dict[str, object]], str]:
    """Run C1: one agent, all read tools, same budget as the team."""

    allowed = set(scheme_ids)
    outcome = BaselineOutcome()

    @tool(args_schema=CheckCandidateArguments)
    async def check_candidate(scheme_id: str) -> str:
        """Observe the rule engine's verdict for one candidate scheme."""
        if scheme_id not in allowed or scheme_id in outcome.verdicts:
            raise AgentActionError("Candidate is outside scope or already checked.")
        try:
            response = EligibilityResponse.model_validate(await evaluate(scheme_id))
            if response.scheme_id != scheme_id:
                response = None
        except (MCPToolError, ValidationError, TypeError):
            response = None
        outcome.verdicts[scheme_id] = response
        if response is None:
            return observation(VerdictObserved(scheme_id=scheme_id, status="unavailable"))
        return observation(VerdictObserved(
            scheme_id=scheme_id, status="observed", result=response.result,
            missing_fields=response.missing_fields,
            deciding_rule_ids=response.deciding_rule_ids,
        ))

    @tool(args_schema=InspectDocumentsArguments)
    async def inspect_documents(scheme_id: str) -> str:
        """Run the deterministic document comparison for an eligible scheme."""
        checked = outcome.verdicts.get(scheme_id)
        if checked is None or checked.result != "eligible":
            raise AgentActionError("Documents are inspected only for eligible schemes.")
        if scheme_id in outcome.documents:
            raise AgentActionError("Documents were already inspected.")
        try:
            assessment = await inspect(scheme_id)
        except Exception:  # tool failure becomes a safe, visible gap
            outcome.documents[scheme_id] = None
            return observation(DocumentsObserved(scheme_id=scheme_id, status="unavailable"))
        outcome.documents[scheme_id] = assessment
        return observation(DocumentsObserved(
            scheme_id=scheme_id, status=str(assessment.get("status")),
        ))

    @tool(args_schema=FinishBaselineArguments, return_direct=True)
    async def finish_baseline(done: bool = True) -> str:
        """Finish after every candidate has been checked."""
        if set(outcome.verdicts) != allowed:
            raise AgentActionError("Check every candidate before finishing.")
        outcome.finished = True
        return observation(Finished())

    run = await run_agent(
        provider, "single", locale, {"scheme_ids": sorted(allowed)},
        [check_candidate, inspect_documents, finish_baseline],
        budget, max_steps=max_steps,
    )
    return outcome, run.budget, run.trace, run.status
