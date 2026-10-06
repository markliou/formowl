# Issue #56 Runtime and Same-Pipeline Evaluation Plan

**Program:** graph-guided Hybrid KG + Ontology v2 versus strong RAG
**Frozen method:** `evidence_to_knowledge_kg_ontology_v2_hybrid_v1`
**Frozen tokenizer:** `jieba_sentencepiece_frozen_profile_candidate_admission_v1`
**Status on 2026-08-18:** `active-blocked`

This is the active execution plan. It replaces the previous issue #33 plan,
storage-engine campaign, exact-one-call POC direction, and mail-only ontology
factorial as operational instructions. Their original text is preserved under
`docs/archive/2026-08-18/`.

## 1. Gate Before Claims

Run before methodology-quality UAT, comparison, or completion:

```sh
python3 scripts/methodology_authority_check.py --require-ready
```

A nonzero result blocks the claim, not diagnostic implementation. Current
blockers are runtime alignment, raw-source completeness, execution-bound
reports, same-pipeline real-source ablation, and real-user final-answer
acceptance.

## 2. Execution Principles

1. Use one source-complete authorized Observation snapshot for every arm.
2. Use one immutable tokenizer/profile for query and evidence.
3. Pin one final answer model, reasoning effort, prompt, schema, and budget.
4. Keep candidate admission, graph topology, ontology scoring, and execution
   mode as separate factors.
5. Never use final holdout questions or answers to build vocabulary, aliases,
   ontology, graph rules, thresholds, or prompts.
6. Never infer complete sets or counts from top-k retrieval.
7. Preserve permission and provenance at candidate creation and every graph hop.
8. Keep PostgreSQL/pgvector as the canonical storage baseline.

## 3. Work Package A — Runtime Alignment

### A1. Immutable tokenizer profile

Package the target profile with:

```text
profile id and schema version
Jieba dictionary and user-dictionary hashes
SentencePiece model and vocabulary hashes
normalization policy hash
protected-identifier policy hash
candidate-admission policy hash
package/dependency lock hash
```

Protected spans are identified before segmentation. Minimum protected classes:
email addresses, URLs, dates, currency/measurements, mixed CJK-alphanumeric
identifiers, configured business identifiers, and exact reviewed aliases.

### A2. Same-profile invariant

Query tokenization and evidence indexing must expose the same profile
fingerprint. Any fallback to ASCII regex, substring matching, an old index, or
an unpinned model fails the run.

### A3. Re-index without source mutation

Re-tokenize and re-index authorized existing Observations. Do not reparse raw
mail merely to change retrieval tokenization. The migration ledger records old
and new index revisions, observation count, success/failure count, rollback
state, and content-independent public commitments.

### A4. Runtime tests

- mixed Chinese plus protected identifiers;
- profile equality across query/evidence and processes;
- immutable artifact hash drift detection;
- no silent fallback;
- deterministic re-index and rollback;
- denied evidence never tokenized or materialized for the caller.

## 4. Work Package B — Source-Complete Graph Input

Integrate source inventory and Observation completeness rather than relying on
a table-only or document-only projection.

For mail-first validation, preserve:

```text
archive/mailbox/folder/message/thread occurrence identity
sender, recipient, participants, and actor-role evidence
subject and body spans
sent/received/effective timestamps
quoted, forwarded, embedded, reply, and current-state relations
attachments, tables, identifiers, and attachment-origin lineage
version, conflict, correction, and supersession state
permission scope and extraction provenance
```

Produce a source-completeness result that binds the raw/source-system oracle,
Observation manifest, loss taxonomy, and execution fingerprint. Unexplained
loss is a blocking result.

Candidate extraction and entity resolution must preserve source occurrences.
Uncertain merges remain candidates. Matching cannot widen permissions.

## 5. Work Package C — Scoped Ontology

Build from calibration/development evidence only:

```text
small stable core
source-specific mappings
scoped domain terms and frames
reviewed aliases and type mappings
versioned ontology revision
```

Required behavior:

- hard fail-closed validation only for permission, schema/arity, lineage,
  revision pins, canonical-write preconditions, and exact-set coverage;
- inferred type/frame/alias/relation compatibility is soft;
- ontology score is capped and additive;
- mismatch gives no bonus but does not remove an admitted candidate;
- legacy hard type/frame pruning is retained only as a negative ablation.

Tests must include a correct candidate with an inferred mismatch and prove it
remains retrievable.

## 6. Work Package D — Query Execution

### D1. Typed router

Implement:

```text
evidence_lookup
relation_reasoning
exact_set_or_inventory
global_summarization
```

Exact-set language routes deterministically to structured execution.

### D2. Validated plan

A `SemanticQueryPlan` pins actor/scope, source bounds, revisions, entity and
relation slots, allowed paths, temporal policy, budgets, coverage requirement,
output schema, and claim strength. Invalid or scope-widening plans fail closed.

### D3. Strong RAG candidate retrieval

Minimum control:

```text
BM25 lexical retrieval
+ dense retrieval
+ deterministic fusion
+ evidence reranking
```

### D4. Graph-guided expansion

After entity linking, expand only allowed edge kinds and directions within
frozen hop/fan-out/candidate/time budgets. Every hop needs authorized
Observation evidence. Rerank evidence bundles, not isolated chunks.

### D5. Plan repair

Allow at most one bounded repair/retrieval pass for unresolved required slots.
The repair cannot broaden actor, workspace, source, permission, revision, or
claim scope.

### D6. Deterministic executor

