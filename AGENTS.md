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

**Latest 2026-10-06 user authorization:** up to two ordinary implementation
worker slots may request `gpt-6.1-sol` with `reasoning_effort=high`. This supersedes earlier
sol/xhigh and luna/max tiers and conflicting “no recreation” work orders.
The 2026-10-06 SPEC clarification was a closed documentation slice: A's
`SPEC.md` revision finished and B aligned the eight assigned current docs;
Master orchestration-only applied to that slice.
That closed docs-only slice granted scoped document/link/diff checks, no code, tests,
containers, provider, service, or private-source actions; UAT recovery remains open.

**Current user assignments supersede that closed-slice boundary:** the Master
or authorized worker may perform only the explicitly named bounded work. This
does not authorize canonical writes, unsafe permission bypass, or a
methodology-completion claim; it also does not create a standing ban on a later
explicitly authorized provider, Docker, source, or UAT operation.

Current explicit user assignments govern paths and permitted actions. Dated
completed-task write sets, closure reports, and “no further work authorized”
statements apply only to their recorded slice: they neither resume old tasks
nor indefinitely prohibit later user-authorized work. Historical metadata is
not proof of a current worker turn. Evidence is superseded only for the same
proved scope; a later focused pass does not make a whole module or suite green.

No descendants, duplication, or unbounded parallel workers are authorized. The
two-worker cap remains in force, but the lack of an available or verifiable
worker handle is not an availability gate for bounded work.
The worker tier is the requested configuration and a traceability field, not a
precondition for work. Dispatch should request `gpt-6.1-sol`/`high` when the
runtime supports it, but missing or mismatched persisted metadata, an unavailable
model, or an unavailable worker handle must not block a bounded assignment.
Continue with the configured/available execution path and record the status as
`verified`, `unverified`, or `unavailable`; never claim a model or effort that
was not observed. This removes the former metadata deadlock without permitting
silent promotion of a fallback to the requested tier. “No substitution” means
no silent relabelling of the observed model, effort, or worker identity; it does
not prohibit continuing explicitly bounded work with the available execution
path.
Worker metadata inspection remains read-only and safe: retain only task/turn
IDs when present, model/effort when observed, UTC timestamp, and verification
status; exclude inherited contexts, raw rollout paths/content, prompts, and
secrets. An unpinned resume is permitted when explicit pinning is unavailable,
provided its actual configuration is marked unverified and the work remains
within the bounded assignment. UAT remains `gpt-5.5`/`high`.

Dated diagnostic results and unique verification records remain in
`docs/agent-goals/handoff-log.md`. Its later cap-fixture repair supersedes the
earlier unresolved single-case report, not the unrerun whole loader module or
non-green full regression. F841, live UAT, three reviewers and four methodology
gates remain open; feature 待測, step 4 `in-progress`. No standard, readiness,
completion or reviewer acceptance is established.

- Keep bounded assignments sequential and write sets disjoint.
- The temporary exception does not reduce the independent three-reviewer
  acceptance gate or relax safety or methodology authority.
- The Master normally owns only the global view, a plan of at most five steps,
  non-overlapping work assignment, progress and repeated-failure monitoring,
  integration review, and final acceptance. An explicit user assignment may
  authorize the Master to make a bounded documentation or implementation edit;
  worker metadata availability must not prevent that authorized work.
- The Master may inspect repository state, diffs, and verification results, but
  must not write or modify implementation code or durable repository
  documentation unless the current user explicitly authorizes a bounded edit in
  named paths. Repository edits otherwise belong only to the explicitly
  authorized worker or temporary reviewer within its current bounded write set.
- While implementation workers are active, the Master must inspect their
  progress at least every 15 minutes for overengineering, scope or file-count
  growth, parallel abstractions, repeated failed routes, and unnecessary broad
  tests or hardening, then stop, shrink, or repartition the work when found.
  Monitoring applies during active turns, not autonomous wake-ups after final.
- During any monitoring period explicitly requested by the user, each Worker
  must continue executing the assigned work, report progress, evidence,
  blockers, and resource risks, and stop and report when the same path fails
  repeatedly.
- Give the authorized implementer bounded paths and outcomes. If a route repeatedly
  fails, the Master must narrow the work, change the validation method, or
  stop that route rather than duplicate effort or repeat the same attempt.
