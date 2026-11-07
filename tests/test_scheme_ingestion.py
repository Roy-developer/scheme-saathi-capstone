"""Checks on the per-scheme passage files in data/schemes/passages/."""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.api.scheme_search import PassageCorpus, load_passages


def test_loads_three_scheme_corpus_with_review_status_per_passage():
    """The two pilots' 13 human-reviewed passages, plus IGNOAPS (added 2026-11-08).

    Only IGNOAPS's eligibility sentence is marked reviewed (the reviewer
    confirmed it word for word); its other passages are pending review.
    """
    project_root = Path(__file__).parents[1]
    passage_file = project_root / "data" / "schemes" / "passages.json"

# One entry per scheme file: file name -> (scheme_id, jurisdiction).
EXPECTED_SCHEMES = {
    "apy_passages.json": ("APY-IN", "IN"),
    "bhausaheb_fundkar_passages.json": ("BFFL-MH", "IN-MH"),
    "eacs1t7a8t10_passages.json": ("EACS-MH", "IN-MH"),
    "eps_passages.json": ("EPS-IN", "IN"),
    "fadse_passages.json": ("FADSE-MH", "IN-MH"),
    "faishl_passages.json": ("FAISHL-IN", "IN"),
    "fasetdp_passages.json": ("FASETDP-MH", "IN-MH"),
    "igndpsm_passages.json": ("IGNDPSM-MH", "IN-MH"),
    "igndps_passages.json": ("IGNDPS-IN", "IN"),
    "ignwpsm_passages.json": ("IGNWPSM-MH", "IN-MH"),
    "ignwps_mh_passages.json": ("IGNWPS-MH", "IN-MH"),
    "ignwps_passages.json": ("IGNWPS-IN", "IN"),
    "igoapsm_passages.json": ("IGOAPSM-MH", "IN-MH"),
    "ipmwcd_passages.json": ("IPMWCD-IN", "IN"),
    "mahila_samriddhi_passages.json": ("MSY-IN", "IN"),
    "mjpjay_passages.json": ("MJPJAY-MH", "IN-MH"),
    "namo_shetkari_mahasanman_nidhi_yojana_passages.json": ("NSMNY-MH", "IN-MH"),
    "nfbsm_passages.json": ("NFBSM-MH", "IN-MH"),
    "nsap_ignoaps_passages.json": ("NSAP-IGNOAPS-IN", "IN"),
    "pm_kisan_passages.json": ("PM-KISAN-IN", "IN"),
}

    assert len(passages) == 17
    assert {passage.scheme_id for passage in passages} == {
        "IGNWPS-MH",
        "PM-KISAN-IN",
        "IGNOAPS-MH",
    }
    pilots = [p for p in passages if p.scheme_id != "IGNOAPS-MH"]
    assert len(pilots) == 13
    assert {passage.review_status for passage in pilots} == {"reviewed"}
    assert {passage.source.collected_at.isoformat() for passage in pilots} == {"2026-11-01"}
    ignoaps = {p.passage_id: p for p in passages if p.scheme_id == "IGNOAPS-MH"}
    assert ignoaps["IGNOAPS-MH-ELIGIBILITY-01"].review_status == "reviewed"
    assert {p.review_status for pid, p in ignoaps.items() if pid != "IGNOAPS-MH-ELIGIBILITY-01"} == {
        "pending_review"
    }
    assert all(passage.source.source_id for passage in passages)
    assert all(passage.source.locator for passage in passages)


def test_folder_load_includes_marathi_passages():
    languages = Counter(passage.language for passage in load_passages(PASSAGE_DIR))

    assert languages["en"] > 0
    assert languages["mr"] > 0
    assert set(languages) <= {"en", "mr", "hi"}


def test_rejects_duplicate_passage_ids_within_a_file(tmp_path):
    data = json.loads(
        (PASSAGE_DIR / "apy_passages.json").read_text(encoding="utf-8")
    )
    data["passages"].append(data["passages"][0])
    invalid_file = tmp_path / "duplicate-passages.json"
    invalid_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        load_passages(invalid_file)


def test_rejects_duplicate_passage_ids_across_files(tmp_path):
    text = (PASSAGE_DIR / "apy_passages.json").read_text(encoding="utf-8")
    (tmp_path / "a.json").write_text(text, encoding="utf-8")
    (tmp_path / "b.json").write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        load_passages(tmp_path)


def test_empty_folder_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="No passage files"):
        load_passages(tmp_path)


def test_unknown_review_status_is_rejected(tmp_path):
    data = json.loads(
        (PASSAGE_DIR / "apy_passages.json").read_text(encoding="utf-8")
    )
    data["passages"][0]["review_status"] = "approved"
    invalid_file = tmp_path / "bad-status.json"
    invalid_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError):
        load_passages(invalid_file)
