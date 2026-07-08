# Ontology Methodology Review: Why KG + Ontology Underperforms KG Alone

Review date: 2026-07-08.
Reviewed artifacts: `docs/ontology-v2-coordination-frames.md`,
`docs/ontology-v2-coordination-plan.md`,
`python/formowl_graph/ontology.py`,
`python/formowl_graph/coordination_frames.py`,
`experiments/kg_ontology_v2_coordination/fixtures/*`,
`experiments/kg_bert_ablation/run_ontology_ablation.py`, and
`docs/kg-research-method.md`.

Motivating observation from the maintainer: on real email processing, KG
beats no-KG, but KG plus the current v1 ontology performs worse than KG
alone. This review examines the whole methodology — v1 scoped type ontology
and the v2 coordination-frame proposal — identifies the mechanisms by which
the ontology lowers performance, and maps external methods from the
literature onto concrete FormOwl changes.

Post-review hardening update (retained from the first review round): the
evaluator now scores frames within each gold case's `observation_ids`,
`cq7_evidence` requires case-local evidence with a locator and `sha256:` text
hash, `slot_value_recall` scores expected slot values, regression tests cover
cross-case frame scoring plus incomplete evidence and wrong slot values, and
the runner includes a synthetic hard-gate vs soft-gate noisy-type ablation
scaffold. Those fixes address scoring bugs; the methodology analysis below
still applies.

## Verdict Summary

The v2 direction (frame semantics over noun labels for email coordination)
attacks a real problem, and the layering, candidate-only boundary, and
hybrid arm are the right engineering posture. But the regression the
maintainer observed is not caused by the ontology's vocabulary alone — it is
caused by **how and where the ontology is applied**, and v2 inherits that
part unchanged:

1. The v1 ontology acts as a hard filter keyed on an unmeasured, noisy
   attribute inside candidate generation. This converts typing noise into
   permanent recall loss that no downstream scoring can recover.
2. Score composition and fixed thresholds were never recalibrated for an
   ontology signal, adding a second silent recall drop.
3. The type system was designed for governance safety and never measured
   for email discriminability, so on email it sits near the worst point of
   the type-utility curve.
4. The ontology is enforced at extraction/candidate time when its
   governance value only requires enforcement at review/commit time.
5. Every internal evaluation measures the ontology under conditions where
   it cannot lose (oracle types, self-referential fixtures, no false-reject
   metric), which is why internal benchmarks disagree with production.

General law that falls out of this analysis: **any closed vocabulary applied
as a hard key at extraction time converts classification noise into
permanent loss.** v2 changes the vocabulary (frames instead of noun types)
but not the application pattern, so shipping v2 as designed would likely
reproduce the same regression at frame level.

## Part 1: Root Causes, Ranked By Likely Contribution

### RC1: The hard gate is deterministic blocking on a noisy key

`core_supertypes_compatible()` (`python/formowl_graph/ontology.py`) is the
only hard gate in v1: incompatible core supertypes make
`propose_type_alignment_candidate()` raise, so the pair is dropped before
scoring. In record-linkage terms this is a blocking/filtering step keyed on
a single attribute, and the blocking literature is unambiguous about the
design: errors in a blocking key cause **permanent, unrecoverable recall
loss** — no similarity-based method can recover links excluded by blocking,
and single-key exact-agreement blocking is "susceptible to field errors"
(references §5.1). Standard mitigations are unions of multiple blocking
keys or soft scoring, never a single intersection filter.

Nowhere in the pipeline is `core_supertype_id` predicted by a measured
component: assignments come from declared `TypeDefinition` records and
extraction heuristics, with no typing model, no confidence, and no measured
typing accuracy on email. The gate consumes an attribute of unknown
reliability as if it were ground truth. And on email the attribute is noisy
by nature, not by implementation accident: a "quote" is a Document, an
Artifact, or an Event depending on whether the mention refers to the file,
the deliverable, or the approval act; a meeting is an Event or a Document
(the minutes); a customer is a Person or an Organization. With per-mention
typing accuracy `p`, a true pair survives the gate with probability ≈ `p²`:
at `p = 0.85`, ~28% of true matches are silently destroyed before any
similarity scoring runs. KG without the ontology never pays this tax —
sufficient by itself to produce the observed ordering KG > KG+ontology.

### RC2: Threshold miscalibration after score dilution

