"""Dual-label agreement and Cohen's κ for Role 5 persona labels."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from eval.schema import EvalPersona, PersonaEvaluationSet, PersonaLabel, VerdictResult


VERDICTS: tuple[VerdictResult, ...] = (
    "eligible",
    "not_eligible",
    "need_more_information",
)


def cohen_kappa(labels_a: Sequence[str], labels_b: Sequence[str]) -> float:
    """Cohen's κ for two equal-length categorical label sequences."""

    if len(labels_a) != len(labels_b):
        raise ValueError("Label sequences must have the same length.")
    if not labels_a:
        raise ValueError("Need at least one paired label.")

    n = len(labels_a)
    categories = sorted(set(labels_a) | set(labels_b))
    agree = sum(1 for left, right in zip(labels_a, labels_b) if left == right)
    p_o = agree / n

    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    p_e = sum((count_a[cat] / n) * (count_b[cat] / n) for cat in categories)
    if p_e == 1.0:
        return 1.0
    return (p_o - p_e) / (1.0 - p_e)


def _labels_by_labeller(
    personas: Iterable[EvalPersona],
) -> dict[str, list[tuple[str, str, VerdictResult]]]:
    """Map labeller_id → list of (persona_id, scheme_id, result)."""

    by_labeller: dict[str, list[tuple[str, str, VerdictResult]]] = {}
    for persona in personas:
        for label in persona.labels:
            by_labeller.setdefault(label.labeller_id, []).append(
                (persona.persona_id, label.scheme_id, label.result)
            )
    return by_labeller


def agreement_report(
    evaluation_set: PersonaEvaluationSet,
    *,
    labeller_a: str,
    labeller_b: str,
) -> dict[str, object]:
    """Pair overlapping persona×scheme labels from two labellers and score κ."""

    by_labeller = _labels_by_labeller(evaluation_set.personas)
    if labeller_a not in by_labeller:
        raise ValueError(f"No labels for labeller {labeller_a!r}")
    if labeller_b not in by_labeller:
        raise ValueError(f"No labels for labeller {labeller_b!r}")

    index_a = {
        (persona_id, scheme_id): result
        for persona_id, scheme_id, result in by_labeller[labeller_a]
    }
    index_b = {
        (persona_id, scheme_id): result
        for persona_id, scheme_id, result in by_labeller[labeller_b]
    }
    shared = sorted(set(index_a) & set(index_b))
    if len(shared) < 20:
        # PDF asks calibration on 20+ human labels; still compute if fewer.
        note = (
            f"Only {len(shared)} paired labels; PDF asks κ calibration on 20+."
        )
    else:
        note = f"{len(shared)} paired labels meet the 20+ calibration floor."

    labels_a = [index_a[key] for key in shared]
    labels_b = [index_b[key] for key in shared]
    kappa = cohen_kappa(labels_a, labels_b) if shared else None
    disagreements = [
        {
            "persona_id": persona_id,
            "scheme_id": scheme_id,
            "labeller_a": index_a[(persona_id, scheme_id)],
            "labeller_b": index_b[(persona_id, scheme_id)],
        }
        for persona_id, scheme_id in shared
        if index_a[(persona_id, scheme_id)] != index_b[(persona_id, scheme_id)]
    ]
    return {
        "dataset_version": evaluation_set.dataset_version,
        "labeller_a": labeller_a,
        "labeller_b": labeller_b,
        "paired_label_count": len(shared),
        "agreement_rate": (
            (len(shared) - len(disagreements)) / len(shared) if shared else None
        ),
        "cohens_kappa": kappa,
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "note": note,
    }


def attach_second_labeller_copy(
    evaluation_set: PersonaEvaluationSet,
    *,
    source_labeller: str,
    second_labeller: str,
) -> PersonaEvaluationSet:
    """Demo helper: copy one labeller's labels under a second id (κ smoke only).

    Real PDF dual-labelling must be independent Role 1 / teammate work, not a copy.
    """

    personas: list[EvalPersona] = []
    for persona in evaluation_set.personas:
        existing = list(persona.labels)
        extras: list[PersonaLabel] = []
        for label in persona.labels:
            if label.labeller_id != source_labeller:
                continue
            extras.append(
                PersonaLabel(
                    labeller_id=second_labeller,
                    scheme_id=label.scheme_id,
                    result=label.result,
                    status="dual_agreed",
                    note="COPIED for κ harness smoke — replace with independent Role 1 labels",
                )
            )
        personas.append(
            persona.model_copy(update={"labels": tuple(existing + extras)})
        )
    return evaluation_set.model_copy(update={"personas": tuple(personas)})
