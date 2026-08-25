# Issue #33: KG + Ontology v2 Runtime Migration and Same-Pipeline Evaluation Plan

**Status:** proposed, diagnostic-only POC plan  
**Owner:** Issue #33 / Track 2 KG + Ontology research  
**Scope:** runtime migration and same-pipeline evaluation only  
**Frozen target:** `evidence_to_knowledge_kg_ontology_v2_hybrid_v1`  
**Target tokenizer:** `jieba_sentencepiece_frozen_profile_candidate_admission_v1`  
**Not a v3 proposal:** this plan makes the existing Hybrid KG + Ontology v2
method executable and measurable. It must not introduce, rename, or promote an
ontology v3.

## 1. Claim and safety boundary

This plan responds to Issue #33's runtime/evaluation work package. It is
aligned with the Issue #33 maintainer directions dated **2026-08-10**,
including the separate Track 2 R&D boundary and the storage-engine decision
rule below. That issue comment is the authorization and decision authority;
this document operationalizes it and does not create a competing storage
architecture or declare a selected engine.

The authority check on **August 10, 2026** is valid but blocked:

- current runtime tokenizer: `ascii_identifier_regex_v1`;
- target tokenizer: `jieba_sentencepiece_frozen_profile_candidate_admission_v1`;
- `methodology_ready: false`;
- `python3 scripts/methodology_authority_check.py --require-ready` exits
  nonzero.

Therefore this is a **diagnostic POC and migration plan**, not
methodology-quality UAT, not a KG-versus-ontology superiority claim, not an
Issue #33 close condition, and not a production-readiness claim. A later
promotion gate must rerun `--require-ready`; while it is nonzero, promotion,
methodology-quality UAT, and comparative completion claims stop.

The work is limited to candidate-layer artifacts and authorized, existing
`Observation` snapshots. It must not:

- read MAY private evidence, raw PST files, private manifests, or private
  oracle artifacts;
- parse or re-parse a PST;
- change UAT web, Codex sidecar, private projection bindings, deployment, or
  Track 1 artifacts;
- write canonical graph, canonical type, user graph, grant, or wiki state;
- make production code changes as part of this planning slice.

A remote executor may use only an operator-supplied, explicitly authorized,
read-only observation bundle. Public reports contain aggregates and hashes;
they contain no raw text, query text, identifiers, message IDs, source paths,
or private manifest rows.

## 2. Non-negotiable runtime contract

### 2.1 Frozen tokenizer/profile identity

Create one canonical, deterministic JSON profile (canonical UTF-8 JSON,
sorted keys, no timestamps) whose digest is named
`tokenization_profile_fingerprint`. It must include at least:

| Field | Required binding |
| --- | --- |
| `tokenizer_id` | `jieba_sentencepiece_frozen_profile_candidate_admission_v1` |
| `normalization_id` and hash | Unicode/script normalization implementation and configuration |
| `jieba_version`, dictionary hash, user-dictionary hash | exact frozen Jieba behavior |
| `sentencepiece_version`, model hash, vocabulary hash | exact frozen SentencePiece behavior |
| `protected_identifier_policy_id` and hash | identifier grammar and precedence rules |
| `candidate_admission_policy_id` and hash | scoring features, thresholds, DF/IDF/spread caps, component policy |
| `candidate_schema_version` | candidate record serialization contract |
| `runtime image digest` and source revision | executable provenance |

No mutable user dictionary, learned vocabulary, auto-tuning, current date,
locale-dependent sort, or environment-dependent default may enter a run. A
profile change creates a new fingerprint and invalidates prior indexes; it is
not a silent continuation.

### 2.2 Protected identifiers are admitted before segmentation

Protected identifiers are first-class evidence spans, not ordinary CJK terms.
Before Jieba or SentencePiece segmentation, the policy detects and freezes
exact normalized spans for at least: email addresses, domains, URLs, message
or document IDs, part/SKU/order/invoice/contract-like identifiers, dates,
amounts, and explicitly configured business identifiers.

For every protected span, the candidate-admission output must preserve:

- normalized surface and original span offsets;
- `protected=true`, identifier kind, normalization rule, and source
  observation locator/hash;
- exact-token form used by query and evidence indexing;
- a deterministic admission reason.

Segmentation may produce surrounding lexical candidates but may neither split,
merge, drop, rewrite, nor use a protected identifier as an unbounded phrase
mining seed. A protected span is always admitted as a protected candidate;
normal non-protected candidates remain subject to the frozen profile's
frequency, document/thread spread, entropy/association, role-context,
stop-term, and ambiguity rules.

### 2.3 Same-profile query/evidence invariant

For every arm, query tokenization and evidence tokenization must use the same
*exact* `tokenization_profile_fingerprint`, `normalization_id`, protected-ID
policy, candidate-admission fingerprint, and candidate schema version. “Same
algorithm family” or a compatible profile is insufficient.

The query gateway must obtain the fingerprint from the selected index and
reject a query whose active profile does not exactly equal it. It must not
fallback to regex tokenization, an older index, raw string matching, or
category-only matching. Each returned candidate/evidence record carries the
same profile fingerprint so the evaluator can fail closed on a mismatch.

## 3. Migration: re-tokenize/re-index existing observations, never parse PST

### 3.1 Inputs and immutable ledger

The operator supplies a read-only `ObservationSnapshotManifest` containing
only authorized existing observations and a safe source ledger. The manifest
records snapshot ID, count, ordered observation content hashes, extractor-run
IDs/hashes, authorization scope, and manifest hash. It is a *reference* to
previously extracted observations; it does not invoke an extractor or expose
raw source paths.

