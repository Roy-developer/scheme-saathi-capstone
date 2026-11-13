"""Drift check for the canonical paired development retrieval run.

The sidecar records sha256 hashes of the dataset, the passage corpus, the
BM25-only runner and each report. If any input or output changes, these
tests fail until the run is repeated and the sidecar regenerated.
"""

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS = PROJECT_ROOT / "eval" / "reports"
SIDECAR_PATH = REPORTS / "retrieval_canonical_dev.sidecar.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_sidecar() -> dict:
    return json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))


def _corpus_manifest_sha256() -> str:
    corpus = PROJECT_ROOT / "data" / "schemes" / "passages"
    files = sorted(
        (p for p in corpus.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(PROJECT_ROOT).as_posix(),
    )
    manifest = "".join(
        f"{p.relative_to(PROJECT_ROOT).as_posix()}\t{_sha256(p)}\n" for p in files
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def test_dataset_hash_matches_sidecar():
    sidecar = _load_sidecar()
    dataset = PROJECT_ROOT / sidecar["dataset"]["path"]
    assert _sha256(dataset) == sidecar["dataset"]["sha256"]
    assert len(json.loads(dataset.read_text(encoding="utf-8"))["queries"]) == (
        sidecar["dataset"]["query_count"]
    )


def test_corpus_hashes_match_sidecar():
    sidecar = _load_sidecar()
    corpus = sidecar["corpus"]
    assert _corpus_manifest_sha256() == corpus["manifest_sha256"]
    for relpath, digest in corpus["files"].items():
        assert _sha256(PROJECT_ROOT / relpath) == digest, relpath
    assert len(corpus["files"]) == corpus["file_count"]


def test_runner_and_reports_match_sidecar():
    sidecar = _load_sidecar()
    runs = {run["name"]: run for run in sidecar["runs"]}
    bm25_only = runs["B_bm25_only_paired"]
    assert _sha256(REPORTS / "retrieval_canonical_dev_bm25_only_runner.py") == (
        bm25_only["runner_sha256"]
    )
    for run in sidecar["runs"]:
        report_path = PROJECT_ROOT / run["report"]
        assert _sha256(report_path) == run["report_sha256"], run["name"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["query_count"] == run["query_count"]
        assert report["recall_at_k"] == run["recall_at_5"]


def test_sidecar_declares_labels_unvalidated():
    status = _load_sidecar()["status"]
    assert "independent-review-pending" in status
    assert "NOT validated" in status
