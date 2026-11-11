"""Build development-only gold cases with a non-production fact overlay."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from src.rules.facts import FactRegistry
from src.rules.models import Rule
from src.rule_extraction_reflexion.extractor import (
    FactDefinitionLike,
    FactRegistryLike,
)
from src.rule_extraction_reflexion.models import (
    RuleExtractionCase,
    SourceClause,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SELECTION_FILE = PROJECT_ROOT / "data" / "schemes" / "rule_gold_selection.json"
FACT_REVIEW_FILE = (
    PROJECT_ROOT / "data" / "schemes" / "rule_gold_fact_review_queue.json"
)
MAPPING_REVIEW_FILE = (
    PROJECT_ROOT / "data" / "schemes" / "rule_gold_field_mapping_review.json"
)
REGISTRY_FILE = PROJECT_ROOT / "src" / "rules" / "fact_registry.json"
GOLD_DRAFTS_DIR = PROJECT_ROOT / "data" / "schemes" / "rule_gold_drafts"


@dataclass(frozen=True)
class EvaluationFactDefinition:
    """Only type metadata needed by the development extraction benchmark."""

    fact_id: str
    value_type: Literal["boolean", "integer", "decimal", "choice"]
    unit: str | None
    choices: tuple[str, ...] = ()

    def validate_value(self, value: object) -> object:
        """Validate the candidate value's type without production bounds."""

        valid = (
            type(value) is bool if self.value_type == "boolean"
            else type(value) is int if self.value_type == "integer"
            else type(value) in (int, float, Decimal)
            and math.isfinite(float(value)) if self.value_type == "decimal"
            else type(value) is str and value in self.choices
        )
        if not valid:
            raise ValueError(f"{self.fact_id} has an incompatible evaluation value")
        return value


class GoldEvaluationFactRegistry(FactRegistryLike):
    """Read-only overlay; it never changes the app's active fact registry."""

    def __init__(
        self,
        active: FactRegistry,
        overlay: dict[str, EvaluationFactDefinition],
    ) -> None:
        self._active = active
        self._overlay = overlay

    @property
    def overlay_fact_ids(self) -> frozenset[str]:
        """Return the evaluation-only fact IDs in this overlay."""

        return frozenset(self._overlay)

    @property
    def active_fact_count(self) -> int:
        """Return the unchanged production registry size."""

        return len(self._active.definitions)

    def get(self, fact_id: str) -> FactDefinitionLike:
        """Return an active or evaluation-only fact definition."""

        try:
            return self._active.get(fact_id)
        except KeyError:
            try:
                return self._overlay[fact_id]
            except KeyError as error:
                raise KeyError(f"Unknown gold-evaluation fact: {fact_id}") from error


