# Dual-Track UAT and KG Research Coordinator Goal

## Lifecycle

- Label: `active`
- Created: `2026-08-10`
- Owner: Codex coordinator in thread `019f8d32-9002-7f10-840c-0c4c5e43fa32`
- Recovery priority: this file is the bounded cross-machine restart authority
  for the user-assigned dual-track work.

## User-Assigned Objective

Manage two separate but coordinated tracks without allowing either track to
silently redefine the other:

### Track 1 — Internal Diagnostic UAT

Rapidly complete the existing ChatGPT-like UAT over the existing
browser -> Codex sidecar -> exactly one FormOwl MCP architecture and the
already extracted MAY evidence. Do not reparse the PST.

The current exact-set acceptance query must produce:

```text
distinct projection count: 77
projection fingerprint:
  sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705
retrieval_path: mail_authorized_structured_set
claim_state: CANDIDATE_MATCHES
canonical_kg: false
citations/sources: 0
browser -> sidecar -> exactly one MCP call
elapsed time: less than 360 seconds
```

No candidate may be deployed before the exact offline count, fingerprint,
intersection, missing, and unexpected checks pass.

### Track 2 — KG + Ontology Research Return

Use GitHub issue #33 as the primary research owner. Keep Hybrid KG + Ontology
v2 as the frozen research target; do not create v3 merely because the current
runtime is incomplete.

Track 2 must separate:

```text
query-class routing
tokenization and protected identifiers
candidate admission
candidate KG topology
schema-constrained logical-form planning
deterministic exact-set execution
soft ontology/type scoring
hard governed schema invariants
evidence selection and provenance
research exit gates
```

Exact-set and inventory answers remain deterministic executor outputs.
KG/ontology may ground schema, propose candidates, traverse relations, and
explain results, but may not claim complete cardinality without a governed
coverage contract.

## Issue Ownership

- `#33`: Track 2 KG + Ontology research, tokenizer/candidate admission,
  topology, semantic ablations, independent holdout, and research exit gates.
- `#51`: Track 1 generalized source fidelity, structural evidence, coverage,
  structured-set execution, and answer-claim validity.
- `#52`: independent raw-source acceptance; implementation agents may not
  self-certify it.
- `#54`: deployment provenance, dependency-aware readiness, outer errors, and
  runtime bounds. It is not the KG research owner.
- `#49`: indexed required-term execution and all-matching performance.
- `#44`: conversation orchestration and one-MCP tool selection.

## Current Track 1 Evidence State

- The methodology authority is valid but blocked.
- Current mail runtime tokenizer:
  `ascii_identifier_regex_v1`.
- Frozen target tokenizer:
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`.
- The current diagnostic structured-set path remains
  `canonical_kg=false`; a Track 1 pass does not establish Track 2 validity.
- The previously materialized r7 artifact produced 74 values with only 15
  oracle intersections, 59 unexpected values, and 62 missing values. It is
  rejected and must never be deployed.
- Read-only source-header audits found 89 reviewed matrix/header-band
  sections:
  - COO projection: 89 unique strongest, zero ties.
  - part-number projection: 67 unique strongest and 22 equal-top ties.
  - among the 22 ties, a quarantined aggregate-only diagnostic reported 16
    source-equivalent pairs and 6 non-equivalent or incomplete pairs.
- Existing approved-source coverage accounts for only 71 of the 77 accepted
  values. Retained/reverified and not-yet-coordinate-bound source coverage must
  be represented through source commitments, never by hard-coded answer union.
- The final oracle helper's tie traversal is not uniquely reproducible from the
  currently available helper bytes. Runtime first/last-column behavior is
  therefore forbidden as semantic adjudication.

## Contamination Quarantine

One Terra worker accidentally opened a disallowed private oracle artifact
while performing source-only reconciliation. It reported that the oracle was
not used for selection, stopped immediately, and produced no choices,
adjudications, or bindings.

Quarantine evidence:

```text
contamination safe report SHA-256:
  9cf7dbb7774450c84381ef1a2c5b3a498af181d3fac548e5e81c6a31d205b24c
final progress report SHA-256:
  41638e8163e8423ad517eb61f4acfd241ebc3687b25793ec8b8e72b1dd40a680
```

That worker and its context may not author Track 1 semantic selections.
Restart adjudication with a fresh agent and a sanitized source-only packet.

## Power-Cut Recovery Checkpoint — 2026-08-10

No exact-77 candidate is accepted or deployed. The three UAT containers were
stopped before the handoff; the old MCP must not be restarted as acceptance
evidence.

The fresh source-only Terra worker stopped cleanly with no oracle/query/runtime
contamination. It changed five packet-local builder/materializer/test files,
created no outputs, passed the builder tests 6/6, and reached 36 passed plus one
temporary-output-location failure in the combined suite. It patched that test
but did not rerun after the stop request. The private checkpoint archive and
all five hashes are recorded in
`../recovery/2026-08-10/current-session-checkpoint.safe.json`.

The deployment-readiness auditor returned `RELEASE_DECISION: BLOCK`: the deploy
template does not enforce that the semantic preflight hash belongs to the
mounted binding, and its browser verifier command/base URL are still unresolved
materialization inputs. Do not build or deploy until both are closed.

Track 2 is design-ready, not implemented. Its architecture boundary and
same-pipeline runtime/evaluation plan are tracked and hashed; tokenizer
migration, observation re-index, POC ablations, and issue #33 exit gates remain.

Restart order on this or another computer:

1. Read `AGENTS.md` and the required startup files.
2. Read this goal before reopening Track 1 or Track 2 work.
3. Run `python3 scripts/methodology_authority_check.py --check`.
4. Confirm GitHub issues #33, #51, #52, and #54 are still open and read their
   latest maintainer comments.
5. Restore only private artifacts whose hashes match the handoff inventory;
   never reconstruct semantic decisions from expected answers.
6. Rerun the source-only packet tests before generating the five outputs.
7. Keep the deployment-plan audit separate from semantic artifacts and close
   both recorded blockers.
8. Run offline oracle acceptance before any image build.
9. Replace only `formowl-mcp-uat` after an exact offline pass.
10. Run direct MCP, browser contract, and independent human-readability UAT.

## Track 2 Delegation Boundary

Two separate Terra xhigh subagents should own non-overlapping work:

1. Architecture and literature-grounded method contract:
   query classes, deterministic exact-set boundary, hard/soft ontology
   boundary, schema validation, and promotion criteria.
2. Runtime and evaluation migration plan:
   protected identifier tokenizer, same-profile query/evidence re-index from
   existing observations, factorial ablation, no-answer/false-reject metrics,
   topology diagnostics, and a small same-pipeline POC.

They must not modify the current UAT web, sidecar, private projection bindings,
deployment, or raw PST. Their output is a research proposal and bounded POC
plan under #33, not a methodology-ready claim.

## Completion Rules

Track 1 completes only after exact offline acceptance, deterministic repeat,
container verification, one-MCP browser execution, and independent
human-readability review all pass.

Track 2 completes only under issue #33's independent holdout and semantic
ablation close criteria. A Track 1 UAT success cannot close Track 2.

The coordinator goal remains active until both tracks have explicit,
independently verified completion or the user changes their scope.