Exact set, count, inventory, duplicates, missing items, aggregation, and
definitive negatives require schema-validated enumeration and a coverage
contract. Return `partial` or an equivalent bounded status when coverage is not
complete.

## 7. Work Package E — Controlled LLM Use

Record separate identities for planner, extractor/linker, embedding, reranker,
and answer model. All comparison arms share the same final answer model,
reasoning effort, prompt, output schema, context limit, and decoding settings.

The answer model receives only the validated authorized evidence bundle and
plan. It must cite evidence, expose conflicts/incompleteness, and avoid filling
missing graph slots from pretrained knowledge.

No production answer-model claim is made merely because the historical browser
POC used a Codex sidecar.

## 8. Work Package F — Comparative Evaluation

### F1. Frozen arms

| Arm | Candidate admission | Graph topology | Ontology | Executor |
| --- | --- | --- | --- | --- |
| `strong_rag` | lexical+dense | none | none | only when query class mandates it |
| `rag_entity` | same | entity grouping | none | same policy |
| `rag_candidate_kg` | same | bounded | none | same policy |
| `hybrid_v2_soft` | same | bounded | capped additive | same policy |
| `legacy_hard_gate` | same | bounded | hard prune, negative ablation | same policy |
| `structured_exact` | bounded discovery | optional | optional | mandatory deterministic enumeration |

### F2. Frozen strata

```text
single-document direct lookup
cross-message join
cross-source join
entity ambiguity
current vs historical/superseded state
contradiction and provenance
exact set/count/aggregation
no-answer and near-miss
permission denied
```

### F3. Data split

```text
calibration -> profile and protected vocabulary
development -> thresholds and error analysis
evaluation  -> frozen diagnostic report
holdout     -> one sealed final run
transfer    -> materially different source family
```

The holdout oracle remains outside runtime access. Hashes and counts may enter
safe reports; expected answers and private evidence may not.

### F4. Fairness controls

Every arm shares:

- source and Observation manifest;
- permissions and EffectiveGraphView;
- tokenizer/index profile;
- answer model, prompt, reasoning effort, and decoding;
- context/evidence/token/time budget;
- evaluator, grader, container image, and hardware class.

Any difference is declared as an experimental factor.

## 9. Required Artifacts and Fingerprints

Each accepted report binds:

```text
authority id and state fingerprint
execution fingerprint
source and Observation manifests
tokenizer/profile and index revision
graph and ontology revisions
permission/effective-view revision
planner/extractor/linker/embedding/reranker/answer model ids and hashes
prompt, schema, and generation settings hashes
code commit and dirty-state manifest
container image and package lock
case, oracle, evaluator, and grader manifests
hardware/resource class
result artifact hashes by arm
```

A report missing any required binding is diagnostic and cannot satisfy an
authority gate.

## 10. Metrics

At minimum:

```text
final-answer correctness by stratum
required-evidence Recall@k
evidence-bundle coverage
citation support precision/recall
entity-resolution precision/recall
relation/path precision and unsupported-hop count
temporal/current-state accuracy
exact-set precision/recall/F1 and duplicate rate
no-answer precision/recall and false positives
permission leakage and cross-scope attempts
p50/p95 latency, CPU, peak memory, token and model cost
paired transitions and confidence intervals
```

Do not promote retrieval score alone as final-answer quality.

## 11. Pre-Registered Decision Rules

The hybrid path may replace strong RAG only if:

- graph-required strata improve final-answer correctness by at least 10
  percentage points with a positive paired confidence interval;
- direct lookup regresses by no more than 2 percentage points;
- citation support precision is at least 95%;
- no-answer false-positive performance does not regress;
- permission/private-evidence leakage is zero;
- every asserted graph hop resolves to authorized evidence;
- latency and cost satisfy the frozen operational budget.

Failure keeps strong RAG as the answer default. Diagnose the failed factor
without changing the sealed holdout.

## 12. Stop Conditions

Stop the run and emit no quality claim when:

- target tokenizer/profile or query/evidence fingerprints differ;
- source completeness has unexplained loss;
- an arm sees different evidence, permissions, model, prompt, or budget;
- holdout content influenced construction or tuning;
- graph hops lack source evidence;
- exact-set claims use ranked top-k;
- any private evidence, oracle value, raw path, storage/parser detail, or hidden
  identifier reaches public output;
- execution fingerprint or artifact hash chain is incomplete.

## 13. Rollback

Runtime rollout is versioned and reversible:

1. preserve old index and routing revisions;
2. build the target index side by side from authorized Observations;
3. validate fingerprints and focused tests;
4. canary with diagnostic claims only;
5. switch the route through an explicit configuration revision;
6. roll back to strong RAG on safety, correctness, or operational failure.

Rollback never rewrites source evidence, canonical history, or the sealed
comparison artifacts.

## 14. Verification Sequence

```sh
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```

`--check` must remain valid. Until all gates pass, `--require-ready` is expected
to exit nonzero and prevents methodology-quality claims.

## 15. Completion Boundary

**Implementation completion** requires target runtime, source-complete graph
input, scoped ontology, typed routing, strong RAG control, deterministic exact
execution, generalized tests, frozen diagnostic report, synchronized docs, and
three read-only reviewer agreements.

**Comparative close** additionally requires independent holdout and transfer
results, final-answer review, all quality/safety/cost gates, and
`--require-ready` exit zero.

Issue #56 remains open until comparative close. Issues #33 and #55 are not
active continuation authorities.
