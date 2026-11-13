# E3 freeze preparation (2026-11-13)

Proposed only. Role 5 approves; nothing was applied.

Scope: offline hash checks against origin/main (3bf49ec) in a detached worktree. No model calls, no held-out data, no edits to the manifest, playbooks, thresholds, packages or passages.

## Rule packages

Manifest hashing (`scripts/build_freeze_manifest.py` `sha256_file`) uses LF-normalised bytes (CRLF replaced by LF before SHA-256). The committed manifest uses that method.

| Package | Raw-byte SHA-256 | LF-normalised SHA-256 | Manifest `rule_packages.sha256` | Dev cases `package_sha256` | Result |
|---|---|---|---|---|---|
| pmkisan_in.v1.json | fb59df9f7420b29d33f5a41d938cdd00f688db742e62cd989f11a948b11137a1 | d4b05cc2d15bb5e0873d4611b8be9c39237617f34993f012811edd2f6381edce | d4b05cc2d15bb5e0873d4611b8be9c39237617f34993f012811edd2f6381edce | not recorded (4 check cases) | Manifest matches LF hash |
| ignwps_mh.v1.json | 224bf03585d9bb6bc41a64765c890dd84ea36c6006b0907065d9ded8bd5b2c65 | 8db9a7379944f72a79168df1f9986cb2f316d47f50bc3951c280d3a91590c3bd | 8db9a7379944f72a79168df1f9986cb2f316d47f50bc3951c280d3a91590c3bd | not recorded (1 check case) | Manifest matches LF hash |
| ignoaps_mh.v1.json | cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549 | cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549 | cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549 | cd4652b8a7da119561eee6ee8a532b4059cca8b750c9d323d93c6a05c00a6549 | All three match |

No mismatches. The pmkisan and ignwps working copies contain CRLF, so the raw hash differs from the manifest. The LF-normalised hash matches the committed manifest. The ignoaps file has no CRLF, so both hashes are equal.

## Attack suite

Method: same as the manifest (`sha256_file`, LF-normalised). Path `eval/red_team/attacks_v0.json`, suite_version 0.7.0.

| Item | Raw-byte SHA-256 | LF-normalised SHA-256 | Manifest `attack_suite.sha256` | Result |
|---|---|---|---|---|
| attacks_v0.json | 789ccc109b139bf1d48a5d8739750505a3e63c9f3620a5ed88202c3904f0ba4e | 5419658db14c5c3484c0a12037dd6f172dd7eeea08478d8d8af35b3fdbb6a733 | 5419658db14c5c3484c0a12037dd6f172dd7eeea08478d8d8af35b3fdbb6a733 | Manifest matches LF hash |

## Prompt method

Proposed method: import `EXTRACTION_SYSTEM_PROMPT` from `src/rule_extraction_reflexion/extractor.py` (no source-file read), encode the `str` value as UTF-8, and take SHA-256 of those bytes. The string has no CRLF, so raw and LF-normalised values are identical. Type is `str`, 1038 characters, 1038 bytes.

| Item | Value |
|---|---|
| Method | SHA-256 of UTF-8 bytes of `EXTRACTION_SYSTEM_PROMPT` (imported) |
| Result | b52aaca54e871c605d4e7c66a1f457f382963040e8747f9b6025aa3fce5061d5 |
| Manifest entry | None. Not added. |

Role 5 must approve this method before any prompt hash is recorded. The existing manifest `prompts` section uses `sha256_text` (UTF-8 encode, no normalisation) over `agent_config.AGENT_PROMPTS`, which does not cover the extractor prompt, so the extractor prompt would need its own entry.

Proposed only. Role 5 approves; nothing was applied.
