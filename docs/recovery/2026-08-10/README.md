# Dual-Track Recovery Packet — 2026-08-10

This bounded packet preserves the non-private state needed to resume the
user-assigned dual-track work after the planned power outage or from another
computer.

## Remote Recovery Anchors

```text
branch: recovery/dual-track-uat-kg-20260810
goal commit: 4463986
Track 2 issue checkpoint: #33 comment 5235348864
Track 1 issue checkpoint: #51 comment 5235349653
```

Read first:

```text
AGENTS.md
docs/agent-goals/dual-track-uat-kg-coordinator.md
this file
```

Then run:

```sh
python3 scripts/methodology_authority_check.py --check
```

The expected current state is valid but blocked. Do not reinterpret it as
methodology readiness.

## Included Safe Artifacts

- `uat-mcp-r8-deploy.sh`
  - static deployment and rollback plan;
  - must not be run until an independently accepted binding and offline
    semantic report are supplied;
  - mutates only `formowl-mcp-uat`.
- `uat-mcp-r8-safe-deployment-manifest.json`
  - sanitized container/configuration and acceptance contract.
- `uat-mcp-r8-static-self-test.safe.json`
  - expected `status=passed`, zero errors.
- `r8-reconciliation-contamination.safe.json`
  - quarantine record for a worker that accidentally opened an oracle
    artifact and produced no semantic selections.

## Required Pre-Deployment Inputs

The deploy script intentionally retains unresolved placeholders. Supply them
only after a fresh source-only Track 1 worker produces accepted artifacts:

```text
new versioned reviewed binding artifact
exact binding SHA-256
safe offline acceptance report
independent browser-contract verifier command
independent browser-contract report path
```

The offline report must prove:

```text
count = 77
fingerprint =
  sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705
intersection = 77
missing = 0
unexpected = 0
retrieval_path = mail_authorized_structured_set
claim_state = CANDIDATE_MATCHES
canonical_kg = false
citations/sources = 0
```

## Live State At Checkpoint

```text
formowl-mail-diagnostic-uat: stopped
formowl-codex-uat-sidecar: stopped
formowl-mcp-uat: stopped
```

No exact-77 candidate was deployed.

The source-only Terra worker also stopped. It created no outputs and reported
no contamination. Five packet-local implementation/test files are preserved in
the latest private checkpoint archive; focused builder tests passed 6/6, while
the combined suite must be rerun after its final test-location patch.

The deployment-readiness auditor returned `RELEASE_DECISION: BLOCK` because the
deploy template does not bind the semantic preflight hash to the mounted
binding and the browser verifier command/base URL are unresolved. Do not build
or deploy until both findings are fixed and re-reviewed.

## Local Private Recovery Packet

The current computer also contains a local-only, untracked private packet:

```text
directory: .formowl-private-recovery-r8-20260810
size at checkpoint: 36 MiB
file-count manifest entries: 110
SHA256SUMS.private SHA-256:
  3c9c66ea0a734ccc6c0076c5b5499d1848485944fa084c14a9afef113c4a0d4e
UAT/Codex state archive SHA-256:
  35f429268845eebd63fc6bfb9d86d9dc3766a8b957b8b8bf5f3b2e5be826b1ed
```

It contains private reviewed artifacts and runtime utilities, but not a copy of
the raw export. The state archive was created after both running containers
were stopped. It must be transferred only through an approved private channel
and must never be committed or pushed.

The latest source-only worker checkpoint is:

```text
archive:
  track1-r8-source-only-terra-checkpoint.private.tar.gz
SHA-256:
  5b391308b291b5898139b3e8b4a6653ca73cfde95af2a606a9f85a49283ec884
```

It supersedes the earlier source-only archive for packet-local code state. Its
`outputs/` directory is still empty.

## Safe Shutdown Boundary

- Do not start a new PST parse, full-corpus reconstruction, Docker build, or
  deployment before the outage.
- Do not restart the stopped r6 MCP container as acceptance evidence.
- Completed safe documents and reports may be committed and pushed.
- Private MAY evidence, source roots, raw answer values, credentials, and
  private projection bindings are not included in this packet.

## Resume Order

1. Fetch the recovery branch and verify this packet's hashes.
2. Confirm the latest #33 and #51 comments.
3. Restore private artifacts only from their governed storage and verify every
   recorded SHA-256.
4. Start a fresh Track 1 Terra agent from a sanitized source-only packet.
5. Keep Track 2 documents and agents separate from private UAT bindings.
6. Complete offline semantic acceptance.
7. Run the deployment script only after all placeholders and preflight reports
   are supplied.
8. Run direct MCP, browser contract, and independent human-readability review.

## Track 2 Documents

Two independent Terra xhigh agents produced disjoint, non-private documents:

```text
docs/kg-ontology-v2-rd-boundary.md
docs/kg-ontology-v2-runtime-evaluation-plan.md
```

Their hashes are recorded in `SECOND_TRACK_SHA256SUMS`. These documents are
research boundaries and execution plans only; they do not change methodology
authority or the live UAT. Track 2 implementation and same-pipeline experiments
have not started.
