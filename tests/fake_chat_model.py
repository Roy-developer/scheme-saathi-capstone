"""An offline LangChain chat model for agent tests.

Production agents receive ``ChatOpenAI``. Tests subclass ``FakeChatModel`` and
implement ``choose()`` to decide each tool call, so a test can script the
model, inspect what it was shown, or fail if it is called at all.
"""

import json
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, ConfigDict

from src.workflow.agent_config import AGENT_PROMPTS


class ModelDecision(BaseModel):
    """One scripted tool call, with optional token usage."""

    model_config = ConfigDict(extra="forbid")

    action: str
    arguments: dict[str, object]
    input_tokens: int = 0
    output_tokens: int = 0


# create_agent sends the agent prompt as the system message; map it back.
_PROMPT_OWNERS = {
    prompt: (agent, locale)
    for agent, prompts in AGENT_PROMPTS.items()
    for locale, prompt in prompts.items()
}


def _simple_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Show the conversation as role/content pairs (system prompt left out)."""

    simple: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, AIMessage):
            simple.append({"role": "assistant", "content": json.dumps([
                {"tool": call["name"], "arguments": call["args"]}
                for call in message.tool_calls
            ])})
        else:
            simple.append({"role": "user", "content": str(message.content)})
    return simple


class FakeChatModel(BaseChatModel):
    """A chat model whose tool calls come from ``choose()``.

    ``choose(agent, locale, messages, tools)`` receives the agent name and
    language (from the system prompt), the conversation as role/content
    pairs and the bound tools, and returns a ``ModelDecision``. Raising an
    exception makes the model call fail.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    model_name: str = "fake-model"

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling-model"

    def bind_tools(self, tools: list, **kwargs: object) -> "FakeChatModel":
        self.bound_tools = list(tools)
        return self

    async def choose(self, agent, locale, messages, tools) -> ModelDecision:
        raise NotImplementedError

    def _generate(self, *args: object, **kwargs: object) -> ChatResult:
        raise NotImplementedError("Agents call the model asynchronously.")

    async def _agenerate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs,
    ) -> ChatResult:
        system = next((m for m in messages if isinstance(m, SystemMessage)), None)
        agent, locale = _PROMPT_OWNERS.get(str(system.content) if system else "", (None, None))
        decision = await self.choose(
            agent, locale, _simple_messages(messages), getattr(self, "bound_tools", []),
        )
        reply = AIMessage(
            content="",
            tool_calls=[{
                "name": decision.action,
                "args": decision.arguments,
                "id": f"call-{uuid4().hex[:12]}",
            }],
            usage_metadata={
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "total_tokens": decision.input_tokens + decision.output_tokens,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])
