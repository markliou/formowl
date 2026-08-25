# Agent Instructions

This repository is built from the FormOwl specification. At the start of every
new agent session, and again after context compaction, resume, or a long
interruption, read this file first. Before changing code, read these files in
order:

1. `docs/implementation-task-breakdown.md`
2. `docs/methodology-authority.json`
3. `docs/agent-roles.md`
4. `docs/agent-goals/README.md`
5. The active role's goal file under `docs/agent-goals/`
6. `docs/agent-goals/handoff-log.md`
7. `docs/agent-goals/reviewer-gate.md`
8. `SPEC.md`
9. `RESOURCE_EXTRACTION_SPEC.md`
10. `README.md`

After reading the startup files, run:

```sh
python3 scripts/methodology_authority_check.py --check
```

A valid but blocked result is the expected current state. Keep that block
visible in planning, reports, and review.

Before methodology-quality UAT, comparing strong RAG with KG/ontology, changing
the frozen methodology, or marking a methodology slice complete, run:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

Do not continue those claim-bearing actions when it exits nonzero. Diagnostic
implementation may continue only with an explicit blocked claim boundary.

Use `docs/implementation-task-breakdown.md` as the shared work board and
`docs/agent-goals/` as the durable goal registry. Active files are intentionally
bounded. `docs/archive/` is immutable history and is **not** a source of current
instructions. Open it only when historical proof is specifically required.
Files marked “Historical” or “Not Current Instructions” are pointers, not work
orders.

## Active Agent Role

This thread's Codex agent is the Knowledge Graph Research Agent. The durable
role split is in `docs/agent-roles.md`.

Prioritize source-preserving graph integration, ontology governance, entity and
relation resolution, graph lifecycle, effective graph views, graph-guided
hybrid retrieval, deterministic exact execution, and fair evaluation against
strong RAG. Leave broad service/storage/transport implementation to the FormOwl
System Backbone Agent unless the user explicitly assigns it here.

## Master and Subagent Execution Mode

This thread uses one orchestration-only Master and exactly two implementation
subagents. Both subagents must use `gpt-5.6-sol` with
`reasoning_effort=ultra`. Model or dispatch unavailability is a blocker; do not
silently substitute another model, add workers, or let the Master implement.

- The Master owns only the global view, a plan of at most five steps,
  non-overlapping work assignment, progress and repeated-failure monitoring,
  integration review, and final acceptance.
- The Master may inspect repository state, diffs, and verification results, but
  must not write or modify implementation code or durable repository
  documentation. Delegate every repository edit, including agent-spec edits,
  to one of the two subagents.
- Give the two subagents disjoint paths and outcomes. If a route repeatedly
  fails, the Master must repartition the work, change the validation method, or
  stop that route rather than duplicate effort or repeat the same attempt.
- Once created, a plan may update step status only. Rewrite it only for a
  demonstrated new blocker; do not repeatedly expand or reshape it.
- A POC is accepted primarily through the smallest real end-to-end user path.
  API, contract, and unit wiring are local diagnostics and cannot by themselves
  establish that the POC works.
- During the current pre-outage time box, prioritize rapid minimal E2E proof.
  Hardening, onboarding, broad negative matrices, and production reinforcement
  may be deferred until feasibility is shown, but remain required follow-up
  rather than permanent exemptions.
- This mode never relaxes methodology authority, permission, privacy, source
  provenance, candidate-before-canonical, or no-secret/no-raw-path boundaries,
  and it does not let the Master take over broad System Backbone ownership.

## Active Methodology Program

GitHub issue #56 is the current KG research program:

```text
heterogeneous sources
  -> source-preserving Observation
  -> candidate entities/claims/relations/frames
  -> reviewed canonical KG + scoped ontology
  -> permission-filtered EffectiveGraphView

query
  -> typed router and validated SemanticQueryPlan
  -> BM25 + dense retrieval
  -> entity linking + bounded graph traversal
  -> temporal/provenance filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic executor or cited LLM answer
```

Frozen target:

```text
evidence_to_knowledge_kg_ontology_v2_hybrid_v1
jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

Current runtime truth remains:

```text
mail_candidate_kg_broad_ontology_diagnostic_v1
ascii_identifier_regex_v1
CJK support: false
```

Therefore:

- Strong RAG is a required component and comparison baseline, not a discarded
  predecessor.
- KG supplies heterogeneous integration, reviewed identity, cross-source joins,
  bounded topology, time, contradiction, and provenance.
- Ontology is small-core, scoped, data-first, versioned, and a capped soft
  retrieval signal. Inferred mismatch must not prune admitted evidence.
- Exact set, count, inventory, aggregation, and definitive negative claims use
  deterministic structured execution, never top-k inference.
- Final answer-model identity is pinned per run and held constant across arms.
- Independent holdout questions cannot tune tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or models.
- PostgreSQL/pgvector remains the canonical storage baseline. Do not resume
  Neo4j migration, dual-write, or storage-selection work.
- Completed issue #55 document-first POC and earlier issue #33 plans are
  historical only; do not resume their next actions or constraints.

Canonical methodology documents:

1. `docs/kg-research-method.md`
2. `docs/kg-ontology-v2-rd-boundary.md`
3. `docs/kg-ontology-v2-runtime-evaluation-plan.md`
4. `docs/methodology-authority.json`

## Working Rules

- Pick one unchecked task or the task explicitly assigned by the user.
- Treat the machine-readable methodology authority and executable probe as the
  source of truth for readiness. Prose cannot override it.
- Never claim graph/ontology advantage from historical synthetic, regex,
  candidate-only, or document-first evidence.
- Do not fit runtime behavior to UAT or holdout questions.
- Stay inside the listed owner paths when possible.
- Do not create parallel replacement modules, schemas, indexes, ontologies,
  truth stores, or answer services when the specification names an owner path.
- Keep extraction, graph governance, effective-view assembly, query execution,
  and projection as separate layers.
- External extractors and LLMs produce candidates only. They do not silently
  mutate canonical graph/type/user-graph/wiki state or external systems.
- Entity matching does not grant access. Graph visibility does not grant raw
  evidence access. Canonical merge does not grant either.
- Do not expose raw filesystem, NAS, object-store, database, worker, parser,
  oracle, or hidden-source internals through ChatGPT-facing MCP tools.
- Mark `[x]` only after code, tests, relevant docs, and required review are
  complete. Leave partial work unchecked with a concise state note.
- Update the active role goal and handoff log before pausing or transferring
  work that affects a future session or another agent.
- Archive active history losslessly before retention limits are exceeded; never
  edit an existing dated archive.
- Use the dev container as the canonical development and verification
  environment. Host checks are supplemental only.
- If a required test/helper is missing from the dev container, treat that as a
  tooling bug to fix or document before completion.

## Current Starting Point

The implementation program starts with issue #56 Work Package A and B:

```text
current Observation snapshot
  -> source-completeness reconciliation
  -> immutable target tokenizer/profile
  -> same-profile query/evidence re-index
  -> strong RAG control
  -> reviewed candidate graph and scoped ontology
  -> graph-guided hybrid execution
```

Do not start methodology-quality comparison until `--require-ready` permits it.

Run the existing Python tests before reporting completion:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```
