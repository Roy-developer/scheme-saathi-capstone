"""Code-validated initial profile-fact proposals for the intake specialist."""

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, StrictBool, StrictStr
from langchain_core.language_models import BaseChatModel

from src.mcp_servers.service_routing import ToolActor
from src.rules.models import FactName, HouseholdProfile
from src.workflow.agent_runtime import (
    AgentAction,
    AgentActionError,
    AgentRunResult,
    AgentSchema,
    copy_agent_budget,
    run_react_loop,
)
from src.workflow.questions import parse_interpreted_answer


class ReadFactsArguments(AgentSchema):
    """Request the reviewed MCP fact list for the selected scheme."""

    scheme_id: str = Field(min_length=1, max_length=80)


class ReadFactsObservation(AgentSchema):
    """Validated list of rule facts observed from the rule-engine service."""

    required_facts: list[FactName]


class ProposedFact(AgentSchema):
    """One typed fact candidate; it is not applied until the person confirms."""

    fact_name: FactName
    value: StrictBool | StrictStr


class ProposeFactsArguments(AgentSchema):
    """The model's bounded initial-description extraction proposal."""

    facts: list[ProposedFact] = Field(max_length=12)


class ProposeFactsObservation(AgentSchema):
    """Code-validated proposal metadata returned to the model."""

    accepted: list[ProposedFact]
    ignored_confirmed: int = Field(ge=0)
    invalid_count: int = Field(ge=0)


class FinishIntakeArguments(AgentSchema):
    """A model-selected stop after seeing tool observations."""

    confirm: Literal["return_to_supervisor"]


class FinishIntakeObservation(AgentSchema):
    """The intake specialist's typed handoff result."""

    finished: Literal[True]


async def propose_initial_profile_facts(
    provider: BaseChatModel | None,
    client: object,
    actor: ToolActor,
    journey_id: str,
    scheme_id: str,
    description: str,
    profile: HouseholdProfile,
    package_facts: tuple[FactName, ...],
    locale: Literal["en", "hi", "mr"],
    budget: Mapping[str, int] | None,
    discovery_facts: tuple[FactName, ...] = (),
) -> tuple[list[dict[str, object]], dict[str, int], list[dict[str, object]], str]:
    """Interpret synthetic free text as uncommitted facts through permitted tools."""

    if provider is None:
        return [], copy_agent_budget(budget), [], "deterministic"

    required_facts: set[str] = set()
    accepted_proposals: list[dict[str, object]] = []
    ignored_confirmed = 0
    invalid_count = 0

    async def read_facts(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, ReadFactsArguments):
            raise AgentActionError("Invalid fact lookup input.")
        if arguments.scheme_id != scheme_id or actor != "intake":
            raise AgentActionError("Fact lookup is outside the intake scope.")
        try:
            result = await getattr(client, "call_tool")(
                "required_facts", {"scheme_id": scheme_id}
            )
        except Exception as error:
            raise AgentActionError("Required facts are unavailable.") from error
        if getattr(result, "is_error", True):
            raise AgentActionError("Required facts are unavailable.")
        content = getattr(result, "structured_content", None)
        if not isinstance(content, list):
            raise AgentActionError("Required facts returned an invalid schema.")
        declared = set(package_facts)
        if not all(isinstance(item, str) and item in declared for item in content):
            raise AgentActionError("Required facts returned an invalid schema.")
        required_facts.update(content)
        required_facts.update(discovery_facts)
        return ReadFactsObservation(
            required_facts=list(dict.fromkeys([*content, *discovery_facts])),
        )

    async def propose_facts(arguments: AgentSchema) -> AgentSchema:
        nonlocal ignored_confirmed, invalid_count
        if not isinstance(arguments, ProposeFactsArguments) or not required_facts:
            raise AgentActionError("Read allowed fact names before proposing facts.")
        profile_values = profile.model_dump(mode="python")
        for proposal in arguments.facts:
            if proposal.fact_name not in required_facts:
                invalid_count += 1
                continue
            if profile_values.get(proposal.fact_name) is not None:
                ignored_confirmed += 1
                continue
            parsed = parse_interpreted_answer(
                proposal.fact_name, proposal.value, locale
            )
            if parsed.kind != "value" or parsed.value is None:
                invalid_count += 1
                continue
            try:
                HouseholdProfile.model_validate({
                    **profile_values,
                    proposal.fact_name: parsed.value,
                })
            except (ValueError, TypeError):
                invalid_count += 1
                continue
            value = (
                parsed.value.isoformat()
                if hasattr(parsed.value, "isoformat")
                else parsed.value
            )
            accepted_proposals.append({
                "fact_name": proposal.fact_name,
                "value": value,
            })
        validated = [
            ProposedFact.model_validate(proposal)
            for proposal in accepted_proposals
        ]
        return ProposeFactsObservation(
            accepted=validated,
            ignored_confirmed=ignored_confirmed,
            invalid_count=invalid_count,
        )

    async def finish(arguments: AgentSchema) -> AgentSchema:
        if not isinstance(arguments, FinishIntakeArguments):
            raise AgentActionError("Invalid intake handoff.")
        return FinishIntakeObservation(finished=True)

    actions = [
        AgentAction(
            "read_required_facts",
            "Read the scheme's required facts from the authorized rule service.",
            "intake",
            ReadFactsArguments,
            ReadFactsObservation,
            read_facts,
        ),
        AgentAction(
            "propose_profile_facts",
            "Propose only clearly stated required household facts.",
            "intake",
            ProposeFactsArguments,
            ProposeFactsObservation,
            propose_facts,
        ),
        AgentAction(
            "finish_intake",
            "Finish after observing the fact proposals.",
            "intake",
            FinishIntakeArguments,
            FinishIntakeObservation,
            finish,
            terminal=True,
        ),
    ]
    result: AgentRunResult = await run_react_loop(
        "intake",
        actor,
        locale,
        {
            "scheme_id": scheme_id,
            "required_fact_names": list(package_facts),
            "initial_description": description,
        },
        actions,
        provider,
        budget,
    )
    return (
        accepted_proposals if result.status == "completed" else [],
        result.budget,
        result.trace,
        "model_assisted" if result.status == "completed" else "deterministic_fallback",
    )
