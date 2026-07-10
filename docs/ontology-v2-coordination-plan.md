# Ontology v2 Coordination Plan

This is the current working plan for issue #28. It is written as a review
packet for another model or reviewer. It describes what I am implementing now,
what evidence the current slice can support, and what must remain future work.

## Objective

Design and test a stable ontology method for cross-document, cross-department
enterprise knowledge graph construction. The goal is not to add more labels to
the current ontology. The goal is to introduce a coordination-frame method that
can recover business coordination semantics from mixed sources such as email,
meeting transcripts, project issues, documents, and chat logs.

The core abstraction should answer:

```text
Who requested what?
Who committed to what?
What was decided?
What changed status?
What is blocked?
What is at risk?
Which deadline matters?
Which evidence supports the frame?
Which domain does this belong to?
Is this only a mention, or does it create an obligation?
What should appear in follow-up or progress views?
```

## Current Diagnosis

The existing FormOwl ontology is useful but incomplete:

```text
Core type + extension type + promoted type
```

That path is a scoped type-governance layer. It is good for avoiding false
matches such as person-vs-document or customer-vs-project. It is not enough for
enterprise coordination because it mostly extends nouns, not process semantics.

Current limitations:

- `CandidateAtom` and `CandidateRelation` are too flat for mixed
  email/document coordination.
- Existing type governance can say a `Quote` is a work object, but not who
  requested the quote revision, who owns the follow-up, which blocker gates it,
  what fallback plan exists, or which evidence span supports the obligation.
- Email cannot be modeled as a domain. Email is a communication substrate that
  carries many domains at once.
- Adding labels such as `Invoice`, `Shipment`, `Requirement`, or `Complaint`
  still does not model the frames and roles around approvals, commitments,
  blockers, deadlines, and escalations.

## Target Method

Use an evidence-backed coordination-frame ontology:

```text
Layer 0: Evidence / source ontology
Layer 1: Stable coordination-frame core
Layer 2: Scoped domain object packs
Layer 3: Projection / view ontology
```

### Layer 0: Evidence / Source

Reuses the current FormOwl source-preserving model:

- `Asset`
- `Observation`
- `EvidenceSnapshot`
- `Citation`
- `PermissionScope`
- evidence span locators and text hashes

No raw filesystem paths, NAS paths, raw PST content, object-store internals, or
worker scratch paths may appear in public graph outputs.

### Layer 1: Stable Coordination Core

The closed core currently being tested:

```text
Request
Commitment
Decision
Assignment
StatusUpdate
StatusChange
Blocker
Risk
Issue
OpenQuestion
Deadline
Dependency
Escalation
Change
Exception
Constraint
```

This layer should change slowly. It is the cross-domain coordination vocabulary
used by email, meetings, project issues, documents, wiki sections, and chat
transcripts.

### Layer 2: Scoped Domain Packs

Domain packs add local business objects and domain-specific process frame
names. They must extend the coordination core.

Examples:

```text
QuoteApproval -> Decision
InventoryShortage -> Blocker
ShipmentDelay -> Issue or Blocker
InvoiceApproval -> Decision
FirmwareCapabilityQuestion -> OpenQuestion
CustomerCommitment -> Commitment
```

A domain pack must not create a parallel ontology bypassing the core. If a
domain-specific frame cannot map to a stable coordination core frame, it should
remain a candidate requiring review, not become a new canonical core concept.

### Layer 3: Projection / View

Views are derived projections, not primary ontology:

```text
FollowUpQueueView
DecisionLogView
RiskRegisterView
CaseProgressView
CustomerHistoryView
ShipmentTrackerView
RequirementTraceView
ProjectHubView
```

This slice evaluates projection readiness through competency-question
answerability. It does not yet implement production follow-up queue or case
progress view generation.

## Proposed Data Path

The target candidate path is:

```text
Observation
  -> CandidateMention
  -> CandidateFrame
  -> CandidateBusinessObject
  -> CandidateRelation
  -> reviewed CanonicalFrame / CanonicalObject / CanonicalRelation
  -> UserGraph
  -> WikiProjection
```

The current slice implements only candidate contracts, candidate stores, a
deterministic fixture extractor, a domain-pack loader, and an experiment
runner. It intentionally does not implement canonical frame commit.

