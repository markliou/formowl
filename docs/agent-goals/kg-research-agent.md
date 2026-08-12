# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active`
- Lossless history: `../archive/2026-07-11/kg-research-agent.md`
- Retention: keep role, current objective, status, blockers, and next action
  only; target at most 180 lines and archive before 250 lines.

## Role

Knowledge Graph Research Agent.

Durable role definition: `../agent-roles.md`.

## Current Objective

Implement GitHub issue #51 as one source-neutral, end-to-end evidence
completeness repair rather than a sequence of private-query patches.

The governed path is:

```text
Raw Asset
  -> SourceInventory
  -> StructuralObservation
  -> persisted normalized evidence and versioned index
  -> query-scoped CoverageLedger
  -> bounded fallback
  -> TaskAnsweringEngine-owned AnswerClaimState
  -> MCP / JSON-RPC / UAT projection
  -> durable task lifecycle
```

The reviewed execution contract is GitHub issue #51 comment `5070970116`.
Gate 0 is the clean integration branch `issue/51-integration-baseline` at
`79bc129081597f8733317e587243c7db3e2ff816`. Implementation must use its
ordered, disjoint work packages and must not use the dirty repository root as
evidence.

Default Candidate Evidence Retrieval remains the only default retrieval
method: it counts a logical source item, uses capped additive ontology
reranking, and keeps regex-only, hard-pruning, and other alternatives
ablation-only through `retrieve_ablation`. The index-owned
`CandidateEvidenceTextPolicyRuntime` accepts query text only and binds the
runtime id, tokenizer implementation hash, and frozen profile; a free-form hash
is rejected. Context/time admissibility and `CandidateEvidenceAccessBinding`
filtering precede tokenization. Raw query text may express only control intent;
retrieval anchors come from runtime-produced tokens. All four access
collections are immutable `frozenset` values, and cross-context permission is
an actual boolean.

## Status

`active` — WP1 is frozen and integrated. The code freeze is
`0f2e69b065d082fdb5fb43506f309b1dc2efc1f1`; the reviewed code-plus-packet
head is `eac8473d`, and integration merge `9e8a5f6` has parents `bed52a4` and
`eac8473d`. The durable packet is
`docs/issue51-wp1-interface-freeze.md`.

The separately assigned bounded Issue #33 **Track 2 implementation lane is
complete and retired** at
`03d6d269725a3d9890bb3c8f1bab37dcba4d2d87`. Its tokenizer/profile binding and
generic inferred-type ontology correction must not be reimplemented under
another Track 2 task. Neo4j benchmarking, adapter, migration, and projection
work is closed by maintainer decision; PostgreSQL remains the canonical
baseline. This does not mark methodology authority ready or satisfy Issue #33's
independent-holdout and semantic-comparison close criteria.

## Acceptance Criteria

- One shared contract module owns `SourceInventory`, structural observations,
  claim requirements, `CoverageLedger`, and the four answer-claim states.
- The canonical PST adapter inventories every raw structure and preserves
  table topology, blank/populated distinctions, version/quote depth, MIME
  alternatives, attachments, failures, and explicit exclusions.
- File and PostgreSQL persistence round-trip deterministically; migration
  numbering does not collide with OAuth `005_oauth_identity.sql`.
- Existing indexed candidate intersection searches structured evidence,
  enforces authorization before vocabulary/candidates/counting, rejects stale
  fingerprints, and uses only bounded fallback.
- `TaskAnsweringEngine` alone constructs, validates, enforces, and serializes
  claims. MCP, JSON-RPC, UAT HTTP, and the conversation orchestrator may not
  infer a second claim state.
- `human_uat_upload._parse_uat_uploaded_pst` delegates only to
  `run_upload_session_mail_import`; UAT does not fabricate a parallel Asset,
  parser, bundle, index, coverage model, or answer service.
- Issue #53 lands first as a dedicated reviewed lifecycle commit with the exact
  API/path/ancestry gate in the contract, then WP5 integrates it.
- UAT-L1 through UAT-L10, generalized structural/metamorphic cases,
  file/PostgreSQL/cold-warm-rebuilt parity, restart, refresh, revocation, and
  numeric budget behavior pass in the canonical dev container.
- Full unit tests, Ruff check/format, migration replay, diff checks, and three
  independent read-only reviewers agree.
- The board stays unchecked until all implementation proof exists. #51 can
  claim only “ready for #52,” not independent acceptance, methodology
  readiness, comparative superiority, or launch readiness.

## Blockers

- `scripts/methodology_authority_check.py --check` is valid but blocked.
  The methodology authority guard observes current runtime
  `ascii_identifier_regex_v1`, not the frozen target.
  Authority fingerprint is
  `sha256:c8e3fc5ec13d690f33d27797942a3b9b090319d4be8f269c77bccd646d787177`;
  execution fingerprint is
  `sha256:291c7ea5c5737079cc9ae9d4100fd9ce94f926adfff1a112235ed0aa93cf9665`;
  pipeline source binding count is `64`.
- `--require-ready` exits nonzero. No methodology-quality UAT,
  KG-versus-ontology claim, methodology completion, or launch-readiness claim
  is permitted.
- Issue #53 is open and its dedicated prerequisite commit does not yet exist.
  WP5 cannot start until the exact seam is implemented, reviewed, and recorded.
- Issue #52 remains the sole independent raw-PST oracle acceptance authority.
  #51 implementation and its agents cannot self-certify it.
- The broad KG real-evidence objective remains separately blocked; #51 does not
  close or weaken its remaining evidence gates.

## Next Action

Begin WP2: complete raw inventory and structural extraction, then reconcile it
against an independent raw oracle. Consume the frozen WP1 interface without
mutating it; freeze and review each upstream interface before its consumer
starts. Issue #53 must land as a dedicated reviewed lifecycle prerequisite
before WP5, and Issue #52 remains the only independent acceptance authority.
Keep all acceptance and methodology claims fail-closed. Do not dispatch or
resume work under the retired Track 2 implementation label.
