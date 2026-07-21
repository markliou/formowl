# Ontology v2 Temporal-Evidential Coordination Frames

This note records the historical issue #28 specialized coordination
experiment. The canonical general methodology is defined in `SPEC.md`:
`Observation -> CandidateBusinessObject -> CandidateAssertion`, where
coordination is one of five universal assertion families. This experiment
retains `CandidateFrame` as a reversible coordination-specific representation;
it does not redefine the cross-domain core.

For historical implementation context, see
`docs/ontology-v2-coordination-plan.md`. For the methodology critique that
motivated the soft-gate and evaluation changes, see
`docs/ontology-v2-review-comments.md`.

## Default Candidate Evidence Retrieval

Coordination-frame extraction does not replace retrieval. New harnesses first
use stable logical source item identity, access/context/time admissibility
before planning, conjunctive same-source anchors, and capped additive ontology
reranking. The historical frame, hard-gate, and component comparisons in this
document are ablation evidence only; ontology hard-pruning is not the default.
The active harness also requires an index-owned
`CandidateEvidenceTextPolicyRuntime` for the
Unicode-NFKC/protected-ASCII/Jieba/corpus-bound SentencePiece/frozen-profile
stack and exact admission/model/corpus SHA-256 hashes. The binding also pins
the runtime id and tokenizer implementation hash; runtime code mismatch fails
closed. Default callers pass query text only; raw tokens and free-form hashes
are not sufficient. Access and explicit context/time admissibility precede
tokenization; experiments use `retrieve_ablation`.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Diagnosis

The existing ontology path is useful for scoped type governance:

```text
core type -> extension type -> promoted type -> type alignment candidate
```

That path answers whether two mentions have compatible coarse types. It does
not directly answer enterprise coordination questions such as who requested
what, who committed, what was decided, what is blocked, which deadline matters,
or what evidence supports the obligation.

Email exposes the gap because email is a communication substrate, not a domain.
One thread can carry sales, R&D, warehouse, production, finance, management, and
project coordination semantics at once. Adding more labels such as `Email`,
`Invoice`, or `Shipment` would not define the roles inside requests, blockers,
decisions, commitments, status changes, and follow-up obligations.

## Method

Ontology v2 uses an evidence-backed, temporal-evidential coordination-frame
model:

```text
Layer 0 Evidence/source ontology
  -> Asset, Observation, EvidenceSnapshot, Citation, EvidenceSpan, PermissionScope
Layer 1 Temporal-evidential assertion core
  -> CandidateAssertion, TemporalContext, epistemic status, lifecycle status,
     provenance, as_of_world_time, known_as_of
Layer 2 Stable coordination-frame core
  -> Request, Commitment, Decision, Assignment, StatusUpdate, StatusChange,
     Blocker, Risk, Issue, OpenQuestion, Deadline, Dependency, Escalation,
     Change, Exception, Constraint
Layer 3 Scoped domain packs
  -> domain objects, process frames, temporal-role mappings, epistemic
     mappings, and lifecycle mappings that extend but do not replace the core
Layer 4 Projection/view ontology
  -> follow-up queues, decision logs, risk registers, case progress views,
     project hubs, and other user-facing graph projections
```

The canonical method and this specialized experiment relate as follows:

```text
Observation
  -> CandidateBusinessObject
  -> CandidateAssertion(kind=coordination, TemporalContext,
       epistemic_status, lifecycle_status)
  -> CandidateTemporalView(as_of_world_time, known_as_of)
  -> optional CandidateMention / CandidateFrame / CandidateRelation experiment
  -> reviewed CanonicalFrame / CanonicalObject / CanonicalRelation
```

The implementation added here stops at candidates. It does not create canonical
frame stores, user graph revisions, wiki revisions, raw asset grants, or
canonical type writes.

The design is aligned with frame semantics and semantic-role extraction: a
frame carries a situation type and named roles rather than flattening everything
into entity labels. The research direction also follows document-level
extraction work: cross-sentence argument linking matters for email threads and
documents, and relation extraction often requires synthesizing multiple
sentences rather than reading one entity pair at a time.

## Contracts

The contract layer adds:

