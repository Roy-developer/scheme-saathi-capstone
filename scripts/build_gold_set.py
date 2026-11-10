"""Build the retrieval gold set from the reviewed passage corpus.

Cases are authored by hand (below), written against passage text *before* any
retrieval run. This script validates them against the corpus and writes:

  eval/golden/retrieval_gold_dev.json        (~20 development cases)
  eval/heldout/retrieval_gold_heldout.json   (40+ held-out cases)

Split rule: whole schemes go to one split, so related variants never straddle
dev and held-out. Run:  python scripts/build_gold_set.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASSAGES = ROOT / "data" / "schemes" / "passages"
EXISTING = [
    ROOT / "data" / "schemes" / n
    for n in (
        "retrieval_eval_dev.json",
        "retrieval_eval_all_schemes_dev.json",
        "retrieval_calibration_dev.json",
    )
]

# (scheme_group, intent, query, [relevant passage ids])
DEV = [
    ("AABYM-MH", "eligibility", "Is a landless farm labourer aged 45 covered by the Maharashtra accident insurance scheme?", ["AABYM-MH-BENEFICIARY-01"]),
    ("AABYM-MH", "benefit", "What amount does the family get if the insured member dies in an accident?", ["AABYM-MH-BENEFIT-02"]),
    ("AABYM-MH", "benefit", "Do children of insured members get any study scholarship?", ["AABYM-MH-BENEFIT-03"]),
    ("AABYM-MH", "exclusion", "Can I join if I already have another similar insurance cover?", ["AABYM-MH-ELIGIBILITY-03"]),
    ("APY-IN", "benefit", "What happens to the Atal Pension account if the subscriber dies before turning 60?", ["APY-IN-BENEFIT-04"]),
    ("APY-IN", "eligibility", "How are the monthly contributions to Atal Pension Yojana collected?", ["APY-IN-ELIGIBILITY-03"]),
    ("APY-IN", "benefit", "Is there any income tax saving on Atal Pension Yojana contributions?", ["APY-IN-BENEFIT-05"]),
    ("APY-IN", "application", "Can I enrol in APY online through my bank's internet banking?", ["APY-IN-APPLICATION-01", "APY-IN-APPLICATION-03"]),
    ("FADSE-MH", "eligibility", "What is the age range for a disabled person to get self-employment financial assistance in Maharashtra?", ["FADSE-MH-ELIGIBILITY-03"]),
    ("FADSE-MH", "benefit", "What share of the loan is funded by the nationalized bank for disabled entrepreneurs?", ["FADSE-MH-BENEFIT-03"]),
    ("FASETDP-MH", "eligibility", "What minimum disability percentage is required for the vocational training based assistance in Maharashtra?", ["FASETDP-MH-ELIGIBILITY-01"]),
    ("IGNDPS-IN", "eligibility", "Are persons of short stature (dwarfs) eligible for the national disability pension?", ["IGNDPS-IN-ELIGIBILITY-05"]),
    ("IGNDPS-IN", "eligibility", "Does a disabled applicant need to be below the poverty line for the central disability pension?", ["IGNDPS-IN-ELIGIBILITY-06"]),
    ("IGNDPS-IN", "documents", "Which card shows poverty status when applying for the disability pension?", ["IGNDPS-IN-DOCUMENTS-01"]),
    ("IGNDPSM-MH", "eligibility", "How much disability must a person have to get the Maharashtra Indira Gandhi disability pension?", ["IGNDPSM-MH-ELIGIBILITY-04"]),
    ("IGNDPSM-MH", "benefit", "How much does the Centre pay monthly to a disabled beneficiary under the Maharashtra scheme?", ["IGNDPSM-MH-BENEFIT-01"]),
    ("PMJJBY-IN", "eligibility", "What is the entry age band for the Jeevan Jyoti life insurance for bank account holders?", ["PMJJBY-IN-ELIGIBILITY-03"]),
    ("PMJJBY-IN", "benefit", "From which month to which month does the PMJJBY yearly cover run?", ["PMJJBY-IN-BENEFIT-06"]),
    ("PMJJBY-IN", "eligibility", "Can both holders of a joint bank account take PMJJBY?", ["PMJJBY-IN-ELIGIBILITY-04"]),
    ("PMSBY-IN", "benefit", "Can a nominee make more than one claim under the Suraksha Bima accident scheme?", ["PMSBY-IN-BENEFIT-08"]),
    ("PMSBY-IN", "benefit", "Does PMSBY reimburse hospital expenses after an accident?", ["PMSBY-IN-BENEFIT-07"]),
    ("PMSBY-IN", "benefit", "How does PMSBY define an accident?", ["PMSBY-IN-BENEFIT-05"]),
]

HELDOUT = [
    ("EPS-IN", "eligibility", "Until what age does a member stay in the Employees' Pension Fund?", ["EPS-IN-ELIGIBILITY-03"]),
    ("EPS-IN", "definition", "Who counts as family of a female member under the employees pension scheme?", ["EPS-IN-ELIGIBILITY-06"]),
    ("EPS-IN", "definition", "How does EPS define an orphan?", ["EPS-IN-ELIGIBILITY-07"]),
    ("FAISHL-IN", "benefit", "What is the largest home loan amount on which interest subsidy is given to war widows' families?", ["FAISHL-IN-ELIGIBILITY-02"]),
    ("FAISHL-IN", "benefit", "How long is the home loan interest subsidy paid for ex-servicemen's dependants?", ["FAISHL-IN-BENEFIT-02"]),
    ("FAISHL-IN", "benefit", "How often is the interest subsidy paid and to whom?", ["FAISHL-IN-BENEFIT-04"]),
    ("IGNOAPS-MH", "benefit", "What monthly old age pension does Maharashtra give each beneficiary under Indira Gandhi scheme?", ["IGNOAPS-MH-BENEFIT-03"]),
    ("IGNOAPS-MH", "exclusion", "Can I get old age pension if I already receive another social security pension?", ["IGNOAPS-MH-ELIGIBILITY-03"]),
    ("IGNOAPS-MH", "documents", "Is an Aadhaar card needed to apply for the Maharashtra old age pension?", ["IGNOAPS-MH-DOCUMENTS-01"]),
    ("IGNWPS-IN", "benefit", "What monthly pension does a widow aged between 40 and 79 receive from the Centre?", ["IGNWPS-IN-BENEFIT-01"]),
    ("IGNWPS-IN", "eligibility", "Does the national widow pension require a BPL household?", ["IGNWPS-IN-ELIGIBILITY-02"]),
    ("IGNWPS-IN", "application", "Can I apply for the widow pension through the UMANG app?", ["IGNWPS-IN-APPLICATION-01"]),
    ("IGNWPSM-MH", "eligibility", "Is a widow from Maharashtra who is 38 years old eligible for the Indira Gandhi widow pension?", ["IGNWPSM-MH-ELIGIBILITY-01"]),
    ("IGNWPSM-MH", "application", "Where in Maharashtra do I submit the widow pension application?", ["IGNWPSM-MH-APPLICATION-01"]),
    ("IPMWCD-IN", "eligibility", "Who can apply for the Ministry of Women and Child Development internship programme?", ["IPMWCD-IN-ELIGIBILITY-01"]),
    ("IPMWCD-IN", "benefit", "Are travel costs reimbursed for interns on tour with the women and child development ministry?", ["IPMWCD-IN-BENEFIT-02"]),
    ("IPMWCD-IN", "documents", "Do I need to attach a photograph for the WCD internship application?", ["IPMWCD-IN-DOCUMENTS-01"]),
    ("MSY-IN", "eligibility", "What is the maximum project cost for a safai karamchari's loan under Mahila Samridhi Yojana?", ["MSY-IN-ELIGIBILITY-01"]),
    ("MSY-IN", "benefit", "What is the repayment period and moratorium under Mahila Samridhi Yojana loans?", ["MSY-IN-BENEFIT-04"]),
    ("MSY-IN", "benefit", "Who pays for skills training and stipend for groups of women under MSY?", ["MSY-IN-BENEFIT-05"]),
    ("MJPJAY-MH", "eligibility", "Since when is cashless treatment available to everyone in Maharashtra under Mahatma Jyotirao Phule Jan Arogya Yojana?", ["MJPJAY-MH-ELIGIBILITY-01"]),
    ("MJPJAY-MH", "benefit", "How many health benefit packages does MJPJAY cover for most categories?", ["MJPJAY-MH-BENEFIT-03"]),
    ("NSMNY-MH", "benefit", "How much does a farmer family get per instalment under Namo Shetkari Mahasanman Nidhi?", ["NSMNY-MH-BENEFIT-05"]),
    ("NSMNY-MH", "eligibility", "What land holding date decides eligibility for the Namo Shetkari scheme?", ["NSMNY-MH-ELIGIBILITY-04"]),
    ("NSMNY-MH", "application", "How do I register for the Maharashtra Namo Shetkari yojana?", ["NSMNY-MH-APPLICATION-01"]),
    ("NSIGSE-IN", "benefit", "When can a girl draw the incentive deposit made for secondary education?", ["NSIGSE-IN-BENEFIT-04", "NSIGSE-IN-BENEFIT-05"]),
    ("NSIGSE-IN", "eligibility", "Is there an income limit for SC/ST girls to get the secondary education incentive?", ["NSIGSE-IN-ELIGIBILITY-03"]),
    ("NSIGSE-IN", "documents", "Which birth proof is accepted for the girl child incentive scheme?", ["NSIGSE-IN-DOCUMENTS-01"]),
    ("PG-IGSSGC-IN", "eligibility", "Is the single girl child PG scholarship available for distance education courses?", ["PG-IGSSGC-IN-EXCLUSION-03"]),
    ("PG-IGSSGC-IN", "benefit", "How many new scholarships are given each year to single girl child postgraduate students?", ["PG-IGSSGC-IN-BENEFIT-02"]),
    ("PG-IGSSGC-IN", "eligibility", "Which course year must the only girl child be admitted to for the Indira Gandhi PG scholarship?", ["PG-IGSSGC-IN-ELIGIBILITY-03"]),
    ("PM-KISAN-IN", "benefit", "How is the yearly 6000 rupees split across the year for farmers?", ["PM-KISAN-IN-BENEFIT-02"]),
    ("PM-KISAN-IN", "eligibility", "What is the cut-off date for deciding PM-KISAN beneficiaries?", ["PM-KISAN-IN-ELIGIBILITY-03"]),
    ("PM-KISAN-IN", "eligibility", "If land was bought by sale deed after the cut-off, can the buyer get PM-KISAN?", ["PM-KISAN-IN-ELIGIBILITY-05"]),
    ("PMAY-U-IN", "eligibility", "Who is eligible for urban housing if they have no pucca house anywhere in India?", ["PMAY-U-IN-ELIGIBILITY-01"]),
    ("PMAY-U-IN", "benefit", "Can an EWS family build a house on its own plot under PMAY-Urban 2.0?", ["PMAY-U-IN-BENEFIT-03"]),
    ("PMFBY-IN", "eligibility", "Which farmers can take voluntary crop insurance under PMFBY?", ["PMFBY-IN-ELIGIBILITY-02"]),
    ("PMFBY-IN", "benefit", "Are hailstorm and landslide losses on individual farms covered by crop insurance?", ["PMFBY-IN-BENEFIT-05"]),
    ("PMKMDY-IN", "eligibility", "How many hectares can a small and marginal farmer own to join the farmers' pension scheme?", ["PMKMDY-IN-ELIGIBILITY-02"]),
    ("PMKMDY-IN", "benefit", "Does the Government match the farmer's contribution to the Kisan Maandhan pension?", ["PMKMDY-IN-BENEFIT-02"]),
    ("PMKMDY-IN", "benefit", "Can the pension contribution be deducted from the PM-KISAN benefit?", ["PMKMDY-IN-BENEFIT-03"]),
    ("PMUY2-IN", "eligibility", "Can a woman get a free LPG connection under Ujjwala if her household already has one?", ["PMUY2-IN-ELIGIBILITY-02"]),
    ("PMUY2-IN", "application", "Where do I submit an application for an Ujjwala gas connection?", ["PMUY2-IN-APPLICATION-01"]),
    ("PMVBRY-IN", "eligibility", "Who is considered a new employee under the Viksit Bharat employment scheme?", ["PMVBRY-IN-ELIGIBILITY-02"]),
    ("PMVBRY-IN", "benefit", "In how many instalments is the first-timer employment incentive paid?", ["PMVBRY-IN-BENEFIT-04"]),
    ("PMVBRY-IN", "benefit", "How many days after meeting conditions is the incentive disbursed?", ["PMVBRY-IN-BENEFIT-09"]),
    ("POST-DIS-IN", "benefit", "What is the maximum tuition fee support in the post-matric scholarship for students with disabilities?", ["POST-DIS-IN-BENEFIT-01"]),
    ("POST-DIS-IN", "exclusion", "How many children from one family can get the disability post-matric scholarship?", ["POST-DIS-IN-EXCLUSION-01"]),
    ("PRE-DIS-IN", "eligibility", "Is a UDID card required for the pre-matric scholarship for disabled students?", ["PRE-DIS-IN-ELIGIBILITY-04"]),
    ("PRE-ST-IN", "eligibility", "How is parental income counted when both parents work for the ST pre-matric scholarship?", ["PRE-ST-IN-ELIGIBILITY-03"]),
    ("PRE-ST-IN", "benefit", "For how many months is the ST pre-matric scholarship paid in a year?", ["PRE-ST-IN-BENEFIT-03"]),
    ("PSGS-DIP-IN", "eligibility", "What is the allowed gap between passing the qualifying exam and diploma admission for the AICTE girls' scholarship?", ["PSGS-DIP-IN-ELIGIBILITY-02"]),
    ("PSGS-DIP-IN", "benefit", "How many Pragati scholarships for diploma girls are awarded each year?", ["PSGS-DIP-IN-BENEFIT-03"]),
    ("RASSNB-MH", "eligibility", "Can two people in the same family get a Ramai Awas house?", ["RASSNB-MH-ELIGIBILITY-03"]),
    ("RASSNB-MH", "eligibility", "Do I need to own land to get a house under Ramai Awas Yojana?", ["RASSNB-MH-ELIGIBILITY-04"]),
    ("RASSNB-MH", "exclusion", "Can someone who got a different government housing benefit before apply for Ramai Awas?", ["RASSNB-MH-ELIGIBILITY-05"]),
    ("SBSSPS-MH", "eligibility", "How many years of Maharashtra residence are needed for the Sanjay Gandhi destitute pension?", ["SBSSPS-MH-ELIGIBILITY-03"]),
    ("SBSSPS-MH", "eligibility", "Must the applicant be destitute to get the Shravanbal / Sanjay Gandhi support pension?", ["SBSSPS-MH-ELIGIBILITY-04"]),
    ("TCE-SC-IN", "exclusion", "How many siblings in one family can get the top class education scholarship for SC students?", ["TCE-SC-IN-EXCLUSION-01"]),
    ("TCE-SC-IN", "eligibility", "What portion of slots is reserved for SC girl students in the top class education scheme?", ["TCE-SC-IN-ELIGIBILITY-04"]),
    ("TCE-SC-IN", "benefit", "Until when does the SC top class scholarship continue once awarded?", ["TCE-SC-IN-BENEFIT-01"]),
    ("TFEFVS-MH", "eligibility", "Is a VJNT student with one failed year still eligible for fee reimbursement?", ["TFEFVS-MH-ELIGIBILITY-03"]),
    ("TFEFVS-MH", "benefit", "Which fees are reimbursed to the college for VJNT students?", ["TFEFVS-MH-BENEFIT-02"]),
    ("TFEFVSSSHS-MH", "eligibility", "Which classes are covered by the fee reimbursement for DNT and SBC high school students?", ["TFEFVSSSHS-MH-BENEFICIARY-01"]),
    ("TMDVSO-MH", "benefit", "How much is paid per student for posting the driving licence?", ["TMDVSO-MH-BENEFIT-03"]),
    ("WMCL-IN", "eligibility", "Which students of coffee plantation workers get an incentive award for merit?", ["WMCL-IN-ELIGIBILITY-03"]),
    ("WMCL-IN", "eligibility", "Can a student who gets the educational stipend also receive the incentive award?", ["WMCL-IN-ELIGIBILITY-05"]),
]


def load_passages() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in glob.glob(str(PASSAGES / "*.json")):
        for x in json.load(open(p, encoding="utf-8"))["passages"]:
            out[x["passage_id"]] = x
    return out


def build(rows, prefix: str, split: str, corpus, existing_q: set[str]):
    cases, per_group = [], {}
    for group, intent, query, ids in rows:
        for pid in ids:
            if pid not in corpus:
                sys.exit(f"unknown passage id {pid!r} in {query!r}")
            if not pid.startswith(group + "-"):
                sys.exit(f"{pid} does not belong to group {group}")
        if query.strip().lower() in existing_q:
            sys.exit(f"duplicates an existing dev query: {query!r}")
        per_group[group] = per_group.get(group, 0) + 1
        cases.append({
            "case_id": f"{prefix}-{len(cases) + 1:03d}",
            "group": group,
            "scheme_id": corpus[ids[0]]["scheme_id"],
            "intent": intent,
            "language": "en",
            "query": query,
            "relevant_passage_ids": ids,
        })
    return cases


def main() -> None:
    corpus = load_passages()
    existing_q = set()
    for f in EXISTING:
        for q in json.load(open(f, encoding="utf-8"))["queries"]:
            existing_q.add(q["query"].strip().lower())

    dev = build(DEV, "GOLD-DEV", "development", corpus, existing_q)
    held = build(HELDOUT, "GOLD-HO", "heldout", corpus, existing_q)
    if {c["group"] for c in dev} & {c["group"] for c in held}:
        sys.exit("a scheme group appears in both splits")
    # Distinct query text across the whole set.
    allq = [c["query"].lower() for c in dev + held]
    if len(set(allq)) != len(allq):
        sys.exit("duplicate query text inside the gold set")

    note = (
        "Synthetic English queries written from reviewed passage text. Labels mark "
        "passages that directly answer the query (not an eligibility outcome). "
        "Authored by one person who also works on retrieval; the guide wants a different "
        "role to own held-out cases, so treat held-out as provisional until Role 5 "
        "re-labels or replaces it. No human domain review is claimed. Hindi/Marathi "
        "excluded (translations unvalidated)."
    )
    meta = {"dataset_version": "0.1.0", "created": "2026-11-09", "n_schemes_in_corpus": len({v['scheme_id'] for v in corpus.values()}), "annotation_note": note}
    (ROOT / "eval" / "golden").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval" / "heldout").mkdir(parents=True, exist_ok=True)
    for path, split, cases, prot in (
        (ROOT / "eval/golden/retrieval_gold_dev.json", "development", dev, False),
        (ROOT / "eval/heldout/retrieval_gold_heldout.json", "heldout", held, True),
    ):
        doc = {**meta, "split": split, "protected": prot, "cases": cases}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(cases)} cases, {len({c['group'] for c in cases})} schemes")
    print(f"total {len(dev) + len(held)}")


if __name__ == "__main__":
    main()