The migration accepts only an observation adapter. The execution environment
must have no raw-PST mount and no parser command, parser library entrypoint, or
PST-path argument. The run ledger must record:

```text
raw_pst_read_count = 0
pst_parser_invocation_count = 0
new_extractor_run_count = 0
input_kind = existing_observations_only
```

Any nonzero value is a stop condition.

### 3.2 Deterministic two-pass process

1. **Validate input.** Verify the observation-manifest hash, authorization
   scope, ordering, and uniqueness; reject missing content hashes or duplicate
   observation IDs.
2. **Protect, normalize, tokenize, and admit.** Process observations in
   manifest order with the frozen profile. Persist only candidate-layer records
   with source observation hash/locator and admission/protected-ID reason.
3. **Re-index atomically.** Build a new index namespace keyed by
   `(observation_snapshot_hash, tokenization_profile_fingerprint,
   candidate_schema_version)`. Do not overwrite the regex index.
4. **Verify evidence parity.** Compare processed count, unique observation IDs,
   protected-ID count, admitted/rejected candidate counts, and source-lineage
   completeness to the input manifest. Every output candidate must resolve to
   exactly one authorized observation snapshot entry.
5. **Activate only for an experiment handle.** The evaluator receives the new
   immutable index handle. No shared runtime default changes and no canonical
   state mutation occur in this POC.

A retokenization is valid only when it has an `IndexBuildManifest` with the
input ledger hash, profile fingerprint, candidate output hash, index hash,
ordered observation-count parity, and zero parser/extractor counters.

## 4. Deterministic structured executor boundary

Route queries before KG/ontology scoring:

| Query class | Permitted execution | Completeness claim |
| --- | --- | --- |
| `exact_set` / inventory | schema-validated logical form + deterministic structured executor | only when a governed coverage contract is present |
| evidence lookup / relation navigation | candidate KG ranking plus evidence selection | no complete cardinality claim |
| semantic/frame diagnostic | candidate frame/type/graph scoring | diagnostic only |
| no-answer / denied | deterministic abstention or denial | explicit state and reason |

The exact-set executor must accept a typed, allowlisted logical form; validate
scope, permissions, source coverage, predicates, grouping/deduplication key,
and ordering; then execute deterministic set algebra over governed structural
observations. Its output is stable ordering plus evidence/provenance references
and a claim state. Candidate KG, ontology, and frames may propose a logical
form, grounded candidate IDs, joins, or explanatory traversal, but cannot add
uncovered records or assert a total count.

The executor factor below compares this deterministic boundary to a diagnostic
candidate-ranking path. The ranking path is never credited with a complete
inventory/cardinality answer, even if its text happens to match a gold set.
All permission checks and hard schema invariants remain enabled in every arm;
they are not experimental gates.

## 5. Small real-source same-pipeline POC

### 5.1 POC corpus and split

Use a small, operator-authorized, non-MAY real-source observation snapshot with
at least two source/modalities where available and a pre-registered query
manifest. It must include positive retrieval, exact-set, no-answer/no-match,
permission-denied, identifier-heavy, and CJK/mixed-script cases. The case
manifest is sealed before execution and records case IDs/hashes, query class,
expected outcome class, authorized scope, and required evidence identifiers as
safe hashes.

This POC may use development and evaluation partitions from the same snapshot,
but they must be labeled `development` and `evaluation`, never `holdout`.
Vocabulary, thresholds, topology caps, and the profile are frozen before the
evaluation partition is run. Results are diagnostic only.

An **independent holdout** follows only after this POC: separately sourced or
time-separated observations, independently authored case set, no threshold or
profile tuning after its case hashes are disclosed, and no shared query/evidence
membership with the POC. Historical generated same-corpus cases and fixed
redacted replay are not an independent holdout.

### 5.2 Pre-registered 2 × 2 × 3 × 2 factorial

Run the full 24-arm factorial on one immutable observation snapshot and one
pre-registered query manifest. Every arm receives the same authorized cases,
permissions, source ledger, evaluation code revision, deterministic seed,
container image, and output schema.

| Factor | Levels | Purpose |
| --- | --- | --- |
| **A: candidate admission** | `regex_baseline`; `frozen_jieba_sp_protected_admission` | isolate frozen Jieba + SentencePiece plus protected-ID and admission effect |
| **G: candidate KG topology** | `flat_candidate_ranking`; `topology_capped_candidate_kg` | isolate graph construction, bounded edges, component splitting/community policy, and graph traversal |
| **O: ontology treatment** | `none`; `soft_type_frame_scoring`; `hard_type_frame_gate` | distinguish soft evidence weighting from the explicitly risky hard-gate arm |
| **E: execution** | `candidate_ranked_diagnostic`; `deterministic_structured_executor` | isolate schema-constrained exact-set execution from ranking |

Arm IDs must encode all four factors, for example:

```text
A=frozen_jieba_sp_protected_admission__G=topology_capped_candidate_kg__O=soft_type_frame_scoring__E=deterministic_structured_executor
```

For fairness, each A-level constructs both query and evidence tokens with that
A-level's exact profile. This is not a cross-tokenizer query/evidence
comparison. The `hard_type_frame_gate` may reject only candidate
entity/relation/frame hypotheses after protected-ID admission; it cannot
bypass permission/schema invariants, mutate canonical state, or suppress
protected identifiers. It is expected to be an ablation arm, not a default.