- `TemporalContext`: a normalized, source-neutral qualifier for phenomenon,
  source, observation, assertion, effective, valid, result, recorded, due, and
  supersession time. The POC validates field names and simple interval order;
  `captured_at` is bound to source Observation capture time rather than supplied
  by a Domain Pack. Candidate materialization remains a separate
  `CandidateAssertion.created_at` knowledge boundary; source capture alone does
  not make the candidate visible.
- `CandidateAssertion.epistemic_status`: separates planned, expected,
  committed, requested, asserted, observed, and actual semantics from candidate
  review state.
- `CandidateAssertion.lifecycle_status`: independently records active,
  cancelled, corrected, or superseded state, allowing an actual assertion to
  also be corrected or superseded.
- `CandidateMention`: a source-grounded mention with location, hash,
  confidence, review state, and source observations.
- `CandidateBusinessObject`: a work object candidate such as a quote,
  firmware spec, invoice, work order, shipment, or project plan. Its
  `object_supertype` must be one of the coordination object supertypes.
- `CandidateFrame`: the specialized issue #28 coordination unit. It has a stable coordination
  `frame_type`, structured `slots`, evidence spans, domain hints, granularity,
  access boundary, ontology revision pin, review state, source mention ids, and
  optional linked business objects.
- `CanonicalFrame`: the governed target shape for a future reviewed commit
  workflow. It exists as a contract, not as a generic storage write path.

Domain packs are loaded through `DomainPackDefinition`. A domain-specific frame
such as `InvoiceApproval`, `InventoryShortage`, or
`FirmwareCapabilityQuestion` must map to a stable coordination core frame. A
domain object such as `Invoice`, `Quote`, or `FirmwareSpec` must map to a
coordination object supertype. A pack that bypasses the core is rejected.
Domain Packs may also map domain labels such as promised date or posting date to
shared `TemporalContext` fields and select shared epistemic and lifecycle
statuses. The extractor normalizes those labels before candidate ids are
generated.

## Experiment

The experiment lives under:

```text
experiments/kg_ontology_v2_coordination/
```

Inputs:

- `fixtures/email_cross_domain_cases.json`
- `fixtures/gold_competency_answers.json`

Command:

```sh
python experiments/kg_ontology_v2_coordination/run_coordination_frame_experiment.py
```

Arms:

- `no_ontology_metadata_only`: parses mention-like metadata without stable
  frame semantics.
- `current_atom_path`: current deterministic atom extractor over the same
  observations.
- `coordination_frame_v2`: v2 candidate mention, frame, and business object
  extraction.
- `hybrid_v1_type_gate_v2_projection`: v2 frames with the current atom path
  retained as a baseline/type-gate signal.

Synthetic email-first scenarios:

- Sales + R&D: quote request, firmware blocker, fallback, customer deadline.
- Warehouse + Production: material shortage, work-order delay, owner
  assignment.
- Finance + Sales: payment commitment, invoice approval decision, renewal risk.
- Management / Project coordination: decision, dependency, open question, and
  action assignment.

Current result for the checked synthetic marker fixture:

| Arm | Candidate frames | Candidate atoms | Slot recall | Slot value recall | CQ answerability |
| --- | ---: | ---: | ---: | ---: | ---: |
| no ontology metadata only | 13 surrogate frames | 0 | 0.0 | 0.0 | 0.4375 |
| current atom path | 0 | 2 | 0.0 | 0.0 | 0.09375 |
| coordination frame v2 | 13 | 0 | 1.0 | 1.0 | 1.0 |
| hybrid v1 gate + v2 projection | 13 | 2 | 1.0 | 1.0 | 1.0 |

This is round-trip contract verification, not production performance evidence.
The gold questions cover the issue #28 competency set: request, commitment,
decision, blocker, deadline, status change, evidence support, domain, mention
versus obligation, and follow-up queue membership.

The evaluator is case-bounded: required frames, slots, and competency
questions are scored only against frames whose source or evidence spans
intersect the gold case's observation ids. The evidence-support competency
requires an evidence span with a case-local source observation, locator, and
`sha256:` text hash.
The report also includes slot-value recall, so a frame with the correct slot
key and incorrect value no longer receives full quality credit.

The runner includes a historical synthetic noisy-type hard-vs-soft ablation.
Neither arm is the retrieval default. Current Candidate evidence retrieval
uses capped additive ontology reranking and never hard-prunes source evidence.
Core-type incompatibility may still govern a later type-alignment or canonical
review decision, but it must not be moved into retrieval as an early evidence
gate.

