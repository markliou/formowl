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

## Operator-Provided Procurement PST Follow-Up

The procurement real-case follow-up summary is tracked at:

```text
results/procurement_full_pst_domain_hard_summary_2026-07-09.json
```

This artifact is a redacted aggregate summary only. It does not include raw
mail content, query text, message identifiers, subjects, senders, attachment
names, private manifest rows, PST hashes, or private paths.

Result summary:

| Arm | Passed | Positive passed | No-match passed | Permission-denied passed |
| --- | ---: | ---: | ---: | ---: |
| Baseline retrieval | 11/100 | 1/80 | 0/10 | 10/10 |
| Candidate KG fusion | 19/100 | 9/80 | 0/10 | 10/10 |
| Ontology-guided KG | 19/100 | 9/80 | 0/10 | 10/10 |
| Best ordered ontology factorial arm | 19/100 | 9/80 | 0/10 | 10/10 |

Interpretation: candidate KG structure helped on the procurement corpus, but
the current ontology-guided arm did not improve beyond KG-only. The 326-arm
ordered ontology factorial search found 0 arms better than KG-only, 2 tied
KG-only, and 324 worse; the best arm used zero ontology operators.

This is an operator-provided full-PST domain-hard retrieval and candidate-only
KG/ontology measurement. It is not business answer generation, not a general
PST parser-readiness claim, not raw-mail access, not canonical graph/type/user
graph/wiki mutation, and not production readiness.

## EXM Lexical Candidate-Admission 50,000-Case Follow-Up

The EXM lexical ontology follow-up summary is tracked at:

```text
results/exm_lexical_ontology_50000_summary_2026-07-09.json
```

This run uses all currently available EXM PST parsed corpora as private input
and compares the existing regex policy against the user's requested
`jieba + SentencePiece` lexical policy across 50,000 generated cases. The
public artifact is aggregate-only: it excludes raw mail text, query text,
subjects, senders, message ids, observation ids, attachment names, private
paths, parser commands, and private manifest rows.

Result summary:

| Arm | Passed | Positive passed | No-match passed | Permission-denied passed |
| --- | ---: | ---: | ---: | ---: |
| Regex admission + candidate KG | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Regex admission + type-compatibility proxy | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Jieba + SentencePiece admission + candidate KG | 16,811/50,000 | 11,811/40,000 | 0/5,000 | 5,000/5,000 |
| Jieba + SentencePiece admission + type-compatibility proxy | 16,811/50,000 | 11,811/40,000 | 0/5,000 | 5,000/5,000 |

Interpretation: the lexical tokenizer plan has a real positive-retrieval
effect versus regex-only matching, but it is not yet stable enough. It created
very large lexical components and failed every no-match guard case. The
type-compatibility proxy arm tied the lexical KG arm exactly, so this run does
not show an incremental type-compatibility or frame-semantic effect. The next method step is not
to promote this tokenizer output directly; it is to add data-driven term
quality scoring, IDF or document-spread caps, component splitting/community
detection, and no-match calibration before ontology promotion or any
production retrieval claim.

## EXM Weak-Label Candidate-Admission 50,000-Case Follow-Up

The historically named programmatic-ontology artifact is tracked at:

```text
results/exm_programmatic_ontology_50000_summary_2026-07-09.json
```

This historical artifact predates the issue #33 report-schema correction. It
keeps `jieba + SentencePiece` as an upstream candidate generator, then compiles
a candidate-admission policy before KG edge construction:

- document-frequency gates reject low-value or over-broad terms;
- protected mention typing keeps explicit organization, contact, and business
  identifier candidates;
- a CPU-bounded deterministic weak-label MLP assigns candidate scores to CJK
  term mentions, with model hash and weak-label training counts in the safe
  summary;
- the category/type scoring proxy requires an exact compiled term candidate and cannot use
  category-only fallback.

Result summary:

