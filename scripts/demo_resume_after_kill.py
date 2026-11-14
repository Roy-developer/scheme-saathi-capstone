"""Live demo: hard-kill the app mid-interview, then resume in a new process.

Required evidence (capstone guide, L8): "Stop the process mid-run and resume
it." Two separate Python processes share only the on-disk SQLite checkpoint:

  1. start   - begin an IGNWPS-MH interview, answer one question, then die
               with ``os._exit(137)`` (no shutdown hooks, no cleanup).
  2. resume  - a brand-new process reads the saved journey, sees the same
               pending question, finishes the interview and prints the verdict.

No model key is needed; the rule engine and checkpoint are all real.

    python scripts/demo_resume_after_kill.py               # mid-interview
    python scripts/demo_resume_after_kill.py application   # mid-application

The ``application`` scenario kills the app after a human approval exists on
an exact draft, then submits from a fresh process with the saved approval.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def child_env(tmp: str, portal_port: int) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)
    env.update({
        "SCHEME_SAATHI_DISABLE_DOTENV": "1",
        "SCHEME_SAATHI_DISABLE_CROSS_ENCODER": "1",
        "SCHEME_SAATHI_CHECKPOINT_DB": str(Path(tmp) / "journey.sqlite3"),
        "SCHEME_SAATHI_APPLICATION_DB": str(Path(tmp) / "applications.sqlite3"),
        # Own portal port so the demo never collides with a running dev stack.
        "SCHEME_SAATHI_PORTAL_URL": f"http://127.0.0.1:{portal_port}",
        "PYTHONPATH": str(ROOT),
    })
    return env


DOCUMENTS = {
    "identity_proof": "available", "bank_account_proof": "available",
    "widow_status_proof": "available",
}
DRAFT_BODY = {
    "scheme_id": "IGNWPS-MH", "documents": DOCUMENTS,
    "profile_name": "Synthetic Example",
    "document_metadata": {"identity_proof": {"name": "Synthetic Example"}},
}


def application_start(state_file: Path) -> None:
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from src.api.app import app

    cid = str(uuid4())
    with TestClient(app) as client:
        verdict = client.post("/api/v1/journey", json={
            "action": "evaluate", "conversation_id": cid, "scheme_id": "IGNWPS-MH",
            "profile": {"date_of_birth": "1986-01-01", "application_date": "2026-01-01",
                        "is_widow": True, "bpl_card_shown": True},
        }).json()
        client.post(f"/api/v1/journey/{cid}/documents", json=DRAFT_BODY)
        draft = client.post(f"/api/v1/journey/{cid}/drafts", json=DRAFT_BODY).json()
        url = f"/api/v1/journey/{cid}/drafts/{draft['draft_id']}/approval"
        identity = {"revision": draft["revision"], "fingerprint": draft["fingerprint"]}
        approved = client.post(url, json={"action": "approve", **identity}).json()
        print(f"[start] verdict={verdict['status']}; draft rev {draft['revision']} "
              f"approved={approved['approved']}; NOT yet submitted")
        state_file.write_text(json.dumps(
            {"cid": cid, "draft_id": draft["draft_id"], **identity}), encoding="utf-8")
        print("[start] KILL: os._exit(137) with an approved, unsubmitted draft")
        sys.stdout.flush()
        os._exit(137)


def application_resume(state_file: Path) -> None:
    from fastapi.testclient import TestClient
    from src.api.app import app

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    cid, draft_id = saved["cid"], saved["draft_id"]
    identity = {"revision": saved["revision"], "fingerprint": saved["fingerprint"]}
    with TestClient(app) as client:
        draft = client.get(f"/api/v1/journey/{cid}/drafts/{draft_id}").json()
        print(f"[resume] new process pid={os.getpid()}; draft rev {draft['revision']} "
              f"approved={draft['approved']}, same fingerprint="
              f"{draft['fingerprint'] == saved['fingerprint']}")
        assert draft["approved"] and draft["fingerprint"] == saved["fingerprint"]
        url = f"/api/v1/journey/{cid}/drafts/{draft_id}/approval"
        stale = client.post(url, json={"action": "submit", "revision": identity["revision"],
                                       "fingerprint": "0" * 64})
        print(f"[resume] submit with a wrong fingerprint -> HTTP {stale.status_code}")
        assert stale.status_code == 409
        done = client.post(url, json={"action": "submit", **identity})
        print(f"[resume] submit with the saved approval -> HTTP {done.status_code}, "
              f"receipt={done.json().get('receipt_id')}")
        assert done.status_code == 200 and done.json().get("receipt_id")
        print("[resume] OK: the approved draft survived a hard kill and was submitted once.")


def phase_start(state_file: Path) -> None:
    if os.environ.get("DEMO_SCENARIO") == "application":
        return application_start(state_file)

    from fastapi.testclient import TestClient
    from src.api.app import app

    with TestClient(app) as client:
        body = client.post("/api/v1/journey", json={
            "action": "interview", "scheme_id": "IGNWPS-MH",
            "profile": {"application_date": "2026-10-30"},
        }).json()
        cid = body["conversation_id"]
        print(f"[start] asked: {body['pending_fact']} -> answering 'yes'")
        body = client.post(
            f"/api/v1/journey/{cid}/messages", json={"message": "yes"}).json()
        print(f"[start] now waiting on: {body['pending_fact']}")
        state_file.write_text(json.dumps(
            {"cid": cid, "pending": body["pending_fact"]}), encoding="utf-8")
        sys.stdout.flush()
        print("[start] KILL: os._exit(137), no graceful shutdown")
        sys.stdout.flush()
        os._exit(137)


def phase_resume(state_file: Path) -> None:
    if os.environ.get("DEMO_SCENARIO") == "application":
        return application_resume(state_file)
    from fastapi.testclient import TestClient
    from src.api.app import app

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    cid = saved["cid"]
    with TestClient(app) as client:
        body = client.get(f"/api/v1/journey/{cid}").json()
        print(f"[resume] new process pid={os.getpid()}; saved status={body['status']}, "
              f"pending={body['pending_fact']} (was {saved['pending']})")
        assert body["pending_fact"] == saved["pending"], "pending question was lost"
        for answer in ["30 October 1976", "yes"]:
            body = client.post(
                f"/api/v1/journey/{cid}/messages", json={"message": answer}).json()
        print(f"[resume] final status: {body['status']}")
        assert body["status"] == "eligible", body["status"]
        print("[resume] OK: the interview survived a hard kill and finished.")


def stop_orphans(ports: tuple[int, ...]) -> None:
    """A hard kill orphans the portal child; stop only listeners on our ports."""

    import re

    listing = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in listing.splitlines():
        match = re.search(r"127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
        if match and int(match.group(1)) in ports:
            subprocess.run(["taskkill", "/F", "/PID", match.group(2)],
                           capture_output=True)


def main() -> int:
    if len(sys.argv) == 3:  # internal: child phase
        {"start": phase_start, "resume": phase_resume}[sys.argv[1]](Path(sys.argv[2]))
        return 0
    os.environ["DEMO_SCENARIO"] = sys.argv[1] if len(sys.argv) == 2 else "interview"
    stop_orphans((8791, 8792))  # leftovers from an interrupted earlier run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = subprocess.run(
                [sys.executable, __file__, "start", str(state)],
                env=child_env(tmp, 8791), cwd=ROOT)
            print(f"[parent] first process exit code: {first.returncode} (killed on purpose)")
            if first.returncode != 137 or not state.exists():
                print("[parent] FAIL: the first process did not reach the kill point")
                return 1
            second = subprocess.run(
                [sys.executable, __file__, "resume", str(state)],
                env=child_env(tmp, 8792), cwd=ROOT)
            return second.returncode
    finally:
        stop_orphans((8791, 8792))


if __name__ == "__main__":
    raise SystemExit(main())
