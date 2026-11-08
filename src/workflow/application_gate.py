"""Persist an interrupt while a synthetic application draft awaits review."""

from typing import Any, TypedDict
from uuid import uuid5, NAMESPACE_URL

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalState(TypedDict, total=False):
    draft: dict[str, Any]
    decision: dict[str, Any]


def build_application_gate(checkpointer: BaseCheckpointSaver) -> Any:
    """Build the small checkpointed graph used only for exact draft approval."""

    async def approval_gate(state: ApprovalState) -> dict[str, Any]:
        decision = interrupt({
            "draft": state["draft"],
            "message": "Review and decide on this exact synthetic draft.",
        })
        return {"decision": decision}

    graph = StateGraph(ApprovalState)
    graph.add_node("approval_gate", approval_gate)
    graph.add_edge(START, "approval_gate")
    graph.add_edge("approval_gate", END)
    return graph.compile(checkpointer=checkpointer)


def application_gate_thread_id(
    conversation_id: str, draft_id: str, revision: int
) -> str:
    """Return a stable, opaque checkpoint thread identifier."""

    return str(uuid5(
        NAMESPACE_URL,
        f"scheme-saathi-application:{conversation_id}:{draft_id}:{revision}",
    ))


async def pause_for_application_approval(
    graph: Any,
    conversation_id: str,
    draft: dict[str, Any],
) -> None:
    """Checkpoint and pause until a user reviews this exact draft revision."""

    config = {
        "configurable": {
            "thread_id": application_gate_thread_id(
                conversation_id, draft["draft_id"], draft["revision"]
            )
        }
    }
    snapshot = await graph.aget_state(config)
    if snapshot.interrupts:
        return
    await graph.ainvoke({"draft": draft}, config=config)
    paused = await graph.aget_state(config)
    if not paused.interrupts:
        raise RuntimeError("The application approval graph did not pause.")


async def resume_application_approval(
    graph: Any,
    conversation_id: str,
    draft: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Resume the saved approval pause and return its accepted decision."""

    config = {
        "configurable": {
            "thread_id": application_gate_thread_id(
                conversation_id, draft["draft_id"], draft["revision"]
            )
        }
    }
    snapshot = await graph.aget_state(config)
    if not snapshot.interrupts:
        await pause_for_application_approval(graph, conversation_id, draft)
    result = await graph.ainvoke(Command(resume=decision), config=config)
    accepted = result.get("decision")
    if accepted != decision:
        raise RuntimeError("The approval graph returned a different decision.")
    return accepted
