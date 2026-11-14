# E1 team-override status (2026-11-14)

Tracks Scheme Saathi C0/C1/C2 cost-benefit beyond a PDF held-out bar.

## Team override (2026-11-14)

**Decision:** Do **not** require Role-5 protected held-out personas for this E1
record. Use development personas under freeze pins. Results are **team
override — not PDF unseen held-out**.

| Field | Value |
|---|---|
| Bar | `team_override_dev_personas` |
| Live runner | `scripts/run_e1_live.py` (C1 = journey `single_agent_provider`) |
| Claim level | **Team override — not PDF unseen held-out** |
| Freeze | `eval/freeze/manifest.json#e1_team_override_freeze` |
| Comparative report | `eval/reports/e1_team_override_comparison_2026-11-14.json` |

## Checklist

| # | Item | Status |
|---|---|---|
| 1 | Shared budget pins from `agent_config` | **Done** |
| 2 | Model pin (`openai/gpt-4o-mini` / free Nemotron for live) | **Done** |
| 3 | C1 wired through journey single-agent path | **Done** |
| 4 | Development comparative summary (task success + cost/latency) | **Done** |
| 5 | Fresh freeze-pinned journey-C1 live run | **Done** — `e1_team_override_journey_live_2026-11-14.json` (79/79 all arms; free Nemotron) |
| 6 | Protected held-out path (≥40 local custody) | **Done** — local n=40 scored: `e1_held_out_journey_live_2026-11-14.json` (40/40; not dual-labelled PDF) |
| 7 | Honest “team benefit” interpretation | **Done** — same success, C2 costs more |
| 8 | Threshold sign-off | Lead + **R5** approved report-only; **R1/R3 still open** |
| — | PDF final claim (dual labels + owner full sign-off + HO repeats) | **Still open** |

## Commands

```bash
python scripts/summarize_e1_live_report.py
python scripts/run_e1_live.py --team-override --yes --free-model \
  --out eval/reports/e1_team_override_journey_live_2026-11-14.json
python scripts/run_e1_live.py --held-out --yes --free-model \
  --out eval/reports/e1_held_out_journey_live_2026-11-14.json
```

## What must not be done

- Call team-override or undual-labelled held-out a **final PDF** E1 result.
- Claim the specialist team improves quality on this evaluate-only synthetic set.
- Commit files under `eval/held_out/local/`.
- Forge R1/R3 threshold signatures.