# Provenance and Reproducibility Contract

This document defines the active provenance contract for the issue #56
source-preserving, graph-guided Hybrid KG + Ontology v2 method. Historical
provenance text is preserved under `docs/archive/2026-08-18/`; it is not current
instruction.

Provenance is not only a citation attached to an answer. It is the complete,
reproducible chain that explains:

```text
what source material was authorized and captured
what was extracted or omitted
what a model or rule proposed
what governance accepted, rejected, or changed
what graph and ontology revisions were visible
how a query was planned and executed
what evidence supported each returned claim
which model, prompt, code, and environment produced the output
```

A result without this chain may be used for debugging, but it cannot support a
methodology-quality comparison, canonical graph change, exact-set claim, or
reviewed projection.

## 1. Canonical Traceability Chain

```text
Source / Asset / EvidenceSnapshot / source occurrence
  -> source inventory and completeness reconciliation
  -> ExtractorRun
  -> source-preserving Observation
  -> candidate mention, entity, claim, relation, state, event, or frame
  -> review and governance decision
  -> CanonicalGraphRevision + OntologyRevision
  -> permission-filtered EffectiveGraphView
  -> validated SemanticQueryPlan
  -> EvidenceBundle or deterministic exact result
  -> citation-grounded answer, projection, or reviewed action proposal
```

Each arrow is an explicit versioned transformation. No layer may replace an
upstream identifier with an untraceable summary, model memory, raw filesystem
path, or backend-specific locator.

## 2. Lineage Dimensions

Every methodology-bearing artifact preserves six distinct dimensions:

| Dimension | Required meaning |
| --- | --- |
| source lineage | Which source object and source occurrence supplied the evidence |
| interpretation lineage | Which extractor, rule, model, prompt, schema, and tokenizer produced derived candidates |
| governance lineage | Which review or policy decision accepted, rejected, corrected, split, merged, or superseded a candidate |
| authorization lineage | Which actor, workspace, grant, policy, and effective view permitted visibility |
| execution lineage | Which validated plan, indexes, graph traversal, scoring, budgets, and executor produced the result |
| output lineage | Which citations, evidence items, graph objects, and revisions support each answer or projection |

These dimensions are not interchangeable. Entity matching does not grant
access. Access does not perform canonical merge. Canonical merge does not grant
raw asset access. A high model score does not replace review.

## 3. Stable Identifiers

Use stable FormOwl identifiers and immutable revision references, including as
applicable:

```text
asset_id
asset_occurrence_id
source_ref
source_occurrence_id
evidence_snapshot_id
source_inventory_id
source_completeness_artifact_id
extractor_run_id
observation_id
candidate_id
review_event_id
canonical_object_id
graph_revision_id
ontology_revision_id
policy_revision_id
index_profile_id
index_revision_id
effective_view_id
query_plan_id
query_execution_id
evidence_bundle_id
projection_spec_id
projection_revision_id
execution_fingerprint
workspace_id
user_id
grant_id
audit_event_id
```

Raw NAS, SMB, NFS, local, object-store, database, parser, worker, and scratch
paths are implementation details. They are never public provenance identifiers.

## 4. Source and Completeness Lineage

Before a source snapshot may participate in issue #56 comparative evaluation,
its authorized Observation manifest must be reconciled against an independent
raw-source or source-system inventory.

The completeness artifact binds:

```text
source inventory or oracle manifest hash
authorized Asset and EvidenceSnapshot manifest hash
source occurrence manifest hash
ExtractorRun manifest hash
Observation manifest hash
source-unit and Observation counts
policy-redacted, unsupported, failed, normalized-away, deduplicated, and unexplained counts
adapter, parser, package, code, and container revisions
reconciliation policy and reviewer
execution fingerprint
```

Every absent source unit is classified as one of:

```text
policy redaction
unsupported source feature
extractor failure
normalization loss
deduplication or occurrence-lineage loss
unknown unexplained loss
```

Only intentional policy redaction may be excluded without failing the
completeness gate. Unsupported or failed units weaken the coverage claim;
unknown loss blocks methodology readiness. Graph ranking and answer generation
cannot repair or hide missing source evidence.

