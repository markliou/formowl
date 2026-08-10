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

This plan responds to Issue #33's runtime/evaluation work package. `gh issue
view 33` was unavailable when this plan was written, so the issue boundary is
read from `docs/agent-goals/dual-track-uat-kg-coordinator.md`.

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
