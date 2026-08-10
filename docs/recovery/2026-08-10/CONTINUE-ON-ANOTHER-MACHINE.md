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
  expected to be running after this checkpoint.
- Terra worker `019fe9b2-ca09-7591-aab2-ec55f411e4ea` stopped at a safe
  checkpoint. It verified all 280 source-packet manifest entries with zero
  checksum failures, but did not inspect source evidence, make semantic
  selections, or create choices, adjudications, bindings, retained-lineage
  output, or a safe output report.
- Its only failed probe was a packet-local import check because the copied
  `source-python` tree did not include
  `formowl_graph.research_acceptance`. No repair was attempted. Treat this as a
  packet/tooling preflight item, not as semantic progress.
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

## Public Recovery Tools Added At This Checkpoint

The following tracked tools preserve the current coordinator-side acceptance
work:

```text
docs/recovery/2026-08-10/build-semantic-preflight-r8.py
docs/recovery/2026-08-10/test-build-semantic-preflight-r8.py
docs/recovery/2026-08-10/verify-browser-contract-r8.py
docs/recovery/2026-08-10/test-verify-browser-contract-r8.py
```

The semantic preflight converts an exact private offline acceptance result into
the hash/count-only deployment-preflight shape. The browser verifier checks the
actual sidecar session-summary deltas, matching orchestrator/model state,
exactly one FormOwl tool call, exact response metadata, 77 distinct readable
bullets, no table wall, no initial citations/sources, no raw diagnostic dump,
and no answer-value leak in failure reports.

Verification completed before the power-cut handoff:

```text
host:
  browser verifier tests: 10/10 passed
  semantic preflight tests: 4/4 passed

read-only formowl-dev:local container:
  browser verifier tests: 10/10 passed
  semantic preflight tests: 4/4 passed
```

The earlier verifier review blocked three issues: hard-coded route provenance,
Markdown duplicate bypass, and missing negative tests. The files above contain
the corresponding patches. The same reviewer reran the focused test in the
read-only dev container (10/10 passed) and returned
`RELEASE_DECISION: AGREE` with no remaining concrete blockers.

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

The fresh source-only Terra packet is also private and is not in Git:

```text
.formowl-private-track1-r8-source-only-20260810/
```

It contains 280 manifest entries, has no worker outputs, and is bound to:

```text
INPUT_SHA256SUMS.private:
0dd583b779d93e3e6b585f517a3a0202a991c9da7abeb6b9e27e2ccad263b191

SOURCE_COMMIT.txt content:
34c76d2520f3157a9087430b20f0c21cae5189dd
```

A separately transferable private archive was created beside the older
recovery archive:

```text
.formowl-private-recovery-r8-20260810/track1-r8-source-only.private.tar.gz
.formowl-private-recovery-r8-20260810/TRACK1-SOURCE-ONLY-SHA256.private
```

Expected archive SHA-256:

```text
31d715891d320ee6faff54c8b52cd2b37f4a895ee7302c929b6c60abbde8c3ec
```

Transfer this archive only through an approved private channel. On the other
machine:

```sh
sha256sum -c TRACK1-SOURCE-ONLY-SHA256.private
tar -xzf track1-r8-source-only.private.tar.gz
cd .formowl-private-track1-r8-source-only-20260810
sha256sum -c INPUT_SHA256SUMS.private
```

Do not commit either private directory or either private archive.

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

The live Codex thread, tool sessions, subagent process state, Docker process
state, and in-memory context cannot be restored by `git pull`. The durable
replacement is:

```text
thread: 019f8d32-9002-7f10-840c-0c4c5e43fa32
goal status: active
goal authority: docs/agent-goals/dual-track-uat-kg-coordinator.md
operational checkpoint: this file
private evidence/runtime checkpoint: the two separately transferred private
  recovery archives above
```

After pulling, do not assume any container or subagent is alive. Reconstruct
from the tracked goal and verified private packet, then resume from source-only
semantic adjudication rather than from remembered answer values.