`_score_from_breakdown()` averages all breakdown components with equal
weight (`sum/len`). Adding an ontology component to a breakdown that
previously held one or two strong lexical/embedding signals shifts the score
distribution downward wherever the type signal is weak or wrong — while the
downstream acceptance thresholds (`legacy_cpu_bert` 0.70,
`gpu_bge_large_en_v1_5` 0.62, per `docs/kg-research-method.md`) stay where
they were calibrated **without** that component. A fixed threshold over a
shifted distribution is a classic silent regression: the ontology signal can
be individually informative and still lower end-to-end recall because the
operating point no longer matches the distribution. Any ablation that
toggles the ontology without recalibrating the threshold per arm confounds
signal quality with threshold mismatch.

### RC3: The type system was designed for governance, never measured for discrimination

The 8 closed supertypes (with a single ancestor edge
`Document -> Artifact`) were chosen to prevent governance failures such as
person-vs-document false merges. They were never evaluated for whether they
carve **email content** at its joints. DeepType's central result (§5.2) is
that the type system itself is the design variable: it selects the type
partition by directly optimizing disambiguation utility, because
hand-designed partitions frequently have negative utility under predicted
types. Email content is dominated by coordination semantics — requests,
commitments, deadlines, approvals, statuses — which all collapse into
`Concept`/`Document`/`Artifact` under the v1 lattice. Two consequences:

- when everything maps to the same one or two supertypes, the gate carries
  no information (pure cost, no benefit);
- when the mapping is arbitrary between adjacent supertypes, the gate is
  actively destructive (RC1 fires).

Either way, on email v1 sits near the worst point of the type-utility
curve. This is the deepest answer to "why does adding the ontology make it
worse": **a type constraint only helps when the type system fits the domain
and the type assignments are reliable; on email, v1 has neither.** The
ontology-guided-extraction literature reports the same trade-off from the
other side: constraining to a target schema hurts when the text carries a
richer ontology than the schema (§5.3).

### RC4: The ontology is applied at the wrong stage

The Extract-Define-Canonicalize line of work (§5.3) shows that
schema-constrained extraction underperforms **open extraction followed by
post-hoc canonicalization**, especially when the schema is large,
ill-fitting, or absent. AutoSchemaKG (§5.4) goes further: schemas induced
from the corpus post-hoc reach 92% semantic alignment with human-crafted
schemas with zero manual work.

FormOwl's own architecture already contains the right place for the
ontology: the review/adjudication/canonicalization layer, explicitly
documented as "the decision layer". The methodology error is that the
ontology **also** acts inside candidate generation as a hard pre-filter.
Governance requires that nothing wrong becomes canonical; it does not
require that candidates be destroyed before review. A gate that annotates
(`type_conflict=true`, demoted rank) instead of deleting preserves the
entire governance guarantee while removing the recall damage. The
ontology's governance value lives at commit time; its current cost is paid
at candidate time; the two are separable and the methodology conflates
them.

### RC5: The evaluation methodology is structurally blind to the damage

Every ontology evaluation in the repo evaluates the gate under conditions
where it cannot lose:

- **Oracle typing.** The 20k ontology ablation
  (`experiments/kg_bert_ablation/run_ontology_ablation.py`) assigns
  `core_supertype` from the source family — gold labels — and constructs
  its cross-type hard negatives **from the same type labels the gate
  checks**. The gate trivially removes exactly the negatives injected by
  its own criterion; typing noise is never simulated. The headline result
  (F1 +0.41, 10,000 cross-type false positives removed) measures the gate
  under oracle typing; production runs it under unmeasured predicted
  typing. Both that result and the production regression can be true at
  once.
- **No false-reject instrument.** No metric anywhere counts true pairs the
  gate destroys on realistic data. False positives removed are counted and
  celebrated; false negatives created are invisible. A methodology whose
  instruments can only register a component's benefit and never its cost
  will always conclude the component helps.
- **Self-referential v2 fixtures.** The v2 fixture observations in
  `email_cross_domain_cases.json` are literally written in the
  deterministic extractor's input grammar
  (`Request: actor=...; deadline=...;` parsed by `_parse_frame_line()`), so
  the v2 arm's 1.0 scores are a serialization round trip. The CQ
  answerability metric is defined in v2's own schema (frame_type + slot
  lookups), so arm 0 and arm 1 lose by construction — the current atom
  path's low score (0.09375 after the case-local scoring fix) measures
  schema mismatch, not capability. The arm that matters most is absent:
  the actual production "KG without ontology" path that beats KG+ontology.

