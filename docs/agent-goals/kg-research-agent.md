# Knowledge Graph Research Agent Goal

## Lifecycle

- Label: `active-blocked`
- Active program: GitHub issue #56
- Historical pre-rewrite state:
  `../archive/2026-08-18/active/docs/agent-goals/kg-research-agent.md`
- Retention: keep this file at or below 180 lines.

## Role

Knowledge Graph Research Agent. Durable role definition:
`../agent-roles.md`.

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
replacement, and objective completion. Diagnostic implementation may proceed.

The methodology authority guard is valid and must remain fail-closed. Current
runtime still reports:

```text
method: mail_candidate_kg_broad_ontology_diagnostic_v1
tokenizer: ascii_identifier_regex_v1
CJK support: false
```

Frozen target:

```text
method: evidence_to_knowledge_kg_ontology_v2_hybrid_v1
tokenizer: jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

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

The executable authority still blocks:

1. runtime pipeline matching the frozen method/tokenizer;
2. source completeness against a raw/source-system oracle;
3. evaluation reports bound to one execution fingerprint;
4. same-pipeline real-source strong-RAG versus Hybrid-v2 ablation;
5. real-user final-answer acceptance.

Historical regex, candidate-only, synthetic, issue #33, and issue #55 results
cannot satisfy these gates.

## Current Work Sequence

1. Package the immutable target tokenizer/profile and enforce same-profile
   query/evidence indexing without fallback.
2. Reconcile the authorized Observation snapshot against a source oracle and
   classify every loss.
3. Build the strong RAG control over that same snapshot.
4. Add typed routing and deterministic exact execution.
5. Add conservative entity linking, bounded source-backed traversal, and
   evidence-bundle reranking.
6. Add scoped ontology mappings and capped soft scoring; retain hard pruning
   only as a negative ablation.
7. Freeze model/prompt/budget/fingerprint manifests and run diagnostic arms.
8. Run independent holdout and transfer-domain final-answer evaluation only
   after the authority permits it.

## Acceptance Boundary

Implementation completion and comparative close are distinct.

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

Start issue #56 Work Package A with the smallest implementation slice: package
and hash the immutable Jieba + SentencePiece profile, bind query and evidence
to the same profile, add mixed-CJK/protected-identifier and no-fallback tests,
and keep every output diagnostic until the authority gate is ready.
