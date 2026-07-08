# Ontology v2 Coordination-Frame Experiment

Date: 2026-07-08

Status: issue #28 fixture experiment checkpoint. Do not treat this as issue
#28 completion or production ontology readiness.

## Purpose

Issue #28 changes the ontology target from a label-registry model to a
coordination-frame model:

```text
Evidence/source ontology
+ stable coordination-frame core
+ scoped domain object packs
+ projection/view ontology
```

This checkpoint implements the first narrow, reversible experiment slice. It
tests whether a minimal frame-centered representation improves competency
question answerability over the current flat semantic labeling path on
synthetic cross-domain email cases.

## Implemented Slice

The contract layer now has candidate and reviewed-frame surfaces for the v2
path:

- `CandidateMention`
- `CandidateBusinessObject`
- `CandidateFrame`
- `CanonicalFrame`
- `DomainPackDefinition`

The experiment script is
`scripts/ontology_v2_coordination_frame_experiment.py`. It compares:

| Arm | Representation |
| --- | --- |
| `current_flat_atom_path` | current flat semantic label/atom-style answerability proxy |
| `ontology_v2_coordination_frame_path` | observation-grounded mentions, business objects, and coordination frames |

The fixture is `examples/ontology-v2-cross-domain-email-cases.json`. It covers
four email-first cross-domain scenarios:

1. Sales + R&D quote and firmware capability coordination.
2. Warehouse + Production material shortage and work-order impact.
3. Finance + Sales invoice/payment approval and customer commitment.
4. Management + Project launch dependency and open coordination.

Each scenario contains structured lines for `Request`, `Blocker`,
`Commitment`, `Decision`, and `StatusUpdate`. The script converts those lines
into candidate-only frame records with ontology revision pins, evidence spans,
domain hints, candidate mention links, candidate business object links,
extractor run provenance, and pending-review state.

Domain packs are loaded for sales, R&D, warehouse, production, finance,
management, and project. Each pack defines domain business object types and
frame specializations that must extend coordination core frame types.
For this first slice, `CandidateFrame` and `CanonicalFrame` instances accept
only coordination core frame types. Domain-specific frame specializations are
validated in `DomainPackDefinition`; instantiating specialized frames should
wait for an explicit domain-pack binding field so flat business labels cannot
re-enter as frame types.

## Result

The current fixture run reports:

| Metric | Value |
| --- | ---: |
| Scenarios | 4 |
| Domain packs | 7 |
| Competency questions | 10 |
| Question-case pairs | 40 |
| Candidate frames | 20 |
| Current flat path answerable | 16/40 |
| Ontology v2 frame path answerable | 40/40 |
| Delta | +24 |

The measured improvement is answerability over this fixture, not production
retrieval quality or general ontology correctness.

Run and validate the public report:

```sh
python scripts/ontology_v2_coordination_frame_experiment.py \
  --output /tmp/ontology-v2-coordination-frame-experiment.json
python scripts/ontology_v2_coordination_frame_experiment.py \
  --validate-report /tmp/ontology-v2-coordination-frame-experiment.json \
  --output /tmp/ontology-v2-coordination-frame-validation.json
```

Canonical completion evidence must come from the dev container, together with
the repository test and formatting commands.

## Claim Boundary

This slice supports only these claims:

- A minimal issue #28 coordination-frame contract exists.
- Domain pack frame specializations extend the stable coordination-frame core.
- Synthetic email examples no longer collapse into only flat metadata labels.
- The fixture experiment compares the current flat path against the v2 frame
  path.
- The report evaluates competency-question answerability.

This slice does not claim:

- issue #28 is complete;
- real mail parser readiness;
- production ontology readiness;
- business answer generation;
- raw mail access;
- canonical type writes;
- canonical KG writes;
- user graph writes;
- wiki projection;
- production readiness.

## Next Iteration

The next issue #28 work should move from structured fixture lines to an
extractor-like candidate generation path over ordinary observations. It should
also add old atom/relation migration notes, test more negative/no-obligation
mentions, and evaluate the projection/view layer without mutating wiki or user
graph state.
