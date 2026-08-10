# Hybrid KG + Ontology v2 R&D Architecture Boundary

**Status:** Track 2 / GitHub issue #33 research handoff; architecture and
bounded-POC contract only.  This is **not** a runtime migration, UAT result,
methodology-readiness claim, production design approval, or a v3 proposal.

**Frozen target:** `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` with
`jieba_sentencepiece_frozen_profile_candidate_admission_v1`.

**Authority at handoff:** `docs/methodology-authority.json` is valid but
`blocked`.  The checked runtime remains
`mail_candidate_kg_broad_ontology_diagnostic_v1` with
`ascii_identifier_regex_v1`; the target runtime, complete-source coverage,
execution-bound reports, same-pipeline real-source ablation, and real
end-answer acceptance are all unresolved.  Do not call this methodology ready
or compare KG with KG-plus-ontology for quality until
`python3 scripts/methodology_authority_check.py --require-ready` succeeds.

## 1. Scope, safety, and ownership

This document defines the boundary between deterministic query execution,
candidate KG/ontology research, and governed canonical knowledge.  It is
written from public repository contracts and the local issue #33/coordinator
summary only.  It deliberately excludes MAY/private evidence, raw PST content,
private manifests, expected-answer bindings, raw paths, UAT web/sidecar work,
runtime/deployment changes, and parser operations.

The only permitted Track 2 outputs before a separate implementation assignment
are public/redacted designs, reproducible candidate-only experiment artifacts,
and bounded POC plans.  They must not mutate canonical graph/type/user-graph or
wiki state, grant raw access, or make business decisions.

The layer separation remains:

```text
Asset / EvidenceSnapshot
  -> ExtractorRun -> Observation
  -> semantic/term/type/relation/frame candidates
  -> review and scoped governance
  -> canonical graph revision
  -> user/effective graph view
  -> evidence, exact-set, reasoning, or projection result
```

An extractor, tokenizer, LLM, embedding model, or graph algorithm may only
produce observations or candidates.  It cannot directly create canonical
truth.  Entity matching does not grant access; data access does not authorize a
canonical merge; canonical graph visibility does not grant raw asset access.

## 2. Query-class router

Route a request before retrieval or generation.  A request may have one primary
class only; compound requests are split into independently auditable subplans.
A model may propose a plan, but a schema validator and router choose the class.

| Query class | Typical intent | Authoritative execution path | KG/ontology role | Forbidden claim |
| --- | --- | --- | --- | --- |
| `exact_set_or_inventory` | “all”, “every”, distinct list, count, bounded inventory | Deterministic governed executor over declared source schema and coverage contract | Validate declared schema/revision; explain returned rows only | KG-derived membership, fuzzy expansion, inferred complete count, or an unqualified absence claim |
| `evidence_lookup` | Locate statements, records, observations, or citations | Permission-filtered observation/evidence retrieval | Candidate ranking, relation-aware retrieval, type/frame scoring | Corpus completeness, final business correctness, or access to hidden evidence |
| `relation_reasoning` | Why/how related, dependencies, actor/object/temporal relations | Provenance-constrained graph traversal plus cited evidence | Candidate relation/frame traversal and scored explanation | Unreviewed relation as canonical fact, hidden-endpoint disclosure, or coverage-complete answer |
| `global_summarization` | Summarize a declared corpus, thread, project, or effective view | Bounded, permission-filtered source/evidence set | Organize themes, frames, and uncertainty | “all sources”, exhaustive state, or canonicalization from summary text |

### Router rules

1. Route to `exact_set_or_inventory` if the requested answer contains an
   exhaustive quantifier, a cardinality/count, a distinct projection, or a
   governed closed inventory predicate.  Ambiguous “list” requests default to
   evidence lookup unless the user confirms an inventory scope.
2. Route to `evidence_lookup` when the requested output is cited source
   evidence, even if KG ranking is used.
3. Route to `relation_reasoning` only when each asserted hop can be returned as
   a visible candidate/canonical relation with observation lineage; otherwise
   downgrade to evidence lookup or return `pending_review`/`not_found`.
4. Route to `global_summarization` only with an explicit bounded source scope.
   The result must name its scope and coverage state.
5. Permission enforcement occurs before routing results are materialized and at
   every downstream traversal; unknown scope fails closed.

## 3. Deterministic exact-set boundary

