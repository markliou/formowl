# Agent Handoff Log

Use this log for short cross-session and cross-machine notes. Keep detailed
status in each role's goal file and task completion in
`docs/implementation-task-breakdown.md`.

## 2026-06-27

- Created durable goal registry under `docs/agent-goals/`.
- Imported the Knowledge Graph Research Agent goal from session
  `019eda5f-7dd6-74a2-ac56-4f84e5d58560` into
  `docs/agent-goals/kg-research-agent.md`.
- Added `docs/agent-goals/system-backbone-agent.md` as an abstract placeholder
  for the System Backbone Agent running on another machine. The owning agent
  should fill in its exact objective, status, blockers, commit, and next
  action.
- Updated the default reviewer gate to 6 effective read-only reviewers: 3
  Codex/GPT reviewers plus 3 Antigravity Gemini reviewers through the real
  local `agy` CLI. The user authorized `agy` reviewer use. See
  `docs/agent-goals/reviewer-gate.md`.
- Knowledge Graph Research Agent implemented the scoped ontology/type
  governance contracts and KG research acceptance suite. Dev-container
  verification passed, and GPT/Codex reviewer gate progress is 3/3 agreed for
  that reviewer class (`Kuhn`, `Goodall`, `Pasteur`) after blocker fixes.
  Overall gate remains 3/6 because Antigravity Gemini reviewer calls through
  `agy` were rejected for external model data-egress risk and require explicit
  user approval before retrying.
- Added an upfront authorization rule for future KG goal resumes: if the
  reviewer gate is expected to need Antigravity Gemini reviewers through `agy`,
  ask the user at the start for bounded external review-packet approval before
  doing long-running local work. This rule is recorded in the `use-agy`
  repo-local skill, the KG goal file, the reviewer gate, and the work board.
- Added a compact-friendly execution rule for the KG goal: checkpoint durable
  state more often than usual, especially after reviewer attempts, blockers,
  verification results, and acceptance-status changes, so future compaction or
  resume cycles do not depend on long chat history.
- Completed the KG research method/acceptance-harness slice. Current-state dev-container
  verification passed: default KG research acceptance suite returned
  `passed_with_explicit_limits` with only expected failed/blocked items,
  focused KG acceptance tests ran 4 OK, focused ontology tests ran 4 OK, and
  full unittest ran 246 OK. Reviewer gate passed 6/6:
  `Kuhn`, `Goodall`, `Pasteur`, `Ada-Sandbox`, `Lamport-Sandbox`, and
  `Curie-Sandbox`. The KG Research Evaluation and Acceptance work-board item is
  now checked complete.
- Correction: the previous entry completed only the scoped ontology and KG
  research method/acceptance-harness slice, not the user's full KG
  real-evidence objective. `docs/agent-goals/kg-research-agent.md` is reset to
  `active`. The stricter `.formowl/kg-eval` broad acceptance snapshot still has
  `overall_passed=false` with failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
- Added an unchecked work-board item for the full KG real-evidence objective.
  Future KG sessions must not treat `passed_with_explicit_limits` or a checked
  method-slice item as total completion. Completion requires broad KG-eval
  gates to pass, strict main-repo KG research acceptance to pass, canonical
  dev-container verification, and the configured reviewer gate for newly
  completed slices.
- 2026-06-27 review return: the reviewed canonical graph commit workflow was
  unchecked for rework. Current code builds child graph revisions from only the
  newly committed candidate atoms/relations and resolves candidate relations
  only against atoms in the same commit, so incremental canonical graph history
  can drop prior graph membership. Also, the stricter `.formowl/kg-eval`
  harness/snapshot is ignored by Git, so future sessions on another machine
  cannot rely on it unless the essential acceptance artifacts are moved to a
  tracked path or explicitly unignored.
- 2026-06-27 portability follow-up: `.gitignore` now allows the sanitized
  `.formowl/kg-eval` strict acceptance harness, restart note, fixtures,
  templates, work orders, preview packets, and non-authoritative blocked-state
  snapshots under `snapshots/current_blocked/` to be tracked. Runtime
  `.formowl/kg-eval/results/`, the long local `.formowl/kg-eval/HANDOFF.md`,
  operator real roots under `inputs/*_real/`, and canonical real evidence
  packets remain ignored. This makes the broad acceptance harness reproducible
  across sessions while avoiding stale generated results as completion
  evidence. The KG objective is still active with the same four failed
  real-evidence gates.
- 2026-06-27 portability verification: dev-container KG-eval unittest ran
  360 tests OK and main repo unittest ran 246 tests OK. Broad KG-eval reports
  `overall_passed=false`, 8 passed gates, 4 failed gates, and synchronized
  blocked real-evidence preflight/work orders. Main-repo KG acceptance default
  reports `passed_with_explicit_limits`; strict mode fails as expected on the
  known failed/blocked readiness claims.
- 2026-06-27 portability reviewer result: 3 final-version Antigravity Gemini
  reviewers agreed after one reviewer found and re-reviewed a real blocker.
  The fixed blocker was stale/private-data tracking risk from broad `inputs/`
  and runtime `results/` unignore rules. The final ignore policy tracks only
  sanitized harness/fixtures/templates/work orders/work packets and
  non-authoritative blocked snapshots while excluding runtime results,
  operator real roots, canonical evidence packets, and local long-form handoff
  history.