## Current Implementation Scope

Implemented or being implemented in this slice:

- `COORDINATION_FRAME_TYPES`
- `COORDINATION_OBJECT_SUPERTYPE_IDS`
- `CandidateMention`
- `CandidateBusinessObject`
- `CandidateFrame`
- `CanonicalFrame` contract target
- stable id helpers for the above
- validators for frame type, object supertype, evidence spans, access boundary,
  provenance, review state, confidence, and raw-reference rejection
- file-backed candidate stores:
  - `CandidateMentionStore`
  - `CandidateBusinessObjectStore`
  - `CandidateFrameStore`
- `DomainPackDefinition`
- deterministic coordination-frame extractor for controlled fixtures
- four-arm answerability experiment
- synthetic email-first cross-domain fixtures
- contract, extraction, storage, and experiment tests
- design note and method documentation

Not implemented in this slice:

- production email/PST body parser
- document-generated domain-pack induction from real private corpus
- canonical frame commit workflow
- canonical frame store
- user graph assembly from frames
- production follow-up queue or case progress projection
- UI/reviewer task cards for frame review
- enterprise-scale latency or extraction-quality claims

## Experiment Design

Experiment directory:

```text
experiments/kg_ontology_v2_coordination/
```

Runner:

```sh
python experiments/kg_ontology_v2_coordination/run_coordination_frame_experiment.py
```

Fixtures:

- `fixtures/email_cross_domain_cases.json`
- `fixtures/gold_competency_answers.json`

### Experimental Arms

Arm 0: `no_ontology_metadata_only`

- Parses marker-like observations into surrogate metadata frames.
- Does not have stable frame semantics or slots.
- Tests what happens when the system has source metadata but no ontology.

Arm 1: `current_atom_path`

- Uses the existing deterministic `CandidateAtom` marker path.
- Represents the current flat atom baseline.
- Can receive limited partial credit only where the gold question explicitly
  allows v1 partial credit.

Arm 2: `coordination_frame_v2`

- Uses `CandidateMention`, `CandidateFrame`, and `CandidateBusinessObject`.
- Requires evidence spans, access boundaries, domain hints, and ontology
  revision id.
- This is the main v2 method under test.

Arm 3: `hybrid_v1_type_gate_v2_projection`

- Retains the current atom/type-gate path as a compatibility signal.
- Uses v2 frames for competency answerability and projection readiness.
- This is likely the most practical migration path because it does not require
  deleting v1 type governance.

### Fixture Scenarios

The synthetic fixture currently covers four issue-required scenarios:

1. Sales + R&D
   - quote request
   - firmware capability blocker
   - fallback plan
   - customer-facing deadline

2. Warehouse + Production
   - material shortage
   - work-order impact
   - production delay
   - owner assignment

3. Finance + Sales
   - invoice/payment issue
   - customer commitment
   - approval decision
   - risk or escalation

4. Management / Project coordination
   - decision
   - action item / assignment
   - dependency
   - open question

### Metrics

Current implemented metrics:

- candidate frame count
- candidate atom count
- frame type recall
- slot recall
- slot value recall
- competency-question answerability score
- per-question answerability status
- provenance completeness
- candidate-only claim boundary
- unauthorized slot leak count
- synthetic hard-gate vs soft-gate noisy-type ablation

Planned next metrics:

- frame precision and recall against manually reviewed fixtures
- slot partial F1
- evidence span F1
- redaction-correct answerability
- follow-up queue precision/recall
- domain-pack generalization on held-out documents
- granularity validity and split/merge pressure
- reviewer disagreement rate

## Current Contract Round-Trip Snapshot

Host-side and dev-container focused tests both pass for the current synthetic
fixture. This is a contract round-trip result over deterministic marker
fixtures, not production extraction evidence or proof that v2 fixes the real
email regression.

| Arm | Candidate frames | Candidate atoms | Slot recall | Slot value recall | CQ answerability |
| --- | ---: | ---: | ---: | ---: | ---: |
| no ontology metadata only | 13 surrogate frames | 0 | 0.0 | 0.0 | 0.4375 |
| current atom path | 0 | 2 | 0.0 | 0.0 | 0.09375 |
| coordination frame v2 | 13 | 0 | 1.0 | 1.0 | 1.0 |
| hybrid v1 gate + v2 projection | 13 | 2 | 1.0 | 1.0 | 1.0 |

