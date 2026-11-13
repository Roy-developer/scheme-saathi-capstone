"""Checks on the per-scheme passage files in data/schemes/passages/."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from src.api.scheme_search import PassageCorpus, load_passages


PASSAGE_DIR = Path(__file__).resolve().parents[1] / "data" / "schemes" / "passages"
PASSAGE_FILES = sorted(PASSAGE_DIR.glob("*.json"))

# One entry per scheme file: file name -> (scheme_id, jurisdiction).
EXPECTED_SCHEMES = {
    "aabym_passages.json": ("AABYM-MH", "IN-MH"),
    "apy_passages.json": ("APY-IN", "IN"),
    "bhausaheb_fundkar_passages.json": ("BFFL-MH", "IN-MH"),
    "eacs1t7a8t10_passages.json": ("EACS-MH", "IN-MH"),
    "eps_passages.json": ("EPS-IN", "IN"),
    "fadse_passages.json": ("FADSE-MH", "IN-MH"),
    "faishl_passages.json": ("FAISHL-IN", "IN"),
    "fasetdp_passages.json": ("FASETDP-MH", "IN-MH"),
    "igndps_mh_passages.json": ("IGNDPS-MH", "IN-MH"),
    "igndps_passages.json": ("IGNDPS-IN", "IN"),
    "igndpsm_passages.json": ("IGNDPSM-MH", "IN-MH"),
    "ignoaps_mh_passages.json": ("IGNOAPS-MH", "IN-MH"),
    "ignwps_mh_passages.json": ("IGNWPS-MH", "IN-MH"),
    "ignwps_passages.json": ("IGNWPS-IN", "IN"),
    "ignwpsm_passages.json": ("IGNWPSM-MH", "IN-MH"),
    "ipmwcd_passages.json": ("IPMWCD-IN", "IN"),
    "mahila_samriddhi_passages.json": ("MSY-IN", "IN"),
    "mjpjay_passages.json": ("MJPJAY-MH", "IN-MH"),
    "namo_shetkari_mahasanman_nidhi_yojana_passages.json": ("NSMNY-MH", "IN-MH"),
    "nfbsm_passages.json": ("NFBSM-MH", "IN-MH"),
    "nsap_ignoaps_passages.json": ("NSAP-IGNOAPS-IN", "IN"),
    "nsigse_passages.json": ("NSIGSE-IN", "IN"),
    "nswf_passages.json": ("NSWF-IN", "IN"),
    "pg_igssgc_passages.json": ("PG-IGSSGC-IN", "IN"),
    "pm_kisan_passages.json": ("PM-KISAN-IN", "IN"),
    "pmay_u_passages.json": ("PMAY-U-IN", "IN"),
    "pmfby_passages.json": ("PMFBY-IN", "IN"),
    "pmjjby_passages.json": ("PMJJBY-IN", "IN"),
    "pmkmdy_passages.json": ("PMKMDY-IN", "IN"),
    "pmsby_passages.json": ("PMSBY-IN", "IN"),
    "pmuy2_passages.json": ("PMUY2-IN", "IN"),
    "pmvbry_passages.json": ("PMVBRY-IN", "IN"),
    "post_dis_passages.json": ("POST-DIS-IN", "IN"),
    "pre_dis_passages.json": ("PRE-DIS-IN", "IN"),
    "pre_st_passages.json": ("PRE-ST-IN", "IN"),
    "psgs_dip_passages.json": ("PSGS-DIP-IN", "IN"),
    "rassnb_passages.json": ("RASSNB-MH", "IN-MH"),
    "sbssps_passages.json": ("SBSSPS-MH", "IN-MH"),
    "tce_sc_passages.json": ("TCE-SC-IN", "IN"),
    "tfefvs_passages.json": ("TFEFVS-MH", "IN-MH"),
    "tfefvssshs_passages.json": ("TFEFVSSSHS-MH", "IN-MH"),
    "tmdvso_passages.json": ("TMDVSO-MH", "IN-MH"),
    "wmcl_passages.json": ("WMCL-IN", "IN"),
}


def test_legacy_single_corpus_file_is_gone():
    assert not (PASSAGE_DIR.parent / "passages.json").exists()


def test_every_expected_scheme_file_is_present():
    assert {path.name for path in PASSAGE_FILES} == set(EXPECTED_SCHEMES)


@pytest.mark.parametrize("path", PASSAGE_FILES, ids=lambda path: path.name)
def test_each_file_is_a_valid_single_scheme_corpus(path):
    corpus = PassageCorpus.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    scheme_id, jurisdiction = EXPECTED_SCHEMES[path.name]

    assert corpus.passages
    assert {passage.scheme_id for passage in corpus.passages} == {scheme_id}
    assert {passage.jurisdiction for passage in corpus.passages} == {jurisdiction}
    assert len({passage.scheme_name for passage in corpus.passages}) == 1
    assert {passage.review_status for passage in corpus.passages} == {"reviewed"}


@pytest.mark.parametrize("path", PASSAGE_FILES, ids=lambda path: path.name)
def test_each_passage_has_id_prefix_text_and_citation(path):
    for passage in load_passages(path):
        assert passage.passage_id.startswith(passage.scheme_id)
        assert passage.text.strip()
        assert str(passage.source.url).startswith("https://")
        assert passage.source.source_id
        assert passage.source.publisher
        assert passage.source.locator


@pytest.mark.parametrize("path", PASSAGE_FILES, ids=lambda path: path.name)
def test_no_garbled_characters(path):
    text = path.read_text(encoding="utf-8")

    assert "�" not in text
    for marker in ("â€", "Ã", "Â"):
        assert marker not in text


def test_folder_load_combines_every_file_with_unique_ids():
    passages = load_passages(PASSAGE_DIR)
    per_file_total = sum(len(load_passages(path)) for path in PASSAGE_FILES)

    assert len(passages) == per_file_total
    assert len({passage.passage_id for passage in passages}) == len(passages)
    assert {passage.scheme_id for passage in passages} == {
        scheme_id for scheme_id, _ in EXPECTED_SCHEMES.values()
    }
    assert {passage.review_status for passage in passages} == {"reviewed"}


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


def test_selected_gold_quotes_are_grounded_in_the_combined_corpus():
    project_root = Path(__file__).parents[1]
    schemes_dir = project_root / "data" / "schemes"
    manifest = json.loads(
        (schemes_dir / "rule_gold_selection.json").read_text(encoding="utf-8")
    )
    passages = {
        passage.passage_id: passage
        for passage in load_passages(PASSAGE_DIR)
    }

    def normalized(text: str) -> str:
        return re.sub(r"\s+", " ", text).casefold().strip()

    for selected in manifest["schemes"]:
        gold = json.loads(
            (schemes_dir / selected["draft_file"]).read_text(encoding="utf-8")
        )
        for rule in gold["rules"]:
            passage = passages[rule["source_passage_id"]]
            assert passage.scheme_id == selected["scheme_id"]
            assert normalized(rule["source_quote"]) in normalized(passage.text), (
                selected["scheme_id"],
                rule["rule_id"],
            )


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