The production regression is the first measurement not subject to this
selection effect — which is why it disagrees with every internal benchmark.

### Interaction note

RC1–RC4 compound: an ill-fitting type system (RC3) raises the typing error
rate, the hard gate (RC1) converts every typing error into permanent recall
loss, score dilution plus stale thresholds (RC2) remove further borderline
true pairs, and stage misplacement (RC4) means none of this loss is
recoverable at review. The blind evaluation (RC5) then reports the sum as
an improvement.

## Part 2: What v2 Fixes And What It Inherits

What v2 gets right relative to the root causes:

- **RC3 (vocabulary misfit) is the one v2 genuinely attacks.** Coordination
  frames are far closer to what email actually contains than noun
  supertypes. The frame core closely matches the email speech-act
  literature (Request/Commit/Propose/Deliver — §5.5), which independently
  validates the direction. The mention-vs-obligation distinction is the
  right competency question for email.
- The candidate-first boundary, evidence spans with hashes, access
  boundaries with redacted slots, ontology revision pins, and the
  domain-pack rule "must map to a core frame or stay a review-required
  candidate" are all correct and consistent with FormOwl governance.

What v2 inherits unchanged:

- **RC1, RC2, RC4 are untouched.** The hybrid arm keeps the v1 hard gate
  and the same score/threshold machinery. If RC1/RC2 drive the production
  regression, v2 ships and the regression persists.
- **The same design pattern at a new level.** v2 applies a hand-authored
  closed schema (16 frame types, hand-written domain packs) at extraction
  time and evaluates with schema-referential metrics. Frame-type confusion
  will play the role typing noise plays in v1: Blocker / Issue / Risk /
  Exception, StatusUpdate / StatusChange / Change, and Request /
  OpenQuestion are highly confusable — the plan document itself leaves
  `ShipmentDelay -> Issue or Blocker` undecided — and the competency
  evaluator looks up frames by exact `frame_type` match, so a frame
  extracted with the "wrong" sibling type hard-misses every downstream
  lookup. v2 already contains its own version of the v1 gate.
- **`object_supertype` on `CandidateBusinessObject` is RC3 one level up.**
  A closed forced-choice typing decision that will be noisy on real email
  exactly the way core supertypes are today. No future code path should
  hard-gate on `object_supertype` equality, or a v3 will be written for the
  same reason as v2.
- **Layer 3 is measured by proxy.** Projection readiness is scored via the
  schema-referential CQ metric; the plan should not describe Layer 3 as
  "evaluated" until a follow-up queue is generated and checked against a
  gold queue.

## Part 3: External Methods Mapped To FormOwl Changes

### 3.1 Demote the gate: soft, confidence-weighted type priors

Sources: NEST soft type constraints; DeepType; blocking literature (§5.1,
§5.2). Type compatibility becomes a weighted score feature with per-mention
type confidence; hard reject only when **both** endpoint confidences exceed
a high threshold **and** the supertypes conflict. The repo now has a
`soft_core_supertypes_compatible()` scaffold with exactly this shape; the
remaining work is (a) an actual typing-confidence source, (b) fitting the
multiplier/threshold on labeled email pairs instead of the hand-set
0.65/0.9, and (c) wiring it into the production candidate path, not just
experiments. If gating is ever needed for scale, use a union of multiple
blocking keys (type ∪ lexical block ∪ embedding block), never type as the
sole intersection filter. Recalibrate acceptance thresholds per
configuration on a fixed validation set (fixes RC2).

### 3.2 Select the type system empirically (DeepType pattern)

Treat the partition as a variable rather than freezing 8 supertypes (v1) or
16 frame types (v2) a priori: on a labeled email matching set with
**predicted** types, greedily merge/split supertypes or frame types to
maximize end-task F1. Types that annotators or extractors cannot reliably
distinguish get merged. This gives a principled answer to "should
Blocker/Issue/Risk be three types or one" instead of a design-taste answer.
The email speech-act literature did exactly this: its final taxonomy was
iterated against inter-annotator agreement, merging acts annotators
confused (§5.5).

### 3.3 Move the ontology to post-hoc canonicalization (EDC pattern)

Restructure the candidate path as extract-open → define → canonicalize:

```text
Observation
  -> open extraction (no schema constraint; free-form relation/frame phrases)
  -> define (self-describe each extracted item)
  -> canonicalize (align to core supertypes / coordination frames via
     embedding retrieval over the ontology; unalignable items stay
     candidates flagged for review — never dropped)
  -> review / adjudication (existing FormOwl decision layer; ontology
     enforced HERE, at commit time)
```

