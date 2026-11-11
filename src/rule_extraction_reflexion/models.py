"""Structured data for the development-only rule-extraction improvement loop."""

from datetime import datetime, timezone
import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from src.rules.models import Rule


TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class StrictModel(BaseModel):
    """Reject undeclared fields and prevent silent post-creation edits."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceClause(StrictModel):
    """A human-selected excerpt whose text remains untrusted model input."""

    clause_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=5000)
    location: str | None = Field(default=None, max_length=200)


class ExtractedRule(StrictModel):
    """Minimal model proposal; source metadata and policy labels are code-owned."""

    field: str = Field(min_length=1, max_length=80)
    operator: Literal["eq", "gt", "gte", "lt", "lte"]
    value: StrictBool | StrictInt | StrictFloat | StrictStr
    unit: str | None = Field(default=None, max_length=80)
    source_clause_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/()-]{0,119}$"
    )


class RuleExtractionOutput(StrictModel):
    """Compact model proposals; never approved or executable policy."""

    rules: tuple[ExtractedRule, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def compact_legacy_rules(cls, value: object) -> object:
        """Accept existing test fixtures but discard code-owned rule metadata."""

        if not isinstance(value, dict) or not isinstance(
            value.get("rules"), (tuple, list)
        ):
            return value
        compact_rules = []
        fields = set(ExtractedRule.model_fields)
        known_rule_fields = set(Rule.model_fields)
        for item in value["rules"]:
            if isinstance(item, Rule):
                compact_rules.append(
                    {name: getattr(item, name) for name in fields}
                )
            elif isinstance(item, dict):
                unknown = set(item) - known_rule_fields
                if unknown:
                    compact_rules.append(item)
                else:
                    compact_rules.append(
                        {name: item[name] for name in fields if name in item}
                    )
            else:
                compact_rules.append(item)
        return {**value, "rules": compact_rules}


class LessonText(StrictModel):
    """What the reflection model writes: the lesson's words only.

    The model does not choose tags. Free-form model tags broke the tag format
    (a real run wrote "rule-extraction") and, worse, need not match the tags
    later cases use, so an approved lesson could never be found again. Code
    copies the case's ``topic_tags`` instead (see ``propose_lesson``).
    Extra fields a model adds on its own (such as "tags") are dropped, not
    rejected, so they cannot fail the lesson.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, str_strip_whitespace=True)

    instruction: str = Field(min_length=1, max_length=500)
    when_to_apply: str = Field(min_length=1, max_length=300)


class LessonProposal(StrictModel):
    """A lesson awaiting human review: the model's words plus the case's tags."""

    instruction: str = Field(min_length=1, max_length=500)
    when_to_apply: str = Field(min_length=1, max_length=300)
    tags: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def require_safe_tags(self) -> "LessonProposal":
        if len(self.tags) != len(set(self.tags)) or any(
            not TAG_PATTERN.fullmatch(tag) for tag in self.tags
        ):
            raise ValueError("Lesson tags must be unique lowercase identifiers")
        return self


class RuleDifference(StrictModel):
    """Immutable differences for one rule ID."""

    rule_id: str
    attributes: tuple[str, ...]


class PendingLesson(StrictModel):
    """An immutable proposed lesson with development-case evidence."""

    lesson_id: str = Field(min_length=1, max_length=64)
    proposal: LessonProposal
    source_case_id: str = Field(min_length=1, max_length=120)
    source_clauses: tuple[SourceClause, ...] = Field(min_length=1)
    expected_rules: tuple[Rule, ...]
    proposed_rules: tuple[Rule, ...]
    differences: tuple[RuleDifference, ...]
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: Literal["pending"] = "pending"


class LessonReview(StrictModel):
    """A human decision stored separately from the model's proposal."""

    lesson_id: str = Field(min_length=1, max_length=64)
    decision: Literal["approved", "rejected"]
    reviewer_id: str = Field(min_length=1, max_length=150)
    reason: str = Field(min_length=1, max_length=1000)
    reviewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ApprovedLesson(StrictModel):
    """A reviewed lesson copied into a versioned playbook snapshot."""

    lesson_id: str
    instruction: str
    when_to_apply: str
    tags: tuple[str, ...]
    reviewer_id: str
    review_reason: str


class PlaybookSnapshot(StrictModel):
    """Immutable set of reviewed lessons with a verifiable content hash."""

    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    lessons: tuple[ApprovedLesson, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RuleExtractionCase(StrictModel):
    """One development case; callers must never load protected held-out data."""

    case_id: str = Field(min_length=1, max_length=120)
    clauses: tuple[SourceClause, ...] = Field(min_length=1)
    expected_rules: tuple[Rule, ...] = ()
    boolean_exclusion_rule_ids: tuple[str, ...] = ()
    allowed_fact_ids: tuple[str, ...] = Field(min_length=1)
    # Required: lessons learned from this case carry these tags, and later
    # cases find lessons by them. A case without tags could never reuse one.
    topic_tags: tuple[str, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_case_references(self) -> "RuleExtractionCase":
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("Source clause IDs must be unique")
        fact_ids = [fact_id.strip() for fact_id in self.allowed_fact_ids]
        if any(not fact_id for fact_id in fact_ids):
            raise ValueError("Allowed fact IDs cannot be blank")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Allowed fact IDs must be unique")
        if len(self.boolean_exclusion_rule_ids) != len(
            set(self.boolean_exclusion_rule_ids)
        ):
            raise ValueError("Boolean exclusion rule IDs must be unique")
        expected_by_id = {rule.rule_id: rule for rule in self.expected_rules}
        if not set(self.boolean_exclusion_rule_ids) <= set(expected_by_id):
            raise ValueError("Boolean exclusion IDs must reference expected rules")
        if any(
            expected_by_id[rule_id].operator != "eq"
            or type(expected_by_id[rule_id].value) is not bool
            for rule_id in self.boolean_exclusion_rule_ids
        ):
            raise ValueError("Boolean exclusions must be eq rules with boolean values")
        if len(self.topic_tags) != len(set(self.topic_tags)) or any(
            not TAG_PATTERN.fullmatch(tag) for tag in self.topic_tags
        ):
            raise ValueError("Case tags must be unique lowercase identifiers")
        return self


class EvaluationCaseResult(StrictModel):
    """Machine-checkable result for one supplied evaluation case."""

    case_id: str
    exact_match: bool
    differences: tuple[RuleDifference, ...]


class PlaybookEvaluation(StrictModel):
    """Aggregate results tied to one immutable playbook version."""

    playbook_version: str | None
    playbook_hash: str | None
    case_count: int
    exact_match_count: int
    model_call_count: int
    results: tuple[EvaluationCaseResult, ...]