Analyze main effects and interactions only against arms that differ in the
named factor and share the other three levels. Report `O=soft` and `O=hard`
separately; never combine their results into an “ontology” average that masks
false rejects.

## 6. Required metrics and report schema

All reports must bind `observation_snapshot_hash`, case-manifest hash,
profile/index/graph/executor fingerprints, arm ID, code revision, image digest,
seed, start/end timestamps, and artifact hashes. Report primary retrieval only
on authorized positive-retrieval cases. Never count automatically denied cases
as retrieval successes.

| Section | Required measurements |
| --- | --- |
| `positive_retrieval` | case count, recall@k, precision@k, MRR where applicable, required-evidence coverage, and confidence intervals/bootstrap method if sample size permits |
| `exact_set` | exact-set match rate; set precision/recall/F1; missing/unexpected counts; duplicate rate; coverage-contract present/absent; executor claim-state distribution. Candidate-ranked arms report `complete_cardinality_claim=false`. |
| `no_answer_or_no_match` | correct abstentions, false answers/false matches, abstention precision/recall, and reason-code distribution; report separately from positives. |
| `hard_gate_false_reject` | required candidate/evidence/frame admitted upstream but rejected by `O=hard`; count, rate, affected query class, and whether it is a protected-ID or exact-set dependency. |
| `frame_type_quality` | measured precision/recall/F1 only if independently labeled; otherwise `not_measured` with no inherited retrieval lift. |
| `evidence_span_quality` | evidence support precision/recall and locator/hash completeness if independently labeled; otherwise `not_measured`. |
| `graph_topology_diagnostics` | nodes, edges, candidate edge reasons, components, largest-component size/share, degree percentiles, isolated-node share, cross-scope edges rejected, community/splitting actions, and per-query reachable-component sizes. |
| `latency_and_resource_use` | per stage and end-to-end wall time; p50/p95 across repeated warm/cold runs; CPU time; maximum RSS; input observation/candidate/edge counts; image/runtime identity. Do not generalize small-POC numbers to enterprise scale. |
| `permission_safety` | allowed/denied counts, unauthorized-evidence retrievals, unauthorized provenance disclosures, cross-scope edge attempts, redaction failures. Any safety failure is explicit, never converted to a successful abstention. |
| `provenance` | every returned evidence item resolves to observation hash, locator hash, extraction-run hash, profile fingerprint, candidate ID, graph edge/frame IDs where used, and authorization decision. Record missing/ambiguous lineage count. |

The report additionally names the case partition as `development` or
`evaluation`; it must never call same-corpus generated cases “holdout.” Surface
forms and raw evidence may appear only in the authorized local artifact where
permitted; shared artifacts use safe IDs/hashes and aggregate counts.

## 7. Reproducible remote execution protocol

The following is the required operational sequence for the #33 implementation
owner on another computer. `issue33_runtime_eval` below is the planned,
containerized evaluator interface; it must be implemented and code-reviewed
before use, not improvised in a shell session.

1. **Clean state.** Start from a clean clone at a recorded commit. Record
   `git rev-parse HEAD`, `git diff --check`, the container image digest, and
   dependency lock hashes. Do not reuse a mutable local index or cache.
2. **Authority preflight.** Run:

   ```sh
   python3 scripts/methodology_authority_check.py --check
   python3 scripts/methodology_authority_check.py --require-ready
   ```

   Record both outputs. The second command is currently expected to exit
   nonzero. That blocks promotion/UAT/comparative completion, but it does not
   erase a clearly labeled diagnostic POC result.
3. **Receive safe inputs.** Mount only the operator-authorized, read-only
   observation snapshot and sealed case manifest. Do not mount raw PST,
   private oracle, or MAY material. Verify their supplied hashes before work.
4. **Freeze and validate profile.** Materialize the canonical profile JSON;
   hash it; execute protected-ID fixtures (including CJK/mixed text); and
   fail if normalized spans or token signatures differ from the fixture.
5. **Retokenize and re-index.** Invoke the planned runner with
   `--input-kind existing-observations-only`, a parser-denial guard, the
   snapshot manifest, and the frozen profile. Verify count/lineage parity and
   zero parser/extractor counters before any evaluation.
6. **Run all factorial arms.** Each arm writes only to a new immutable
   experiment namespace. Execute repeated cold and warm runs in randomized arm
   order with the same seed policy; do not tune after evaluation starts.
7. **Validate artifacts.** A validator rejects missing fingerprints, mismatched
   query/evidence profile fingerprints, incomplete lineage, private fields in
   shareable reports, unauthorized evidence, or a claim-state/cardinality
   violation.
8. **Restart reproduction.** Destroy the experiment container and ephemeral
   index namespace; rebuild from the same clean commit and inputs; rerun the
   profile, re-index, and factorial. Compare deterministic artifact hashes and
   metric outputs. Environmental metadata may differ only in predeclared
   nonsemantic fields such as host ID and timestamps.
9. **Publish only safe summary.** Publish aggregate report, manifest hashes,
   command/image identity, validation result, and explicit blocked authority
   state. Retain authorized detailed artifacts under the operator's access
   boundary; do not copy them into the repository or Track 1.

## 8. Artifact manifest and hash chain

Use SHA-256 for every artifact. Parent manifests include child hash lists in
canonical order, giving this chain:

```text
observation_snapshot_manifest
  -> frozen_tokenization_profile
  -> retokenization_candidate_manifest
  -> index_build_manifest
  -> per-arm graph/executor manifest
  -> sealed_case_manifest
  -> per-arm raw-safe result
  -> aggregate_same_pipeline_report
  -> reproducibility_comparison_report
```