- Once created, a plan may update step status only. Rewrite it only for a
  demonstrated new blocker; do not repeatedly expand or reshape it.
- A POC is accepted primarily through the smallest real end-to-end user path.
  API, contract, and unit wiring are local diagnostics and cannot by themselves
  establish that the POC works.
- When a user authorizes a POC time box, prioritize rapid minimal E2E proof.
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
       -> authorized source retrieval / native structured execution
       -> optional zero-to-many candidate annotations/entities/claims/relations/frames
            -> review -> canonical KG + scoped ontology
            -> permission-filtered EffectiveGraphView

query
  -> typed router and validated SemanticQueryPlan
  -> agent-expanded, schema-validated tool queries
  -> modality-appropriate source retrieval / deterministic structured execution
     (frozen text control: BM25 + dense retrieval)
  -> optional entity linking + bounded source-backed graph traversal
  -> temporal/provenance filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> bounded iterative tool execution/requery with safe phase trace
  -> deterministic executor or cited LLM answer
```

Frozen target:

```text
evidence_to_knowledge_kg_ontology_v2_hybrid_v1
jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

Historical runtime truth on 2026-08-18 (not current instructions):

```text
mail_candidate_kg_broad_ontology_diagnostic_v1
ascii_identifier_regex_v1
CJK support: false
```

The 2026-10-02 canonical dev-container probe matches the frozen target above
with CJK support true: authority valid=true, ready=false, errors=[].
Source completeness, accepted execution-fingerprint binding, same-pipeline
real-source ablation, and independent final-answer acceptance remain blocked.
This is not a production-tokenization or methodology-completion claim; host
dependency failures are supplemental, not canonical runtime evidence.

Therefore:

- Strong RAG is a required component and comparison baseline, not a discarded
  predecessor.
- KG supplies heterogeneous integration, reviewed identity, cross-source joins,
  bounded topology, time, contradiction, and provenance.
- Ontology is small-core, scoped, data-first, versioned, and a capped soft
  retrieval signal. Inferred mismatch must not prune admitted evidence.
- Sources retain text, structured values, images, speech, non-speech audio/music,
  and video evidence with native locators. OCR/transcripts/descriptions are derived
  representations; text proxies or fixture labels do not prove native media support.
- Ontology annotations are optional and zero-to-many per document/Observation;
  reviewed KG identity/relation overlays link back to source evidence. Direct
  authorized lookup and native structured execution need no graph match or annotation;
  missing overlay entries never establish source absence.
- Bounded source context may include paragraphs, cell ranges, image crops, or media
  clips with native citations and revalidated hash/revision/lineage/permissions.
  Spreadsheet execution preserves formula/raw/cached/display distinctions, types,
  precision, units, blanks/nulls, merged headers, coordinates, and same-row association.
  Current attachment XML values and text-backed media fixtures do not prove that
  complete contract; disclose unsupported native features and incomplete coverage.
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
- 2026-10-06: validated `evidence_lookup` + nonempty validated requested fields
  ALL lacking verified support => one materially different same-authorized-scope
  bounded recheck, subject to existing safety/eligibility/budgets. Partial misses
  MUST be disclosed and MUST NOT trigger; source-backed blanks count as verified
  coverage. Empty sets resolve the validated evidence-need plan or clarify.
  Zero citations/status/projection failure alone cannot trigger or establish
  eligibility. Eligible immutable source lookup works without failed projection,
  preserving source/hash/lineage/revision/permission checks/no-inline-rebuild.
  Missing diagnostic identity metadata => incomparable is separate from
  business-field coverage.
- Missing, unsealed, or unactivated retrieval projections are distinct from
  an independently validated immutable source snapshot. Fallback may start
  from that source snapshot without failed projection when eligible, preserving authorized
  source/hash/lineage/revision checks; no inline rebuild. Projection failure alone is not eligibility.
- Do not forward a raw or under-specified user prompt directly as an MCP query
  when intent, identifier, field, or source semantics need resolution. The
  Query Agent must expand and validate each tool query, then iterate only
  within the pinned attempt/tool-call/evidence/token/time/repair budgets.
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

For an authorized implementation-completion verification, run the existing
Python tests before reporting completion. This is not an implicit full-suite
grant for a bounded assignment:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```