## 5. Extraction and Candidate Lineage

An `Observation` records:

```text
asset or evidence snapshot
source reference and source occurrence
extractor run and output manifest
source-native locator
raw and normalized extracted values
captured, observed, and source times
permission scope
confidence, warnings, and review requirement
content hash
```

A semantic or graph candidate additionally records:

```text
source Observation ids and occurrences
candidate family and proposed subject/predicate/value or frame
candidate granularity
entity-link and relation-link alternatives
ontology revision used for interpretation
rule/model, prompt, schema, settings, and package revisions
score components and confidence
review state
```

Deterministic extraction and semantic interpretation remain separate. Candidate
records are proposals and cannot silently mutate canonical graph, ontology,
user graph, wiki, or external-system state.

## 6. Governance and Canonical Graph Lineage

Every canonical commit records:

```text
accepted, rejected, corrected, split, merged, deferred, and superseded candidate ids
source Observation ids and source occurrences
reviewer or approving policy
permission and target scope
previous and new graph revisions
ontology and policy revisions
entity-resolution and contradiction decisions
commit and audit event ids
```

Canonical means governed within a declared owner, workspace, project, customer,
or grant scope. It does not mean universally true.

Lifecycle operations are revisioned mappings, not destructive replacement:

```text
split_into
merged_into
summarized_by
supersedes
deprecated_by
equivalent_to
derived_from
archived_as
```

Old identifiers remain resolvable for citations, audits, effective views, and
historical projections.

## 7. Permission and Effective-View Lineage

An `EffectiveGraphView` binds:

```text
actor and workspace
current memberships and grants
source and evidence visibility
canonical graph revision
ontology and policy revisions
included and excluded object ids or safe counts
redaction and access-overlay decisions
view creation time and expiry
view hash
```

Permission filtering occurs before evidence, vector hits, graph nodes, or
neighborhoods are materialized for a query. Denied or hidden data must not
contribute scores, counts, snippets, graph paths, model context, or no-answer
logic.

For shared knowledge, preserve:

```text
source owner and scope
source Asset, Observation, and evidence ids
grant and access-request ids
visible-to actor
visibility level: answer_only | graph_snippet | evidence_snippet | raw_asset
audit event
```

Prefer linked references over copied private evidence. Revocation removes the
linked material from later effective views without deleting historical audit.

## 8. Query-Plan Lineage

Every executed query has a validated `SemanticQueryPlan`. The plan pins:

```text
plan schema version
query class and maximum claim strength
actor, workspace, task, source, and permission scope
effective-view, graph, ontology, policy, tokenizer, and index revisions
entity, relation, temporal, provenance, and evidence slots
allowed edge types and directions
hop, fan-out, candidate, evidence, token, latency, and repair budgets
coverage requirement and output schema
planner model, prompt, reasoning, decoding, and schema fingerprint when used
```

An LLM may propose a plan. Deterministic validation decides whether it is
executable. Invalid, scope-widening, revision-unbound, or under-specified plans
fail closed. A bounded repair pass stays inside the original source and
permission scope and creates no hidden candidate or canonical writes.

## 9. EvidenceBundle and Exact-Result Lineage

An `EvidenceBundle` is the unit passed to reranking and answer generation. It
records:

```text
bundle id and query execution id
query plan id and execution fingerprint
authorized Observation ids and source occurrences
linked canonical object ids and evidence-backed graph paths
lexical, dense, entity-link, graph, temporal, provenance, coverage, and ontology scores
score caps and fusion/reranking policy
conflict, supersession, incompleteness, and redaction annotations
stable citations and safe locators
ordering and truncation reason
```

Every answer-relevant graph hop resolves to authorized Observations. A graph
edge without visible evidence cannot support an answer claim.

Exact set, count, inventory, aggregation, duplicate, missing-item, and
definitive-negative results use deterministic execution rather than top-k
retrieval. The result binds:

```text
bounded source and effective-view scope
coverage policy and status
enumerated item count
policy-redacted, unsupported, and unresolved counts
duplicate policy and stable ordering
evidence lineage per item
query, graph, ontology, policy, and index revisions
```