Minimum manifest fields:

```json
{
  "artifact_type": "IndexBuildManifest",
  "schema_version": 1,
  "source_revision": "<git commit>",
  "container_image_digest": "sha256:<digest>",
  "observation_snapshot_hash": "sha256:<digest>",
  "tokenization_profile_fingerprint": "sha256:<digest>",
  "candidate_manifest_hash": "sha256:<digest>",
  "index_hash": "sha256:<digest>",
  "input_kind": "existing_observations_only",
  "raw_pst_read_count": 0,
  "pst_parser_invocation_count": 0,
  "new_extractor_run_count": 0
}
```

The aggregate report must contain the authority check's
`authority_state_fingerprint` and `execution_fingerprint` as observed, rather
than asserting that a historical experiment represents the new runtime.

## 9. Promotion gates, rollback, and stop conditions

### 9.1 Gates

| Gate | Required result | Allows | Does **not** allow |
| --- | --- | --- | --- |
| G0: authority visibility | `--check` valid; blocked claims/fingerprints copied verbatim | diagnostic planning/POC | readiness claim |
| G1: frozen profile | two clean builds produce identical profile hash and protected-ID fixture signatures | same-profile reindex POC | profile/default promotion |
| G2: source-preserving migration | manifest parity; all parser/extractor counters zero; full candidate provenance | same-pipeline factorial | raw-source/PST claim |
| G3: safety and determinism | zero unauthorized evidence/provenance disclosures; zero profile mismatch; clean-build/restart result agreement | small POC report | production or methodology-quality UAT |
| G4: diagnostic usefulness | no-answer/permission non-regression versus the matched regex control; topology remains within preregistered caps; soft and hard arms reported separately | independent-holdout preparation | ontology promotion |
| G5: independent holdout | independently sourced/sealed holdout; predeclared thresholds met; hard-gate false rejects acceptable under its explicit policy; all semantic labels independently governed | Issue #33 review packet | broad methodology completion |
| G6: authority promotion | all authority gates, including execution-bound reports, target runtime alignment, same-pipeline real-source ablation, raw-oracle completeness, and end-answer acceptance pass; `--require-ready` exits zero | methodology-quality UAT consideration | automatic production rollout |

No G0–G5 result changes the current blocked authority. G6 requires separate
review and is outside this plan's POC.

### 9.2 Immediate stop conditions

Stop the affected run, preserve only safe diagnostic metadata, and do not
promote its artifacts if any of the following occurs:

1. raw PST/MAY/private-oracle access, parser invocation, or new extraction;
2. missing/mismatched query/evidence profile fingerprint or input-manifest
   hash;
3. protected identifier split, loss, merge, or normalization drift;
4. any unauthorized evidence retrieval/disclosure, cross-scope leakage, or
   missing provenance for a returned item;
5. exact-set cardinality/completeness claim emitted without a valid governed
   coverage contract;
6. hard-gate rejection of a required protected identifier or required evidence;
7. no-answer case converted into an unsupported positive answer;
8. topology collapse: largest component exceeds the preregistered cap of the
   smaller of **5% of nodes** or **five times** the matched regex-control
   largest-component share; or required component-splitting diagnostics are
   absent;
9. max RSS exceeds the declared container limit, p95 end-to-end latency exceeds
   twice the matched control without an attributable nonsemantic I/O exclusion,
   or clean-build/restart semantic outputs differ;
10. missing hash-chain link, noncanonical report JSON, unsealed case manifest,
    post-evaluation tuning, or private field in a shareable artifact.

### 9.3 Rollback

This POC has no canonical or production state to roll back. On a stop:

- revoke the experiment handle and delete only newly created candidate/index/
  graph namespaces for that run;
- retain the safe stop report, manifests, hashes, and counter values for audit;
- leave the current regex runtime/index and all Track 1 systems untouched;
- label the affected arm/result `invalid` rather than silently dropping it;
- require a new profile or corrected implementation and a fresh sealed case
  manifest for a retry. No threshold relaxation or manual output repair is
  permitted.

## 10. Expected decision after the small POC

The POC chooses only one of these next actions:

1. **Proceed to independent holdout:** G0–G4 pass and the frozen-profile,
   topology-capped, soft-scoring configuration has a useful, safety-preserving
   diagnostic signal.
2. **Revise candidate admission/topology:** raw lexical components collapse,
   no-answer behavior regresses, protected-ID behavior drifts, or profile
   reproducibility fails. Keep v2 frozen; change the upstream candidate policy
   under a new fingerprint and rerun from existing observations.
3. **Keep hard gate experimental or reject it:** any material false-reject
   signal appears. Do not make it a default merely because it reduces false
   positives.
4. **Stop Track 2 POC:** a safety/provenance/private-boundary stop condition
   occurs, or G6 remains blocked after all admissible diagnostic work. Escalate
   as an authority/implementation issue rather than claiming a methodology
   result.

The plan deliberately separates candidate admission, graph topology, soft
ontology evidence, hard ontology gating, and deterministic exact-set execution.
It retains Hybrid KG + Ontology v2 as the target, produces evidence suitable for
Issue #33 review, and makes no claim that the methodology is ready today.

## 11. Storage-engine same-contract benchmark and promotion gate

This bounded Track 2 benchmark implements the Issue #33 maintainer direction
dated **2026-08-10**. PostgreSQL remains the current implementation and
specification baseline. No benchmark has run, and this plan does not select
PostgreSQL or Neo4j as a winner.

### 11.1 Purpose, current gap, and exclusions