Exact-set and inventory answers are an executor product, not a KG completion
product.  They are allowed to claim a count, distinct members, an exhaustive
list, or a negative only when all of the following are validated:

1. **Declared inventory semantics.**  The logical form names a governed source
   schema, collection/relation, projection, predicates, distinctness rule, and
   sort/canonicalization rule.  Natural-language category labels alone are not
   a collection definition.
2. **Coverage contract.**  A versioned coverage record identifies the expected
   source population and snapshot/revision, inclusion/exclusion policy,
   permission basis, known gaps, and the conditions under which the population
   is complete for this query.  It records deterministic count/fingerprint and
   executor/version fingerprints where applicable.
3. **Exact deterministic execution.**  The executor uses only declared fields,
   validation rules, and a fixed equivalence/deduplication policy.  It does not
   add membership through vector similarity, graph communities, aliases,
   ontology predictions, LLM completion, or source-union heuristics.
4. **Permission-stable result.**  The actor can see every returned element and
   the coverage contract is valid for that actor/scope.  A hidden element,
   mixed-scope collection, or permission uncertainty prevents a complete claim.
5. **Provenance.**  Each result element can resolve to governed source/evidence
   references or an approved inventory record; the result carries the coverage
   contract and execution fingerprints.

If any condition fails, fail closed: return `partial`, `pending_review`,
`permission_denied`, or `not_found` as appropriate, with no asserted complete
cardinality.  “No match” is not proof of absence unless the same coverage
contract establishes exhaustive search for the actor's scope.

KG/ontology may supply a non-authoritative explanation such as an approved type
label or relation path after exact execution.  It may not alter the exact set,
count, inclusion decision, or coverage claim.

## 4. Schema-constrained logical-form contract

`HybridV2QueryPlan` is a proposed R&D contract name, not a deployed API schema.
All fields use opaque FormOwl references; public results never contain raw
storage, parser, SQL, worker, or private-evidence handles.

| Field group | Required content | Validation / meaning |
| --- | --- | --- |
| Identity | `contract_version`, `plan_id`, request hash, policy revisions | Immutable plan identity and reproducibility; unsupported version fails closed. |
| Actor and scope | actor-context reference, workspace/scope references, permission basis | Resolve permissions before data access; scope must not widen during planning. |
| Routing | one `query_class`, requested output form, allowed inference mode | Exact-set permits `none` for membership; evidence/rationale modes are explicitly bounded. |
| Logical form | operation, source schema/relation, variables, typed predicates, projection, distinct/order rules, temporal interpretation | Must be syntactically valid, referentially valid, and type-check against the pinned schema. |
| Evidence constraints | source/evidence snapshot/observation references or declared collection, citation requirement, redaction policy | Every asserted result must meet these constraints. |
| Exact-set additions | coverage-contract id/revision, equivalence policy, executor id/version | Required only for `exact_set_or_inventory`; missing values prohibit complete/count claims. |
| Graph additions | candidate/canonical graph revision, ontology/type revision, allowed edge kinds, maximum hops, confidence policy | Required for reasoning; revisions are pins, not permission grants. |
| Output claim | requested claim class, allowed statuses, uncertainty/coverage disclosure | Output validator rejects claims stronger than supplied evidence and coverage. |

Logical-form validation is deterministic.  It validates schema shape, field
names, relation arity, predicate types, required revision pins, source scope,
permission scope, and output status.  It does not validate that a probabilistic
entity/type/relation inference is true.

## 5. Hard validated invariants vs. soft ontology/type signals

The hard/soft distinction prevents a noisy inferred type from becoming an early
recall-killing gate.

### Hard validated invariants

These are non-negotiable and fail closed:

- contract/schema version, identifier/reference syntax, relation arity,
  required fields, and deterministic projection/distinct/order semantics;
- source/evidence/observation existence and allowed lineage;
- actor permission, scope propagation, redaction policy, audit requirements,
  and prohibition on raw/internal locator exposure;
- pinned policy, ontology-definition, coverage, graph, and executor revisions;
- declared type-definition scope and mapping-review state (for example, a
  cross-scope mapping cannot be silently treated as global);
- canonical-write preconditions: review decision, authorized actor, lineage,
  lifecycle event where needed, and no partial mutation;
- exact-set coverage validity before any complete/count/absence claim.

