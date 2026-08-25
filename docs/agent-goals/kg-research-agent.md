# Knowledge Graph Research Agent Goal
## Lifecycle
- Label: `active-blocked`
- Active program: GitHub issue #56
- Historical pre-rewrite state:
  `../archive/2026-08-18/active/docs/agent-goals/kg-research-agent.md`
- Retention: keep this file at or below 180 lines.
## Role
Knowledge Graph Research Agent. Durable role: `../agent-roles.md`.
## Active Execution Model
Issue #56 uses one Master and exactly two implementation subagents:

```text
Master: global plan, decomposition, monitoring, integration review, acceptance
Worker A: gpt-5.6-sol, reasoning_effort=ultra
Worker B: gpt-5.6-sol, reasoning_effort=ultra
```
The Master does not implement or take over assigned edits. Workers receive
non-overlapping write sets. The five-step plan changes only for a concrete new
blocker; repeated failed routes require a changed decomposition or validation
method, not another retry.
## Objective
Implement and fairly evaluate
`evidence_to_knowledge_kg_ontology_v2_hybrid_v1` so FormOwl can use a governed
graph for heterogeneous-data integration and demonstrate a measurable
final-answer advantage over strong RAG on graph-required tasks.

The intended path is:

```text
source-complete authorized Observations
  -> strong RAG control
  -> conservative entity linking
  -> reviewed candidate/canonical graph topology
  -> temporal/provenance/coverage constraints
  -> scoped ontology with capped soft scoring
  -> deterministic exact executor or cited answer
```
Mail is the first source fixture. The method must transfer to a materially
different source family without question-specific core types or aliases.
## Status
`blocked` for methodology-quality UAT, comparative superiority, default-path
replacement, and objective completion. The pinned authority is valid but fail-closed
with four blocking gates. The normal runtime-method gate passes for
`evidence_to_knowledge_kg_ontology_v2_hybrid_v1` and
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`. Remaining gates
are source completeness, accepted execution-fingerprint binding, same-pipeline
real-source ablation, and independent final-answer acceptance. The v3
promotion contract is repaired, but no passed evidence exists to promote.
## Diagnostic Checkpoint — 2026-08-25
The sealed `456`-Observation `workspace_only_v1` package has no tenant
dimension. Its earlier development one-shot is consumed: Hybrid `0/100`, graph
CI `[0,0]`, citations `0%`, no-answer false positives `100`, p95
`1510.841 ms`, and leakage `0`.
Source tracing found the old fixed prompt had zero raw/parser/retrieval
occurrences; v4 corrected that prompt-to-source mismatch and passed with `2`
anchors, `10` paths, and `1` citation. V5/v6 then isolated relation-precompute
latency: v6's cold arm exhausted relation projection at `1415.389724 ms`, while
its primed arm completed at `57.939772 ms` with `10` paths/`1` citation/`48`
scores. Their immutable details remain on the active board and handoff.

Formal v7 mode
`issue56-sealed-source-real-prompt-relation-projection-offline-equivalence-phase-traced-diagnostic-20260825-v7`
is consumed and passed over the same `456` Observations for
`workspace_formowl`, approved actor
`user_full_pst_domain_hard_case_eval_owner`, with no tenant dimension. Its two
isolated presealed views each contained `10281` nodes and `29748` edges.
Cold/after graph preseal took `61825.028571`/`61485.804325 ms`; the after
relation precompute took `4344.986693 ms`. Post-claim cold binding/base/total
were `633.968035`/`3196.093676`/`35771.614738 ms`, moving `0/0 -> 1/1`.
Both normal `1500 ms` ASGI `/mcp` arms completed: cold/after relation projection
was `57.473886`/`58.790683 ms`, query `290.941898`/`298.654947 ms`, and HTTP
`366.720007`/`361.008008 ms`; each produced `10` paths, `1` citation, and `48`
scores with no deadline exhaustion. All `13` timing-free equivalence groups,
all cache checks, and all applicable boundary gates passed.

V7 claim/claim-byte/report-byte are
`sha256:879e903599e95d38d52e0bd1fb0d29fb6266371e7168289547d0bbc23a1d643b`,
`sha256:4de4d694f042f46b3a0d6c68dd93101ca7c7610a0b3f97496f44be34f20b7a0c`,
and `sha256:5b34d191244391c560cda849c0666c2f7e41be1d220fd3799108b6ca738a99d0`;
claim/report sizes are `1508`/`30893` bytes. Trace/execution/source/preflight/
offline-evidence/owner/precompute/cache bindings are
`sha256:9af61b1918c6ef2c31a91a8d6f73a875e796bbf678b13c49f7db44530189e6d6`,
`sha256:a99e1fa89b01d2d383209ae09f742ee55cfddcd2095992c9391878d73b00c649`,
`sha256:b5a8112dd88eb829b26ec7b795a6071ca81a6327362a0d265c1749d41c5f002e`,
`sha256:10c44440e0cde947591af7c8ad9797ba47b755d50d027d280c0cfa464dd8baf0`,
`sha256:bd6d0e962d07ba10f273caa83996a6e57114d6801d56660c551d3728a655fdf1`,
`sha256:8f63bdcf6baa4d18b6574071905900baf002318d9227e0d0da0523bf297a293e`,
`sha256:b2edcd214a19a6b3283abc475a8b67abd984753653a6136396b1630bfbfecf3b`,
and `sha256:d15cf0214e9112b1a28130496dc5ea0c554587606e32dd423886ee14364e110f`.
Temporary evidence passed `51/51`; cross-review found no blocker. With v6's
latency-necessity evidence, v7 accepts the bounded behavior-neutral same-source
relation-precompute POC only. V1-v7 cannot be rerun or tuned; this is not
methodology/UAT/holdout/readiness/superiority/completion evidence.
## Non-Negotiable Method

- Strong RAG means lexical/BM25 + dense retrieval + fusion + evidence
  reranking over the same Observations.
- KG adds reviewed identity, cross-source joins, bounded traversal, temporal
  state, contradiction, provenance, and coverage.
- Ontology is small-core, scoped, data-first, versioned, and capped additive.
  Inferred mismatch cannot prune admitted evidence.
- Permission, schema/arity, lineage, revision pins, canonical-write
  preconditions, and exact-set coverage remain hard invariants.
- Exact set/count/inventory/aggregation/definitive-negative queries use a
  deterministic executor, not top-k inference.
- The final answer model, prompt, reasoning effort, schema, and context budget
  are identical across comparison arms.
- Independent holdout content cannot tune tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or models.
- PostgreSQL/pgvector remains canonical; no Neo4j work is authorized.

## Current Blockers

The authority blocks source completeness, execution-fingerprint binding,
same-pipeline real-source ablation, and real-user final-answer acceptance.
Historical, candidate-only, synthetic, and consumed diagnostics cannot satisfy
them.

## Current Five-Step POC Plan

1. The Master freezes two disjoint worker write sets and one real end-to-end
   success path, then records only status changes unless evidence reveals a new
   blocker.
2. Worker A implements the immutable target tokenizer/profile and same-profile
   query/evidence indexing without fallback, including the smallest runnable
   path that proves the profile is actually used.
3. Worker B implements the complementary source-preserving strong-RAG/control
   path needed to carry an authorized Observation through real retrieval and
   result production; contract-only wiring is insufficient.
4. The workers extend their non-overlapping slices into one bounded issue #56
   path covering typed routing, deterministic exact execution where applicable,
   conservative graph expansion, and capped soft ontology scoring.
5. The Master integrates and inspects the end-to-end evidence, redirects any
   repeated blocker instead of retrying blindly, and accepts only the claim
   actually proven. Independent holdout, transfer evaluation, broad hardening,
   and release review remain later gates.

Plan status: step 4 is `in-progress`; the five-step wording remains frozen. No
further execution of the consumed development one-shot is authorized.

## Acceptance Boundary

Implementation completion and comparative close are distinct.

POC evidence must cover this real path:

```text
authorized source/Observation
  -> frozen query/evidence profile and index
  -> strong RAG plus bounded graph/ontology execution
  -> deterministic result or cited answer
```

Contracts, schemas, mocks, or isolated tests alone are insufficient. POC
evidence never relaxes permission, privacy, provenance, candidate-before-
canonical, no-secret/no-raw-path, fail-closed authority, or public-output
boundaries, and cannot earn readiness, superiority, or completion claims.

Implementation completion requires target runtime, source-complete graph input,
strong RAG, typed plans, deterministic exact execution, graph/ontology path,
generalized tests, frozen diagnostic artifacts, synchronized docs, canonical
container verification, and 3/3 reviewer agreement.

Comparative close additionally requires the independent holdout and transfer
domain to pass pre-registered correctness, citation, no-answer, privacy,
latency, and cost gates, plus:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

exiting zero.

## Next Action

Remain within step 4 and do not rerun or tune v1-v7. The bounded relation
precompute POC is accepted only inside its diagnostic claim boundary. Next,
close the four blocked authority gates with legitimate evidence; do not execute
holdouts prematurely.
