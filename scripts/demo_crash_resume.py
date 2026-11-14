"""Crash-resume demo: kill the process mid-interview, restart, carry on.

Run:  python scripts/demo_crash_resume.py

The journey graph is checkpointed to SQLite after every node (the same
AsyncSqliteSaver the API uses). This script runs three separate OS processes
against one temporary database:

  1. ``start``  - begin an eligibility interview, answer two questions, then
                  die abruptly with ``os._exit`` (no cleanup, like a crash).
  2. ``resume`` - a brand-new process opens the same database and continues
                  the same conversation_id from the pending question.
  3. a check that the resumed process asks exactly the question the crashed
     one was waiting on, and that earlier answers were not lost.

Deterministic: no network or LLM. Search/eligibility tools are stubbed, and
"yes"/"no" replies are parsed by the journey's built-in answer handling.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEME_ID = "IGNWPS-MH"
PROFILE = {"application_date": "2026-10-30"}


async def _open_graph(db_path: str):
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from src.api.eligibility import EligibilityResponse
    from src.rules.data_provider import RulePackageProvider
    from src.workflow.intake import AnswerInterpretation
    from src.workflow.journey import build_journey_graph

    async def search_tool(_client, _query):
        return []

    async def identity_rewriter(query):
        return query

    async def eligibility_tool(_client, scheme_id, _profile):
        return EligibilityResponse(
            scheme_id=scheme_id, result="eligible", reason="Demo stub.",
            age_on_application_date=40, missing_fields=[],
            deciding_rule_ids=[], evidence=[],
        )

    async def uncertain(_fact, _question, _reply):
        return AnswerInterpretation(kind="uncertain", confidence=0.0)

    connection = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(connection)
    await checkpointer.setup()
    graph = build_journey_graph(
        None,
        RulePackageProvider().packages,
        search_tool=search_tool,
        eligibility_tool=eligibility_tool,
        query_rewriter=identity_rewriter,
        answer_interpreter=uncertain,
        checkpointer=checkpointer,
    )
    return graph, connection


def _emit(tag: str, result) -> None:
    print(f"  [{tag}] status={result.status} pending_fact={result.pending_fact}")
    print(f"  [{tag}] question={result.question!r}")


async def _start(db_path: str) -> None:
    from src.workflow.journey import JourneyRequest, resume_journey, run_journey

    graph, _ = await _open_graph(db_path)
    result = await run_journey(
        graph, JourneyRequest(action="interview", scheme_id=SCHEME_ID, profile=PROFILE),
    )
    _emit("process 1, Q1", result)
    result = await resume_journey(graph, result.conversation_id, "yes")
    _emit("process 1, Q2", result)
    state = {
        "conversation_id": str(result.conversation_id),
        "pending_fact": result.pending_fact,
        "question": result.question,
        "known": sorted(result.known_fact_names),
    }
    Path(db_path + ".state.json").write_text(json.dumps(state), encoding="utf-8")
    print("  [process 1] CRASH now (os._exit, no cleanup)")
    sys.stdout.flush()
    os._exit(137)


async def _resume(db_path: str) -> None:
    from uuid import UUID

    from src.workflow.journey import get_journey, resume_journey

    before = json.loads(Path(db_path + ".state.json").read_text(encoding="utf-8"))
    graph, connection = await _open_graph(db_path)
    cid = UUID(before["conversation_id"])

    try:
        recovered = await get_journey(graph, cid)
        _emit("process 2, recovered", recovered)
        assert recovered.pending_fact == before["pending_fact"], "pending question lost"
        assert recovered.question == before["question"], "question text changed"
        assert set(before["known"]) <= set(recovered.known_fact_names), "answers lost"
        print("  [process 2] same question and all earlier answers recovered: OK")

        nxt = await resume_journey(graph, cid, "1986-10-30")
        _emit("process 2, continued", nxt)
        assert nxt.pending_fact != before["pending_fact"] or nxt.status != "awaiting_answer"
        print("  [process 2] interview continued past the crash point: OK")
    finally:
        await connection.close()


def _run_child(phase: str, db_path: str) -> int:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), phase, db_path], cwd=ROOT,
    ).returncode


def main() -> int:
    if len(sys.argv) == 3:
        phase, db_path = sys.argv[1], sys.argv[2]
        asyncio.run({"start": _start, "resume": _resume}[phase](db_path))
        return 0

    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / "demo_journey.sqlite3")
        print("== Process 1: start interview, answer two questions, then crash ==")
        code = _run_child("start", db_path)
        print(f"  process 1 exit code: {code} (non-zero = crashed)\n")
        if code == 0:
            print("FAIL: process 1 should have crashed")
            return 1
        print("== Process 2: fresh process, same database, same conversation ==")
        code = _run_child("resume", db_path)
        if code != 0:
            print("FAIL: resume did not succeed")
            return 1
    print("\nPASS: journey survived a hard process crash and resumed from SQLite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