This is a storage POC, not a second implementation of FormOwl. It answers only:

```text
Which engine implements the same bounded, governed graph-storage contract
more effectively under one sealed workload?
```

The current PostgreSQL code provides migration, metadata, transaction, grant,
and pgvector adapter contracts, but it does **not** yet provide a complete
PostgreSQL canonical-graph/lifecycle/traversal repository. The current
file-backed canonical and projection stores are useful behavioral references,
not a valid PostgreSQL benchmark implementation. Therefore the benchmark must
introduce a small, benchmark-only storage port and implement that port once per
engine. It must not compare a working Neo4j graph implementation with
PostgreSQL JSON-record writes alone.

The benchmark is explicitly excluded from:

- Track 1 UAT, MCP, sidecar, web, deployment, and MAY evidence work;
- raw source access, PST parsing or reparsing, private manifests, and oracle
  artifacts;
- tokenizer/model tuning, candidate-admission evaluation, semantic-quality
  claims, or KG-versus-ontology comparisons;
- production migrations, a permanent dual-write path, or a new public storage
  API; and
- canonical `SPEC.md`, architecture, or infrastructure changes before a
  subsequent, separately reviewed decision packet authorizes them.

Each engine loads its own disposable state from the sealed package, executes
the same work, exports a safe semantic digest, and is destroyed. Neither engine
may read the other engine, replay its change stream, or become a live mirror.

### 11.2 One storage-neutral benchmark port

Define a private-to-the-benchmark `GovernedGraphBenchmarkStore` contract. The
shared evaluator speaks only this contract; SQL and Cypher remain adapter
implementation details and never enter MCP-facing surfaces or public reports.

| Operation | Required behavior | Explicit non-goal |
| --- | --- | --- |
| `stage_candidate_batch` | Validate and atomically stage a candidate node/relation batch with scope, observation-hash, profile, and ontology pins. | Candidate generation, NLP, or source extraction. |
| `reviewed_commit_with_lifecycle` | In one transaction, validate review/policy pins, write the canonical revision and its reviewed members, write one lifecycle event where requested, and append one success audit record. | Unreviewed canonical writes or automatic merge decisions. |
| `effective_view` | Return only actor-visible canonical nodes/relations plus opaque provenance references under the pinned grant/time decision. | Raw evidence access or an access grant inferred from graph matching. |
| `bounded_traverse` | Execute the formal bounded traversal in §11.4 and return a canonical ordered result. | Unbounded graph analytics, recommendation, or engine-specific path semantics. |
| `resolve_lifecycle` | Resolve historical IDs through the pinned lifecycle chain with the existing split/merge/archive/deprecate/supersede/equivalence meanings. | Deleting historical identities. |
| `structured_set_handoff` | Return permission-filtered, deterministically sorted opaque structural row references for the common exact-set executor. | NLP planning, ranking-derived membership, or a complete claim without the coverage pin. |
| `semantic_state_digest` / `backup_restore` | Produce a canonical safe-state digest, back up the disposable namespace, restore it, and prove semantic equality. | Backup of raw sources, credentials, or production state. |

The port's request and response records must use canonical UTF-8 JSON, sorted
keys, stable opaque IDs, and an explicit schema version. Returned identifiers
are sorted by the contract, not by the engine's incidental row/path order.
Every result is validated by the same pure-Python oracle-free comparator before
timing or promotion logic reads it.

The PostgreSQL and Neo4j adapters may use native query capabilities internally,
but must not add a query class, index, inference rule, traversal convention, or
visibility rule that is unavailable to the other adapter. The evaluator must
not accept raw SQL, Cypher, connection strings, source locators, or arbitrary
engine options.

FormOwl's governed actor/scope authorizer is the sole authority for whether a
result may be materialized. In particular, Neo4j property-based RBAC is
defense in depth only: it may add a second deny barrier, but it must not be the
sole deny path or change an allow into a FormOwl permission decision. The
authorizer must make and record its decision against the sealed, current
actor/scope/grant contract before the adapter may materialize a node, edge,
path, lineage field, count, or exact-set row.

### 11.3 Sealed package and fixture

The first implementation uses a deterministic, source-free fixture generator,
not a PST or a private observation export. It produces two package profiles
from the same generator and contract:

| Profile | Purpose | Fixed minimum content |
| --- | --- | --- |
| `conformance_r1` | All validation, denial, rollback, lifecycle, and restoration faults. | 32 staged candidates, 48 staged relations, 16 reviewed canonical members, 24 canonical relations, 6 valid lifecycle events, 12 structured rows, 3 actor/grant profiles, and 2 isolated scopes. |
| `workload_r1` | Modest graph-shaped latency/resource workload, still disposable and small. | 1,024 staged candidates, 4,096 staged relations, 256 reviewed canonical members, 1,024 canonical relations, 12 lifecycle chains, 128 structured rows, the same 3 actor/grant profiles, and 2 isolated scopes. |

The exact generator revision, count values, fixture seed, and every expected
semantic result hash are sealed before either engine starts. These profiles
exercise governed storage behavior only. They cannot establish a real-source
methodology result or select an engine merely because a synthetic traversal is
fast.

The canonical `StorageEngineBenchmarkPackage` must contain at least:

