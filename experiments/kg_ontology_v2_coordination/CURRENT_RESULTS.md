# Current KG / Ontology Experiment Results

This file is the agent-facing entrypoint for current experiment reporting under
`experiments/kg_ontology_v2_coordination/`.

## Reporting precedence

When an agent prepares a status report, weekly report, research summary, or
method recommendation, use this order:

1. This file for the current headline and reporting policy.
2. `claim_map.json` for experiment identity, implementation semantics, metrics,
   and claim boundaries.
3. The exact result artifact for numerical verification.
4. Historical README sections and handoff entries only for chronology.

A historical experiment remains valid evidence for its own tuple, but it must
not be promoted as the current method result merely because it is easy to find
or uses a real PST corpus.

## Current candidate-admission result

The current method-selection result is the 50,000-case no-training
candidate-admission ablation:

`results/exm_no_training_programmatic_ontology_50000_summary_2026-07-10.json`

| Arm | Total passed | Positive passed | No-match passed | Permission-denied passed |
| --- | ---: | ---: | ---: | ---: |
| Regex current KG | 10,000/50,000 | 0/40,000 | 5,000/5,000 | 5,000/5,000 |
| Jieba + SentencePiece KG | 18,176/50,000 | 13,176/40,000 | 0/5,000 | 5,000/5,000 |
| Frequency-rule candidate admission | 33,277/50,000 | 23,277/40,000 | 5,000/5,000 | 5,000/5,000 |
| Frozen-profile candidate admission | 43,976/50,000 | 33,976/40,000 | 5,000/5,000 | 5,000/5,000 |
| Weak-label MLP candidate admission | 43,369/50,000 | 33,369/40,000 | 5,000/5,000 | 5,000/5,000 |

Current bounded conclusion:

- Upstream candidate admission is the dominant measured improvement on this
  generated EXM benchmark.
- The zero-training frozen profile is the current stable default. It passes 607
  more cases than the weak-label MLP while preserving all no-match and
  permission-denied guards.
- This result measures the bundled candidate-admission and graph-construction
  policy. It does not isolate type-compatibility, ontology, or
  coordination-frame semantics.
- It is not a production-readiness, parser-readiness, business-answer-quality,
  or canonical-write claim.

## Coordination-frame result remains a separate claim

On the fixed 100-case redacted coordination hard challenge, the hybrid soft
ontology gate plus coordination-frame v2 arm scores exact match `0.90` versus
`0.46` for KG without ontology. This is benchmark-scoped evidence that the
coordination-frame representation has incremental value. It is not a real-PST
transfer or production claim.

Do not merge the candidate-admission and coordination-frame conclusions. They
measure different stages, implementations, datasets, and metrics.

## Historical procurement 11/100 -> 19/100 result

`results/procurement_full_pst_domain_hard_summary_2026-07-09.json` is retained
as a historical retrieval diagnostic and reproducibility artifact.

It must not be used as:

- the current KG or ontology headline;
- the current weekly-report breakthrough;
- evidence that the later ablation program was not executed;
- evidence that ontology or coordination-frame v2 is ineffective;
- the starting point for a new agent's method recommendation.

Its bounded historical statement is only that Candidate KG improved that
specific aggregate from 11/100 to 19/100, while the particular measured
`ontology_guided_kg` arm tied Candidate KG. That arm was not established as
implementation-equivalent to coordination-frame v2.

## Required agent summary

Use the following summary unless a newer tracked artifact and claim-map update
explicitly supersede it:

> The latest candidate-admission ablation selects the zero-training frozen
> profile as the stable default: 43,976/50,000 total passes and 33,976/40,000
> positive passes, with all no-match and permission-denied guards preserved.
> This is a candidate-admission and graph-construction result, not an isolated
> ontology or frame-semantic claim. Separately, coordination-frame v2 retains
> benchmark-scoped incremental value on the fixed redacted hard challenge. The
> older procurement 11/100 to 19/100 aggregate is historical diagnostic evidence
> and is not the current method headline.