A hard schema check may confirm that a `TypeDefinition` exists and is valid in a
scope.  It must not convert an inferred instance assignment such as “this
mention is an Organization” into a hard fact merely because the type exists.

### Soft inferred signals

These are candidates, scores, or explanations and must preserve uncertainty:

- mention boundaries, Chinese/mixed-language term candidates, aliases, entity
  matches, relation candidates, frame candidates, and temporal normalization
  suggestions;
- type probabilities and compatibility scores; ontology alignment candidates;
- graph-neighborhood, lexical, embedding, or LLM scores; candidate admission
  signals; and summarization themes.

Soft signals may rank candidates, request review, select a declared reasoning
path, or add an uncertainty note.  They cannot change an exact inventory,
granted scope, canonical type state, canonical graph state, or final coverage
claim.  Any future calibrated hard gate requires pre-registered false-reject,
no-answer, permission, and end-task measurements; until then it remains soft.

## 6. What KG + ontology v2 may and may not do

| May do in Track 2 | Must not do in Track 2 |
| --- | --- |
| Produce provenance-linked term, mention, entity, relation, frame, and type-alignment candidates from observations. | Read raw MAY/private evidence or expose raw/internal source locations. |
| Preserve protected identifiers while testing frozen-profile candidate admission. | Treat tokenizer output, LLM output, embedding similarity, or alias clustering as canonical truth. |
| Build candidate topology, diagnose components, and test candidate-admission policies. | Use topology or fuzzy similarity to complete an exact inventory or claim absence. |
| Ground a logical form in a scoped ontology definition and score compatible relation/frame paths. | Turn an inferred type into a hard filter without calibrated false-reject evidence. |
| Traverse visible, provenance-backed relations and return a cited, uncertainty-labeled explanation. | Reveal hidden nodes/edges, let matching grant access, or let graph visibility grant raw asset access. |
| Create review packets, ontology-health reports, and promotion proposals. | Directly write canonical graph/type/user-graph/wiki state or bypass lifecycle/review governance. |
| Compare candidate-only arms under a truthful report schema. | Claim production quality, methodology readiness, or KG-vs-ontology superiority from historical, synthetic, redacted replay, or mismatched-runtime results. |

Coordination-frame v2 remains additive: request, commitment, decision, blocker,
deadline, dependency, escalation, follow-up, and related business-object
semantics may structure candidates and explanations.  This is not a new v3.

## 7. Provenance, permission, coverage, and canonical governance

### Provenance minimum

Every result or candidate must preserve a chain sufficient to audit:

```text
asset/source_ref or EvidenceSnapshot
  -> ExtractorRun
  -> Observation(s)
  -> semantic/term/type/relation/frame candidate(s)
  -> policy and ontology revision(s)
  -> review decision and canonical commit, if any
  -> user/effective graph view
  -> query plan and result/projection
```

Record opaque source refs, evidence snapshot ids, observation ids, extractor
and configuration/model/prompt hashes where applicable, candidate ids,
confidence, review state, policy ids, ontology revision, graph revision,
permission scope, redaction policy, and output claim/coverage state.  Public
reports aggregate or hash sensitive surfaces unless they are safe fixtures.

### Permission and effective-view rules

Permission scope propagates from source through observations, candidates,
canonical objects, graph views, and projections.  Unknown or conflicting scope
fails closed.  Candidate fusion across scopes may produce an access-safe review
item but cannot merge access or disclose the hidden endpoint.  Effective graph
views are actor- and grant-aware projections; they are not raw-asset grants.

### Coverage rules

Coverage is independent of graph connectivity and ontology confidence.  A
coverage contract is required only for complete/exact-set claims, but evidence
lookup and summary outputs must still disclose their searched/bounded scope and
known incompleteness.  Source commitments and missing-source accounting must
remain explicit; no hard-coded answer union is permitted.

### Canonical governance rules

Candidate generation, candidate review, canonical commit, user-graph assembly,
and wiki projection remain separate workflows.  Types are scoped and versioned;
a type canonical in one domain/scope is not automatically canonical elsewhere.
Promotion requires provenance, governed review, compatible permissions,
revision pins, lifecycle-safe identity handling, and audit.  A canonical commit
does not rewrite source evidence or erase historical identifiers.

## 8. Issue #33 work-package mapping and bounded exits

GitHub issue access was unavailable during this handoff, so this map uses the
public local #33 summary.  It does not rename the issue, create a v3, or claim
that unlabelled topics are closed.