## Redacted Effectiveness Regression

The runner now also evaluates a fixed redacted email replay pack:

```text
experiments/kg_ontology_v2_coordination/fixtures/regression_redacted_cases.json
```

This pack is not raw PST extraction and contains no raw message bodies,
subjects, sender addresses, mailbox ids, attachment names, or filesystem
paths. It is a fixed replay surface for the observed failure pattern: KG alone
can answer some email coordination questions, while KG plus the current hard
ontology gate loses recall under noisy predicted types or misleading structure.

Effectiveness result on the fixed redacted replay:

| Arm | Exact match | Slot-value F1 | False positives | Hard false rejects |
| --- | ---: | ---: | ---: | ---: |
| KG without ontology | 0.666667 | 0.914286 | 1 | 0 |
| KG + current hard ontology | 0.166667 | 0.260870 | 0 | 2 |
| KG + soft ontology gate | 0.666667 | 0.787879 | 0 | 0 |
| Coordination frame v2 | 1.0 | 1.0 | 0 | 0 |
| Hybrid soft gate + v2 frame | 1.0 | 1.0 | 0 | 0 |

Interpretation:

- The fixed replay reproduces the motivating regression:
  `KG + current hard ontology` is 0.5 exact-match points below
  `KG without ontology`.
- The soft gate removes the two low-confidence hard false rejects and recovers
  to the KG-without-ontology exact-match level while retaining the
  high-confidence negative guard.
- The v2 frame path and the hybrid soft-gate + v2 path both answer all fixed
  replay cases, including the follow-up/fallback case that flat KG only
  answers partially.
- This is the first positive effectiveness signal for v2, but the claim is
  still bounded to a redacted replay pack. It is not a production email parser
  result and not raw PST body extraction.

## Original And 100-Case Ablations

The original first-version fixture is still present:

```text
experiments/kg_ontology_v2_coordination/fixtures/email_cross_domain_cases.json
experiments/kg_ontology_v2_coordination/fixtures/gold_competency_answers.json
```

It remains a synthetic marker round-trip fixture. The runner now exposes it
under `ablation_versions.original_synthetic_marker_fixture` so it can be
compared against the redesigned hard challenge without overwriting history.

The redesigned hard challenge is a fixed 100-case redacted fixture:

```text
experiments/kg_ontology_v2_coordination/fixtures/challenge_redacted_100_cases.json
```

It is designed from ontology failure modes, not generated from raw PST parser
output. It has 30 dev cases and 70 holdout cases, with this failure-bucket
distribution:

| Failure bucket | Cases |
| --- | ---: |
| gate false reject | 20 |
| alignment suppressed | 15 |
| structure misleads | 15 |
| frame type confusion | 15 |
| cross-thread dependency | 10 |
| follow-up or fallback missing | 10 |
| false-positive guard | 10 |
| access or redaction boundary | 5 |

Two-version ablation result:

| Version | Arm | Exact / answerability | Slot-value F1 / recall | False positives | Hard false rejects |
| --- | --- | ---: | ---: | ---: | ---: |
| Original marker fixture | no ontology metadata only | 0.4375 CQ | 0.0 recall | n/a | n/a |
| Original marker fixture | current atom path | 0.09375 CQ | 0.0 recall | n/a | n/a |
| Original marker fixture | coordination frame v2 | 1.0 CQ | 1.0 recall | n/a | n/a |
| Original marker fixture | hybrid v1 gate + v2 projection | 1.0 CQ | 1.0 recall | n/a | n/a |
| 100-case hard challenge | KG without ontology | 0.46 exact | 0.801382 F1 | 11 | 0 |
| 100-case hard challenge | KG + current hard ontology | 0.22 exact | 0.329239 F1 | 0 | 30 |
| 100-case hard challenge | KG + soft ontology gate | 0.74 exact | 0.936396 F1 | 0 | 0 |
| 100-case hard challenge | Coordination frame v2 | 0.82 exact | 0.925859 F1 | 1 | 0 |
| 100-case hard challenge | Hybrid soft gate + v2 frame | 0.90 exact | 0.981133 F1 | 1 | 0 |

