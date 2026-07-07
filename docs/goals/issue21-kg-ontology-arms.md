# Issue 21 KG Ontology Arms Goal

Date: 2026-07-07

Status: active. This is not an experiment completion claim.

## Objective

Redesign the #21 full-PST hard-domain mail evidence comparison as an
ontology-native KG plus ontology experiment. The new run must not treat
ontology as a late KG-first reranker. It must encode typed mail frames,
entities, slots, values, and relations before graph fusion, then evaluate the
pre-registered ontology-native arms against the same hard-domain case hashes.

## Current Evidence

- The operator-provided full-PST hard-domain baseline and preserved work
  directory already exist under the #21 checkpoint S/T/U flow.
- Current measured results before this redesign:
  - baseline retrieval: 20/100
  - non-BERT candidate KG: 30/100
  - broad ontology-guided KG: 29/100
  - KG-first ordered ontology-operator factorial best arm: 30/100
- These results are valid as KG-first evidence only. They do not prove that
  ontology cannot help when it is encoded before graph fusion.
- The pre-registration design is
  `docs/mail-ontology-native-factorial-design.md`.
- Four math/research read-only reviewers audited the design:
  - `Jason`: agreed after scoring, label-blindness, and arm-family blockers
    were fixed.
  - `Planck`: agreed with the staged 324 plus 8 design.
  - `Maxwell`: agreed with deterministic mail-native frame and relation
    encoding before fusion.
  - `Hypatia`: agreed after exact paired tests, Holm-Bonferroni correction,
    primary-arm protocol, and numeric help gates were fixed.

## Required Experiment Shape

The main experiment family is:

```text
3 type inventories
x 3 corpus encoders
x 3 query encoders
x 4 scoring/gating modes
x 3 candidate-pool sizes
= 324 ontology-native arms
```

The run also reports 8 controls:

1. Existing governed baseline retrieval.
2. KG-only replay.
3. Broad ontology replay.
4. Current KG-first factorial best replay.
5. Lexical observation-only.
6. Query expansion only.
7. Shuffled ontology labels.
8. Frequency-matched random type labels.

Total report entries: 332.

## Non-Negotiable Constraints

- Build corpus typed state before opening the private hard-case manifest.
- Retrieval and scoring may see only query text, requester/workspace/permission
  context, fixed arm configuration, and fixed evidence budget.
- Retrieval and scoring must not see `result_kind`, domain labels, pattern
  labels, required source observation ids, expected status, baseline result, or
  KG-only result.
- Keep thread membership as a typed context/provenance relation, not as a
  pre-fused component union.
- Preserve `.test-tmp` intermediates. Do not delete the work directory after
  the run.
- Public reports must remain hash/status/count/timing only.
- Do not expose query text, PST contents, message ids, subjects, senders,
  snippets, observation ids, object locators, parser commands, scratch paths,
  SQL, local paths, or environment values.
- The experiment remains candidate-only. It must not write canonical KG,
  canonical type state, user graph state, grants, raw access state, wiki
  projections, or production adapter state.

## Statistical Decision Rules

- The frozen primary arm is:

```text
type inventory: hierarchical broad+fine with core mapping
corpus encoder: typed relation/path graph
query encoder: relation-slot plus type intent
scoring/gating: two-pass recall then high-confidence rerank/gate
candidate pool: 64
```

- Primary comparison uses exact paired binomial/McNemar testing over
  non-denied discordant cases at alpha `0.05`.
- Exploratory best-arm claims must apply Holm-Bonferroni correction across all
  324 main ontology-native arms. The 8 controls are diagnostic and excluded
  from the correction denominator.
- Ontology helps only if permission-denied remains 10/10, leak guards pass,
  non-denied quality improves by at least +5 cases, positive cases do not
  materially regress, no-match precision does not regress, gains are not
  concentrated in one domain or pattern, and changed wins are attributable to
  typed or relational evidence rather than broad vocabulary expansion alone.

## Implementation Deliverables

- Add an ontology-native harness separate from the existing KG-first ordered
  factorial script.
- Add focused tests for:
  - 324 plus 8 arm generation;
  - fixed primary arm and statistical decision metadata;
  - label-blind retrieval/scoring;
  - deterministic scoring weights, thresholds, tie-breakers, and evidence
    budget;
  - safe public report validation;
  - no raw/internal field leakage;
  - no canonical graph/type/user-graph/wiki side effects; and
  - preserved intermediate data behavior.
- Run the focused tests in the dev container.
- Run the ontology-native experiment over the preserved full-PST work
  directory in the dev container.
- Validate the saved report with its validator.
- Share a redacted result packet with `Jason`, `Planck`, `Maxwell`, and
  `Hypatia`.
- If any reviewer identifies a stronger fair design after seeing the result,
  update the pre-registration or add a new addendum, rerun the affected
  experiment family, and record the reason.

## Completion Criteria

This goal is complete only when all of the following are true:

- The ontology-native harness exists and follows
  `docs/mail-ontology-native-factorial-design.md`.
- The 324 main arms and 8 controls have been run or explicitly reported as
  blocked by a validated safe blocker.
- The report validator passes with `blockers=[]`.
- Dev-container focused tests for the new harness pass.
- Relevant docs and handoff files record the results, limitations, and claim
  boundaries.
- The four design reviewers have received the redacted result packet and have
  either agreed the result can stand or their blockers have been addressed and
  rerun.
- No intermediate `.test-tmp` data required for follow-up experiments has been
  deleted.
- No completion claim is made for business answer generation, production
  readiness, raw mail access, actual ChatGPT file transfer, canonical KG/type
  writes, user graph writes, or wiki projection.

## Next Action

Implement the ontology-native harness and focused tests, then run the
container-backed baseline over the preserved #21 full-PST work directory.