```text
benchmark_schema_version and fixture_generator_revision/hash
fixture_profile, seed, fixture_content_hash, and expected-result hashes
observation_snapshot_manifest_hash and ordered opaque observation-content hashes
input_kind=synthetic_governed_fixture_only
raw_pst_read_count=0, pst_parser_invocation_count=0, new_extractor_run_count=0
tokenization_profile_fingerprint, candidate-admission profile hash,
  candidate schema version, and candidate graph manifest/hash
ontology revision ID/hash, policy-pin manifest/hash, and reviewed decision hash
actor/grant/scope decision manifest/hash and fixed authorization timestamp
permission-property adversarial manifest/hash and FormOwl authorizer-trace hash
coverage/completeness contract manifest/hash and deterministic executor hash
sealed query manifest/hash, traversal-bound manifest/hash, and fault manifest/hash
adapter contract hash, evaluator source revision/hash, dependency lock hash,
  container-image digests, and resource-profile hash
authority_state_fingerprint and execution_fingerprint observed from --check
```

The package also records the expected blocked authority state:
`methodology_ready=false`, current tokenizer
`ascii_identifier_regex_v1`, target tokenizer
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`, and an expected
nonzero `--require-ready` result. A storage result must carry this state
forward; it cannot replace it.

The package is canonicalized and SHA-256 hashed before either load. The loader
rejects a missing field, a different fixture profile, a count/hash mismatch,
nonzero parser/extractor counter, a private/raw field, or a package that was
changed after the first engine began. A package mismatch invalidates **both**
engine results rather than favoring the engine that happened to run first.

### 11.4 Predeclared query and traversal suite

The sealed query manifest contains the following classes. Every class has a
stable case ID, request hash, actor/scope decision hash, expected status,
expected ordered result hash, expected provenance hash, and, where relevant,
expected pre/post semantic-state hash.

| Class | Contract exercise | Included result checks |
| --- | --- | --- |
| `candidate_stage_write` | Valid idempotent stage batch and rejected cross-scope/invalid-lineage batch. | Returned stage digest; rejected batch leaves the stage digest unchanged. |
| `review_commit` | Reviewed candidate-to-canonical commit, revision creation, and success audit. | Member/revision/audit digest; no direct unreviewed write capability. |
| `effective_view_allow` / `effective_view_deny` | Same graph under a valid grant and a denied actor. | Allowed opaque IDs; denied result is non-enumerating and reveals no hidden endpoint, count, or provenance. |
| `property_permission_adversarial` | Permission-property variants: missing, explicit `null`, wrong type, nonmatching value, a matching value changed before materialization, and matching value. | The first five variants are denied by FormOwl before materialization; adapter materialization-call count is zero and no node/edge/path/lineage/count payload is emitted. The matching variant is allowed only when the complete current FormOwl actor/scope/grant contract also passes. |
| `bounded_traversal_allow` / `bounded_traversal_deny` | Permission-filtered relation navigation from an allowed and denied start. | Ordered node/edge/path digest; no hidden path is used as an intermediate result. |
| `lifecycle_resolution` | Historical-ID resolution through each valid lifecycle kind and a multi-hop split-then-merge chain. | Status, current IDs, and lifecycle-event IDs exactly match the shared contract. |
| `structured_set_handoff` | Coverage-pinned structural filtering followed by the common deterministic executor. | Ordered opaque row IDs, dedup/order behavior, coverage pin, executor result fingerprint, and no graph-derived membership. |
| `schema_and_ontology_reject` | Unsupported schema, stale ontology revision, illegal type mapping, bad policy pin, and malformed plan. | Closed generic rejection, no result payload, and no state mutation. |

`bounded_traverse` is deliberately formal rather than engine-defined:

```text
direction                  = outgoing
maximum_hops               = 2
per_frontier_fanout        = 4
maximum_returned_paths     = 32
cycle policy               = no repeated node in a path
visibility check           = start node, every edge, and every target node
ordering                   = (hop_count, target_node_id, incoming_edge_id)
timeout                    = 1 second per traversal request
cross-scope relation       = rejected at stage/load time
```

Both adapters may use native recursive or graph traversal queries, but the
contract defines the resulting breadth-first set and order. The shared
comparator rejects duplicate paths, cycle leakage, over-cap output, different
ordering, an unauthorized intermediate, a timeout reported as success, or a
denial that reveals whether a hidden node exists.

`structured_set_handoff` is intentionally a handoff, not a second storage
engine query language. It accepts only a sealed typed fixture predicate and
coverage-contract ID, returns permitted opaque rows in the declared
deduplication/order, and passes them to one common deterministic executor.
Neither storage adapter may use candidate rank, ontology confidence, aliases,
or a graph path to add a row or strengthen a completeness claim.

The property adversarial suite is a required governance test, not an
engine-specific result feature or performance sample. The same six logical
cases are represented in both adapters. For Neo4j, they are additionally run
with any configured native property-based RBAC policy enabled; its result may
only corroborate the FormOwl decision. If that Neo4j feature is unavailable in
the pinned edition, the FormOwl cases still run and native RBAC is reported
`not_configured`, never treated as a waived permission check. The mutable case
starts with a matching value, changes it after planning but before
materialization, forces current authorization re-evaluation, and must deny.

### 11.5 Hard invariants, provenance, and fault injection

The following are hard invariants. A failure makes the affected comparison
`invalid`; performance values from that run are not eligible for a decision.

| Invariant | Required evidence |
| --- | --- |
| Semantic equality | Every valid case has the expected ordered result, status, provenance digest, and post-operation semantic-state digest in both engines. |
| Permission safety | Unauthorized retrievals, hidden-endpoint disclosure, cross-scope edge acceptance, raw locator exposure, missing fixed-time grant validation, and all missing/null/wrong-type/nonmatching/mutable property cases equal zero. The matching property case still requires FormOwl actor/scope/grant approval. |
| Provenance completeness | Every visible result resolves to the sealed observation hash, extractor-run hash, candidate ID, ontology revision, review decision, scope decision, and coverage contract when applicable. |
| Governed atomicity | Canonical members, revision, lifecycle event, and success audit commit together or not at all. Candidate staging is separately atomic. |
| Schema/ontology enforcement | Bad schema, stale revision, illegal type map, and malformed query plan fail closed with no mutation. |
| Traversal bounds | Hop, fan-out, path, cycle, scope, timeout, and ordering rules in §11.4 hold for every response. |
| Restore equality | Backup then restore returns exactly the same canonical semantic-state digest and valid-result digests as the pre-backup state. |
| Determinism | A clean rebuild from the same package produces the same semantic outputs and state digests. Only declared timestamps, host identity, and elapsed-resource fields may differ. |

The fault manifest must inject at least the following failures independently in
both adapters:

1. invalid candidate batch after validation begins;
2. review decision rejected or absent before a canonical write;
3. injected failure after canonical-member staging but before revision write;
4. injected failure after revision write but before lifecycle/success-audit
   completion;
5. connection loss/driver exception while the commit transaction is open,
   followed by reconnect and state-digest verification;
6. duplicate prior lifecycle ID and a lifecycle cycle attempt;
7. stale ontology revision, bad policy pin, and malformed typed plan;
8. denied actor, expired/revoked/wrong-scope grant, and an attempted
   cross-scope relation; and
9. missing, explicit `null`, wrong-type, nonmatching, mutable, and matching
   permission-property values, with a trace that denied variants make zero
   adapter materialization calls; and
10. traversal fan-out/path/time limit exhaustion.

For faults 1–9, the relevant pre-fault semantic-state digest must equal the
post-fault digest. There must be no success audit for a failed transaction.
The runner may record a safe external failure event in its operational ledger,
but it must not call a failed transaction a committed graph event. Fault 10
must return the predeclared bounded failure/partial status without leaking
unvisited nodes and without mutation.

### 11.6 Resources, cold/warm protocol, and measurements

Use one idle Docker-capable host, two independent disposable local volumes, a
private benchmark network, and no mounted production data. The sealed
`resource_profile_r1` applies to both engines:

```text
CPU limit                  = 2 logical CPUs
memory limit               = 4 GiB
memory + swap limit        = 4 GiB
PID limit                  = 256
GPU                        = forbidden
benchmark workers          = 1
storage                    = local Docker-managed volume on the same host class
input package              = read-only mount
network                    = private benchmark network only
```

The engine-image digest, driver version, and all engine settings are part of
the sealed resource profile. Each engine may have the minimum vendor-required
memory setting to stay within the common cgroup limit, but no tuning, query
hints, extra replicas, full-text/vector/analytics index, or engine-specific
feature may be enabled after the profile is sealed. Both slices receive only
the logically equivalent ID, scope, relation-endpoint, lifecycle-prior-ID, and
structured-handoff indexes required by the contract.

The runner performs three independent clean rebuild cycles. For each cycle it
uses a counterbalanced engine order and a sealed randomized query order:

1. create a fresh engine namespace and load the sealed package;
2. record provision/load/ready time separately;
3. run five **cold** complete-sequence samples, each from a fresh
   provision/load/first-connection state;
4. run one unmeasured normalization pass to establish the declared warm state;
5. run five **warm** complete-sequence samples; reset the disposable namespace
   to the baseline before every write-bearing sequence;
6. run the fault suite outside the timing samples;
7. back up, restore to a fresh namespace, validate semantic equality, then
   destroy both namespaces and volumes.

This gives fifteen cold and fifteen warm samples per engine/query class across
the three rebuild cycles. Report cold and warm values separately; never hide
provisioning/load time inside query latency and never use an unmeasured engine
warm-up that changes data or indexes.

Measure monotonic wall time for every operation and whole-workload pass, CPU
time where the container runtime exposes it, and cgroup `memory.peak` (or
equivalent per-container maximum RSS). Record p50, p95 using the declared
nearest-rank method, median, raw safe numeric samples, input counts, and the
resource-observation method. Missing or incomparable memory/CPU telemetry
produces the non-promotional `invalid_comparison` verdict; it must not be
silently relabeled as a functional comparison result.

### 11.7 Operational ledger and safe reports

The evaluator writes one append-only, safe `StorageEngineOperationalLedger` per
engine/cycle. Each entry contains only:

```text
benchmark package hash, resource-profile hash, adapter/image/driver identity
phase: provision | schema-load | package-load | ready | cold | warm |
  fault | backup | restore | validate | teardown
