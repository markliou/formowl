# Mail Ontology-Native Factorial Design

Date: 2026-07-07

Status: historical pre-registration design, superseded for active retrieval by
the source-neutral `CandidateEvidenceIndex` method in `SPEC.md` Section 9.7.2
and `docs/kg-research-method.md`. Keep this file as the design record for the
older ontology-native factorial question; do not treat its 20/30/29 scores or
planned grid as the current FormOwl retrieval method.

## Default Candidate Evidence Retrieval

Any rerun must onboard the current logical source item method first: trusted
access before query vocabulary, explicit context/time admissibility,
conjunctive anchors within one source, and capped additive ontology reranking.
The node/component grids and late ontology hard gates below are historical
ablation definitions only. They must not be used as the default harness or as
current gold.
The rerun must use an index-owned `CandidateEvidenceTextPolicyRuntime` for the
Unicode-NFKC/protected-ASCII/Jieba/corpus-bound SentencePiece/frozen-profile
stack and exact admission/model/corpus SHA-256 hashes. The binding also pins
the runtime id and tokenizer implementation hash; runtime code mismatch fails
closed. Default callers pass query text only; raw tokens and free-form hashes
are not onboarding evidence. Access and explicit context/time admissibility
precedes tokenization. Every operator arm below must enter through
`retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Why This Rework Exists

The #21 hard-domain mail benchmark currently has these measured results over
the same operator-provided full-PST preserved work directory:

| Arm | Score |
| --- | ---: |
| Baseline retrieval | 20/100 |
| KG-only candidate components | 30/100 |
| Broad-domain ontology reranker | 29/100 |
| KG-first 326 ordered ontology-operator factorial best arm | 30/100 |

The 326-arm KG-first factorial result is valid only as a stress test of
ontology-as-reranker over existing KG components. It is not a fair test of
ontology-native retrieval because the evidence representation is already fixed
before ontology is applied.

Four read-only math/research subagents reviewed the design:

- Jason: `REWORK`. Use typed proof graphs, not precomputed token/thread
  components. Thread membership is one relation feature, not a component union.
- Maxwell: `REWORK`. Encode deterministic mail-native frames and typed
  relations before graph fusion.
- Hypatia: `ACCEPTABLE` only with pre-registration. Treat 326+ arm searches as
  exploratory unless a confirmatory holdout or correction is used.
- Planck: `REWORK`. Replace arbitrary ordered permutations with staged
  encoders plus a small hyperparameter grid. Recommended 324 main arms plus 8
  controls.

## Ontology-Native Representation

Build the corpus state before opening the private hard-case manifest.

### Nodes

- Segment nodes: existing visible `email_body_segment` observations with
  observation id, message/thread locators, timestamp, and token features.
- Entity/mention nodes: typed candidates anchored to segments. Core supertypes
  include `Person`, `Organization`, `Project`, `Artifact`, `Document`,
  `Event`, `Concept`, and `Location`.
- Mail-native frame nodes: `Decision`, `Commitment`, `Request`, `Blocker`,
  `Risk`, `StatusUpdate`, `Approval`, `Rejection`, `Deadline`, `Conflict`,
  `OwnershipAssignment`, `Shipment`, `Payment`, `Reconciliation`,
  `EngineeringChange`, and `DocumentReference`.
- Value nodes: normalized dates, amounts, quantities, currencies, units,
  deadlines, and ETAs.
- Message context nodes: message/thread/occurrence carriers. These are
  provenance context, not business truth.

Concrete identifiers such as PO, SKU, invoice, work-order, quote, shipment,
or contract numbers are artifact/entity candidates with hashed normalized
identifiers. They must not become ontology type names.

### Slots

Frames may carry:

- `actor`, `owner`, `requester`, `approver`, `assignee`
- `vendor`, `supplier`, `customer`, `buyer`, `partner`
- `target`, `artifact`, `project`, `reason`, `status`, `polarity`
- `date`, `amount`, `quantity`, `currency`, `unit`
- `source`, `recipient`, `sent_at`

### Relations

Candidate relations include:

- `has_role(frame, entity)`
- `about_artifact(frame, artifact)`
- `has_date(frame, date_value)`
- `has_amount(frame, amount_value)`
- `has_quantity(frame, quantity_value)`
- `approves`, `rejects`, `blocks`, `commits_to`, `requests`
- `updates`, `supersedes`, `contradicts`
- `same_artifact_candidate`
- `before`, `after`, `part_of_thread`
- `supported_by(frame, observation/message_occurrence)`

Every frame and relation remains candidate-only and stores provenance,
`ontology_revision_id`, rule id, confidence, and review state.

## Deterministic Extraction Rules

Immediate experiment is non-neural. It may use:

- Regex/gazetteers for identifiers: PO, purchase order, invoice, INV, SKU,
  part, material, work order, WO, SO, quote, contract, tracking, shipment.
- Date parsing for ISO dates, common US date forms, month names, `due`, `ETA`,
  `by`, and `before`. Relative dates must be anchored to `sent_at`.
- Amount and quantity parsing for currency, decimals, units, counts, cases,
  pallets, hours, and percentages.
- Actor extraction from headers first. Body names count only near role cues.
- Event cues:
  - approval: approved, sign off, authorize, waiver, rejected, denied, pending
    approval
  - blocker: blocked by, waiting on, hold, shortage, cannot until, pending
  - commitment: will, commit, promise, ETA, due by, owner
  - request: please, need, action item, can you
  - status: shipped, received, paid, closed, reconciled, deployed
- Polarity and negation rules for not approved, no longer blocked, cancelled,
  tentative, and superseded.
- Quoted or forwarded text must be marked as quoted context unless matched to
  a known message occurrence.

## Scoring Model

Parse each query into the same typed frame schema. Ranking should prefer compact
typed proof neighborhoods, not large thread components.

### Label-Blindness Rule

Corpus encoding must run before opening the private hard-case manifest. During
retrieval and scoring, each arm may see only:

- the query text;
- the requester, workspace, and permission context required for access checks;
- fixed experiment configuration for that arm; and
- the public evidence budget.

It must not see `result_kind`, domain labels, pattern labels, required source
observation ids, expected status, baseline result, KG-only result, or any other
evaluation label. Those fields are evaluation-only and may be opened only after
the arm has produced its selected evidence hashes/status.

### Fixed Feature Definitions

All feature values are normalized to `[0, 1]` before weighting:

- `L` lexical anchor match: query anchor token coverage against the candidate
  proof neighborhood, with exact normalized identifier hits capped at `1.0`.
- `T` type compatibility: `1.0` exact fine type, `0.75` shared core supertype,
  `0.5` broad-domain match, `0.25` unknown type, `0.0` incompatible core type.
- `S` slot coverage: matched required typed slots divided by required query
  slots. If the query has no typed slot constraints, use neutral `0.5`.
- `R` typed relation/path match: `1.0` exact predicate/path match, `0.75`
  compatible relation group, `0.5` thread/provenance-only support, `0.0` none.
- `M` temporal consistency: `1.0` compatible date/order evidence, `0.5` no
  temporal constraint, `0.0` contradicted temporal constraint.
- `P` provenance density: fraction of selected evidence budget covered by
  directly supported frames or relations, capped at `1.0`.
- `A` ambiguity penalty: fraction of same-artifact or same-score competing
  neighborhoods in the recall pool, capped at `1.0`.
- `Z` proof-size penalty: `min(1.0, max(0, proof_node_count - 8) / 24)`.
- `V` constraint violation penalty: `1.0` when a hard domain, range,
  cardinality, permission, or ontology-core constraint is violated; otherwise
  `0.0`.

Conceptual score:

```text
 lexical anchor match
