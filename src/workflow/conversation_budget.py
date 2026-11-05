"""Reserve conversation work durably before any external model or search call.

The counters live in the LangGraph ``Store`` (namespace ``("budget",)``,
key = conversation ID), separate from the conversation's checkpoints, so a
reservation survives even when the node that made it crashes.
"""

from contextvars import ContextVar
from typing import TypedDict

from langgraph.store.base import BaseStore


BUDGET_NAMESPACE = ("budget",)


class BudgetState(TypedDict, total=False):
    """The stored record for one conversation."""

    counters: dict[str, int]
    attempted_facts: list[str]


class ConversationBudget:
    """Keep reservations independent of a specialist node's eventual success."""

    def __init__(self, store: BaseStore) -> None:
        self.store = store
        self.conversation_id = ""
        self.values: BudgetState = {}

    async def load(self, conversation_id: str) -> None:
        """Read the saved record at the start of a serialized request."""

        self.conversation_id = conversation_id
        item = await self.store.aget(BUDGET_NAMESPACE, conversation_id)
        self.values = dict(item.value) if item else {}

    async def _save(self) -> None:
        await self.store.aput(BUDGET_NAMESPACE, self.conversation_id, dict(self.values))

    async def reserve(self, counters: dict[str, int]) -> None:
        """Save before dispatch; persistence failure prevents the external call."""

        updated = {**self.values.get("counters", {}), **counters}
        self.values = {**self.values, "counters": updated}
        await self._save()

    async def reserve_fact(self, fact: str) -> None:
        """Record one interpretation attempt even if its parent node crashes."""

        facts = sorted(set(self.values.get("attempted_facts", [])) | {fact})
        self.values = {**self.values, "attempted_facts": facts}
        await self._save()


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