Every governance guarantee is kept (nothing canonical without passing the
ontology at review) while the extraction-time constraint — the performance
cost the literature identifies — is removed. This fits FormOwl's
candidate-first philosophy better than the current design does.

### 3.4 Induce domain packs from the corpus (AutoSchemaKG pattern)

The v2 plan already flags hand-authored domain packs as a limitation.
Generate candidate packs from document/email observations via LLM
conceptualization, validate on a held-out fixture split, and keep the
existing review-required governance for pack acceptance. Also add a
cardinality/lifecycle constraint: nothing currently prevents 500 packs with
one frame each; require review on pack creation, not only on frame-to-core
mapping.

### 3.5 Ground Layer 1 in the email speech-act literature

Cohen, Carvalho & Mitchell's email speech acts are the direct ancestor of
v2's coordination frames, with three transferable results: taxonomy
iteration against annotator agreement (§3.2); thread context — sequential
correlation between messages in a thread significantly improves act
classification, so the v2 extractor should consume threads, not isolated
messages; and follow-up intent-identification work provides ready
evaluation designs for the issue #28 competency questions. `Approval` is
arguably a distinct primitive from `Decision` in enterprise workflows (it
has a required approver role and a pending state) and worth considering for
the core.

### 3.6 Dual metrics: conformance AND faithfulness, plus a false-reject counter

Text2KGBench separates ontology conformance (output fits the schema) from
faithfulness (output grounded in the source text). The v2 evaluator
measures conformance-shaped quantities; the deterministic 1.0 results are
conformance scores. Adopt both axes, keep `slot_value_recall`, and add the
missing instrument from RC5 — a gate-false-reject counter — so every future
ontology mechanism is charged for its recall cost, not only credited for
its precision benefit. Where arms have different output schemas, grade
competency answers representation-neutrally (rubric or LLM judge) instead
of looking up v2-shaped objects.

### 3.7 Use the ontology where it can only help: retrieval/projection

OG-RAG grounds **retrieval** in an ontology (hypergraph fact clusters) and
improves factuality without constraining extraction. For FormOwl this maps
to Layer 3: use frames/ontology to cluster and route evidence for follow-up
queues and case views. At this layer the ontology filters nothing
irrecoverably, so its failure mode is graceful.

## Part 4: Recommended Order Of Work

1. **Instrument first (cheap, decisive).** Add gate-false-reject counting
   and per-arm threshold recalibration to the existing benchmark harness;
   extend the ontology ablation with a typing-noise sweep (flip x% of core
   supertypes and plot gate impact vs noise). This turns the production
   regression into a measured, attributable quantity and tests RC1/RC2
   directly. Complement it with a bucketed error analysis of 50–200 real or
   PST-redacted cases where KG-alone answered correctly and KG+ontology did
   not (`gate_false_reject` / `alignment_suppressed` / `structure_misleads`
   / `other`).
2. **Soft gate in the production path.** Wire
   `soft_core_supertypes_compatible()` into candidate generation with a
   real confidence source; fit its parameters on labeled email pairs. The
   smallest change that can plausibly recover the regression.
3. **Restructure v2 extraction as extract-open → canonicalize** (§3.3) so
   v2 does not re-create the v1 failure at frame level; evaluate with
   conformance + faithfulness + false-reject metrics (§3.6) and include the
   real production no-ontology arm.
4. **Empirical taxonomy iteration** for the frame core (§3.2, §3.5) using
   thread-aware extraction on 30–50 redacted real emails with
   human-verified gold frames held out from prompt development, scored
   with slot-value F1 — the first non-circular v2 datapoint. The success
   criterion for steps 1–4 should be the same downstream email metric that
   exposed the regression.
5. **Domain-pack induction** (§3.4) and projection-layer grounding (§3.7)
   after the above are stable.

Acceptance-criteria amendments for the v2 slice:

- Add: "the production regression (KG+ontology < KG on email) is reproduced
  on a fixed case set and decomposed by failure bucket."
- Add: "gate false-rejects are counted under a typing-noise sweep."
- Add: "at least one arm is the real production no-ontology KG path."
- Reword the results tables in both v2 documents to label the v2 1.0 scores
  as round-trip contract verification, not comparative performance.

## Part 5: References

### 5.1 Blocking / record linkage (RC1, §3.1)

