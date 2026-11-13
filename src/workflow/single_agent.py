"""Single model agent over code-bound Saathi journey actions."""

from collections.abc import Awaitable, Callable, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from src.workflow.agent_runtime import AgentSchema, observation, run_agent
from src.workflow.intake_agent import ProposedFact, ProposeFactsArguments


class NoArguments(AgentSchema):
    """A backend-bound action with no model-supplied arguments."""


class CandidateArguments(AgentSchema):
    """Select one of the currently available candidates."""

    scheme_id: str


class ActionObservation(AgentSchema):
    """Return only the code-owned action status to the model."""

    action: str
    status: str
    required_facts: list[str] = []
    accepted_count: int = 0


SINGLE_AGENT_TOOLS = (
    "read_required_facts", "propose_profile_facts", "collect_information",
    "search_schemes", "evaluate_eligibility",
    "check_documents", "prepare_draft", "edit_draft", "submit_draft",
    "read_application_status",
)


async def run_single_agent_action(
    model: BaseChatModel,
    locale: str,
    context: Mapping[str, object],
    budget: Mapping[str, int],
    execute: Callable[[str, object], Awaitable[dict[str, object]]],
) -> tuple[dict[str, int], list[dict[str, object]], str]:
    """Execute one model-selected action under the shared agent middleware.

    The callback owns authorization, state transitions and domain service calls.
    No tool accepts profile data, portal arguments or a human approval decision.
    """

    async def perform(action: str, argument: object = None) -> str:
        result = await execute(action, argument)
        return observation(ActionObservation(action=action, **result))

    @tool(args_schema=CandidateArguments)
    async def read_required_facts(scheme_id: str) -> str:
        """Read the allowed fact names for the current intake task."""
        return await perform("read_required_facts", scheme_id)

    @tool(args_schema=ProposeFactsArguments)
    async def propose_profile_facts(facts: list[ProposedFact]) -> str:
        """Propose only reader-observed facts for the citizen to confirm."""
        return await perform("propose_profile_facts", facts)

    @tool(args_schema=NoArguments, return_direct=True)
    async def collect_information() -> str:
        """Check the citizen's supplied information or ask the next question."""
        return await perform("collect_information")

    @tool(args_schema=NoArguments, return_direct=True)
    async def search_schemes() -> str:
        """Search Saathi's cited scheme service for the current request."""
        return await perform("search_schemes")

    @tool(args_schema=CandidateArguments, return_direct=True)
    async def evaluate_eligibility(scheme_id: str) -> str:
        """Evaluate an available candidate using the deterministic rule service."""
        return await perform("evaluate_eligibility", scheme_id)

    @tool(args_schema=NoArguments, return_direct=True)
    async def check_documents() -> str:
        """Check the current task's document metadata using Saathi's service."""
        return await perform("check_documents")

    @tool(args_schema=NoArguments, return_direct=True)
    async def prepare_draft() -> str:
        """Prepare only the explicitly requested synthetic draft."""
        return await perform("prepare_draft")

    @tool(args_schema=NoArguments, return_direct=True)
    async def edit_draft() -> str:
        """Edit only the explicitly requested synthetic draft."""
        return await perform("edit_draft")

    @tool(args_schema=NoArguments, return_direct=True)
    async def submit_draft() -> str:
        """Submit only the explicitly requested, separately approved draft."""
        return await perform("submit_draft")

    @tool(args_schema=NoArguments)
    async def read_application_status() -> str:
        """Read the status of the draft bound to the current application task."""
        return await perform("read_application_status")

    result = await run_agent(
        model, "single", locale, context,
        [
            read_required_facts, propose_profile_facts,
            collect_information, search_schemes, evaluate_eligibility,
            check_documents, prepare_draft, edit_draft, submit_draft,
            read_application_status,
        ],
        budget,
    )
    return result.budget, result.trace, result.status
