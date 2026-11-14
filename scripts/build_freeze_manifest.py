"""Build or check the Phase 5 evaluation freeze manifest (offline, deterministic).

Usage:
    python scripts/build_freeze_manifest.py           # rewrite eval/freeze/manifest.json
    python scripts/build_freeze_manifest.py --check   # exit 1 if the committed file differs

The manifest records pins only. It does not authorize paid evaluation runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "eval" / "freeze" / "manifest.json"
PLAYBOOK_PATH = ROOT / "data" / "schemes" / "rule_extractor_playbook.json"
ATTACK_SUITE_PATH = ROOT / "eval" / "red_team" / "attacks_v0.json"
RULE_PACKAGE_DIR = ROOT / "src" / "rules" / "packages"
LLM_CLIENT_PATH = ROOT / "src" / "llm_client.py"
SCHEME_SEARCH_PATH = ROOT / "src" / "api" / "scheme_search.py"

# Specialist allowlists as stated in the prompts in src/workflow/agent_config.py
# (eligibility, supervisor, intake, documents) and the MCP actor map in
# src/mcp_servers/service_routing.py (ACTOR_TOOLS, read below via import).
SPECIALIST_TOOLS = {
    "eligibility": ["check_candidate", "handoff_verdict", "request_clarification", "refer_for_help"],
    "supervisor": ["propose_plan", "finish_plan"],
    "intake": ["read_required_facts", "propose_profile_facts", "finish_intake"],
    "documents": ["inspect_document_metadata"],
}


def sha256_file(path: Path) -> str:
    # Hash with LF line endings, so a Windows CRLF checkout matches Linux CI.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _string_constant(path: Path, name: str) -> str:
    match = re.search(rf'^{name}\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    if match is None:
        raise ValueError(f"{name} not found in {path.name}")
    return match.group(1)


CASES_PATH = ROOT / "data" / "schemes" / "rule_extraction_cases_dev.json"
E3_PLAYBOOK_PATH = ROOT / "data" / "schemes" / "playbooks" / "1.0.0.json"
E3_PLAYBOOK_1_1_0_PATH = ROOT / "data" / "schemes" / "playbooks" / "1.1.0.json"
E3_PLAYBOOK_1_1_1_PATH = ROOT / "data" / "schemes" / "playbooks" / "1.1.1.json"
E3_PLAYBOOK_1_1_2_PATH = ROOT / "data" / "schemes" / "playbooks" / "1.1.2.json"
E4_STATUS_DOC = ROOT / "docs" / "e4_team_override_status_2026-11-13.md"
E4_PERSONA_SET = ROOT / "eval" / "development" / "personas_v1.json"
E4_RUNNER = ROOT / "scripts" / "evaluate_e4_signature_ablation.py"
E4_LLM_ARM = ROOT / "eval" / "harness" / "e4_llm_arm.py"
E4_SHADOW = ROOT / "eval" / "harness" / "e4_shadow.py"
E1_STATUS_DOC = ROOT / "docs" / "e1_team_override_status_2026-11-14.md"
E1_LIVE_RUNNER = ROOT / "scripts" / "run_e1_live.py"
E1_HARNESS = ROOT / "eval" / "harness" / "e1_runner.py"
E1_SINGLE_AGENT = ROOT / "src" / "workflow" / "single_agent.py"
E1_EXPERIMENT = ROOT / "eval" / "experiments" / "e1_agent_cost.json"
SCHEME_RULES_PATH = ROOT / "src" / "rule_extraction_reflexion" / "scheme_rules.py"
EXTRACTION_HO_MANIFEST = ROOT / "eval" / "held_out" / "extraction" / "manifest.json"


def e3_check_case_ids() -> list[str]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases["cases"] if isinstance(cases, dict) else cases
    return sorted(c["clause_id"] for c in cases if c.get("split") == "check")


def extraction_prompt_sha256() -> str:
    sys.path.insert(0, str(ROOT))
    from src.rule_extraction_reflexion.extractor import EXTRACTION_SYSTEM_PROMPT

    return sha256_text(EXTRACTION_SYSTEM_PROMPT)


def playbook_content_hash(path: Path = E3_PLAYBOOK_PATH) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["content_hash"]


def e3_playbook_1_1_0_freeze() -> dict:
    """Pins for playbook 1.1.0. Does not authorize a paid or held-out run."""

    if not E3_PLAYBOOK_1_1_0_PATH.exists():
        return {
            "status": "playbook_missing",
            "path": "data/schemes/playbooks/1.1.0.json",
        }
    ho = {}
    if EXTRACTION_HO_MANIFEST.exists():
        ho = json.loads(EXTRACTION_HO_MANIFEST.read_text(encoding="utf-8"))
    return {
        "scope": (
            "Reflexion E3 playbook 1.1.0 pins (exclusion + approved inclusion "
            "lessons). Not a held-out or paid-run authorization."
        ),
        "playbook": {
            "version": "1.1.0",
            "path": "data/schemes/playbooks/1.1.0.json",
            "content_hash": playbook_content_hash(E3_PLAYBOOK_1_1_0_PATH),
            "file_sha256": sha256_file(E3_PLAYBOOK_1_1_0_PATH),
            "lesson_count": 3,
            "lesson_tags": ["exclusion_clause", "inclusion_clause"],
        },
        "extraction_model": {
            "constant": _string_constant(SCHEME_RULES_PATH, "DEFAULT_EXTRACTION_MODEL"),
            "env_override": "OPENROUTER_RULE_EXTRACTION_MODEL",
        },
        "extraction_prompt": {
            "name": "EXTRACTION_SYSTEM_PROMPT",
            "hash_method": "sha256 of the UTF-8 bytes of the string value, imported not read from source",
            "sha256": extraction_prompt_sha256(),
        },
        "held_out_extraction": {
            "manifest": "eval/held_out/extraction/manifest.json",
            "status": ho.get("status", "missing_manifest"),
            "case_count": ho.get("case_count", 0),
            "blocker": ho.get("blocker"),
        },
        "paid_run_gate": {
            "authorised": False,
            "budget_cap_usd": 20,
            "requires": (
                "explicit go-ahead after held-out extraction cases exist with "
                "dual independent labels; see docs/e3_pdf_path_status_2026-11-13.md"
            ),
        },
        "approval": {
            "status": "playbook_frozen_paid_held_out_not_authorised",
            "approved_on": "2026-11-13",
            "note": (
                "1.1.0 playbook file frozen from approved drafts. "
                "Paid/held-out evaluate remains blocked until custody + go-ahead."
            ),
        },
    }


def build_manifest() -> dict:
    sys.path.insert(0, str(ROOT))
    from src.mcp_servers.service_routing import ACTOR_TOOLS
    from src.workflow import agent_config
    from src.workflow.single_agent import SINGLE_AGENT_TOOLS

    budgets = {
        name.lower(): value
        for name, value in vars(agent_config).items()
        if name.isupper() and isinstance(value, int) and not isinstance(value, bool)
    }
    prompts = {
        f"{agent}.{locale}": {"sha256": sha256_text(text)}
        for agent in sorted(agent_config.AGENT_PROMPTS)
        for locale, text in sorted(agent_config.AGENT_PROMPTS[agent].items())
    }
    packages = {
        path.name: sha256_file(path) for path in sorted(RULE_PACKAGE_DIR.glob("*.json"))
    }
    attack_suite = json.loads(ATTACK_SUITE_PATH.read_text(encoding="utf-8"))

    return {
        "schema_version": 1,
        "purpose": "Phase 5 evaluation freeze pins (offline). Not an authorization for paid runs.",
        "paid_runs": {
            "status": "BLOCKED",
            "requires": "explicit human approval recorded outside this manifest",
        },
        "approval": {
            "status": "approved_by_project_lead",
            "approved_by": "Roy-developer (lead), 2026-11-12",
            "approver_role": "Project lead; freeze owner per team roles, to be confirmed in review",
            "paid_budget_cap_usd": 20,
            "paid_budget_status": "recommended_cap_approved_by_project_lead",
            "restricted_run_gate": {
                "authorised": "conditional",
                "condition": "run only after the threshold sign-offs are recorded in the threshold decisions file",
            },
            "thresholds_status": "approved_by_roy_developer_lead_2026-11-12_other_owners_still_to_sign",
            "note": "Approves this frozen configuration and the recommended budget cap. A held-out run needs the threshold condition above to be met first.",
        },
        "model": {
            "provider": "openrouter",
            "chat_model": _string_constant(LLM_CLIENT_PATH, "DEFAULT_CHAT_MODEL"),
            "chat_model_env_override": "OPENROUTER_CHAT_MODEL",
            "reranker_model": _string_constant(SCHEME_SEARCH_PATH, "OPENROUTER_RERANKER_MODEL"),
            "production_settings_frozen": "snapshot_recorded_pending_owner_approval",
        },
        "prompts": {
            "prompt_version": agent_config.PROMPT_VERSION,
            "entries": prompts,
        },
        "tool_allowlists": {
            "single_agent_c1": sorted(SINGLE_AGENT_TOOLS),
            "specialist_agent_prompts_c2": {k: sorted(v) for k, v in sorted(SPECIALIST_TOOLS.items())},
            "mcp_actor_tools": {actor: sorted(tools) for actor, tools in sorted(ACTOR_TOOLS.items())},
        },
        "budgets": dict(sorted(budgets.items())),
        "rule_packages": {"sha256": packages},
        "attack_suite": {
            "path": "eval/red_team/attacks_v0.json",
            "suite_version": attack_suite["suite_version"],
            "sha256": sha256_file(ATTACK_SUITE_PATH),
        },
        "playbook": (
            {"path": "data/schemes/rule_extractor_playbook.json", "sha256": sha256_file(PLAYBOOK_PATH)}
            if PLAYBOOK_PATH.exists()
            else "absent"
        ),
        "e3_extraction_freeze": {
            "scope": "Reflexion E3 before/after on the development check split. Development only; not held-out.",
            "split": "check",
            "case_ids": e3_check_case_ids(),
            "case_file": {
                "path": "data/schemes/rule_extraction_cases_dev.json",
                "sha256": sha256_file(CASES_PATH),
            },
            "extraction_model": {
                "constant": _string_constant(SCHEME_RULES_PATH, "DEFAULT_EXTRACTION_MODEL"),
                "env_override": "OPENROUTER_RULE_EXTRACTION_MODEL",
            },
            "extraction_prompt": {
                "name": "EXTRACTION_SYSTEM_PROMPT",
                "hash_method": "sha256 of the UTF-8 bytes of the string value, imported not read from source",
                "sha256": extraction_prompt_sha256(),
            },
            "playbook": {
                "version": "1.0.0",
                "path": "data/schemes/playbooks/1.0.0.json",
                "content_hash": playbook_content_hash(),
                "file_sha256": sha256_file(E3_PLAYBOOK_PATH),
            },
            "approval": {
                "status": "approved_by_project_lead_on_behalf_of_role5",
                "approved_on": "2026-11-13",
                "paid_budget_cap_usd": 20,
                "runs": "3 repeats, before (no playbook) and after (1.0.0), check split only",
                "note": "Budget and freeze approved by the project lead on behalf of Role 5. Results are directional: 6 cases.",
            },
        },
        "e3_playbook_1_1_0_freeze": e3_playbook_1_1_0_freeze(),
        "e3_playbook_1_1_1_freeze": (
            {
                "scope": (
                    "Accuracy follow-up playbook 1.1.1 (1.1.0 + APY multi-condition "
                    "and PM-KISAN pension boolean lessons). Team-override evaluate."
                ),
                "playbook": {
                    "version": "1.1.1",
                    "path": "data/schemes/playbooks/1.1.1.json",
                    "content_hash": playbook_content_hash(E3_PLAYBOOK_1_1_1_PATH),
                    "file_sha256": sha256_file(E3_PLAYBOOK_1_1_1_PATH),
                    "lesson_count": 5,
                },
                "paid_run_gate": {
                    "authorised": True,
                    "note": "Team-override free-model evaluate authorised; not PDF unseen held-out.",
                },
            }
            if E3_PLAYBOOK_1_1_1_PATH.exists()
            else {"status": "playbook_missing"}
        ),
        "e3_playbook_1_1_2_freeze": (
            {
                "scope": (
                    "Accuracy follow-up playbook 1.1.2 (1.1.1 + APY multi-sentence "
                    "clause text lesson). Pair with build_cases unique source_text join."
                ),
                "playbook": {
                    "version": "1.1.2",
                    "path": "data/schemes/playbooks/1.1.2.json",
                    "content_hash": playbook_content_hash(E3_PLAYBOOK_1_1_2_PATH),
                    "file_sha256": sha256_file(E3_PLAYBOOK_1_1_2_PATH),
                    "lesson_count": len(
                        json.loads(E3_PLAYBOOK_1_1_2_PATH.read_text(encoding="utf-8"))[
                            "lessons"
                        ]
                    ),
                },
                "paid_run_gate": {
                    "authorised": True,
                    "note": "Team-override free-model evaluate authorised; not PDF unseen held-out.",
                },
            }
            if E3_PLAYBOOK_1_1_2_PATH.exists()
            else {"status": "playbook_missing"}
        ),
        "e4_team_override_freeze": (
            {
                "scope": (
                    "E4 signature ablation team-override on development personas "
                    "(n=46). Not PDF unseen held-out."
                ),
                "paid_run_gate": {
                    "authorised": True,
                    "note": (
                        "Team-override free-model evaluate authorised; "
                        "not PDF unseen held-out."
                    ),
                },
                "persona_set": {
                    "path": "eval/development/personas_v1.json",
                    "sha256": sha256_file(E4_PERSONA_SET),
                    "case_count": sum(
                        len(p.get("expected_by_scheme") or {})
                        for p in json.loads(
                            E4_PERSONA_SET.read_text(encoding="utf-8")
                        ).get("personas", [])
                    ),
                },
                "runner": {
                    "path": "scripts/evaluate_e4_signature_ablation.py",
                    "sha256": sha256_file(E4_RUNNER),
                },
                "modules": {
                    "e4_llm_arm": {
                        "path": "eval/harness/e4_llm_arm.py",
                        "sha256": sha256_file(E4_LLM_ARM),
                    },
                    "e4_shadow": {
                        "path": "eval/harness/e4_shadow.py",
                        "sha256": sha256_file(E4_SHADOW),
                    },
                },
                "status_doc": "docs/e4_team_override_status_2026-11-13.md",
            }
            if E4_PERSONA_SET.exists() and E4_RUNNER.exists() and E4_LLM_ARM.exists()
            else {"status": "e4_team_override_artifacts_missing"}
        ),
        "e2_defences_freeze": (
            {
                "scope": (
                    "E2 defences off/on, development only: 8 scripted application-boundary "
                    "scenarios plus offline injection/ID/scam checks. Not independent, not frozen-independent."
                ),
                "paid_run_gate": {"authorised": False, "note": "E2 uses scripted models; no paid calls."},
                "runners": {
                    "runtime": {"path": "scripts/evaluate_e2_runtime.py", "sha256": sha256_file(ROOT / "scripts" / "evaluate_e2_runtime.py")},
                    "defences_dev": {"path": "scripts/evaluate_e2_defences_dev.py", "sha256": sha256_file(ROOT / "scripts" / "evaluate_e2_defences_dev.py")},
                },
                "modules": {
                    "e2_runner": {"path": "eval/harness/e2_runner.py", "sha256": sha256_file(ROOT / "eval" / "harness" / "e2_runner.py")},
                },
                "tests": {
                    "test_e2_runtime": {"path": "tests/test_e2_runtime.py", "sha256": sha256_file(ROOT / "tests" / "test_e2_runtime.py")},
                },
                "record": {"path": "docs/E2_RUNTIME_RECORD_2026-11-14.md", "sha256": sha256_file(ROOT / "docs" / "E2_RUNTIME_RECORD_2026-11-14.md")},
            }
            if (ROOT / "scripts" / "evaluate_e2_runtime.py").exists()
            and (ROOT / "docs" / "E2_RUNTIME_RECORD_2026-11-14.md").exists()
            else {"status": "e2_artifacts_missing"}
        ),
        "e1_team_override_freeze": (
            {
                "scope": (
                    "E1 C0/C1/C2 cost-benefit team-override on development "
                    "personas. Not PDF unseen held-out."
                ),
                "paid_run_gate": {
                    "authorised": True,
                    "note": (
                        "Team-override live/free-model evaluate authorised; "
                        "not PDF unseen held-out."
                    ),
                },
                "model_id": "openai/gpt-4o-mini",
                "budget": {
                    "model_calls": agent_config.MAX_CONVERSATION_MODEL_CALLS,
                    "agent_tool_calls": agent_config.MAX_CONVERSATION_TOOL_CALLS,
                    "domain_calls": agent_config.MAX_CONVERSATION_DOMAIN_TOOL_CALLS,
                    "agent_steps": agent_config.MAX_CONVERSATION_AGENT_STEPS,
                    "total_tokens": agent_config.MAX_CONVERSATION_TOKENS,
                    "max_completion_tokens": agent_config.MAX_COMPLETION_TOKENS,
                },
                "runner": {
                    "path": "scripts/run_e1_live.py",
                    "sha256": sha256_file(E1_LIVE_RUNNER),
                },
                "modules": {
                    "e1_runner": {
                        "path": "eval/harness/e1_runner.py",
                        "sha256": sha256_file(E1_HARNESS),
                    },
                    "single_agent": {
                        "path": "src/workflow/single_agent.py",
                        "sha256": sha256_file(E1_SINGLE_AGENT),
                    },
                },
                "experiment": {
                    "path": "eval/experiments/e1_agent_cost.json",
                    "sha256": sha256_file(E1_EXPERIMENT),
                },
                "status_doc": "docs/e1_team_override_status_2026-11-14.md",
            }
            if (
                E1_LIVE_RUNNER.exists()
                and E1_HARNESS.exists()
                and E1_SINGLE_AGENT.exists()
                and E1_EXPERIMENT.exists()
            )
            else {"status": "e1_team_override_artifacts_missing"}
        ),
        "memory_policy_version": "1.0.0",
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    rendered = render(build_manifest())
    if "--check" in argv:
        committed = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else ""
        if committed != rendered:
            print(f"{MANIFEST_PATH} is out of date; run scripts/build_freeze_manifest.py")
            return 1
        print("freeze manifest is up to date")
        return 0
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
