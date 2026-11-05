"""Bounded document-check actions for the documents specialist."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from pydantic import Field
from langchain_core.language_models import BaseChatModel

from src.workflow.agent_runtime import (
    AgentAction,
    AgentActionError,
    AgentRunResult,
    AgentSchema,
    recover_authorized_action,
    run_react_loop,
)


class InspectDocumentsArguments(AgentSchema):
    """Request a code-owned metadata comparison for one scheme."""

    scheme_id: str = Field(min_length=1, max_length=80)


class InspectDocumentsObservation(AgentSchema):
    """Return only machine-readable document statuses and discrepancy codes."""

    status: Literal[
        "checklist_complete", "mismatch", "missing_items", "unknown_items",
        "requirements_unverified",
    ]
    discrepancy_codes: list[Literal["name_mismatch", "date_of_birth_mismatch"]] = Field(
        default_factory=list
    )


class DocumentHandoffArguments(AgentSchema):
    """Choose a typed next step after observing the deterministic report."""

    outcome: Literal["ready", "correction", "clarification", "referral"]


class DocumentHandoffObservation(AgentSchema):
    """Confirm the code-approved document handoff."""

    outcome: Literal["ready", "correction", "clarification", "referral"]
    guidance_code: Literal[
        "documents_ready", "resolve_mismatch", "complete_demo_checklist",
        "requirements_unverified",
    ]


def _expected_document_outcome(status: str) -> tuple[str, str]:
    """Translate a deterministic checklist status into a safe handoff."""

    return {
        "checklist_complete": ("ready", "documents_ready"),
        "mismatch": ("correction", "resolve_mismatch"),
        "missing_items": ("clarification", "complete_demo_checklist"),
        "unknown_items": ("clarification", "complete_demo_checklist"),
        "requirements_unverified": ("referral", "requirements_unverified"),
    }.get(status, ("referral", "requirements_unverified"))


async def run_document_specialist(
    provider: BaseChatModel | None,
    scheme_id: str,
    locale: str,
    budget: Mapping[str, int],
    inspect: Callable[[], Awaitable[dict[str, object]]],
) -> tuple[dict[str, object] | None, dict[str, int], list[dict[str, object]], str]:
    """Run an observation-driven checklist and discrepancy handoff."""

    assessment: dict[str, object] | None = None
    expected: tuple[str, str] | None = None

    async def inspect_action(arguments: AgentSchema) -> AgentSchema:
        nonlocal assessment, expected
        if not isinstance(arguments, InspectDocumentsArguments):
            raise AgentActionError("Invalid document inspection request.")
        if arguments.scheme_id != scheme_id or assessment is not None:
            raise AgentActionError("Document inspection is outside this task.")
        assessment = await inspect()
        status = assessment.get("status")
        if not isinstance(status, str):
            raise AgentActionError("The document service returned no status.")
        expected = _expected_document_outcome(status)
        discrepancies = assessment.get("discrepancies", [])
        codes = [
            item.get("code") for item in discrepancies if isinstance(item, dict)
        ] if isinstance(discrepancies, list) else []
        return InspectDocumentsObservation(
            status=status,
            discrepancy_codes=[
                code for code in codes
                if code in {"name_mismatch", "date_of_birth_mismatch"}
            ],
        )

    async def handoff(arguments: AgentSchema) -> AgentSchema:
        if (
            not isinstance(arguments, DocumentHandoffArguments)
            or expected is None
            or (arguments.outcome, _expected_document_outcome(
                str((assessment or {}).get("status"))
            )[1]) != expected
        ):
            raise AgentActionError("The handoff does not match the observed checklist.")
        return DocumentHandoffObservation(
            outcome=expected[0], guidance_code=expected[1],
        )

    if provider is None:
        try:
            result = await inspect()
        except Exception:
            return None, dict(budget), [], "deterministic_fallback"
        return result, dict(budget), [], "deterministic"

    run: AgentRunResult = await run_react_loop(
        "documents",
        "documents",
        locale,
        {"scheme_id": scheme_id},
        [
            AgentAction(
                "inspect_document_metadata",
                "Inspect the supplied demo metadata with the deterministic checker.",
                "documents",
                InspectDocumentsArguments,
                InspectDocumentsObservation,
                inspect_action,
            ),
            AgentAction(
                "handoff_documents",
                "Choose the next step that exactly matches the observed report.",
                "documents",
                DocumentHandoffArguments,
                DocumentHandoffObservation,
                handoff,
                terminal=True,
            ),
        ],
        provider,
        budget,
        max_steps=2,
    )
    recovered = run.status in {"budget_exhausted", "model_unavailable"}
    if assessment is None:
        assessment = await recover_authorized_action(run, inspect)
    return (
        assessment if run.status == "completed" or recovered else None,
        run.budget,
        run.trace,
        "model_assisted" if run.status == "completed" else "deterministic_fallback",
    )