| Arm | Passed | Positive passed | No-match passed | Permission-denied passed |
| --- | ---: | ---: | ---: | ---: |
| Regex admission + candidate KG | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Regex admission + type-compatibility proxy | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Jieba + SentencePiece admission + candidate KG | 18,176/50,000 | 13,176/40,000 | 0/5,000 | 5,000/5,000 |
| Jieba + SentencePiece admission + type-compatibility proxy | 18,176/50,000 | 13,176/40,000 | 0/5,000 | 5,000/5,000 |
| Weak-label MLP candidate admission + type-compatibility proxy | 43,369/50,000 | 33,369/40,000 | 5,000/5,000 | 5,000/5,000 |

Interpretation: the revised candidate-admission and graph-construction bundle
has measured effect. This does not isolate type compatibility or coordination-
frame semantics. The raw lexical arms still fail every no-match
guard; the programmatic policy keeps all no-match and permission-denied guards
while recovering most positive cases. The largest programmatic component
remains large, so community detection or stricter component splitting is still
needed before production retrieval claims.

## EXM No-Training Candidate-Admission 50,000-Case Follow-Up

The historically named no-training programmatic-ontology artifact is tracked at:

```text
results/exm_no_training_programmatic_ontology_50000_summary_2026-07-10.json
```

This run keeps the same parsed corpus hash, 50,000-case manifest shape,
`jieba + SentencePiece` candidate generator, document-frequency gates,
protected mention handling, and exact-candidate-only category/type-proxy retrieval. It
adds two training-free controls:

- `frequency_rule_candidate_admission`: data-driven CJK term admission with no
  neural scoring and zero training examples;
- `frozen_profile_candidate_admission`: a hashable fixed CJK scoring profile
  with zero training examples and zero training epochs.

Result summary:

| Arm | Passed | Positive passed | No-match passed | Permission-denied passed |
| --- | ---: | ---: | ---: | ---: |
| Regex current KG | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Regex current ontology | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Jieba + SentencePiece KG | 18,176/50,000 | 13,176/40,000 | 0/5,000 | 5,000/5,000 |
| Jieba + SentencePiece ontology | 18,176/50,000 | 13,176/40,000 | 0/5,000 | 5,000/5,000 |
| Frequency-rule candidate admission | 33,277/50,000 | 23,277/40,000 | 5,000/5,000 | 5,000/5,000 |
| Frozen-profile candidate admission | 43,976/50,000 | 33,976/40,000 | 5,000/5,000 | 5,000/5,000 |
| Weak-label MLP candidate admission | 43,369/50,000 | 33,369/40,000 | 5,000/5,000 | 5,000/5,000 |

Interpretation: both no-training programmatic controls beat raw lexical
ontology while preserving no-match and permission-denied guards. The
zero-training frozen profile scored `607` more passed cases than the weak-label
MLP on the same generated EXM benchmark. The current default recommendation is
therefore the hashable frozen-profile programmatic policy, not a self-trained
weak-label MLP. BGE-M3 through FlagEmbedding remains the preferred future
optional true frozen neural adapter, but it was not executed in the default dev
container because that container intentionally does not include torch,
transformers, FlagEmbedding, GLiNER, HanLP, or CKIP.

## Issue #33 Work Package A Report Boundary

Newly generated reports use `development` and `evaluation` case labels. They do
not call generated same-corpus cases a holdout. Arm identifiers separately name
the candidate-admission policy and whether the run stops at candidate-KG
ranking or adds the category/type scoring proxy. Every arm also declares its KG
construction, type-compatibility, and frame-semantics modes.

The primary retrieval accuracy contains only positive retrieval cases.
No-answer/no-match behavior and permission safety are separate sections, so an
automatically blocked permission-denied case cannot inflate retrieval accuracy.
The report has explicit sections for `positive_retrieval`,
`no_answer_or_no_match`, `permission_safety`, `frame_type_quality`,
`slot_value_quality`, `evidence_span_quality`, `latency_and_resource_use`, and
`graph_topology_diagnostics`. This harness marks `frame_type_quality` and slot
value quality as not measured rather than treating candidate-admission lift as
semantic evidence.