Interpretation:

- The current atom path can recover only a small part of the fixture because it
  treats the examples as flat labels.
- The no-ontology metadata path sees source structure but cannot recover slots
  or frame semantics.
- The v2 path recovers the required frame/slot structure because the synthetic
  fixture is written in the deterministic frame marker format.
- This result proves the contract and evaluation shape. It does not prove
  production extraction quality or comparative production performance.

Evaluator hardening now binds scoring to each gold case's `observation_ids`.
A frame from another case cannot satisfy a question or slot requirement for
the current case. The evidence competency question also sets
`required_evidence=true`, so a frame with missing locator/text hash or only
out-of-case evidence can receive at most partial credit.
The report now includes `slot_value_recall`, and the tests prove that a frame
with the right slot key but wrong slot value no longer receives full quality
credit.

Claude's review correctly identified that the motivating email regression has
not been reproduced by the synthetic marker fixture. The runner now includes a
fixed redacted replay pack that evaluates the regression pattern without raw
PST content:

```text
experiments/kg_ontology_v2_coordination/fixtures/regression_redacted_cases.json
```

The fixed redacted replay uses representation-neutral answer scoring over five
arms:

- `kg_without_ontology`
- `kg_hard_ontology`
- `kg_soft_ontology_gate`
- `coordination_frame_v2_redacted`
- `hybrid_soft_gate_v2_frame`

Current effectiveness result:

| Arm | Exact match | Slot-value F1 | False positives | Hard false rejects |
| --- | ---: | ---: | ---: | ---: |
| KG without ontology | 0.666667 | 0.914286 | 1 | 0 |
| KG + current hard ontology | 0.166667 | 0.260870 | 0 | 2 |
| KG + soft ontology gate | 0.666667 | 0.787879 | 0 | 0 |
| Coordination frame v2 | 1.0 | 1.0 | 0 | 0 |
| Hybrid soft gate + v2 frame | 1.0 | 1.0 | 0 | 0 |

This fixed replay now reproduces the hard ontology regression:
`KG + current hard ontology` is 0.5 exact-match points below
`KG without ontology`. Soft gating removes the two hard false rejects and
recovers to KG-without-ontology exact match. v2 and hybrid both reach exact
match `1.0` on this fixed replay. This is an effectiveness signal, but still
not a production parser or raw PST extraction claim.

The next production-quality experiment is now narrower:

```text
Private real/PST-redacted parser output
  -> same fixed answer rubric
  -> same five arms
  -> same failure buckets
  -> same slot-value/evidence scoring
```

## PST Usage Plan

An ignored local private PST corpus is available as a future stress source, but
it is not used in the default tests or committed experiment fixtures.

Safe PST plan:

```text
PST asset
  -> metadata inventory
  -> redacted derived fixture
  -> private evidence packet with local span hashes
  -> optional non-default smoke test
```

Rules:

- Do not commit raw message subjects, bodies, attachments, mailbox ids, sender
  addresses, recipient addresses, raw folder paths, or PST export paths.
- Do not use full `readpst` export by default.
- Default unit tests must stay synthetic and small.
- Future PST smoke must be opt-in, metadata/redaction-first, and must clean up
  scratch output.
- BCC, attachment occurrence, and folder occurrence must be treated as access
  boundary stress cases.

## Governance Boundary

Every output in this slice is candidate-only:

- canonical graph write allowed: false
- canonical type write allowed: false
- raw asset access granted: false
- user graph mutation: false
- wiki revision mutation: false
- PST raw content included: false

The correct future canonical path is reviewed commit:

```text
CandidateFrame
  -> frame review / split / merge / reject / approve
  -> entity and relation resolution
  -> policy pins
  -> CanonicalFrame / CanonicalObject / CanonicalRelation
  -> graph revision
```

## Risks And Mitigations

Risk: the deterministic fixture is too easy.

Mitigation: treat it as a contract/evaluation proof only. Next iteration should
derive redacted fixtures from real documents or PST metadata/body spans and keep
a held-out split.

Risk: domain packs become a new uncontrolled label registry.

Mitigation: enforce that domain frames extend stable core frames and domain
objects extend coordination object supertypes. Keep generated packs scoped,
candidate-only, and review-required.

