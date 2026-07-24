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

As of July 24, 2026, the final live human-UAT image is the current
human-readable + dynamic-tool-racefix + mobile-clearance build. The LAN surface
is ready with automatic restart. Desktop results use a 1120px,
content-dominant table; mobile uses labeled stacked cards. Taipei times are
human-readable, long content wraps, and the independent synthetic browser check
passed with 196px last-card clearance and no horizontal overflow.

The backend race occurred when turn completion outran an in-flight dynamic
tool. Requests are now pre-registered, and completion drains accepted tools
with a bounded timeout. Focused proof passes HTTP 47/47, orchestrator 25/25,
the JS UI smoke, Ruff/format, and diff checks.

One authorized source-backed independent test before the race fix blocked
because the request failed; existing non-content event evidence led to the
repair. Both private-evidence sidecar authorizations are exhausted, so no
post-fix source-backed automated retest was performed. The next evidence action
is the user's manual live webpage query. Methodology authority remains
valid-but-blocked: this is human-UAT surface engineering evidence, not
methodology-quality UAT, a KG-vs-ontology comparison, issue #33 closure, or
production readiness. The broad KG real-evidence objective remains blocked and
incomplete.

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

The user should run the next manual query on the live webpage. Keep the Task
Answering reviewer gate and four broad real-evidence gates independent, retain
the valid-but-blocked methodology authority, and make no methodology-quality,
comparative, issue #33 completion, or production-readiness claim from this
human-UAT repair.
