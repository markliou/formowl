# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active-blocked`
- Lossless history: `../archive/2026-07-11/kg-research-agent.md`
- Retention: keep role, current objective, status, blockers, and next action only;
  target at most 180 lines and archive before 250 lines.

## Role

Knowledge Graph Research Agent.

Durable role definition: `../agent-roles.md`.

## Current Objective

Complete the FormOwl Knowledge Graph method exploration and acceptance work:
fill in external recent literature comparison, ontology integration method,
multi-user KG and KG fusion experiments, multimodal enterprise-data validation,
annotation/adjudication workflow through either legacy human evidence or a
four-professional-specialist LLM subagent panel, production adapter gate, and a
total acceptance suite that clearly marks passed and failed items.

Historical source: Codex session `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.

Status: `blocked` for the broad KG real-evidence acceptance objective. Current
repo-side tooling is synchronized, but four broad real-evidence gates still
require operator-supplied or public reproducible evidence before completion can
be claimed. Product-level production readiness, top-tier scientific validation,
raw access, canonical graph writes, autonomous business judgment, and
enterprise-scale latency/scalability remain outside any future completion
claim.

## Status

`blocked`

## Current Acceptance State

Do not treat the broad KG real-evidence acceptance objective as complete in the
current authority state. The stricter current state is blocked, and no broad
completion claim is supported until the four remaining gates have accepted
canonical packets and all authority reports are synchronized and passing.

`SPEC.md` is now rewritten around one generalized evidence-to-knowledge
methodology rather than mail, procurement, or wiki as the product center.
Source formats are adapters, departments use scoped domain packs, and
cross-domain acceptance requires at least one materially different non-mail
transfer domain. This authority change does not itself satisfy any of the four
blocked real-evidence gates.

## Current POC Execution Mode

- Keep Hybrid KG + Ontology v2 as the frozen methodology target; do not create
  a v3 for the current correction.
- Align the actual runtime with the Jieba + SentencePiece frozen-profile
  candidate-admission target first.
- Prefer focused tokenizer, one-path runtime, and small real-source diagnostic
  checks over large generated suites during the POC.
- Defer the full 300–500-question holdout, whole-repository verification, and
  production-grade reviewer campaign until the POC shows a useful signal.
- As of 2026-08-11, exclude `agy` from all worker, reviewer, implementation,
  UAT, and subagent-coordinator assignments because its quota is exhausted.
  Use Codex/GPT subagents until the user explicitly re-enables `agy`.
- POC results remain diagnostic: they do not establish methodology readiness,
  support KG-versus-ontology superiority claims, close GitHub issue #33, or
  authorize methodology-quality UAT.

## Semantic Query Direction

- Diagnostic documentation direction only: use schema- and ontology-grounded
  LLM planning with a strict typed `SemanticQueryPlan`, deterministic
  privacy-filtered public-term grounding, data-first versioned/provenanced
  SKOS-style lexical mappings, and deterministic permission-aware exact
  execution. MAY evidence, people, part numbers, identifiers, and source
  payloads remain inside the private boundary.
- The valid but blocked methodology authority means this direction does not
  establish runtime implementation, readiness, or methodology-quality UAT;
  ambiguity or unsafe grounding requires clarification rather than broadening.

## Blockers

- The broad KG real-evidence objective remains unchecked on the active board.
- Issue #38's authority harness is state-independent and clean-clone
  reproducible. Its explicit blocked fixture still correctly reports the four
  unresolved real-evidence gates; that blocked evidence state is not harness
  drift.
- The methodology authority guard is valid but blocked. The real mail runtime
  still probes as `ascii_identifier_regex_v1`, while the target pipeline
  requires Jieba plus SentencePiece with frozen-profile candidate admission,
  complete source evidence, execution-bound reports, same-pipeline real-source
  ablation, and final-answer acceptance.
- No canonical completion claim is valid until the required packets, reports,
  dev-container checks, and reviewer gate agree.

## Current Mail UAT Root-Cause Track

- GitHub issue #51 owns implementation of raw-source inventory, structural
  table/version observations, coverage-aware retrieval with bounded fallback,
  and the closed answer-claim contract. It forbids private-case hard-coding and
  cannot self-certify end-to-end acceptance.
- GitHub issue #52 is the independent raw-PST oracle acceptance authority.
  On 2026-08-01 this agent recorded `RELEASE_DECISION: BLOCK` after the live
  chat path returned HTTP 500 from a revoked dependency while reporting ready.
- GitHub issue #54 now owns the generalized clean-build provenance,
  dependency-aware readiness, atomic claim-contract, outer-error, and runtime
  bounds patch. The webpage remains diagnostic until #51 and #54 pass, #52
  reruns in full, and `scripts/methodology_authority_check.py --require-ready`
  permits a methodology-quality claim.
- The active internal POC restores
  `browser -> Codex sidecar -> exactly one FormOwl MCP` over the existing MAY
  export without invoking PST parsing again. The current acceptance query
  requires one structured-set retrieval, 15 distinct answer bullets, no
  initial sources, and the frozen answer-set fingerprint.
- The semantic-unavailable MIME-child correction has focused container proof
  and three independent reviewer agreements in the isolated UAT candidate
  workspace. The first full aggregate rerun ended without OOM only because its
  report parent directory had not been pre-created; no implementation change
  was needed. The same constrained container was restarted after a
  directory-existence/type/write preflight. Its final 452,127-item report
  passed with zero failed, unrecognized, intentional-exclusion, result-error,
  and source/parser/binding rejection gates.
- The first native-scope pass then exposed a general coverage bug: ancillary
  sidecar/attachment files were incorrectly required to have top-level message
  occurrences. The isolated correction retains exact fail-closed message
  topology, rejects malformed or disallowed ancillary states, passes 65/65
  focused dev-container tests and Ruff, and has 3/3 reviewer agreement. The
  same constrained existing-export native-scope container is rerunning.

## Next Action

Resume the exact-set internal UAT from
`dual-track-uat-kg-coordinator.md`. The sole next action is private
reconciliation of the reviewed runtime's 69-item set against the independently
reviewed 77-item oracle. Do not reparse PST, rename the frozen root cause,
change the oracle, or patch production until that probe proves one general
runtime rule.

## Track 2 Diagnostic Checkpoint — 2026-08-11

- Existing-Observation-only Hybrid-v2 evidence lookup improved required
  evidence from 1/2 to 2/2; no-answer false matches stayed 0, ontology
  hard-gate false rejects stayed 1, and final-answer generation stayed 0.
  Query/evidence fingerprints match within each run and PST/parser/extractor
  counters are all zero. The generated calibration SentencePiece model is not
  yet a production-packaged immutable artifact, so cross-run profile stability
  remains blocked.
- PostgreSQL and Neo4j passed the same sealed conformance package in three
  cycles: 24/24 faults, exact retry, permission/provenance, lifecycle/schema,
  structured-set determinism, rollback, and destructive restore all passed.
  Corrected conformance latency and cgroup memory favored PostgreSQL.
- Storage verdict is `decision_blocked`, with PostgreSQL retained
  operationally. Fresh-server cold samples, isolated native Neo4j traversal,
  and a corrected replicated full-workload campaign remain missing; no
  migration, dual-write, SPEC, or authority-store change is authorized.

## Track 2 Maintainer Decision And Diagnostic — 2026-08-12

- The maintainer rejected Neo4j for this project. PostgreSQL remains the
  canonical baseline. Preserve prior Neo4j artifacts only as historical
  diagnostics; do not continue benchmarking, adapter, projection, migration,
  dual-write, or SPEC work for Neo4j.
- The generic ontology correction keeps explicit core-supertype governance
  hard, but treats inferred candidate-type compatibility as a capped additive
  rerank signal. Inferred mismatch now receives no bonus and never deletes or
  zeros an admitted candidate.
- The focused canonical container ontology suite passes 5/5. The existing
  Observation-only Hybrid-v2 diagnostic passes 4/4 and reports required
  evidence 1/2 to 2/2, ontology false rejects 1 to 0, final supported
  extractive answers 1 to 2, unsupported answers 0, and no-answer false
  matches 0 to 0.
- This is diagnostic-only synthetic/authorized-Observation evidence. The
  methodology authority remains valid but blocked. The calibration
  SentencePiece model is not yet a repository-packaged immutable artifact, so
  cross-process frozen-profile stability and real-source/end-answer acceptance
  remain blockers.