- A Comparison of Blocking Methods for Record Linkage:
  https://arxiv.org/pdf/1407.3191
- Efficient Record Linkage in the Age of LLMs — The Critical Role of
  Blocking: https://www.mdpi.com/1999-4893/18/11/723
- Record linkage overview: https://en.wikipedia.org/wiki/Record_linkage
- Entity resolution blocking practice notes:
  https://www.zingg.ai/post/entity-resolution-at-scale-part-3-blocking

### 5.2 Type systems and type constraints in linking (RC3, §3.1, §3.2)

- DeepType: Multilingual Entity Linking by Neural Type System Evolution:
  https://arxiv.org/abs/1802.01021
- NEST: Neural Soft Type Constraints to Improve Entity Linking in Tables:
  https://ebooks.iospress.nl/volumearticle/57404
- Entity Linking Meets Deep Learning (survey):
  https://arxiv.org/pdf/2109.12520

### 5.3 Schema-constrained vs open extraction (RC4, §3.3)

- Extract, Define, Canonicalize: An LLM-based Framework for KG
  Construction (EMNLP 2024): https://arxiv.org/abs/2404.03868 /
  https://aclanthology.org/2024.emnlp-main.548/
- LLM-empowered knowledge graph construction: A survey (schema-based vs
  schema-free paradigms): https://arxiv.org/abs/2510.20345
- ODKE+: Ontology-Guided Open-Domain Knowledge Extraction with LLMs:
  https://arxiv.org/pdf/2509.04696
- TextMineX (documents the richer-ontology-than-schema trade-off):
  https://arxiv.org/pdf/2509.15098

### 5.4 Schema induction (§3.4)

- AutoSchemaKG: Autonomous KG Construction through Dynamic Schema
  Induction (ACL 2026): https://arxiv.org/abs/2505.23628 /
  https://github.com/HKUST-KnowComp/AutoSchemaKG

### 5.5 Email coordination semantics (§3.5)

- Learning to Classify Email into "Speech Acts" (Cohen, Carvalho,
  Mitchell, EMNLP 2004):
  https://www.semanticscholar.org/paper/bd24b47165407a8b2d32016645ca71f7c9213636
- On the Collective Classification of Email "Speech Acts" (SIGIR 2005):
  https://dl.acm.org/doi/10.1145/1076034.1076094
- Context-Aware Intent Identification in Email Conversations (SIGIR
  2019): https://dl.acm.org/doi/pdf/10.1145/3331184.3331260

### 5.6 Evaluation and retrieval grounding (§3.6, §3.7)

- Text2KGBench: A Benchmark for Ontology-Driven KG Generation from Text
  (ISWC 2023): https://arxiv.org/abs/2308.02357
- OG-RAG: Ontology-Grounded Retrieval-Augmented Generation (Microsoft,
  2024): https://arxiv.org/abs/2412.15235

## Appendix: Answers To The v2 Plan's Review Questions

1. *Additive and reversible?* Structurally yes — candidate-only stores, no
   canonical writes, v1 untouched. But `DomainPackDefinition` packs pinned
   to ontology revisions are a second ontology registry in practice.
   Reversibility should be tested by deleting the v2 stores and rerunning
   the v1 suite, named in the acceptance criteria.
2. *Core types too broad/narrow?* Too many confusable siblings (Part 2);
   resolve empirically per §3.2, and consider `Approval` as a primitive
   distinct from `Decision`.
3. *Domain packs constrained enough?* The mapping rule is good; add a
   cardinality/lifecycle constraint and review on pack creation (§3.4).
4. *Is CQ answerability the right primary metric?* The concept is right;
   the implementation must become representation-neutral and value-aware
   (§3.6). `slot_value_recall` is a good first step.
5. *PST plan?* The redaction-first boundary is sound. One gap: span hashes
   over redacted derived fixtures cannot verify against original bodies
   unless hashing happens before redaction on the private side; specify
   where the hash is computed.
6. *Is the hybrid path credible?* As a deployment strategy yes, but the
   hybrid arm keeps the v1 hard gate, so it inherits RC1/RC2. Run the
   hybrid arm in two variants: hard gate and soft gate.
7. *Minimal next experiment?* Not a bigger synthetic fixture — steps 1 and
   2 of Part 4 (instrumented regression reproduction, then soft-gate vs
   hard-gate under predicted types), followed by the 30–50 redacted-email
   gold set as the first non-circular v2 datapoint.
