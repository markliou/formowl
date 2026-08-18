# Agent Handoff Log

Lifecycle label: `active`.

This is a bounded active window. Earlier entries are immutable history under
`docs/archive/`, including the complete pre-rewrite log at
`../archive/2026-08-18/active/docs/agent-goals/handoff-log.md`.

## Retention Rule

- Keep the latest 14 calendar days and at most 300 lines.
- Archive a complete dated entry before trimming it.
- Record only current facts, blockers, verification, and next action.
- Historical pointers are not restart instructions.

## 2026-08-18 — Issue #56 becomes the sole active KG methodology program

- GitHub issue #56 defines the active objective: graph-guided Hybrid KG +
  Ontology v2 must earn a measurable final-answer win over strong RAG on
  heterogeneous integration tasks.
- Frozen target remains
  `evidence_to_knowledge_kg_ontology_v2_hybrid_v1` with
  `jieba_sentencepiece_frozen_profile_candidate_admission_v1`; no v3 was
  created.
- Architecture is strong RAG retrieval plus reviewed entity links, bounded
  graph traversal, temporal/provenance/coverage filtering, capped soft ontology
  scoring, evidence-bundle reranking, and deterministic exact-set execution.
- Inferred ontology mismatch no longer prunes admitted evidence. The old hard
  gate is a negative ablation only.
- The final answer model is not an architectural shortcut: every arm must pin
  and share the same model, prompt, reasoning effort, schema, and budget.
- Independent holdout questions cannot influence tokenizer, aliases, ontology,
  graph rules, thresholds, prompts, or model choice.
- PostgreSQL/pgvector remains canonical. Do not resume Neo4j benchmarks,
  migration, projection, or dual-write work.
- Issue #55's document-first exactly-one-call POC and issue #33 plans are
  historical only. Their complete active-file state before this rewrite is
  preserved under `docs/archive/2026-08-18/`.
- Methodology authority check is valid but blocked. Runtime remains
  `ascii_identifier_regex_v1` with CJK support false, and all five readiness
  gates remain unresolved.
- Next KG action: implement the immutable target tokenizer/profile and
  same-profile query/evidence binding, then source-completeness reconciliation
  and a strong RAG control. No methodology-quality comparison may start while
  `--require-ready` exits nonzero.
- The Issue #20 operator helper now derives or validates one safe non-secret predefined client ID; app configuration replaces only the ChatGPT-displayed callback; if the same client ID cannot be used, the live campaign stops as an external blocker.
- Issue #20 remains open and unchecked; this KG documentation rewrite does not change its external evidence state.

## 2026-08-18 — Active-document rewrite verification

- Active KG, architecture, workflow, provenance, infrastructure, evaluation,
  role, goal, and startup documents now point to issue #56 and the frozen
  Hybrid-v2 target. Superseded mail-only, issue #33, and issue #55 files are
  explicit historical pointers; their pre-rewrite content remains immutable
  under `docs/archive/2026-08-18/`.
- `python3 scripts/methodology_authority_check.py --check` passes with 53 bound
  sources. Authority remains valid but blocked; all five readiness gates remain
  unresolved and `--require-ready` must continue to exit nonzero.
- The focused documentation/methodology/container suite passed 150 tests with
  one skip. The canonical full suite ran 1,558 tests and is not green:
  11 failures and one error remain in legacy coordination-frame metrics,
  Issue #20 function-onboarding state, and an unrelated PST extractor test.
  Those failures are outside this documentation rewrite's write set and were
  not hidden or broadly repaired.
- Issue #20 remains open and unchecked; this documentation-only verification
  does not change its external evidence or closure state.
- Next KG action remains Work Package A: immutable Jieba + SentencePiece
  profile packaging and same-profile query/evidence indexing, followed by
  source-completeness reconciliation and the strong RAG control.
