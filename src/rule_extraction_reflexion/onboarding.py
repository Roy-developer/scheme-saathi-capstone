"""Put a scheme into the app: the mechanical steps only.

This module does the file work of putting a scheme in the app, which used to
be done by hand:

    move the package -> write its bundle -> cite its source on each fact ->
    re-pin the registry hash -> add search passages -> update the Reflexion case

``plan_onboarding`` works out every change in memory, then runs the app's real
loader on a temporary copy of the project with those changes applied, so
nothing is written unless the result would load. ``apply_onboarding`` writes
the plan.

The app never imports this module; ``python -m src.rule_extraction_reflexion.scheme_rules onboard`` runs it.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.rules.facts import FactDefinition, FactRegistry
from src.rules.models import RulePackage

# Runs in a separate Python, inside the temporary copy, so it exercises the
# copy's own loader and its re-pinned hashes rather than the code already loaded.
_LOAD_CHECK = """
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import src

if Path(src.__file__).resolve().parent != (Path.cwd() / "src").resolve():
    raise SystemExit("The load check imported the wrong copy of the project")

from src.rules.data_provider import RulePackageProvider

provider = RulePackageProvider()
if provider.bundles[sys.argv[1]].activation_state != "approved":
    raise SystemExit("The new bundle is not approved")
"""


class OnboardingRefused(ValueError):
    """A required input is missing or wrong, so nothing may be written."""


@dataclass(frozen=True)
class ProjectPaths:
    """Where each onboarding file lives under one project root."""

    root: Path

    @property
    def rules(self) -> Path:
        return self.root / "src" / "rules"

    @property
    def packages(self) -> Path:
        return self.rules / "packages"

    @property
    def fact_registry(self) -> Path:
        return self.rules / "fact_registry.json"

    @property
    def bundle_registry(self) -> Path:
        return self.rules / "bundle_registry.json"

    @property
    def schemes(self) -> Path:
        return self.root / "data" / "schemes"

    @property
    def staged_packages(self) -> Path:
        return self.schemes / "reflexion_packages"

    @property
    def sources(self) -> Path:
        return self.schemes / "rule_extraction_sources"

    @property
    def passages(self) -> Path:
        return self.schemes / "passages"

    def passages_file(self, scheme_id: str) -> Path:
        """The one corpus file holding this scheme's passages."""

        return self.passages / f"{scheme_id.lower().replace('-', '_')}_passages.json"

    @property
    def cases(self) -> Path:
        return self.schemes / "rule_extraction_cases_dev.json"

    @property
    def docs(self) -> Path:
        return self.root / "docs"


@dataclass(frozen=True)
class OnboardingPlan:
    """Every change for one scheme, worked out but not yet written."""

    scheme_id: str
    staged_package: Path
    changes: dict[Path, bytes]
    summary: tuple[str, ...]
    for_people: tuple[str, ...]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _like(original: bytes, text: str) -> bytes:
    """Encode LF text with the line endings of the file it replaces."""

    return (text.replace("\n", "\r\n") if b"\r\n" in original else text).encode("utf-8")