start/end timestamps, duration, status, generic reason code, and retry count
semantic-state/result hashes, migration/schema hash, backup/restore hash
resource measurements, automatic/manual intervention count, and safe log hash
```

The ledger must specifically account for provisioning, temporary schema or
database setup, package load, migration/DDL, index creation, readiness,
backup, restore, validation, teardown, retry, and any manual intervention.
It must not contain DSNs, credentials, raw SQL/Cypher, raw evidence, source
paths, message IDs, or command-line environment values.

The final safe comparison report contains both sealed input hashes, every
hard-invariant status, per-class semantic digests, cold/warm/resource summaries,
operational-ledger summaries, rebuild/restore outcomes, declared threshold
evaluation, and the carried-forward blocked methodology authority state. It
must distinguish:

```text
invalid_comparison
postgresql_baseline_retained
neo4j_projection_only
neo4j_authority_eligible
decision_blocked
```

`invalid_comparison` is reserved for a sealed-input, contract, or comparable
telemetry failure. A hard governance/correctness failure after valid execution
retains PostgreSQL with an `authority_ineligible` reason code. No verdict means
that a migration happened. Public reports remain aggregate/hash-only even
though the first fixture is source-free.

### 11.8 Predeclared promotion thresholds

PostgreSQL stays the baseline unless all of the following conditions hold. No
weighted score may override a hard invariant.

1. **Both adapters are valid.** All hard invariants in §11.5 pass in all three
   clean rebuild cycles, and every expected semantic digest agrees across both
   engines. A PostgreSQL adapter failure is an implementation/contract defect,
   not evidence that Neo4j wins.
2. **Neo4j is materially better on the whole governed workload.** In **every**
   clean-rebuild replicate, Neo4j's end-to-end p95 for the complete warm
   sequence is at most `0.75 ×` PostgreSQL's corresponding p95: at least 25%
   lower. The complete sequence contains each valid class in §11.4 once; it is
   not a traversal-only microbenchmark.
3. **All declared operational SLOs and budgets hold.** Both engines meet every
   sealed per-query SLO, clean rebuild/restore SLO, and the declared
   container/operations/TCO budget. Neo4j has no failed automatic provision,
   restore, or teardown step, no unresolved edition/entitlement blocker, and
   zero unplanned manual interventions.
4. **Telemetry is comparable and the container limit is respected.** Maximum
   RSS/CPU telemetry is complete and comparable for every run, neither engine
   breaches the common 4 GiB cgroup memory cap or its declared resource SLO,
   and the safe report records the raw measurements. There is deliberately no
   fixed relative-RSS cutoff: the sealed container limit, workload SLOs, and
   TCO/operations budget decide acceptability.

If all four conditions hold, report
`neo4j_authority_eligible`. Only then may a separate, reviewed
architecture/specification and migration issue propose Neo4j as the authority
store. That later issue must define canonical-data migration, rollback,
operations, access control, backup, MCP boundaries, and the fate of PostgreSQL;
this benchmark does none of those things.

If hard invariants pass but only the bounded traversal class meets a material
advantage, report `neo4j_projection_only`: PostgreSQL remains the
authority and any later Neo4j use must be rebuildable from PostgreSQL, with no
dual-write. If no material threshold is met, or a valid comparison has an
`authority_ineligible` hard-gate reason, report
`postgresql_baseline_retained`. If required operational, entitlement, or
TCO-budget evidence is absent, report `decision_blocked`. These are storage
decisions only and cannot override blocked tokenizer alignment, source
completeness, same-pipeline ablation, real-answer acceptance, or
`--require-ready`.

### 11.9 Minimal implementation handoff

The earlier nine-path handoff can be reduced without losing the vertical slice.
Use five required benchmark files:

```text
python/formowl_graph/storage/benchmark_contract.py
  - sealed package/result records, deterministic source-free fixture generator,
    pure comparator, state digests, and port protocol
