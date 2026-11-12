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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _string_constant(path: Path, name: str) -> str:
    match = re.search(rf'^{name}\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    if match is None:
        raise ValueError(f"{name} not found in {path.name}")
    return match.group(1)


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
        "model": {
            "provider": "openrouter",
            "chat_model": _string_constant(LLM_CLIENT_PATH, "DEFAULT_CHAT_MODEL"),
            "chat_model_env_override": "OPENROUTER_CHAT_MODEL",
            "reranker_model": _string_constant(SCHEME_SEARCH_PATH, "OPENROUTER_RERANKER_MODEL"),
            "production_settings_frozen": "TBD_FIXED_BEFORE_RUN",
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
        "memory_policy_version": "TBD_WAVE_2",
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