def _json_like(original: bytes, data: object) -> bytes:
    return _like(original, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _file_for_scheme(folder: Path, scheme_id: str) -> Path | None:
    """Find the JSON file naming this scheme, whatever the file is called."""

    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        if json.loads(path.read_bytes()).get("scheme_id") == scheme_id:
            return path
    return None


def _bundle_facts(package: RulePackage, registry: FactRegistry) -> dict[str, FactDefinition]:
    """Return every fact the rules need, including what derived facts are built from."""

    fact_ids = set(package.required_facts)
    try:
        for rule in package.rules:
            fact_ids.update((rule.field, *registry.get(rule.field).derived_from))
        return {fact_id: registry.get(fact_id) for fact_id in sorted(fact_ids)}
    except KeyError as error:
        raise OnboardingRefused(f"Fact is not in the registry: {error.args[0]}") from error


def _require_same_official_text(package: RulePackage, source: dict) -> None:
    """Refuse a package whose clauses differ from the confirmed source file."""

    source_text = {case["clause_id"]: case["text"] for case in source["cases"]}
    for rule in package.rules:
        if source_text.get(rule.source_clause_id) != rule.source_text:
            raise OnboardingRefused(
                f"Rule {rule.rule_id} does not quote the source file's text "
                f"for {rule.source_clause_id}"
            )


def _with_scheme_source_on_facts(
    raw: bytes, facts: dict[str, FactDefinition], source_url: str,
) -> tuple[bytes, list[str]]:
    """Cite the scheme's source on each of its facts, leaving others untouched."""

    uncited = sorted(
        fact_id for fact_id, definition in facts.items()
        if source_url not in {str(url) for url in definition.source_refs}
    )
    if not uncited:
        return raw, []
    data = json.loads(raw)
    for definition in data["definitions"]:
        if definition["fact_id"] in uncited:
            definition["source_refs"].append(source_url)
    return _json_like(raw, data), uncited


def _bundle_entry(
    package: RulePackage,
    package_file: str,
    package_sha: str,
    registry_version: str,
    registry_sha: str,
    facts: dict[str, FactDefinition],
    registry: FactRegistry,
) -> dict:
    return {
        "scheme_id": package.scheme_id,
        "bundle_version": package.package_version,
        "activation_state": "approved",
        "package_file": package_file,
        "package_version": package.package_version,
        "package_sha256": package_sha,
        "registry_version": registry_version,
        "registry_sha256": registry_sha,
        "fact_ids": list(facts),
        "source_clause_ids": sorted({rule.source_clause_id for rule in package.rules}),
        "checklist_version": None,
        "mock_form_version": None,
    }


def _passages(package: RulePackage, details: dict) -> list[dict]:
    """Build search passages from the source file; the package supplies the source."""

    source = package.source
    return [
        {
            "passage_id": item["passage_id"],
            "scheme_id": package.scheme_id,
            "scheme_name": details["scheme_name"],
            "jurisdiction": details["jurisdiction"],
            "language": item.get("language", "en"),
            "section": item["section"],
            "text": item["text"],
            "source": {
                "source_id": details["source_id"],
                "publisher": source.publisher,
                "url": str(source.source_url),
                "collected_at": source.collected_at.isoformat(),
                "publication_date": details.get("publication_date"),
                "locator": item["locator"],
            },
            "review_status": item["review_status"],
        }
        for item in details["passages"]
    ]


def _with_case_entries(
    raw: bytes, cases: list[dict], package_file: str, package_sha: str,
) -> tuple[bytes, list[str]]:
    """Point Reflexion cases at the live package, keeping one case per line."""

    lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
    without_split = []
    for case in cases:
        marker = f'"clause_id": {json.dumps(case["clause_id"], ensure_ascii=False)}'
        found = [index for index, line in enumerate(lines) if marker in line]
        if len(found) > 1:
            raise OnboardingRefused(f"Clause listed twice in the cases file: {case['clause_id']}")
        if found:
            line = lines[found[0]]
            comma = "," if line.rstrip().endswith(",") else ""
            entry = json.loads(line.strip().rstrip(","))
            entry.pop("package_dir", None)
            entry["package_sha256"] = package_sha
            lines[found[0]] = "    " + json.dumps(entry, ensure_ascii=False) + comma
        else:
            entry = {
                "package": package_file,
                "package_sha256": package_sha,
                "clause_id": case["clause_id"],
                "context": [],
                "topic_tags": case["topic_tags"],
                "split": case.get("split"),
            }
            last = max(i for i, line in enumerate(lines) if '"clause_id"' in line)
            lines[last] = lines[last].rstrip().rstrip(",") + ","
            lines.insert(last + 1, "    " + json.dumps(entry, ensure_ascii=False))
        if entry.get("split") is None:
            without_split.append(case["clause_id"])
    return _like(raw, "\n".join(lines)), without_split


def _check_in_a_copy(paths: ProjectPaths, scheme_id: str, changes: dict[Path, bytes]) -> None:
    """Refuse unless the app's loader accepts the project with these changes."""

    from src.api.scheme_search import load_passages

    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder)
        shutil.copytree(
            paths.root / "src", copy / "src",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        for path, content in changes.items():
            target = copy / path.relative_to(paths.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        finished = subprocess.run(
            [sys.executable, "-c", _LOAD_CHECK, scheme_id],
            cwd=copy, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if finished.returncode != 0:
            detail = (finished.stderr or finished.stdout).strip().splitlines()
            raise OnboardingRefused(
                "The app's loader would refuse this result: "
                + (detail[-1] if detail else "no detail")
            )
        try:
            load_passages(copy / paths.passages.relative_to(paths.root))
        except ValueError as error:
            raise OnboardingRefused(f"The search passages are invalid: {error}") from error


def plan_onboarding(scheme_id: str, paths: ProjectPaths) -> OnboardingPlan:
    """Work out and check every change for a scheme, writing nothing.

    Raises:
        OnboardingRefused: an input is missing or wrong, or the app's loader
            would refuse the result.
    """

    bundles_raw = paths.bundle_registry.read_bytes()
    bundles = json.loads(bundles_raw)
    if any(bundle["scheme_id"] == scheme_id for bundle in bundles["bundles"]):
        raise OnboardingRefused(f"{scheme_id} is already in the app; nothing to do.")

    staged = _file_for_scheme(paths.staged_packages, scheme_id)
    if staged is None:
        raise OnboardingRefused(
            f"No approved package for {scheme_id} in {paths.staged_packages}"
        )
    package_raw = staged.read_bytes()
    package = RulePackage.model_validate_json(package_raw)
    # Only a package a person has approved for the mock portal may go live.
    if package.approval_status != "approved_for_mock_portal":
        raise OnboardingRefused(
            f"{staged.name} is not approved for the mock portal "
            f"(status: {package.approval_status}); nothing to do."
        )
    package_sha = _sha256(package_raw)
    target = paths.packages / staged.name
    if target.exists():
        raise OnboardingRefused(f"A live package already has this name: {staged.name}")

    source_path = _file_for_scheme(paths.sources, scheme_id)
    if source_path is None:
        raise OnboardingRefused(f"No source file for {scheme_id} in {paths.sources}")
    source = json.loads(source_path.read_bytes())
    _require_same_official_text(package, source)
    details = source.get("onboarding")
    if not details or not details.get("passages"):
        raise OnboardingRefused(
            f"{source_path.name} has no \"onboarding\" block with search passages"
        )

    cases_raw = paths.cases.read_bytes()

    registry_raw = paths.fact_registry.read_bytes()
    registry = FactRegistry.model_validate_json(registry_raw)
    facts = _bundle_facts(package, registry)
    new_registry, cited = _with_scheme_source_on_facts(
        registry_raw, facts, str(package.source.source_url),
    )
    old_sha, new_sha = _sha256(registry_raw), _sha256(new_registry)
    for bundle in bundles["bundles"]:
        bundle["registry_sha256"] = new_sha
    bundles["bundles"].append(_bundle_entry(
        package, staged.name, package_sha, registry.registry_version, new_sha, facts, registry,
    ))

    passages_path = paths.passages_file(scheme_id)
    if passages_path.exists():
        raise OnboardingRefused(f"{passages_path.name} already exists; remove it to re-onboard")
    corpus_raw = b""  # a new file, written with LF line endings
    corpus = {"corpus_version": "0.3.0", "passages": []}
    try:
        new_passages = _passages(package, details)
    except KeyError as error:
        raise OnboardingRefused(
            f"{source_path.name} onboarding block is missing {error.args[0]}"
        ) from error
    corpus["passages"].extend(new_passages)

    new_cases, without_split = _with_case_entries(
        cases_raw, source["cases"], staged.name, package_sha,
    )

    changes = {
        target: package_raw,
        paths.bundle_registry: _json_like(bundles_raw, bundles),
        passages_path: _json_like(corpus_raw, corpus),
        paths.cases: new_cases,
    }
    summary = [
        f"Move package: {staged.name} -> src/rules/packages/",
        f"Add bundle: {scheme_id}, approved, facts {', '.join(facts)}",
        f"Add search passages: {len(new_passages)}",
        f"Update Reflexion cases: {len(source['cases'])}",
    ]
    if cited:
        changes[paths.fact_registry] = new_registry
        summary += [
            f"Cite the scheme's source on: {', '.join(cited)}",
            f"Re-pin the registry hash: {old_sha[:12]} -> {new_sha[:12]} "
            "(all bundles)",
        ]

    _check_in_a_copy(paths, scheme_id, changes)
    summary.append("Load check on a copy with these changes: passed")

    for_people = [
        f"Add data/schemes/{folder}/{scheme_id}.json"
        for folder in ("document_checklists", "mock_forms")
        if not (paths.schemes / folder / f"{scheme_id}.json").exists()
    ]
    unreviewed = sum(item["review_status"] != "reviewed" for item in new_passages)
    if unreviewed:
        for_people.append(f"Review the {unreviewed} search passage(s) still marked pending_review")
    for name, status_of in (
        ("Native-speaker review of questions", lambda fact: fact.question_review_status),
        ("Privacy review", lambda fact: fact.privacy.review_status),
    ):
        waiting = sorted(fact_id for fact_id, fact in facts.items() if status_of(fact) != "approved")
        if waiting:
            for_people.append(f"{name}: {', '.join(waiting)}")
    if without_split:
        for_people.append(f"Choose learn or check for: {', '.join(without_split)}")
    for_people += [
        "Re-check the search thresholds, because passages changed (paid)",
        "Walk through the scheme in the running app (eligible, not eligible, don't know)",
    ]
    return OnboardingPlan(scheme_id, staged, changes, tuple(summary), tuple(for_people))


def apply_onboarding(plan: OnboardingPlan) -> None:
    """Write a checked plan, restoring every file if any write fails."""

    originals = {path: path.read_bytes() if path.exists() else None for path in plan.changes}
    try:
        for path, content in plan.changes.items():
            path.write_bytes(content)
        plan.staged_package.unlink()
    except OSError:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
