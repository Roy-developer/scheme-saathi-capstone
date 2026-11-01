"""Teach/test the MCP tool contract using an in-memory client."""

# asyncio lets a normal pytest function run asynchronous MCP client calls.
import asyncio

# Client is the SDK object a backend workflow uses to call MCP tools.
from mcp import Client

# Importing the server object allows an in-memory test without a subprocess.
from src.mcp_servers.rule_engine import mcp

async def call_practise_tool():
    async with Client(mcp) as client:
        response = await client.call_tool(
            "identify_scheme",
            {"scheme_id": "IGNWPS-MH"},
        )
        return response.structured_content




async def evaluate_examples() -> list[str]:
    """Call one MCP tool with three synthetic cases and collect verdicts."""
    # Each tuple is (expected result, widow answer, BPL-card answer).
    examples = (
        ("eligible", True, True),
        ("need_more_information", True, False),
        ("not_eligible", False, True),
    )
    # Keep actual results in the same order as the examples.
    results: list[str] = []

    # Client(mcp) talks directly to the server object: no port or process.
    async with Client(mcp, raise_exceptions=True) as client:
        # Try the same named MCP tool with each set of profile facts.
        for expected, is_widow, bpl_card_shown in examples:
            # call_tool sends the tool name and its JSON-shaped arguments.
            response = await client.call_tool(
                "evaluate_eligibility",
                {
                    "scheme_id": "IGNWPS-MH",
                    "profile": {
                        "date_of_birth": "1986-10-30",
                        "application_date": "2026-10-30",
                        "is_widow": is_widow,
                        "bpl_card_shown": bpl_card_shown,
                    },
                },
            )
            # A normal eligibility verdict should be a successful tool call.
            assert not response.is_error
            # structured_content is typed data intended for application code.
            actual = response.structured_content["result"]
            # Compare immediately so a failure identifies the wrong example.
            assert actual == expected
            results.append(actual)

    # Return all three verdicts for the outer pytest assertion.
    return results


def test_mcp_tool_evaluates_all_three_verdicts() -> None:
    """Verify that the MCP interface preserves all three evaluator outcomes."""
    # asyncio.run drives the async in-memory MCP test to completion.
    assert asyncio.run(evaluate_examples()) == [
        "eligible",
        "need_more_information",
        "not_eligible",
    ]
