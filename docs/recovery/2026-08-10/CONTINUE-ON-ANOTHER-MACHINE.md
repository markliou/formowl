# Continue On Another Machine

This file is the immediate cross-machine handoff for the active FormOwl
dual-track goal. The live Codex conversation, tool sessions, and stopped
subagent processes cannot be serialized into Git. Their durable objective,
acceptance contract, decisions, and next actions are preserved in the tracked
files listed below.

## Pull This State

```sh
git fetch origin
git switch recovery/dual-track-uat-kg-20260810
git pull --ff-only origin recovery/dual-track-uat-kg-20260810
```

Then read, in order:

```text
AGENTS.md
docs/agent-goals/dual-track-uat-kg-coordinator.md
docs/recovery/2026-08-10/README.md
this file
```

Run:

```sh
python3 scripts/methodology_authority_check.py --check
```

Expected state on 2026-08-10:

```text
authority_valid=true
methodology_ready=false
status=blocked
current tokenizer=ascii_identifier_regex_v1
target tokenizer=jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

This blocked methodology state does not prevent the narrowly scoped internal
diagnostic Track 1 UAT, but that UAT must continue to report
`canonical_kg=false` and must not be represented as methodology-quality
evidence.

## Current Track 1 State

- No r8 semantic binding has been accepted or deployed.
- The rejected r7 result must not be reused.
- All UAT containers were intentionally stopped before the outage.
- No parser, materialization, image build, deployment, or subagent process is
  expected to be running.
- The next implementation worker must be a fresh `fork_context=false` Terra
  xhigh agent using a sanitized source-only packet. It must not read oracle or
  runtime-answer artifacts.
- The worker must resolve the 22 part-number header ties, including the six
  non-equivalent or incomplete cases, review the four
  `admit_after_new_structural_review` sources, and represent any retained
  coverage through commitment-bound source lineage rather than a hard-coded
  answer union.
- The coordinator must independently run the offline oracle acceptance after
  the worker finishes.

The deployment gate remains:

```text
count=77
fingerprint=sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705
intersection=77
missing=0
unexpected=0
retrieval_path=mail_authorized_structured_set
claim_state=CANDIDATE_MATCHES
canonical_kg=false
citations/sources=0
browser -> sidecar -> exactly one MCP
elapsed < 360 seconds
```

Do not build or deploy before every offline field passes exactly.

## Private Packet Is Not In Git

The local private packet cannot be pushed because it contains private MAY
derived artifacts:

```text
.formowl-private-recovery-r8-20260810/
```

Transfer that directory only through an approved private channel. After
transfer, verify from inside the directory:

```sh
sha256sum SHA256SUMS.private
sha256sum uat-codex-state.private.tar.gz
sha256sum -c SHA256SUMS.private --quiet
```

Expected hashes:

```text
SHA256SUMS.private:
3c9c66ea0a734ccc6c0076c5b5499d1848485944fa084c14a9afef113c4a0d4e

uat-codex-state.private.tar.gz:
35f429268845eebd63fc6bfb9d86d9dc3766a8b957b8b8bf5f3b2e5be826b1ed
```

The public recovery manifest and the private manifest were both verified
successfully immediately before this handoff.

## Track 2 State

Track 2 remains separate under issue #33. Its two bounded research documents
are already tracked:

```text
docs/kg-ontology-v2-rd-boundary.md
docs/kg-ontology-v2-runtime-evaluation-plan.md
```

Track 2 must not modify the UAT web, sidecar, private projection bindings,
deployment, or raw PST, and it must not block Track 1 diagnostic acceptance.

## Worktree Safety

The source worktree contains many unrelated modified and untracked files from
other long-running work. Do not run `git reset`, broad `git add`, or a blanket
commit. Continue to stage only explicitly owned recovery or UAT files.
