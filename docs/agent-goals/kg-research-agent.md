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

## Status

`active`

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
  Authority fingerprint is
  `sha256:c8e3fc5ec13d690f33d27797942a3b9b090319d4be8f269c77bccd646d787177`;
  Gate-0 execution fingerprint is
  `sha256:4a19889a41e2c00757ec888c148aa02bfa9e534c6334176c1f73d27a8de51ddb`.
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

Commit and push the clean Gate-0/documentation baseline, then delegate the
contract's disjoint implementation packages only to the three assigned
GPT-5.6-luna/high agents. Freeze and review each upstream interface before its
consumer starts; implement #53 before WP5; keep all acceptance and methodology
claims fail-closed.
