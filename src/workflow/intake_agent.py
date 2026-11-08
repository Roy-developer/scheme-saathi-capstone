"""Code-validated initial profile-fact proposals for the intake specialist."""

from collections.abc import Callable, Mapping
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import Field, StrictBool, StrictStr

from src.mcp_servers.service_routing import ToolActor
from src.rules.facts import FactRegistry, TypedFactStore
from src.rules.models import HouseholdProfile
from src.workflow.agent_runtime import (
    AgentActionError,
    AgentSchema,
    copy_agent_budget,
    observation,
    run_agent,
)
from src.workflow.questions import (
    parse_interpreted_answer,
    parse_interpreted_registered_answer,
)


class ReadFactsArguments(AgentSchema):
    """Request the reviewed MCP fact list for the selected scheme."""

    scheme_id: str = Field(min_length=1, max_length=80)


class ReadFactsObservation(AgentSchema):
    """Validated list of rule facts observed from the rule-engine service."""

    required_facts: list[str]


class ProposedFact(AgentSchema):
    """One typed fact candidate; it is not applied until the person confirms."""

    fact_name: str = Field(min_length=1, max_length=120)
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


def _wire_value(value: object) -> object:
    """Return a proposal value in the form saved with the question."""

    return value.isoformat() if hasattr(value, "isoformat") else value


async def propose_initial_profile_facts(
    provider: BaseChatModel | None,
    client: object,
    actor: ToolActor,
    journey_id: str,
    scheme_id: str,
    description: str,
    profile: HouseholdProfile,
    package_facts: tuple[str, ...],
    locale: Literal["en", "hi", "mr"],
    budget: Mapping[str, int] | None,
    discovery_facts: tuple[str, ...] = (),
) -> tuple[list[dict[str, object]], dict[str, int], list[dict[str, object]], str]:
    """Interpret a description as proposals for ``HouseholdProfile`` fields."""

    profile_values = profile.model_dump(mode="python")

    def checked(fact_name: str, value: bool | str) -> object | None:
        parsed = parse_interpreted_answer(fact_name, value, locale)
        if parsed.kind != "value" or parsed.value is None:
            return None
        try:
            HouseholdProfile.model_validate({**profile_values, fact_name: parsed.value})
        except (ValueError, TypeError):
            return None
        return _wire_value(parsed.value)

    return await _propose_facts(
        provider, client, actor, scheme_id, description, package_facts, locale, budget,
        discovery_facts,
        is_confirmed=lambda fact_name: profile_values.get(fact_name) is not None,
        checked=checked,
    )


async def propose_initial_registered_facts(
    provider: BaseChatModel | None,
    client: object,
    actor: ToolActor,
    scheme_id: str,
    description: str,
    store: TypedFactStore,
    registry: FactRegistry,
    package_facts: tuple[str, ...],
    locale: Literal["en", "hi", "mr"],
    budget: Mapping[str, int] | None,
    discovery_facts: tuple[str, ...] = (),
) -> tuple[list[dict[str, object]], dict[str, int], list[dict[str, object]], str]:
    """Interpret a description as proposals for registered facts."""

    def checked(fact_name: str, value: bool | str) -> object | None:
        parsed = parse_interpreted_registered_answer(registry.get(fact_name), value, locale)
        if parsed.kind != "value" or parsed.value is None:
            return None
        return _wire_value(parsed.value)

    return await _propose_facts(
        provider, client, actor, scheme_id, description, package_facts, locale, budget,
        discovery_facts,
        is_confirmed=lambda fact_name: fact_name in store.facts,
        checked=checked,
    )


async def _propose_facts(
    provider: BaseChatModel | None,
    client: object,
    actor: ToolActor,
    scheme_id: str,
    description: str,
    package_facts: tuple[str, ...],
    locale: Literal["en", "hi", "mr"],
    budget: Mapping[str, int] | None,
    discovery_facts: tuple[str, ...],
    *,
    is_confirmed: Callable[[str], bool],
    checked: Callable[[str, bool | str], object | None],
) -> tuple[list[dict[str, object]], dict[str, int], list[dict[str, object]], str]:
    """Interpret synthetic free text as uncommitted facts through permitted tools."""

    if provider is None:
        return [], copy_agent_budget(budget), [], "deterministic"

    task_scheme_id = scheme_id
    required_facts: set[str] = set()
    accepted_proposals: list[dict[str, object]] = []
    ignored_confirmed = 0
    invalid_count = 0

    @tool(args_schema=ReadFactsArguments)
    async def read_required_facts(scheme_id: str) -> str:
        """Step 1, always first: read the scheme's required facts from the rule service."""
        if scheme_id != task_scheme_id or actor != "intake":
            raise AgentActionError("Fact lookup is outside the intake scope.")
        try:
            result = await getattr(client, "call_tool")(
                "required_facts", {"scheme_id": task_scheme_id}
            )
        except Exception as error:
            raise AgentActionError("Required facts are unavailable.") from error
        if getattr(result, "is_error", True):
            raise AgentActionError("Required facts are unavailable.")
        # MCP wraps a list return value as {"result": [...]}.
        structured = getattr(result, "structured_content", None)
        content = structured.get("result") if isinstance(structured, dict) else None
        if not isinstance(content, list):
            raise AgentActionError("Required facts returned an invalid schema.")
        declared = set(package_facts)
        if not all(isinstance(item, str) and item in declared for item in content):
            raise AgentActionError("Required facts returned an invalid schema.")
        required_facts.update(content)
        required_facts.update(discovery_facts)
        return observation(ReadFactsObservation(
            required_facts=list(dict.fromkeys([*content, *discovery_facts])),
        ))

    @tool(args_schema=ProposeFactsArguments)
    async def propose_profile_facts(facts: list[ProposedFact]) -> str:
        """Step 2, only after read_required_facts: propose clearly stated required facts."""
        nonlocal ignored_confirmed, invalid_count
        if not required_facts:
            raise AgentActionError("Read allowed fact names before proposing facts.")
        for proposal in facts:
            if proposal.fact_name not in required_facts:
                invalid_count += 1
                continue
            if is_confirmed(proposal.fact_name):
                ignored_confirmed += 1
                continue
            value = checked(proposal.fact_name, proposal.value)
            if value is None:
                invalid_count += 1
                continue
            accepted_proposals.append({
                "fact_name": proposal.fact_name,
                "value": value,
            })
        validated = [
            ProposedFact.model_validate(proposal)
            for proposal in accepted_proposals
        ]
        return observation(ProposeFactsObservation(
            accepted=validated,
            ignored_confirmed=ignored_confirmed,
            invalid_count=invalid_count,
        ))

    @tool(args_schema=FinishIntakeArguments, return_direct=True)
    async def finish_intake(confirm: str) -> str:
        """Step 3: finish after observing the fact proposals."""
        return observation(FinishIntakeObservation(finished=True))

    result = await run_agent(
        provider, "intake", locale,
        {
            "scheme_id": task_scheme_id,
            "required_fact_names": list(package_facts),
            "initial_description": description,
        },
        [read_required_facts, propose_profile_facts, finish_intake],
        budget,
    )
    return (
        accepted_proposals if result.status == "completed" else [],
        result.budget,
        result.trace,
        "model_assisted" if result.status == "completed" else "deterministic_fallback",
    )
