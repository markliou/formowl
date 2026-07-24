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

Complete the bounded source-neutral Task Answering methodology slice while
preserving the separate broad FormOwl KG real-evidence objective across
sessions.

The active bounded slice separates:

```text
TaskFrame revision
-> EvidenceRequirement
-> Candidate evidence retrieval
-> permission-filtered source-item field assembly
-> EvidenceCoverage
-> AnswerabilityDecision
-> content-first AnswerProjection
```

It must generalize across mail, documents, tables, application events, and
future source shapes. It must not introduce procurement-specific aliases,
source-specific query methods, UI-defined evidence completeness, canonical
writes, or external actions.

Repository-side authority tooling is reproducible and synchronized, but broad
completion requires accepted real or public reproducible evidence rather than
additional synthetic fixtures or implementation-only proofs.

The user explicitly assigned the cross-track temporary UAT issue #44 in an
isolated worktree. That bounded slice now reaches a pinned Codex app-server
sidecar through a private Unix socket and a narrow JSONL/WebSocket bridge.
Codex is the conversation engine above one FormOwl MCP-style evidence tool
without changing canonical graph, ontology, user-graph, wiki, or
external-system write authority. The source-neutral Task Answering objective
and its reviewer gate remain separate.

## Status

`active`

## Acceptance Criteria

- TaskFrame follow-ups preserve prior anchors, hard constraints, retrieval
  semantics, and evidence requirements unless the new utterance revises them.
- Retrieval reports total and returned logical-source counts plus explicit
  exhaustive/has-more state; all-matching does not use corpus size as a fake
  exact count.
- Evidence assembly can recover content from admissible observations inside a
  selected logical source item even when another observation matched search.
- Projection defaults to content and keeps sender, recipient, headers,
  filenames, and other metadata secondary unless explicitly requested.
- Answerability distinguishes permission denial, missing target, absent
  property, partial evidence, conflict, and sufficiency.
- Mail, PDF/TXT, XLSX/table, and application-event tests use the same contracts.
- Canonical dev-container verification, relevant docs, and the required
  reviewer gate pass before the board item is marked complete.

- Canonical authority reports agree on 12 passed gates, zero failed gates, zero
  remaining gates, and a complete objective audit.
- Each broad gate is backed by an accepted canonical evidence packet rather than
  a template, preview, candidate-only packet, or local ignored artifact.
- Total acceptance, objective audit, preflight, work orders, progress, and the
  tracked checklist all describe the same passing authority state.
- Canonical dev-container verification, relevant research checks, full Ruff,
  `git diff --check`, durable docs, and the required reviewer gate pass.
- Claims remain bounded: broad acceptance does not imply raw asset access,
  autonomous business judgment, canonical graph/type writes, or unrestricted
  production readiness.

## Blockers

Issue #49's earlier intermittent Codex full-chat blocker is resolved in the
current POC deployment. Three fresh anonymous July 23, 2026 sessions returned
HTTP 200 three out of three with 87 total / 10 displayed sources, exhaustive
coverage, 10 primary citations, one FormOwl call, and no fallback or
`chat_failure` event. The formerly failing `03.80503G301` COO/origin prompt
also returned HTTP 200 with the target identifier present. The same
28,036-message cold start now uses four tokenizer workers plus deterministic
parent merge and improved from 2368.108 seconds to 859.372 seconds, a 2.76x
speedup with 17.38GiB sampled peak memory and no OOM. Focused UAT-image checks
pass gateway 38/38, orchestrator 20/20, HTTP 43/43, targeted Ruff, and the
isolated Node 20 UI smoke. Keep Issue #49 unchecked until the final post-change
reviewer gate agrees. Methodology authority remains valid-but-blocked; this
establishes no methodology-quality UAT, KG-vs-ontology result, general
production readiness, or general latency claim.

GitHub issue #50 is complete in the isolated UAT worktree. Authorization was
already succeeding; the defect was that authorized mail body fields were still
sent through the generic public control/metadata redactor. The dedicated
evidence boundary now preserves ordinary body text and locally redacts only
high-confidence credentials and implementation details, while denied access
still returns no content. Live PO verification also exposed that the Codex
engine needed a second refinement query after one successful broad result, so
one turn now permits at most three bounded FormOwl calls and projects the latest
governed refinement. The July 24 LAN replay returned HTTP 200 for PO delivery
and COO/origin, with 87 and 17 exhaustive source items, readable snippets, zero
full-body placeholders, and no chat errors. This remains a POC display/safety
result under the valid-but-blocked methodology authority.

The bounded Task Answering slice passed 895 canonical dev-container tests,
full Ruff, 345-file format check, and `git diff --check`. The required
3-reviewer gate remains before completion.

Issue #44 passed 951 canonical dev-container tests, full Ruff, 275-file format
check, the Node 20 UI smoke, a dedicated non-root UAT image build with pinned
`codex-cli 0.144.6`, real direct and Unix-socket app-server attestation, a
non-root three-container init/serve/client smoke, and `git diff --check`.
Authentication is provisioned in a one-shot container. The current deployment
is explicitly authorized to copy the server's existing Codex ChatGPT auth
cache into isolated sidecar state; the serving sidecar does not mount the
developer's Codex home, authentication input, repository, corpus, evidence
cache, or UAT state.
Full disabled-feature attestation and failed-turn thread rollback closed the
final reviewer blockers; Plato, Volta, and Mencius returned 3/3
`RELEASE_DECISION: AGREE`. The authenticated deployed `8088` live gate also
passed: a greeting used no FormOwl tool, while the source-backed 文顥/pull-in
request invoked the single evidence tool exactly once and returned governed
evidence. The test thread was deleted after verification.

Four real-evidence gates still lack accepted canonical evidence:

- `fair_external_baseline_comparison`
- `annotation_adjudication_protocol`
- `multimodal_semantic_validation`
- `production_adapter_paths`

The completed Candidate Assertion, Domain Pack, Issue #16
temporal-evidential POC, and 93/100 source-neutral Candidate evidence retrieval
iteration are bounded candidate-layer implementation slices. They add no
canonical writes and do not satisfy or weaken these four broad evidence gates.

Default Candidate Evidence Retrieval remains the mandatory base for any future
response packet or evaluation harness: stable logical source item counting,
access/time/context filtering before planning, no lexical transitive closure,
and capped additive ontology reranking. Regex-only, parser-chunk,
component-union, and ontology hard-pruning behavior is ablation-only.
The index-owned `CandidateEvidenceTextPolicyRuntime` binds the actual query
tokenizer to the structured Unicode-NFKC/protected-ASCII/Jieba/corpus-bound
SentencePiece/frozen-profile policy and exact SHA-256 hashes. The binding also
pins the runtime id and tokenizer implementation hash; runtime code mismatch
fails closed. Default callers provide query text only and cannot supply raw
tokens or a free-form hash. Access and explicit context/time admissibility
precede tokenization; experiments use `retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Next Action

Run the final post-change Issue #49 reviewer gate over the multiprocessing,
fallback, bounded multi-tool behavior, tests, and live evidence before marking
that separate board item complete. The Task Answering reviewer gate and four
broad real-evidence gates remain independent. Keep methodology authority
valid-but-blocked and do not reinterpret issues #49 or #50 as
methodology-quality UAT, a KG-vs-ontology result, general production readiness,
or general latency.