python/formowl_graph/storage/benchmark_postgres.py
  - disposable-schema PostgreSQL adapter; no production migration
python/formowl_graph/storage/benchmark_neo4j.py
  - disposable-database Neo4j adapter; no MCP exposure
scripts/issue33_storage_engine_benchmark.py
  - package sealing, direct disposable-Docker orchestration, cgroup measurement,
    safe report, and operational-ledger validation
tests/test_issue33_storage_engine_benchmark.py
  - contract, fixture, adapter fault/permission, and opt-in live two-engine
    tests in separate test classes
```

The fixture is generated canonically by the contract module; a second tracked
JSON fixture would duplicate the source of truth. A shell wrapper is likewise
unnecessary because the Python runner can invoke the pinned Docker commands and
collect their cgroup data directly. If the dev environment lacks a pinned
Neo4j driver/client, `pyproject.toml` and `containers/dev/Dockerfile` are the
only two conditional environment changes. Thus the smallest fair slice is five
new benchmark files, or seven when the dependency must be installed.

The implementation must not add a production `formowl_graph` migration, alter
the public storage exports, edit UAT/deployment code, introduce a live Neo4j
Compose service, or change Track 1/private artifacts. It should use the
existing lifecycle, ontology, permission/effective-view, provenance, and
PostgreSQL transaction contracts as behavioral references, with focused
benchmark tests before any live two-engine run.

### 11.10 Preconditions and decision blockers

The following are known pre-execution requirements, not reasons to infer a
winner:

1. Neo4j is not currently pinned in the repository's dependency or Compose
   configuration. The implementation owner must pin a compatible Neo4j server
   image digest and client-driver version in the benchmark-only harness before
   package sealing.
2. A Docker-capable dev/benchmark host must expose per-container cgroup
   CPU/memory measurements and local disposable volumes. If it cannot, the
   live engine comparison may produce conformance evidence only, not an
   authority-store decision.
3. The existing PostgreSQL graph adapter is intentionally incomplete for this
   workload. The benchmark PostgreSQL slice must implement the port above
   rather than claiming that `PostgreSQLMetadataRepository` already measures
   reviewed canonical commits or bounded traversal.
4. The source-free fixture validates equal storage semantics and operational
   behavior, but does not prove enterprise-scale capacity or methodology
   quality. A later authority-migration proposal must state this limitation
   rather than extrapolating it.
5. `python3 scripts/methodology_authority_check.py --check` remains valid but
   blocked. Its nonzero `--require-ready` result prevents methodology-quality
   UAT and method-comparison claims regardless of either storage result.