Incomplete coverage produces a partial result and a weaker claim.

## 10. Execution Fingerprint

Every accepted evaluation report and reproducible output binds one immutable
execution fingerprint covering at least:

```text
source inventory, Asset, EvidenceSnapshot, occurrence, and Observation manifests
tokenizer/profile and lexical index revision
embedding model and dense index revision
candidate-admission, entity-linking, graph, ontology, and policy revisions
EffectiveGraphView and permission snapshot
query-plan schema, router, traversal, scoring, reranking, and executor revisions
planner, extractor/linker, embedding, reranker, and final-answer model identities
prompt, schema, reasoning effort, decoding, context, evidence, token, time, and repair budgets
evaluator, grader, rubric, and data-split manifests
code commit, dependency lock, container image, and hardware class
methodology-authority state fingerprint
```

Changing any bound input creates a new fingerprint and a new experiment. A
report assembled from different source, tokenizer, graph, ontology, model, or
evaluator revisions is invalid even if each component passed separately.

## 11. Model and Prompt Lineage

There is no single FormOwl KG LLM. Record model roles separately:

```text
planner model, if any
candidate extraction or entity-linking model, if any
embedding model
reranker model, if any
final answer model
```

Each role records provider or package, exact model/revision, prompt hash, output
schema hash, reasoning effort, decoding settings, context budget, and runtime
fingerprint as applicable. Comparison arms use the same final answer model and
settings. Model memory cannot fill missing evidence or alter source coverage.

Independent holdout content cannot become tokenizer data, protected vocabulary,
aliases, ontology mappings, graph rules, thresholds, prompts, models, or grader
policy. A holdout-motivated change starts a new version and requires a new
holdout.

## 12. Time, Conflict, and Confidence

Keep these times distinct:

```text
captured_at
observed_at
asserted_at
effective_at
valid_from and valid_to
due_at
superseded_at
```

Ambiguous time retains raw text, normalized candidate, precision, inference
rule, confidence, and reviewer state.

Conflicting assertions may coexist when sources, times, scopes, or confidence
differ. A current-state view is a projection over history. Correction and
supersession do not erase the original source assertion.

## 13. Projection and Action Lineage

Every cited answer, report, dashboard, review queue, wiki draft, or action
proposal records:

```text
source refs and evidence snapshot ids
Observation ids and citations
graph, ontology, policy, effective-view, and index revisions
query plan, evidence bundle, or deterministic-result ids
projection specification and output revision
generator model and prompt metadata
review and publication state
target/backend revision when applicable
audit event and external_write_performed flag
```

A projection never becomes canonical graph state by implication. External
writes remain proposal-first and require explicit authorization, current
permission, target validation, audit, and no-partial-write behavior.

## 14. Public Reporting and Redaction

Public reports may expose stable ids, hashes, counts, revision labels, bounded
metrics, and safe citations. They must not expose:

```text
raw private source payloads or oracle answers
credentials, tokens, keys, or environment values
raw filesystem, NAS, object-store, database, parser, or worker paths
SQL, connection strings, command lines, or scratch locations
hidden entity names, denied snippets, or inference about redacted topology
unredacted model traces or evaluator private labels
```

Redaction is itself provenance-bearing: record the policy revision, redacted
count, and reason code without revealing the hidden value.

## 15. Acceptance Invariants

The provenance layer is aligned only when:

1. every answer-relevant claim traces to authorized source Observations;
2. source completeness is independently reconciled and unexplained loss blocks;
3. candidate, governance, canonical, authorization, execution, and output
   lineage remain distinct;
4. every executed plan and evidence bundle pins all relevant revisions;
5. exact results include an explicit coverage contract;
6. denied evidence cannot influence scores, paths, counts, or model context;
7. every accepted evaluation report binds one execution fingerprint;
8. comparison arms share source, permission, tokenizer, answer-model, prompt,
   budget, evaluator, and environment lineage;
9. lifecycle and contradiction preserve historical identifiers; and
10. public outputs expose governed identifiers and safe summaries only.
