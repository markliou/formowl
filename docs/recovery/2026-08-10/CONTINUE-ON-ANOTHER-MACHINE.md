# Continue On Another Machine

This file is the immediate cross-machine handoff for the active FormOwl
dual-track goal. The live Codex conversation, tool sessions, and stopped
subagent processes cannot be serialized into Git. Their durable objective,
acceptance contract, decisions, and next actions are preserved in the tracked
files listed below.

## Pull This State

```sh
git fetch origin --prune
git switch recovery/dual-track-uat-kg-20260810
git pull --ff-only origin recovery/dual-track-uat-kg-20260810
```

The current machine used a deliberately dirty composite worktree. Do not
pretend that composite is one clean release branch. Three public refs preserve
the separable Git state:

```text
coordinator/recovery:
  origin/recovery/dual-track-uat-kg-20260810

Issue #51 authority and integrated WP1 baseline:
  origin/issue/51-integration-baseline
  c7fd4b21c6dd5757fdbd18d19beebb2bacd7351f

diagnostic structured-runtime source copied into the source-only packet:
  origin/uat-semantic-structured-recovery-20260805
  34c76d2520f3157a9087430b20f0c21cae5189dd
```

Keep these refs in separate worktrees instead of merging them blindly:

```sh
git worktree add --detach ../formowl-issue51-public \
  origin/issue/51-integration-baseline
git worktree add --detach ../formowl-uat-source \
  origin/uat-semantic-structured-recovery-20260805
```

Then read, in order:

```text
AGENTS.md
docs/agent-goals/dual-track-uat-kg-coordinator.md
docs/recovery/2026-08-10/README.md
this file
```

Run the tracked methodology check from the Issue #51 public worktree:

```sh
cd ../formowl-issue51-public
python3 scripts/methodology_authority_check.py --check
```

The clean public Issue #51 ref was re-extracted and checked immediately before
this handoff. Expected state:

```text
authority_valid=true
methodology_ready=false
status=blocked
target tokenizer=jieba_sentencepiece_frozen_profile_candidate_admission_v1
runtime availability=unavailable_profile
```

The original dirty/private runtime composite separately probed as valid but
blocked with `ascii_identifier_regex_v1`. That runtime-specific state is not a
claim about the clean public Issue #51 worktree. The source-only worker packet
pins its explicit diagnostic mode and source commit independently.

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
- The current source-only Terra worker stopped cleanly and reported no
  oracle/query/expected-answer/browser/runtime contamination.
- It changed only five packet-local builder, materializer, and test files. It
  created no choices, adjudications, bindings, retained-lineage report, safe
  worker report, or checksum manifest; `outputs/` remains empty.
- Builder tests passed 6/6. The combined suite reached 36 passed and one failure
  caused by the test using an external temporary-output location. The worker
  patched that test to use packet `outputs/`, but the suite was not rerun after
  the power-cut stop request.
- Resume from the private Terra checkpoint archive, verify its hash, and rerun
  focused tests before generating any output. Do not infer progress from the
  expected answer set.
- The worker must resolve the 22 part-number header ties, including the six
  non-equivalent or incomplete cases, review the four
  `admit_after_new_structural_review` sources, and represent any retained
  coverage through commitment-bound source lineage rather than a hard-coded
  answer union.
- The coordinator must independently run the offline oracle acceptance after
  the worker finishes.

The deployment-readiness audit returned `RELEASE_DECISION: BLOCK`:

1. the semantic preflight's `candidate_binding_sha256` is not compared with the
   binding mounted by the deployment script; and
2. the browser verifier command, safe report path, and approved browser base URL
   remain unresolved materialization inputs.

The auditor otherwise passed semantic-preflight tests 4/4, browser-contract
tests 10/10, and the static deploy self-test. It also noted that
`root_compose_sha256` is declared but not enforced by the direct-Docker script.
Close both blockers before image build or deployment.

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

The source-only Terra worker's latest packet state is preserved in a newer
private checkpoint archive:

```text
.formowl-private-recovery-r8-20260810/
  track1-r8-source-only-terra-checkpoint.private.tar.gz
  TRACK1-TERRA-CHECKPOINT-SHA256.private
```

Expected SHA-256:

```text
5b391308b291b5898139b3e8b4a6653ca73cfde95af2a606a9f85a49283ec884
```

This archive includes the five packet-local edits and the still-empty
`outputs/` directory. It supersedes the earlier source-only archive for code
checkpoint purposes but does not contain accepted semantic outputs. Transfer it
only through an approved private channel; it is intentionally not in Git.

## Track 2 State

Track 2 remains separate under issue #33. Its two bounded research documents
are already tracked:

```text
docs/kg-ontology-v2-rd-boundary.md
docs/kg-ontology-v2-runtime-evaluation-plan.md
```

Track 2 must not modify the UAT web, sidecar, private projection bindings,
deployment, or raw PST, and it must not block Track 1 diagnostic acceptance.
The design stage is complete; runtime tokenizer migration, re-indexing existing
observations, same-pipeline POC ablations, and issue #33 exit gates have not yet
run.

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
machine-readable checkpoint:
  docs/recovery/2026-08-10/current-session-checkpoint.safe.json
private evidence/runtime checkpoint: the two separately transferred private
  recovery archives above, preferring the Terra checkpoint for the source-only
  packet
```

After pulling, do not assume any container or subagent is alive. Reconstruct
from the tracked goal and verified private packet, then resume from source-only
semantic adjudication rather than from remembered answer values.
