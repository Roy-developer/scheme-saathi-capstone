"""Extract draft rules from scheme passages with a model, then score them.

For each scheme this asks a model for draft rules, throws away any rule whose
quote is not in its passage, writes the rest to ``--output-dir`` and, when
gold drafts exist, scores them. Output is a draft for human review only.

Needs OPENROUTER_API_KEY. Example:
    python -m scripts.extract_scheme_rules --schemes APY-IN PM-KISAN-IN
"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from src.api.scheme_search import load_passages
from src.rules.extraction import (
    DraftRuleSet,
    extract_scheme_rules,
    load_approved_lessons,
    score_many,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "data" / "schemes"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1-mini"


def openrouter_complete(system: str, user: str) -> str:
    """Call the chat model once at temperature 0 and return its text."""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required.")
    payload = json.dumps(
        {
            "model": os.getenv("OPENROUTER_CHAT_MODEL", DEFAULT_MODEL),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_CHAT_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.load(response)
    return body["choices"][0]["message"]["content"]


def load_gold(gold_dir: Path) -> dict[str, DraftRuleSet]:
    gold = {}
    for path in sorted(gold_dir.glob("*.json")):
        rule_set = DraftRuleSet.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        gold[rule_set.scheme_id] = rule_set
    return gold


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DATA / "passages")
    parser.add_argument("--gold-dir", type=Path, default=DATA / "rule_gold_drafts")
    parser.add_argument("--output-dir", type=Path, default=DATA / "rule_extracted")
    parser.add_argument(
        "--playbook", type=Path, default=DATA / "rule_extractor_playbook.json"
    )
    parser.add_argument("--schemes", nargs="*", help="Default: every gold scheme.")
    parser.add_argument("--no-lessons", action="store_true")
    args = parser.parse_args()

    passages = load_passages(args.corpus)
    gold = load_gold(args.gold_dir)
    schemes = args.schemes or sorted(gold)
    lessons = () if args.no_lessons else load_approved_lessons(args.playbook)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scored = {}
    for scheme_id in schemes:
        result = extract_scheme_rules(
            scheme_id, passages, openrouter_complete, lessons
        )
        out = {
            **json.loads(result.rule_set.model_dump_json()),
            "rejected": list(result.rejected),
        }
        (args.output_dir / f"{scheme_id}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if scheme_id in gold:
            scored[scheme_id] = (result.rule_set.rules, gold[scheme_id].rules)
        print(
            f"{scheme_id}: {len(result.rule_set.rules)} rules, "
            f"{len(result.rejected)} rejected"
        )

    if scored:
        report = score_many(scored)
        report["lessons_used"] = [lesson.lesson_id for lesson in lessons]
        (args.output_dir / "_scores.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"micro precision {report['micro_precision']:.2f} "
            f"recall {report['micro_recall']:.2f} f1 {report['micro_f1']:.2f}"
        )


if __name__ == "__main__":
    main()