The 100-case fixture is also expanded inside the runner into a deterministic
10,000-case redacted stress benchmark:

```text
redacted_stress_benchmark_10000
```

This benchmark is generated from the fixed 100-case redacted templates rather
than committed as a large JSON fixture. The split is 1,000 dev cases and 9,000
holdout cases, with bucket counts scaled by 100:

| Failure bucket | Cases |
| --- | ---: |
| gate false reject | 2,000 |
| alignment suppressed | 1,500 |
| structure misleads | 1,500 |
| frame type confusion | 1,500 |
| cross-thread dependency | 1,000 |
| follow-up or fallback missing | 1,000 |
| false-positive guard | 1,000 |
| access or redaction boundary | 500 |

10,000-case generated stress result:

| Arm | Exact match | Slot-value F1 | False positives | Hard false rejects |
| --- | ---: | ---: | ---: | ---: |
| KG without ontology | 0.46 | 0.801382 | 1,100 | 0 |
| KG + current hard ontology | 0.22 | 0.329239 | 0 | 3,000 |
| KG + soft ontology gate | 0.74 | 0.936396 | 0 | 0 |
| Coordination frame v2 | 0.82 | 0.925859 | 100 | 0 |
| Hybrid soft gate + v2 frame | 0.90 | 0.981133 | 100 | 0 |

Interpretation:

- The first version is still useful as contract round-trip evidence, but it is
  not a hard generalization test.
- The redesigned 100-case challenge is harder: hybrid does best, but it does
  not solve all cases.
- The hard ontology regression remains visible at larger scale: hard ontology
  is `-0.24` exact-match points below KG without ontology.
- Soft gating recovers substantially over hard ontology (`+0.52`), and hybrid
  improves over KG without ontology by `+0.44`.
- The 10,000-case stress benchmark is useful for stability and count-level
  failure inspection, but it is generated from redacted template families. It
  is not an independent held-out PST/parser evaluation.

## Access And Granularity

Every candidate frame carries:

- source observation ids;
- evidence spans with locators and text hashes;
- an access boundary with permission scope and redacted slot names;
- an ontology revision id;
- a granularity level.

This keeps the frame reviewable as a coordination obligation. A request, a
blocker, and a deadline can be separated when they need different review or
follow-up behavior, while still sharing evidence and domain hints.

## PST Boundary

An ignored local private PST corpus can be useful as a future stress source,
but this slice does not parse or commit raw PST content. The recommended route
is:

```text
PST asset
  -> metadata inventory
  -> redacted derived fixture
  -> private evidence packet with local span hashes
```

Default tests use synthetic fixtures only. A future PST smoke should be
opt-in, metadata/redaction-first, and must not place raw message subjects,
bodies, attachments, filesystem paths, or mailbox identifiers in committed
artifacts.

## Limitations

- The current extractor is deterministic and fixture-oriented. It proves the
  contract and evaluation boundary, not production email understanding.
- The current experiment uses synthetic marker cases and a fixed redacted
  email replay pack, not raw PST body extraction.
- Domain packs are hand-authored fixture packs. The next iteration should
  generate candidate packs from document observations and evaluate them on a
  held-out fixture split.
- `CanonicalFrame` is only a contract target. A reviewed canonical frame commit
  workflow is still future work.
- Projection/view ontology is evaluated through competency questions only in
  this slice; it does not yet generate real follow-up queue or case progress
  graph views.
- The temporal implementation is a fast candidate-only POC. It does not yet
  provide full interval algebra, cross-assertion temporal cycle detection,
  temporal entity resolution, causal inference, SHACL execution, or canonical
  bitemporal PostgreSQL storage.
- The `KG alone > KG + current ontology` regression is reproduced on the fixed
  redacted replay pack. A production claim still requires the same comparison
  on real/private PST-redacted cases generated from the actual parser path.

## References

- FrameNet project: https://framenet.icsi.berkeley.edu/
- Multi-Sentence Argument Linking / RAMS: https://arxiv.org/abs/1911.03766
- DocRED document-level relation extraction: https://arxiv.org/abs/1906.06127
- W3C PROV overview: https://www.w3.org/TR/prov-overview/
- W3C SKOS reference: https://www.w3.org/TR/skos-reference/
