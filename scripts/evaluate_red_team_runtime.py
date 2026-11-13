"""Run approved application-path attacks and preserve failures as evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "eval" / "reports" / "red_team_runtime_latest.json",
    )
    args = parser.parse_args()
    suite = json.loads((ROOT / "eval" / "red_team" / "attacks_v0.json").read_text(encoding="utf-8"))
    env = os.environ.copy()
    env.pop("SCHEME_SAATHI_BACKUP_DIR", None)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        env["SCHEME_SAATHI_PORTAL_URL"] = f"http://127.0.0.1:{sock.getsockname()[1]}"
    with tempfile.TemporaryDirectory(prefix="saathi-runtime-attacks-") as folder:
        junit = Path(folder) / "results.xml"
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "--tb=short",
                "--disable-warnings", "-o", "junit_family=legacy",
                f"--junitxml={junit}", "tests/test_red_team_runtime.py",
            ],
            cwd=ROOT, env=env, capture_output=True, text=True, errors="replace",
        )
        recorded = {}
        if junit.exists():
            for case in ET.parse(junit).getroot().iter("testcase"):
                properties = {
                    item.attrib["name"]: item.attrib.get("value", "")
                    for item in case.findall("./properties/property")
                }
                attack_id = properties.get("attack_id")
                if attack_id is None:
                    name = case.attrib.get("name", "")
                    attack_id = next(
                        (attack["attack_id"] for attack in suite["attacks"]
                         if f"[{attack['attack_id']}]" in name),
                        None,
                    )
                if attack_id is None:
                    continue
                problem = next(
                    (item for item in case if item.tag in {"failure", "error", "skipped"}),
                    None,
                )
                recorded[attack_id] = {
                    "attack_id": attack_id,
                    "status": (
                        "passed" if problem is None else
                        "failed" if problem.tag == "failure" else
                        "error" if problem.tag == "error" else "not_run"
                    ),
                    "surface": properties.get("surface"),
                    "detail": (
                        "Application-path assertions passed."
                        if problem is None else
                        (problem.text or problem.attrib.get("message", ""))[-4000:]
                    ),
                }
    per_attack = [
        recorded.get(attack["attack_id"], {
            "attack_id": attack["attack_id"], "status": "not_run",
            "surface": None, "detail": "No pytest result recorded.",
        })
        for attack in suite["attacks"]
    ]
    report = {
        "suite_version": suite["suite_version"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": "Synthetic development API/graph/MCP/portal attacks; scripted offline models, not live LLM efficacy or full L9 validation.",
        "limitations": [
            "Search poisoning is injected at the MCP response boundary; corpus is unchanged.",
            "Instruction-override cases enter through intake text, not an uploaded document or a retrieved passage.",
            "The complete APY profile preserves confirmed age on interview; its quarantined reader is not invoked. PM-KISAN inflation cases explicitly require reader execution.",
            "Identifier fixtures are synthetic; checked traces are local responses, checkpoint state and captured logs, not every external telemetry sink.",
            "Memory uses bearer return codes; no authenticated household ownership is established by these checks.",
            "Scam cases cover text lures, not QR image processing.",
            "A passing case establishes only its declared assertions; the suite is not frozen held-out or independent review evidence.",
        ],
        "attack_count": len(per_attack),
        "passed": sum(item["status"] == "passed" for item in per_attack),
        "failed": sum(item["status"] == "failed" for item in per_attack),
        "errors": sum(item["status"] == "error" for item in per_attack),
        "not_run": sum(item["status"] == "not_run" for item in per_attack),
        "pytest_exit_code": result.returncode,
        "per_attack": per_attack,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "per_attack"}, indent=2))
    for item in per_attack:
        if item["status"] != "passed":
            print(f"\n{item['attack_id']}: {item['status']}\n{item['detail']}")
    if result.returncode and not recorded:
        print((result.stdout + result.stderr)[-6000:])
    return int(result.returncode != 0 or report["passed"] != report["attack_count"])


if __name__ == "__main__":
    raise SystemExit(main())
