"""Reserve conversation work durably before any external model or search call."""

from contextvars import ContextVar
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph


class BudgetState(TypedDict, total=False):
    """A separate checkpoint stream that cannot disturb interview interrupts."""

    counters: dict[str, int]
    attempted_facts: list[str]


class ConversationBudget:
    """Keep reservations independent of a specialist node's eventual success."""

    def __init__(self, checkpointer: BaseCheckpointSaver | None) -> None:
        builder = StateGraph(BudgetState)
        builder.add_node("reserve", lambda _state: {})
        builder.add_edge(START, "reserve")
        builder.add_edge("reserve", END)
        self.graph = builder.compile(checkpointer=checkpointer)
        self.config: dict[str, object] = {}
        self.values: BudgetState = {}

    async def load(self, conversation_id: str) -> None:
        """Read the durable stream at the start of a serialized request."""

        self.config = {"configurable": {"thread_id": f"budget:{conversation_id}"}}
        snapshot = await self.graph.aget_state(self.config)
        self.values = dict(snapshot.values)

    async def reserve(self, counters: dict[str, int]) -> None:
        """Save before dispatch; persistence failure prevents the external call."""

        updated = {**self.values.get("counters", {}), **counters}
        await self.graph.aupdate_state(
            self.config, {"counters": updated}, as_node="reserve",
        )
        self.values["counters"] = updated

    async def reserve_fact(self, fact: str) -> None:
        """Record one interpretation attempt even if its parent node crashes."""

        facts = sorted(set(self.values.get("attempted_facts", [])) | {fact})
        await self.graph.aupdate_state(
            self.config, {"attempted_facts": facts}, as_node="reserve",
        )
        self.values["attempted_facts"] = facts


CURRENT_BUDGET: ContextVar[ConversationBudget | None] = ContextVar(
    "conversation_budget", default=None,
)


def durable_counters(counters: dict[str, int]) -> dict[str, int]:
    """Merge a graph snapshot with reservations saved before a failed node."""

    budget = CURRENT_BUDGET.get()
    reserved = budget.values.get("counters", {}) if budget else {}
    return {
        key: max(
            counters[key] if type(counters.get(key)) is int else 0,
            reserved[key] if type(reserved.get(key)) is int else 0,
            0,
        )
        for key in counters.keys() | reserved.keys()
    }


async def reserve_counters(counters: dict[str, int]) -> None:
    """Persist when running inside a conversation; pure helper tests stay local."""

    budget = CURRENT_BUDGET.get()
    if budget is not None:
        await budget.reserve(counters)


def attempted_facts(facts: list[str]) -> set[str]:
    """Include attempts reserved by a node that never completed."""

    budget = CURRENT_BUDGET.get()
    return set(facts) | set(budget.values.get("attempted_facts", []) if budget else [])


async def reserve_fact(fact: str) -> None:
    """Consume the conversation's single interpretation attempt for this fact."""

    budget = CURRENT_BUDGET.get()
    if budget is not None:
        await budget.reserve_fact(fact)
