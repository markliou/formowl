# KG Ontology v2 Coordination-Frame Experiment

This experiment is the issue #28 candidate-layer slice. It compares the current
flat atom path with an additive coordination-frame ontology path over synthetic
email-first cross-domain fixtures.

Run:

```sh
python experiments/kg_ontology_v2_coordination/run_coordination_frame_experiment.py
```

Write a local result artifact:

```sh
python experiments/kg_ontology_v2_coordination/run_coordination_frame_experiment.py \
  --output /tmp/formowl_coordination_result.json
```

The fixture covers:

- Sales + R&D quote and firmware blocker coordination.
- Warehouse + Production material shortage and work-order delay.
- Finance + Sales invoice/payment commitment and renewal risk.
- Management / Project decision, dependency, open question, and assignment.

Experimental arms:

- `no_ontology_metadata_only`
- `current_atom_path`
- `coordination_frame_v2`
- `hybrid_v1_type_gate_v2_projection`

The primary metric is competency-question answerability, reported alongside
slot recall and slot-value recall. The current synthetic fixture is contract
round-trip verification, not production extraction evidence. The runner also
includes a synthetic hard-gate vs soft-gate noisy-type ablation scaffold; this
does not replace the required future real/PST-redacted email regression test.

The runner also emits `effectiveness_regression` from the fixed redacted replay
fixture:

```text
fixtures/regression_redacted_cases.json
```

That report compares:

- `kg_without_ontology`
- `kg_hard_ontology`
- `kg_soft_ontology_gate`
- `coordination_frame_v2_redacted`
- `hybrid_soft_gate_v2_frame`

Current redacted replay result: hard ontology reproduces the regression
against KG without ontology (`0.166667` vs `0.666667` exact match), soft gate
recovers to `0.666667`, and v2 plus hybrid reach `1.0` exact match with zero
false positives. This is fixed redacted replay evidence, not a production PST
parser claim.

Claim boundary:

- synthetic fixture only;
- no raw PST content;
- no canonical graph writes;
- no canonical type writes;
- no user graph or wiki revision mutation;
- no production email parser quality claim.

The design note is [docs/ontology-v2-coordination-frames.md](../../docs/ontology-v2-coordination-frames.md).

## Two-Version Ablation

The first-version synthetic marker fixture is still present and still reports
round-trip contract behavior through `ablation_versions.original_synthetic_marker_fixture`.

The redesigned 100-case hard challenge lives at:

```text
fixtures/challenge_redacted_100_cases.json
```

It is a fixed redacted challenge designed from failure modes, not raw PST parser
output. It contains 30 dev cases, 70 holdout cases, and 100 total cases across
gate false reject, alignment suppression, misleading structure, frame confusion,
cross-thread dependency, follow-up/fallback, false-positive guard, and
access/redaction-boundary buckets.

The runner also emits `redacted_stress_benchmark_10000`, a deterministic
10,000-case stress benchmark generated from the 100-case redacted templates
instead of a committed giant JSON fixture. It uses the user's requested 10/90
split ratio: 1,000 dev cases and 9,000 holdout cases. This is stress validation
over redacted template families, not an independent PST/parser holdout.

Current 100-case result:

| Arm | Exact match | Slot-value F1 | False positives | Hard false rejects |
| --- | ---: | ---: | ---: | ---: |
| KG without ontology | 0.46 | 0.801382 | 11 | 0 |
| KG + current hard ontology | 0.22 | 0.329239 | 0 | 30 |
| KG + soft ontology gate | 0.74 | 0.936396 | 0 | 0 |
| Coordination frame v2 | 0.82 | 0.925859 | 1 | 0 |
| Hybrid soft gate + v2 frame | 0.90 | 0.981133 | 1 | 0 |

Current 10,000-case generated stress result:

| Arm | Exact match | Slot-value F1 | False positives | Hard false rejects |
| --- | ---: | ---: | ---: | ---: |
| KG without ontology | 0.46 | 0.801382 | 1100 | 0 |
| KG + current hard ontology | 0.22 | 0.329239 | 0 | 3000 |
| KG + soft ontology gate | 0.74 | 0.936396 | 0 | 0 |
| Coordination frame v2 | 0.82 | 0.925859 | 100 | 0 |
| Hybrid soft gate + v2 frame | 0.90 | 0.981133 | 100 | 0 |
