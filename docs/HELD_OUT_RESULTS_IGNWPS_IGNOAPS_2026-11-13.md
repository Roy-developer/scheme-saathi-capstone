# Held-out check results: IGNWPS-MH and IGNOAPS-MH (2026-11-13)

## Scope
- 16 shared cases (8 IGNWPS-MH, 8 IGNOAPS-MH). Two labelers, each filled alone, on the same profiles. Verdicts agreed on 16 of 16.
- Person-level claim only. Both schemes are development schemes, so this is not a scheme-level held-out claim.
- Small set. Not a basis for claims about the E3 inclusion lessons.

## Engine score
- Raw result: 10 of 16 correct (62.5%). Reported for transparency; it is not a fair measure, for the reasons below.
- Three repeats gave identical results (the engine is deterministic on this file).

## What the raw score includes
- **4 cases not checkable by the engine:** IGNOAPS-MH-04, -05, -07, -08. Their conditions (residence in Maharashtra, other social-security pension) are not in the approved package, so the engine cannot check them.
- **1 known engine divergence:** IGNWPS-MH-05 (family above the poverty line). Label: not eligible. Engine: need more information, because it treats a missing BPL card as missing data. Open for the rule owner.
- **1 field-name difference:** IGNWPS-MH-07. Verdict matches; the engine reports a different missing-field name.

## Result on checkable cases
- 11 of 12 checkable cases agree with the labels.

## Status and limits
- No rule change was made. A proposed rule (explicit above-poverty-line means not eligible) is recorded as proposed only and is not implemented.
- HO3-IGNWPS-MH-05 is reported here as a divergence. If the rule is changed, that case must be reclassified as development.
- No paid model calls were made.
- Requires unseen cases (at least 40 total, per the held-out README) before any final held-out claim.