Risk: coordination frames become too coarse.

Mitigation: keep `granularity_level`, evidence spans, and separate frame ids.
Requests, blockers, deadlines, and assignments should be independently
reviewable when they have different owners, deadlines, evidence spans, or
follow-up behavior.

Risk: coordination frames become too fine.

Mitigation: add future merge/coarsening proposals based on repeated display,
shared evidence, shared owner/deadline, and projection behavior. Do not silently
rewrite canonical frames.

Risk: access leaks from email/PST.

Mitigation: public artifacts store hashes, locators, redacted slots, and
permission scopes only. Raw body or attachment content must remain behind
FormOwl asset/evidence access checks.

Risk: v2 appears to replace v1 type governance.

Mitigation: keep v1 as baseline and hybrid type-gate signal. v2 is additive in
this branch.

## Acceptance Criteria For This Slice

This slice should be considered complete only when:

- contract models and stable ids exist for candidate mentions, frames, business
  objects, and canonical frame target shape;
- validators reject missing evidence spans, invalid frame types, invalid object
  supertypes, raw references, missing provenance, and malformed access
  boundaries;
- domain packs cannot bypass the coordination core;
- synthetic email-first fixtures cover at least Sales/R&D,
  Warehouse/Production, Finance/Sales, and Management/Project scenarios;
- experiment compares current path, no-ontology baseline, v2 path, and hybrid;
- report evaluates competency answerability, not only entity matching;
- candidate stores persist only candidate collections;
- tests prove no canonical/user graph/wiki mutation in this slice;
- dev-container focused tests and full unittest pass;
- KG acceptance suite still reports only the expected explicit limits;
- reviewer gate passes for engineering, governance/safety, and research method.

## Current Verification State

Current checks already run after the case-bounded evaluator, slot-value
scoring, soft-gate ablation scaffold, neutral round-trip acceptance key names,
raw-reference guard fixes, and 100-case hard challenge addition:

```text
Host:
  PYTHONPATH=python python3 -m unittest discover -s tests -p 'test_coordination_frame*.py'
  -> 22 tests OK
  PYTHONPATH=python python3 -m unittest discover -s tests -p 'test_ontology_contract.py'
  -> 5 tests OK

Dev container:
  python -m unittest discover -s tests -p 'test_coordination_frame*.py'
  -> 25 tests OK
  python -m unittest discover -s tests -p 'test_ontology_contract.py'
  -> 5 tests OK
  python experiments/kg_ontology_v2_coordination/run_coordination_frame_experiment.py
  -> passed
  python -m unittest discover -s tests
  -> 372 tests OK
  ruff check python tests scripts experiments/kg_ontology_v2_coordination
  -> passed
  ruff format --check python tests scripts experiments/kg_ontology_v2_coordination
  -> 168 files already formatted
  python scripts/kg_research_acceptance_suite.py
  -> passed_with_explicit_limits, only expected limits remain

Patch whitespace:
  git diff --check
  -> passed
```

Reviewer gate state:

- Candidate-layer contract slice gate passed 3/3: `Huygens` agreed on
  engineering correctness, `Archimedes` agreed on governance/safety, and
  `Volta` agreed on research method after blocker fixes.
- Redacted-effectiveness gate passed 3/3: `Hume` agreed on engineering
  correctness after optional five-arm key-set hardening was added, `Avicenna`
  agreed on governance/safety after external input path and private test-data
  path blockers were fixed, and `Carver` agreed on research method.
- Final issue #28 effectiveness update was posted as comment `4912426980`.

## Questions For Review

The most useful review questions for Claude or another reviewer:

1. Is the v2 method truly additive and reversible, or does it accidentally
   create a parallel canonical ontology?
2. Are the coordination-frame core types too broad, too narrow, or missing a
   critical enterprise coordination primitive?
3. Are domain packs constrained enough to avoid becoming another label
   registry?
4. Is competency-question answerability the right primary metric for this
   issue, or should slot/evidence F1 dominate even in this early slice?
5. Does the PST plan preserve enough real-evidence value without leaking raw
   private content?
6. Is the hybrid migration path credible: current type gate plus v2 frame
   projection?
7. What minimal next experiment would best test generalization beyond
   deterministic synthetic fixtures?