def build_development_gold_cases() -> tuple[
    tuple[RuleExtractionCase, ...], GoldEvaluationFactRegistry
]:
    """Load selected development rules only and validate their evaluation facts."""

    selection = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
    review = json.loads(FACT_REVIEW_FILE.read_text(encoding="utf-8"))
    mappings = json.loads(MAPPING_REVIEW_FILE.read_text(encoding="utf-8"))
    active = FactRegistry.model_validate_json(REGISTRY_FILE.read_bytes())
    reviewed_fields = {item["field_id"]: item for item in review["fields"]}
    field_mappings = _approved_mappings(mappings)

    grouped_rules: dict[
        tuple[str, str, str], list[tuple[dict, str]]
    ] = defaultdict(list)
    overlay: dict[str, EvaluationFactDefinition] = {}
    for scheme in selection["schemes"]:
        if scheme["split"] != "development":
            continue
        draft = json.loads(
            (GOLD_DRAFTS_DIR / Path(scheme["draft_file"]).name).read_text(
                encoding="utf-8"
            )
        )
        for raw_rule in draft["rules"]:
            quote = raw_rule.get("source_quote")
            passage_id = raw_rule.get("source_passage_id")
            if not isinstance(quote, str) or not quote.strip():
                raise ValueError(f"Missing source quote for {raw_rule['rule_id']}")
            if not isinstance(passage_id, str) or not passage_id:
                raise ValueError(f"Missing source passage for {raw_rule['rule_id']}")
            field_id = field_mappings.get(
                (scheme["scheme_id"], raw_rule["field"]),
                field_mappings.get((None, raw_rule["field"]), raw_rule["field"]),
            )
            raw_rule = {**raw_rule, "field": field_id}
            grouped_rules[(scheme["scheme_id"], passage_id, quote)].append(
                (raw_rule, scheme["family"])
            )
            try:
                active.get(field_id)
            except KeyError:
                field_review = reviewed_fields.get(field_id)
                if (
                    field_review is None
                    or field_review["review_status"]
                    != "meaning_approved_for_gold_evaluation_only"
                ):
                    raise ValueError(
                        f"Gold evaluation fact is not approved: {field_id}"
                    )
                overlay[field_id] = _evaluation_definition(field_review)

    cases = []
    for (scheme_id, passage_id, quote), entries in grouped_rules.items():
        digest = hashlib.sha256(
            f"{scheme_id}\0{passage_id}\0{quote}".encode("utf-8")
        ).hexdigest()[:10]
        clause_id = f"{scheme_id}-{digest}"
        rules = tuple(
            Rule(
                rule_id=raw["rule_id"],
                field=raw["field"],
                operator=raw["operator"],
                value=raw["value"],
                unit=raw.get("unit"),
                source_clause_id=clause_id,
                source_text=quote,
            )
            for raw, _ in entries
        )
        families = {family for _, family in entries}
        if len(families) != 1:
            raise ValueError(f"Mixed scheme families in gold case {clause_id}")
        cases.append(RuleExtractionCase(
            case_id=clause_id,
            clauses=(SourceClause(clause_id=clause_id, text=quote),),
            expected_rules=rules,
            boolean_exclusion_rule_ids=tuple(
                raw["rule_id"]
                for raw, _ in entries
                if raw.get("kind") == "exclusion"
                and raw.get("operator") == "eq"
                and type(raw.get("value")) is bool
            ),
            allowed_fact_ids=tuple(sorted({rule.field for rule in rules})),
            topic_tags=(next(iter(families)),),
        ))

    registry = GoldEvaluationFactRegistry(active, overlay)
    for case in cases:
        for rule in case.expected_rules:
            _validate_gold_rule(rule, registry)
    return tuple(cases), registry


def _approved_mappings(data: dict) -> dict[tuple[str | None, str], str]:
    mappings: dict[tuple[str | None, str], str] = {}
    for item in data["mappings"]:
        field_id = item["gold_field_id"]
        if item.get("status") == "owner_approved":
            mappings[(None, field_id)] = item["candidate_fact_id"]
        for decision in item.get("scheme_decisions", []):
            if decision.get("status") == "owner_approved":
                mappings[(decision["scheme_id"], field_id)] = decision["fact_id"]
    return mappings


def _evaluation_definition(data: dict) -> EvaluationFactDefinition:
    value_type = data["candidate_value_type"]
    if value_type not in {"boolean", "integer", "decimal", "choice"}:
        raise ValueError(
            f"Unsupported gold-evaluation value type for {data['field_id']}: "
            f"{value_type}"
        )
    return EvaluationFactDefinition(
        fact_id=data["field_id"],
        value_type=value_type,
        unit=data.get("candidate_unit"),
    )


def _validate_gold_rule(
    rule: Rule,
    registry: FactRegistryLike,
) -> None:
    """Ensure every gold target conforms to its active or reviewed type."""

    definition = registry.get(rule.field)
    definition.validate_value(rule.value)
    numeric = definition.value_type in {"integer", "decimal"}
    if rule.unit != (definition.unit if numeric else None):
        raise ValueError(
            f"Gold rule {rule.rule_id} unit does not match reviewed fact "
            f"{rule.field}"
        )