+ type compatibility
+ slot coverage
+ typed relation/path match
+ temporal consistency
+ provenance density
- ambiguity
- proof graph size
- constraint violations
```

Selection constraints:

- Permission filtering happens before scoring.
- Returned evidence budget is fixed across KG and ontology arms.
- Each selected frame must have source provenance.
- Hard constraint mode requires zero domain/range/cardinality violations.
- If the best typed proof score is below a pre-registered threshold, return no
  evidence.

### Fixed Scoring Modes

The four scoring/gating modes are fixed before execution:

| Mode | Formula and gate |
| --- | --- |
| soft type | `0.55L + 0.25T + 0.10S + 0.05M + 0.05P - 0.10A - 0.05Z - 0.50V`; return no evidence if best score `< 0.35`. |
| soft type+relation | `0.40L + 0.20T + 0.15S + 0.15R + 0.05M + 0.05P - 0.10A - 0.05Z - 0.75V`; return no evidence if best score `< 0.38`. |
| late core-compatible hard gate | Use the soft type+relation formula, then discard neighborhoods with `V > 0`, `T == 0`, or any incompatible core-supertype edge; return no evidence if best remaining score `< 0.42`. |
| two-pass recall then high-confidence rerank/gate | First-pass recall score is `0.70L + 0.15T + 0.10S + 0.05M`. Rerank the configured candidate pool with `0.30L + 0.20T + 0.20S + 0.20R + 0.05M + 0.05P - 0.10A - 0.05Z - 0.75V`, discard `V > 0`, and return no evidence if best remaining score `< 0.45`. |

Tie-breakers are fixed in this order: higher final score, lower `V`, higher
`S`, higher `R`, higher `T`, smaller `proof_node_count`, higher `P`, then
stable hash of `(arm_id, query_hash, selected_evidence_ids)`. Evidence
selection returns the smallest supporting proof neighborhood up to a fixed
budget of `5` observations. If a tied proof has more than `5` observations,
select direct frame supports before context supports, then apply the same
tie-breakers. No query may receive a larger evidence budget in an ontology arm
than it receives in the KG-only control.

## Experiment Matrix

Use staged encoders plus a small hyperparameter grid, not arbitrary ordered
operator permutations.

Main ontology-native grid:

```text
3 type inventories
x 3 corpus encoders
x 3 query encoders
x 4 scoring/gating modes
x 3 candidate-pool sizes
= 324 main arms
```

Factors:

| Factor | Levels |
| --- | --- |
| Type inventory | broad domain; fine mail/business types; hierarchical broad+fine with core mapping |
| Corpus encoder | typed observations; typed thread/components; typed relation/path graph |
| Query encoder | direct lexical-to-type; SKOS/alias-expanded; relation-slot plus type intent |
| Scoring/gating | soft type; soft type+relation; late core-compatible hard gate; two-pass recall then high-confidence rerank/gate |
| Candidate pool | 16; 32; 64 recall candidates |

Controls:

1. Existing governed baseline retrieval.
2. KG-only replay.
3. Broad ontology replay.
4. Current KG-first factorial best replay.
5. Lexical observation-only.
6. Query expansion only.
7. Shuffled ontology labels.
8. Frequency-matched random type labels.

Total report entries: 332.

## Aliasing And Dominance

Rules:

- Fixed stage order: corpus encode -> query encode -> candidate union ->
  compatibility gate -> rerank -> evidence select.
- Do not enumerate permutations across stages.
- Collapse commutative additive scorers into one canonical order.
- Report arms with identical `case_result_hash` as alias classes, but do not
  remove them from the pre-registered 324-arm multiple-comparison denominator.
- All 324 main arms are admissible. If a scorer asks for a feature not produced
  by a weaker corpus encoder, that feature is deterministically `0.0` or the
  defined neutral value; the arm is still reported and included in correction.
- Treat broad-all-`Concept` hard gates as no-op aliases unless real
  incompatible core supertypes exist.
- SKOS expansion after type inference is an alias unless explicitly modeled as
  a distinct query encoder.

Arm A dominates B if A is casewise no worse, has no worse owner/no-match/denied
counts, no worse leak/safety status, equal or lower complexity/latency, and at
least one strict improvement.

## Evaluation Metrics

Primary comparison is ontology-native arm versus KG-only on identical case
hashes.

The pre-registered primary arm is:

```text
type inventory: hierarchical broad+fine with core mapping
corpus encoder: typed relation/path graph
query encoder: relation-slot plus type intent
scoring/gating: two-pass recall then high-confidence rerank/gate
candidate pool: 64
```

This primary arm is evaluated against KG-only before any best-arm claim.
The full 324-arm main grid is exploratory model-selection evidence unless the
selected arm also survives the correction rule below. The 8 controls are
diagnostic baselines and are not part of the 324-arm ontology-family
correction denominator.

Report:

- Overall pass count: `passed/100`.
- Non-denied quality: `passed/90`.
- Positive retrieval: `passed/80`.
- No-match precision: `passed/10`, where pass means no selected evidence.
- Permission safety: `passed/10`, hard gate.
- Paired transitions: KG fail -> ontology pass, KG pass -> ontology fail, both
  pass, both fail.
- Per-domain and per-pattern deltas.
- Matched required evidence count, selected evidence count, duplicate response
  hashes, and latency.
- Ontology diagnostics: ontology revision hash, policy hash, typed
  node/component coverage, conflicting type evidence, missing type evidence,
  ontology-supported relation count, incompatible-core pruned count, and
  changed-case attribution.

Use paired tests, not independent proportions. The statistical test is an exact
two-sided binomial sign test over non-denied discordant cases, equivalent to
McNemar's exact test without continuity correction. Let `W` be KG-fail ->
ontology-pass non-denied cases and `L` be KG-pass -> ontology-fail non-denied
cases. The null is `P(W) = P(L) = 0.5` over discordant cases. Alpha is `0.05`.
The confidence interval for net paired improvement uses the exact binomial
Clopper-Pearson interval mapped to `W / (W + L)` and reported alongside the raw
net case delta.

For the primary arm, the uncorrected alpha is `0.05` because it is frozen
before implementation. For the exploratory 324-arm family, apply
Holm-Bonferroni correction across all 324 main ontology-native arms. Controls
are reported separately and never used to claim ontology improvement.

## Help Criteria

Ontology helped only if:

- Permission-denied remains 10/10.
- Public raw/internal leak guard passes.
- Ontology beats KG on the primary paired non-denied endpoint with exact
  binomial/McNemar `p <= 0.05`, or the best exploratory arm survives
  Holm-Bonferroni correction at family alpha `0.05`.
- Practical gain is at least `+5` non-denied cases and preferably `+6` or more.
- Positive cases do not materially regress: KG-pass -> ontology-fail positive
  cases must be `<= 2`, and net positive-case delta must be `>= 0`.
- No-match precision does not regress versus KG-only.
- Gains are not concentrated: winning changed cases must span at least `2`
  domains and `2` positive patterns; no single domain or pattern may account
  for more than `60%` of KG-fail -> ontology-pass wins unless total wins are
  fewer than `3`.
- Changed wins are attributable to typed/relational evidence, not only broad
  vocabulary expansion. Each changed case must carry one primary attribution
  label from `typed_frame_match`, `slot_coverage`, `typed_relation_path`,
  `temporal_consistency`, `ontology_pruning`, `lexical_expansion_only`,
  `candidate_pool_only`, or `other`. At least `60%` of KG-fail ->
  ontology-pass wins must be attributed to one of the first five labels, and
  `lexical_expansion_only` wins must be `<= 40%`.

## Redesign Triggers

Redesign before rerunning variants if:

- Ontology score is <= KG-only again.
- Best result appears only after many-arm search without holdout or corrected
  significance.
- No-match remains 0/10.
- Any permission-denied case fails.
- Positive gains are offset by positive regressions.
- Gains come only from broad-domain or SKOS expansion.
- Confidence interval includes zero and practical delta is small.
- Type evidence coverage is shallow on changed cases.
- Public report leaks private evidence or overclaims.

## Post-Result Share-Back

After a run:

1. Validate report schema, hashes, claim boundary, and raw-leak guards.
2. Recompute aggregates from rows.
3. Recompute paired deltas, intervals, and multiple-comparison correction where
   applicable.
4. Prepare a redacted iteration packet with factor levels, arm hashes,
   aggregate counts, alias classes, dominated clusters, Pareto frontier, and
   discordance hashes versus KG.
5. Share the redacted packet back to the four design reviewers.
6. If reviewers identify a stronger fair design, rerun before making a final
   claim.

Private row-level error analysis stays local to the preserved work directory.
Only safe summaries go into docs and handoff files.