| #33 work package/topic | Required deliverable | Exit boundary |
| --- | --- | --- |
| **A — report boundary** (explicitly named) | Reports label generated same-corpus cases as `development` and `evaluation`, not independent holdout; arm metadata separately states candidate admission, KG construction, type compatibility, and frame semantics. | Primary retrieval excludes permission-denied cases; no-answer, permission safety, frame/type quality, slot-value quality, evidence-span quality, latency/resource use, and topology diagnostics are separate.  Unmeasured semantic fields remain `not measured`. |
| **Architecture/method contract** (coordinator Track 2 delegation) | This router, exact-set boundary, hard/soft split, and logical-form/provenance contract. | Contract is reviewed as a proposal and remains separate from UAT/runtime/deployment implementation. |
| **Tokenizer/candidate admission and topology POC** | Same-profile query/evidence candidate path using the frozen target tokenizer policy; protected identifiers; candidate-admission and component/topology diagnostics. | Demonstrates only a bounded candidate-layer signal with no-match, permission, and false-reject safeguards.  It cannot establish semantic lift or methodology readiness. |
| **Semantic ablation and independent evaluation** | Pre-registered KG-only, candidate-admission, soft-type/ontology, and coordination-frame arms with evidence/slot/frame metrics and error analysis. | Requires independent holdout/real-source evidence on one aligned pipeline before a #33 research-close or comparative claim is considered. |
| **Promotion/research exit** | Reviewable evidence packet with execution fingerprints, policy/revision pins, safety results, and independent reviewer decision. | Only after the authority gate is ready and the issue's independent-holdout and semantic-ablation criteria pass; Track 1 UAT cannot close Track 2. |

## 9. Promotion and fail-closed claims

### Promotion criteria

A candidate method/type/domain pack may advance only when all applicable
criteria are met and recorded in a reproducible packet:

1. **Method alignment:** query and evidence use the frozen target pipeline;
   execution fingerprints bind the report to that pipeline.
2. **Safety:** no-match, permission-denied, redaction, and false-reject metrics
   meet pre-registered acceptance thresholds; topology diagnostics do not hide
   giant-component or broad-match failures.
3. **Semantic utility:** an ablation isolates the added type/ontology/frame
   contribution beyond candidate admission and KG-only baselines, with frame,
   slot-value, and evidence-span quality actually measured.
4. **Generalization:** independent holdout/real-source evidence is distinct
   from generated same-corpus development/evaluation cases.
5. **Governance:** coverage, stability, type conflict, permission-boundary
   risk, provenance, scoped mapping, review, and lifecycle requirements pass.
6. **Authority:** `--require-ready` succeeds before methodology-quality UAT,
   KG-versus-ontology quality claims, method changes, or methodology-slice
   completion.

### Claims that must fail closed now

Do not claim any of the following from this document or a Track 2 POC:

- that the current runtime implements Hybrid KG + Ontology v2 or has production
  Chinese tokenization;
- that a historical PST/redacted/synthetic result compares the current target
  method, or that KG outperforms KG-plus-ontology (or vice versa) on real
  sources;
- methodology readiness, methodology-objective completion, #33 closure,
  production readiness, or final business-answer correctness;
- complete inventory/cardinality/absence without the deterministic executor and
  valid coverage contract;
- canonical graph/type/user-graph/wiki mutation, raw asset access, or a grant
  inferred from entity/graph matching;
- an independent holdout label for generated same-corpus cases, or semantic
  quality inferred from candidate-admission lift.

## 10. Continuation checklist for the next computer

1. Re-read `AGENTS.md`, the required startup files, this boundary, and the
   current #33 maintainer comments when GitHub is reachable.
2. Run `python3 scripts/methodology_authority_check.py --check` and preserve its
   blocked/ready state in every plan.  Do not run methodology-quality work if
   `--require-ready` fails.
3. Keep this scope separate from Track 1 exact-77 UAT, web/sidecar/deployment,
   private projection bindings, and raw PST parsing.
4. Start with Work Package A report honesty and a small same-profile
   candidate-only POC; do not label generated data a holdout.
5. Treat every proposed implementation change as a separate assigned slice with
   tests, public/redacted evidence, canonical dev-container verification, and
   the required reviewer gate.  Do not modify this frozen v2 target into v3.
