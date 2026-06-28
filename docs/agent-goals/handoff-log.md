# Agent Handoff Log

Use this log for short cross-session and cross-machine notes. Keep detailed
status in each role's goal file and task completion in
`docs/implementation-task-breakdown.md`.

## 2026-06-27

- Created durable goal registry under `docs/agent-goals/`.
- Agy authorization checkpoint: before continuing KG implementation, the user
  asked to resolve the Antigravity/Gemini reviewer permission issue. Standing
  scoped authorization is now recorded in the repo-local
  `use-agy-antigravity` skill, `docs/agent-goals/reviewer-gate.md`, and
  `docs/agent-goals/kg-research-agent.md`. Codex may run the local `agy` CLI
  with sandbox escalation and may send bounded read-only FormOwl KG reviewer
  packets containing only relevant repo-relative paths, design/test summaries,
  verification results, claim boundaries, and non-sensitive code/docs excerpts.
  The authorization excludes secrets, credentials, raw private source payloads,
  raw backend paths, NAS/object-store admin endpoints, raw SQL, database dumps,
  worker scratch paths, local filesystem internals, and unrelated private data.
  If `agy` is slow, confirm it is still running and wait; if tenant policy or
  approval review rejects external disclosure before execution, record the gate
  blocker and do not bypass it with alternate channels or substitute reviewers.
- Bounded Antigravity write-delegation checkpoint: the user also authorized
  Codex to ask Antigravity to write bounded implementation slices to save Codex
  token budget. Future invocations must state exact owned files/directories,
  keep the workspace minimal, avoid unrelated changes, and leave Codex
  responsible for diff inspection, canonical dev-container verification,
  durable docs, and final commit. Do not use
  `--dangerously-skip-permissions` without separate exact approval.
- Agy policy/write test result: local `agy` availability works
  (`agy --version` returned `1.0.13`, and `agy models` listed
  `Gemini 3.5 Flash (High)`). A minimal bounded FormOwl KG read-only reviewer
  packet was rejected before execution by tenant policy as external disclosure
  to an untrusted reviewer service; no packet was sent and no workaround was
  attempted. Plain one-shot `--add-dir` was not reliable for intended
  workspace writes, while `--new-project --add-dir` successfully wrote to an
  empty intended workspace. Future bounded write delegation should use
  `--new-project --add-dir <smallest-scope>` and Codex must verify local diff
  and tests before accepting Antigravity output.
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
- Historical upfront authorization rule for KG goal resumes: if the reviewer
  gate was expected to need Antigravity Gemini reviewers through `agy`, ask the
  user at the start for bounded external review-packet approval before doing
  long-running local work. This rule is superseded by the 2026-06-28 agy MCP
  route and gate-policy checkpoint below; ordinary KG resumes should not ask
  for Antigravity authorization unless the user explicitly re-enables `agy`.
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
- 2026-06-27 canonical commit rework result: reviewed canonical graph commit
  workflow rework completed. Child graph revisions now preserve same-scope
  committed parent atom/entity/relation membership, relation commits can
  resolve endpoints through parent/current candidate-to-canonical atom mappings,
  relation-only commits require reviewed relations with resolvable endpoints,
  empty commits are rejected, and corrupt parent relation endpoints are rejected
  before child writes. Dev-container verification passed: changed-file Ruff
  check and format check, focused canonical workflow unittest 16 OK, full main
  repo unittest 252 OK, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance failed only on the known expected failed/blocked items,
  and KG-eval unittest 360 OK. GPT/Codex reviewers `Kuhn-GPT`,
  `Goodall-GPT`, and `Pasteur-GPT` agreed on the final diff after Pasteur's
  parent entity/relation membership test-coverage blocker was fixed.
  Antigravity Gemini reviewers `Lamport-Sandbox`, `Ada-Sandbox`, and
  `Curie-Sandbox` agreed through real `agy` on the implementation diff; a
  later attempt to send the test-only final diff to `agy` was blocked by
  sandbox/tenant data-egress policy, and no workaround was attempted. The full
  KG real-evidence objective remains active with the same four failed broad
  gates.
- 2026-06-27 fair-baseline response-intake progress: added a candidate-only
  fair external-baseline response intake path and work-order command. The new
  intake writes only candidate artifacts under
  `inputs/fair_baseline_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`, records custody hashes, rejects unsafe
  payloads/paths/overwrites/symlinks, and never writes the canonical fair
  baseline packet. GPT reviewer blockers for manifest custody hashing,
  post-write assembler failures, parent-file partial writes, and
  production-shaped test cleanup were fixed. Dev-container KG-eval unittest ran
  372 tests OK; main repo unittest ran 252 tests OK; changed-file Ruff check
  and format-check passed; KG-eval acceptance/preflight/work-order reports were
  refreshed and remain blocked/synchronized with the same four failed broad
  gates. GPT/Codex reviewers `Poincare`, `Popper`, and `Carson` agreed after
  blocker fixes. Antigravity Gemini review is blocked at 0/3 because tenant
  policy rejected both a code/diff bounded packet and a closed-book bounded
  summary through real `agy`; no workaround was attempted.
- 2026-06-27 production-adapter response-intake progress: added a
  candidate-only production adapter response intake path and work-order
  command. The new intake writes only candidate artifacts under
  `inputs/production_adapter_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`, records custody hashes, rejects unsafe
  payloads/paths/overwrites/symlinks/parent-file collisions and
  duplicate/missing adapter components, and never writes
  `inputs/production_adapter_evidence_packet.json`. Dev-container verification
  passed so far: KG-eval focused 27 OK, KG-eval full 383 OK, main repo 252 OK,
  changed-file Ruff check and format-check passed, and refreshed reports still
  show `overall_passed=false` with the same four failed broad gates. GPT/Codex
  reviewers `Gauss`, `Archimedes`, and `Noether` returned blockers for
  sandbox/nested output-dir rejection, top-level response field allowlisting,
  missing-component coverage, and work-order side-effect snapshots; the fixes
  passed dev-container focused 30 OK, full KG-eval 386 OK, main repo 252 OK,
  changed-file Ruff check and format-check, and all three reviewers returned
  `RELEASE_DECISION: AGREE`. Antigravity Gemini review is blocked at 0/3:
  `agy --version` and `agy models` succeeded, but three bounded read-only
  review-packet attempts through real `agy` were rejected before execution by
  tenant policy as external data disclosure to an untrusted reviewer service,
  even with user authorization. No packet was sent and no workaround was
  attempted.
- 2026-06-27 enterprise-multimodal response-intake hardening progress:
  hardened the candidate-only enterprise multimodal response intake path for
  `multimodal_semantic_validation`. The intake now rejects unsupported
  top-level response fields, unsafe/nested/sandbox output dirs, symlinks,
  overwrites, parent-file collisions, raw/internal/template payload values,
  raw/internal field names, and promotion arguments; it writes only candidate
  artifacts under `inputs/enterprise_multimodal_real/<operator-run-id>` plus
  optional work-packet manifests, custody-hashes the optional manifest, and
  rolls back intake-created files on assembler, validation, custody,
  serialization, or write failures including after exclusive create/open.
  Dev-container verification passed: focused KG-eval 35 OK, full KG-eval
  396 OK, main repo 252 OK, changed-file Ruff check and format-check, and
  refreshed broad reports still show `overall_passed=false` with the same four
  failed gates. GPT/Codex reviewers `Aristotle`, `Huygens`, and `Lovelace`
  agreed after blocker fixes. Antigravity Gemini review is blocked at 0/3:
  `agy --version` and `agy models` succeeded, but a bounded read-only
  review-packet attempt was rejected before execution by tenant policy as
  external data disclosure to an untrusted reviewer service. No packet was
  sent and no workaround was attempted.
- 2026-06-27 current-state re-execution: after the user asked to execute the
  original agent's latest state, Codex reran the broad KG-eval and main-repo
  verification in the dev container without local code changes. Refreshed
  commands: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
  `real_evidence_collection_work_orders.py`. Dev-container KG-eval unittest
  ran 396 tests OK, and main repo unittest ran 252 tests OK. Main-repo KG
  research acceptance default remains `passed_with_explicit_limits`; strict
  mode still fails only on the known `production_adapter_readiness` failed
  item and `latency_scalability_enterprise_claims` blocked item. Broad
  KG-eval remains incomplete: `overall_passed=false`, 8 passed gates, and the
  same 4 failed real-evidence gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`). Preflight
  reports `inputs/*_real` roots exist but currently contain zero real or
  candidate artifacts, and all four canonical input packets are missing.
- 2026-06-27 operator-guide progress: added a generated, tracked human-readable
  guide for collecting the remaining broad KG real-evidence packets at
  `.formowl/kg-eval/work_packets/remaining_real_evidence_operator_guide.md`.
  The generator is `.formowl/kg-eval/real_evidence_operator_guide.py` and is
  sourced only from the non-authoritative work-order report. It lists blockers,
  required artifacts, candidate-only intake commands, validation commands, and
  safety boundaries for all four remaining gates, while explicitly accepting
  no evidence, promoting no packets, writing no canonical packets, and counting
  as no acceptance gate. Verification passed in the dev container: focused
  operator-guide unittest 6 OK, full KG-eval unittest 402 OK, changed-file Ruff
  check and format check, refreshed broad KG-eval reports, main repo unittest
  252 OK, and main KG acceptance remains unchanged
  (`passed_with_explicit_limits`; strict fails only on known limits). The full
  KG objective is still active and broad KG-eval remains `overall_passed=false`
  with the same four failed real-evidence gates.
- 2026-06-27 operator-guide sync check: added `--check` mode to
  `.formowl/kg-eval/real_evidence_operator_guide.py`, and the tracked guide now
  documents `python3 real_evidence_operator_guide.py --check`. The focused
  tests cover both an up-to-date guide and a stale guide that fails without
  being rewritten. Dev-container verification passed: guide `--check`, focused
  operator-guide unittest 8 OK, full KG-eval unittest 404 OK, changed-file Ruff
  check and format check, refreshed broad KG-eval reports, main repo unittest
  252 OK, and main KG acceptance state remains unchanged. Broad KG-eval is
  still `overall_passed=false` with the same four failed real-evidence gates.
- 2026-06-27 submission-manifest preflight and skill-portability progress:
  added `.formowl/kg-eval/real_evidence_submission_manifest.py`, focused tests,
  and the tracked non-evidence template
  `.formowl/kg-eval/work_packets/remaining_real_evidence_submission_manifest.template.json`.
  The operator guide now tells future operators to run
  `python3 real_evidence_submission_manifest.py --check-template` and validate
  an operator-filled manifest before running candidate-only intake commands.
  This preflight checks response paths directly under the matching ignored
  `inputs/*_real/<operator_run_id>/` run directory, run ids, response packet
  types, output dirs, and non-authoritative claim boundaries only; it reads no
  response-packet contents, writes no candidate artifacts, promotes no
  evidence, and writes no canonical input packets. The repo-local
  `$use-agy-antigravity` skill was
  updated in `.agents/skills/use-agy-antigravity/SKILL.md` so the KG `agy`
  authorization/reviewer/write-delegation workflow is explicitly portable after
  git clone. Template emit/check is restricted to the tracked `.template.json`
  path so it cannot overwrite arbitrary `work_packets/*.json` manifests.
  Dev-container verification passed: submission template check, operator guide
  check, focused submission/guide unittest 17 OK, full KG-eval unittest
  413 OK, changed-file Ruff check and format check, refreshed broad reports,
  main repo unittest 252 OK, and default KG acceptance
  `passed_with_explicit_limits`; strict still fails only on known limits. The
  full KG objective remains active and broad KG-eval is still
  `overall_passed=false` with the same four failed real-evidence gates.
  Antigravity Gemini review for this slice is blocked at 0/3: a bounded
  read-only `agy` reviewer packet containing only relevant paths, summaries,
  verification results, and claim boundaries was rejected before execution by
  tenant policy as external disclosure to an untrusted reviewer service. No
  packet was sent and no workaround or alternate external channel was
  attempted. Codex/GPT reviewers `Dalton`, `Galileo`, `Volta`, and `Feynman`
  returned `RELEASE_DECISION: AGREE`; Dalton's non-blocking template-output
  narrowing suggestion was implemented with a regression test.

## 2026-06-28

- Submission-manifest CLI/work-packet tracking hardening: `--manifest` now
  validates the operator-filled manifest path before reading it and accepts
  only safe repo-relative JSON files under `work_packets/`; templates,
  tracked preview-packet names, absolute/raw/dot-segment paths,
  non-work-packet paths, and symlink components are rejected. `.gitignore` now
  ignores arbitrary operator-generated `work_packets/*.json` outputs and only
  re-includes the four fixed preview packets, the tracked submission template,
  and the tracked operator guide. The guide states that operator-filled
  manifests and generated candidate manifests under `work_packets/` are
  intentionally ignored. This is operator-flow hardening only: it reads no
  response contents, writes no candidate artifacts, promotes no evidence,
  writes no canonical packets, and does not count as an acceptance gate.
  Dev-container verification passed: submission template check, guide check,
  focused submission/guide unittest 20 OK, full KG-eval unittest 416 OK, main
  repo unittest 252 OK, changed-file Ruff check and format check, refreshed
  broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and 4 failed gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`);
  `inputs/*_real` contains no files and the four canonical broad packets are
  absent. GPT/Codex reviewers `Godel`, `Gibbs`, and `Ohm` agreed after
  blockers for dot-segment normalization and broad `*_preview.json` tracking
  were fixed. A bounded `agy` write-delegation attempt for `.formowl/kg-eval`
  was rejected before execution by tenant policy as private repository
  disclosure to an untrusted external Antigravity service; no packet was sent
  and no workaround was attempted.
- Candidate-manifest validation guidance: collection work orders and the
  tracked operator guide now direct post-intake validation to the ignored
  candidate manifests emitted by response intake under
  `work_packets/*_candidate_manifest.json`, while keeping
  `work_orders/*_assembly_manifest.json` generation as optional non-evidence
  scaffold inspection only. `_common_commands` now fails closed if a remaining
  gate lacks a response-intake candidate manifest mapping instead of falling
  back to scaffold validation. This is operator-flow guidance only; it writes
  no candidate artifacts, promotes no evidence, writes no canonical packets,
  and does not count as an acceptance gate. Dev-container verification passed:
  guide check, focused work-order/guide unittest 26 OK, full KG-eval unittest
  417 OK, main repo unittest 252 OK, changed-file Ruff check and format check,
  refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and 4 failed gates; `inputs/*_real`
  contains no files and the four canonical broad packets are absent.
  GPT/Codex reviewers `Bohr`, `Euler`, and `Lorentz` agreed after Lorentz's
  scaffold-fallback blocker was fixed. Antigravity remains blocked by tenant
  policy for bounded FormOwl KG repository disclosure; no workaround was
  attempted.
- Current-state execution after reviewer request: `git fetch origin` found no
  newer `complete-slice-1` commit beyond `f3ba5f8`, and the worktree was clean.
  Codex reran the broad KG-eval and main-repo verification in the dev
  container: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`,
  `real_evidence_collection_work_orders.py`, full KG-eval unittest 417 OK,
  main repo unittest 252 OK, default main KG acceptance
  `passed_with_explicit_limits`, and strict main KG acceptance exited nonzero
  only for the known `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item. Broad KG-eval remains
  incomplete with `overall_passed=false`, 8 passed gates, and 4 failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
  `inputs/*_real` contains zero files and the four canonical broad packets are
  absent. No completion claim is supported.
- Candidate intake execution-plan slice: `real_evidence_submission_manifest.py`
  can now emit a non-evidence candidate intake execution plan from a validated
  operator-filled submission manifest using `--emit-intake-plan`. The plan is
  restricted to safe ignored `work_packets/*.json` outputs, records exact
  candidate-only intake argv/commands, executes nothing, reads no response
  packet contents during planning, writes no candidate artifacts, writes no
  canonical packets, promotes no evidence, and counts as no acceptance gate.
  The operator guide documents the optional plan step. Tests now assert no
  changes to real roots, canonical broad packets, or
  `work_packets/*_candidate_manifest.json`, and invalid-manifest plan emission
  writes no plan file. Dev-container verification passed: focused
  submission/guide unittest 24 OK, full KG-eval unittest 421 OK, main repo
  unittest 252 OK, changed-file Ruff check and format check, guide/template
  checks, refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`; strict still exits nonzero only for known
  limits. Broad KG-eval remains incomplete with the same 4 failed gates.
  GPT/Codex reviewers `Boole`, `Maxwell`, and `Avicenna` agreed after Boole's
  blocker was fixed and Maxwell's hardening note was implemented. Antigravity
  Gemini review is blocked at 0/3 because tenant policy rejected a bounded
  closed-book `agy` reviewer packet before execution as private
  repository-derived disclosure to an untrusted external reviewer service; no
  packet was sent and no workaround was attempted.
- Agy MCP route and gate-policy checkpoint: at the user's request, Codex tested
  whether Antigravity/`agy` can be reached through MCP. Current Codex tool
  discovery exposes no Antigravity/`agy` MCP tool; Codex config has no
  Antigravity MCP server; Antigravity global `mcp_config.json` is empty; this
  repo has no `.agents/mcp_config.json`; `agy --help` exposes no MCP server
  subcommand; `agy plugin list` shows no imported plugins; and a
  no-repository-content `agy --new-project --print "/mcp"` probe from `/tmp`
  returned general MCP configuration guidance rather than an active server/tool
  list. Conclusion: Antigravity can use MCP tools inside its own session, but
  this Codex environment currently has no MCP path for Codex to call
  Antigravity/`agy`. The default FormOwl KG reviewer gate is now 3 Codex/GPT
  reviewers only, and `agy` reviewer/write delegation is disabled unless the
  user explicitly re-enables it after policy, platform, or MCP configuration
  changes. This policy checkpoint does not change broad KG-eval acceptance:
  `overall_passed=false` with the same four failed real-evidence gates.
- Current-state execution after user request: `git fetch origin` found no
  newer commit beyond `63df752` (`Document agy MCP route disablement`) on
  `complete-slice-1`, and the branch matched `origin/complete-slice-1`.
  Codex reran the broad KG-eval and main-repo verification in the dev
  container: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`,
  `real_evidence_collection_work_orders.py`, full KG-eval unittest, operator
  guide `--check`, submission template `--check-template`, main repo unittest,
  default main KG acceptance, and strict main KG acceptance. KG-eval reports
  exited 0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0;
  main repo unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and 4 failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements. No completion claim is supported.
- Follow-up current-state execution after user request: `git fetch origin`
  found no newer commit beyond `bf0fc2b` (`Record KG current verification
  run`) on `complete-slice-1`, and the branch matched
  `origin/complete-slice-1`. Codex reran broad KG-eval and main-repo
  verification in the dev container without code changes:
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest, operator guide `--check`, submission template
  `--check-template`, main repo unittest, default main KG acceptance, strict
  main KG acceptance, and full Ruff lint/format checks. KG-eval reports
  exited 0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0;
  main repo unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Full Ruff lint passed, but full Ruff format-check
  still reports 33 pre-existing files that would be reformatted. Broad KG-eval
  remains incomplete with `overall_passed=false`, 8 passed gates, and 4 failed
  gates: `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements; all four real roots have no files and the four canonical broad
  packets are absent. No completion claim is supported.
- Formatting cleanup: Codex mechanically formatted the 33 files previously
  reported by full Ruff format-check, using the dev container and an external
  `/tmp` Ruff cache to avoid the root-owned `.ruff_cache` permission issue.
  Verification passed after formatting: full Ruff lint and format-check, full
  KG-eval unittest 421 OK, main repo unittest 252 OK, operator guide
  `--check`, submission template `--check-template`, refreshed broad KG-eval
  reports, and default main KG acceptance `passed_with_explicit_limits`;
  strict main KG acceptance still exits nonzero only for known limits. This was
  format-only cleanup and does not change broad KG acceptance:
  `overall_passed=false` with the same four failed real-evidence gates.
- Operator submission-manifest input hardening: `--manifest` now rejects
  generated `*_candidate_manifest.json` and `*_intake_plan.json` paths so
  downstream non-evidence outputs cannot be mistaken for operator-filled
  submission manifests. The operator guide documents this boundary, and tests
  cover the rejected names and guide warning. This does not accept evidence,
  write candidate artifacts, promote canonical packets, or change acceptance
  state. Verification passed: host focused submission/guide unittest 24 OK,
  dev-container focused submission/guide unittest 24 OK, guide/template
  checks, full KG-eval unittest 421 OK, main repo unittest 252 OK, full Ruff
  check and format-check, refreshed broad reports, and default main KG
  acceptance `passed_with_explicit_limits`; strict still exits nonzero only
  for known limits. Broad KG-eval remains `overall_passed=false` with the same
  four failed real-evidence gates. GPT/Codex reviewers `Dirac`, `Zeno`, and
  `Hypatia` agreed; Hypatia re-reviewed the final test-only assertion with
  `RELEASE_DECISION: AGREE`.
- Post-`27ff851` verification checkpoint: local Git state was clean at
  `27ff851` (`Harden KG submission manifest input guard`) on
  `complete-slice-1`, and the branch matched `origin/complete-slice-1`.
  Dev-container verification reran the broad KG-eval reports, full KG-eval
  unittest, operator guide `--check`, submission template `--check-template`,
  main repo unittest, full Ruff check/format-check, default main KG
  acceptance, and strict main KG acceptance. Results: KG-eval reports exited
  0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0; main
  repo unittest ran 252 tests OK; Ruff passed with `200 files already
  formatted`; default main KG acceptance remains `passed_with_explicit_limits`;
  strict main KG acceptance still exits nonzero only for known limits. Broad
  KG-eval remains incomplete with `overall_passed=false`, 8 passed gates, and
  4 failed gates: `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  Work-board unchecked engineering item count remains 9: 1 KG-owned full
  real-evidence objective and 8 System Backbone/product-infra items. No
  completion claim is supported.
- Submission-manifest hardlink-alias guard: `real_evidence_submission_manifest.py
  --manifest` now rejects hardlink aliases for the operator-filled manifest
  input and required `response_packet` files before candidate intake. The
  check inspects only regular-file existence and link count; it still reads no
  response packet contents, writes no candidate artifacts, promotes no
  evidence, writes no canonical packets, and counts as no acceptance gate. The
  tracked operator guide documents the hardlink boundary. Verification passed:
  host focused submission/guide unittest 26 OK; dev-container focused
  submission/guide unittest 26 OK; guide/template checks; full KG-eval
  unittest 423 OK; main repo unittest 252 OK; full Ruff check and
  format-check; refreshed broad reports; and default main KG acceptance
  `passed_with_explicit_limits`. Strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with the same four
  failed real-evidence gates. GPT/Codex reviewers `Confucius`, `Mendel`, and
  `Leibniz` returned `RELEASE_DECISION: AGREE`.
- Canonical broad-packet path guard: the four broad real-evidence validators
  now reject direct symlinks, hardlink aliases (`st_nlink > 1`), and
  non-regular canonical input packet paths before JSON parsing. The blocker
  propagates through `validate_packet()` so reports remain failed and
  claim-boundary flags stay false. Added
  `.formowl/kg-eval/test_canonical_evidence_packet_path_guards.py` for
  symlink, hardlink, and directory packet paths across fair baseline, human
  annotation, enterprise multimodal, and production adapter validators. This
  is acceptance hardening only: it accepts no evidence, writes no candidate
  artifacts, promotes no packets, writes no canonical broad packets, and
  changes no broad gate status. Verification passed: host focused validator
  unittest 107 OK; dev-container focused validator unittest 107 OK; full
  KG-eval unittest 426 OK; main repo unittest 252 OK; full Ruff check and
  format-check; operator guide `--check`; submission template
  `--check-template`; refreshed broad reports; and default main KG acceptance
  `passed_with_explicit_limits`. Strict main KG acceptance still exits
  nonzero only for known limits. Broad KG-eval remains incomplete with the
  same four failed real-evidence gates and empty real roots. GPT/Codex
  reviewer gate passed 3/3: `Nietzsche`, `Bacon`, and `Copernicus`; a no-op
  `Averroes` spawn is not counted.
- Preflight canonical packet path-hazard guard: `real_evidence_preflight.py`
  now detects symlink, hardlink, and non-regular canonical packet paths before
  refreshing total acceptance, objective audit, or per-gate validators. It
  reports `canonical_packet_path_hazards`, leaves the preflight blocked, skips
  validator refreshes under hazards, and avoids reading or hashing alias packet
  paths. Dev-container verification passed: focused preflight unittest 17 OK,
  full KG-eval unittest 428 OK, main repo unittest 252 OK, full Ruff
  check/format-check, refreshed broad reports, operator guide `--check`,
  submission template `--check-template`, and default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with the same four
  failed real-evidence gates, empty real roots, and absent canonical packets.
  GPT/Codex reviewer gate passed 3/3: `Beauvoir`, `Dewey`, and `Rawls` after
  `Beauvoir`'s total/audit refresh blocker and `Dewey`'s test-cleanup /
  no-validator-run blockers were fixed and re-reviewed. A mistakenly spawned
  no-op `Laplace` agent is not counted.
- Candidate-intake execution runner: `real_evidence_submission_manifest.py`
  now supports explicit `--execute-candidate-intakes` for a validated
  operator-filled submission manifest. It uses fixed manifest-derived argv,
  runs existing candidate-only intake helpers without a shell, requires
  existing response packets, rejects path-only execution mode, stops on first
  failed intake, and reports that successful earlier candidate artifacts remain
  for operator review. This runner can read operator response contents and
  write candidate artifacts, but it does not promote evidence, pass promotion
  flags, write canonical broad packets, or count as acceptance. The tracked
  operator guide documents the command and claim boundary. Verification
  passed: focused dev-container submission/guide unittest 33 OK, full KG-eval
  unittest 435 OK, main repo unittest 252 OK, guide/template checks,
  changed-file Ruff check and format-check, refreshed total/preflight reports,
  and default main KG acceptance `passed_with_explicit_limits`; strict still
  exits nonzero only for known limits. Broad KG-eval remains incomplete with
  the same four failed real-evidence gates and empty real roots. Reviewer gate
  passed 3/3 with `Nash`, `Pauli`, and `Locke`; `Hegel`'s docstring/help
  blocker was fixed and re-reviewed by replacement reviewer `Locke`.
  Non-counted agents: `Pascal`, `Sagan`, `Bernoulli`, `Arendt`, and blocker-only
  `Hegel`.
- Candidate-manifest validate-only runner: `real_evidence_submission_manifest.py`
  now supports `--validate-candidate-manifests` after candidate-only intake.
  It validates the operator submission manifest first, requires the four fixed
  emitted `work_packets/*_candidate_manifest.json` files to exist as safe
  regular non-symlink/non-hardlink files, then runs fixed assembler argv in
  `--validate` mode only with no shell. The runner reads candidate manifests
  and candidate artifacts through the assemblers, summarizes validation output
  without echoing assembled candidate packets, writes no candidate artifacts,
  passes no `--promote`, writes no canonical broad packets, promotes no
  evidence, and does not count as acceptance. Verification passed: focused
  dev-container submission/guide unittest 41 OK, full KG-eval unittest 443 OK,
  main repo unittest 252 OK, guide/template checks, full Ruff check/format
  check, refreshed broad reports, default KG acceptance
  `passed_with_explicit_limits`, and strict KG acceptance exits 1 only for the
  known `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked limits. Broad KG-eval
  remains incomplete with the same four failed real-evidence gates, empty real
  roots, and absent canonical packets. Reviewer gate passed 3/3:
  `Einstein`, `Sartre`, and `Heisenberg`; all three suggested direct hardlink
  test coverage for emitted candidate manifests, the test was added, and
  `Einstein` re-reviewed the final delta with `AGREE`.
- Candidate-validation report output: `real_evidence_submission_manifest.py
  --validate-candidate-manifests` now accepts optional
  `--emit-candidate-validation-report` to persist the validate-only result as
  an ignored non-evidence `work_packets/*_candidate_validation_report.json`
  review aid. The output must be a direct child of `work_packets/`, cannot use
  template/preview/candidate-manifest/intake-plan/tracked names, cannot
  overwrite an existing file, and is written through a same-directory
  temporary file plus atomic no-overwrite link so interrupted writes leave no
  final partial JSON report. Invalid operator manifests and missing emitted
  candidate manifests do not write a report; failed assembler validation after
  preflight may write a failure report for manual review only. Verification
  passed: host focused submission/guide unittest 48 OK; dev-container focused
  submission/guide unittest 48 OK; full KG-eval unittest 450 OK; main repo
  unittest 252 OK; guide/template checks; full Ruff check/format-check;
  refreshed broad reports; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for the known
  `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked limits. Broad KG-eval
  remains incomplete with the same four failed real-evidence gates, empty real
  roots, and absent canonical packets. Reviewer gate state: `Turing` agreed;
  `Cicero` agreed after nested-path and partial-write blockers were fixed;
  `Boyle` agreed after missing-durable-doc and stale-checkpoint blockers were
  fixed. Reviewer gate passed 3/3. A no-op `McClintock` spawn is not counted.
- Intake-plan output path hardening: `real_evidence_submission_manifest.py
  --emit-intake-plan` now rejects nested `work_packets/...` output paths.
  Intake plans must be safe direct children of `work_packets/`, matching the
  ignored operator work-packet surface used by candidate-validation reports.
  Focused regression coverage was added. Verification passed: host focused
  submission-manifest unittest 40 OK; dev-container focused
  submission-manifest unittest 40 OK; full KG-eval unittest 450 OK; main repo
  unittest 252 OK; refreshed broad reports; guide/template checks; full Ruff
  check/format-check; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for known limits. Broad KG-eval remains
  incomplete with the same four failed real-evidence gates, empty real roots,
  and absent canonical packets. Reviewer gate passed 3/3: `Anscombe` agreed
  on engineering path safety, `Epicurus` agreed on governance and non-evidence
  boundaries, and `Ptolemy` agreed on durable docs/status honesty.
- 2026-06-28 status-only resume checkpoint: after the user asked for remaining
  engineering-item count, Codex confirmed the work board still has 9 unchecked
  items: 1 KG-owned full real-evidence objective and 8 System
  Backbone/product-infra items. Dev-container verification in this resume
  passed for KG-eval unittest 450 OK and main repo unittest 252 OK. A later
  dev-container report refresh command was rejected by the approval reviewer
  because it required unsandboxed Docker socket access with workspace writes;
  sandbox host-level supplemental report commands exited 0 and still showed
  the same blocked broad KG state. Host `ruff` is unavailable, so lint/format
  was not rerun in this resume. Safety checks found all four `inputs/*_real`
  roots empty and the four canonical broad evidence packets absent. The full
  KG objective remains active and incomplete with the same four failed broad
  gates.
- 2026-06-28 intake-plan partial-write hardening: the candidate-only
  `real_evidence_submission_manifest.py --emit-intake-plan` path now writes
  ignored non-evidence intake plans through a temporary file plus atomic
  no-overwrite link, matching the candidate-validation report writer. A
  regression test now simulates interrupted intake-plan writes and asserts
  that neither a final partial plan nor a temporary partial file remains. This
  accepts no evidence, writes no candidate artifacts, promotes no evidence,
  writes no canonical broad packet, and does not count as acceptance. Host
  verification passed: focused submission-manifest unittest 41 OK, full
  KG-eval unittest 451 OK, main repo unittest 252 OK, guide check after
  regeneration, template check, and host main KG acceptance default
  `passed_with_explicit_limits`; strict exits 1 only for the known failed /
  blocked items. Broad KG-eval remains incomplete with the same four failed
  gates, empty real roots, and absent canonical packets. Canonical
  dev-container verification, Git commit/push, and reviewer gate are pending
  because escalated Docker/Git/network permissions were rejected in this
  resume.
- 2026-06-28 real-root churn preflight hardening: `real_evidence_preflight.py`
  now treats files that disappear during `inputs/*_real` scanning as unstable
  non-evidence. The scanner records `disappeared_file_count` and
  `disappeared_file_paths`, does not count those paths as files or candidate
  artifacts, keeps `root_ready=false`, and makes the hazard summary non-clear.
  This prevents concurrent operator/test cleanup from crashing preflight or
  accepting transient files. A regression test simulates a disappearing real
  artifact during scan. This accepts no evidence, writes no candidate
  artifacts, promotes no evidence, writes no canonical broad packets, and does
  not count as acceptance. Host verification passed: focused preflight unittest
  18 OK, focused submission-manifest unittest 41 OK, full KG-eval unittest
  452 OK, main repo unittest 252 OK, guide/template checks, refreshed broad
  reports, and host main KG acceptance default `passed_with_explicit_limits`;
  strict exits 1 only for known failed / blocked items. Broad KG-eval remains
  incomplete with the same four failed gates, empty real roots, absent
  canonical packets, and zero disappeared-file hazards in the current scan.
  Canonical dev-container verification, Git commit/push, and reviewer gate are
  still pending because escalated Docker/Git/network permissions were rejected
  in this resume.
- 2026-06-28 work-order disappeared-file contract hardening:
  `real_evidence_collection_work_orders.py` now carries
  `real_root_disappeared_file_count` in each work-order preflight snapshot and
  fails closed if per-gate preflight rows omit, mistype, or report nonzero
  `disappeared_file_count`. This keeps unstable real-root scans from being
  treated as clean missing-evidence absence in operator work orders. Reviewer
  blocker fix: real-root scanning now uses `lstat()` before file-type
  classification, so a path that disappears before the old `is_file()` check
  is reported through `disappeared_file_count` instead of being silently
  treated as clean absence. The tracked operator guide remains synchronized
  after the work-order report schema/hash changed. This accepts no evidence,
  writes no candidate artifacts, promotes no evidence, writes no canonical
  broad packets, and does not count as acceptance. Canonical dev-container
  verification passed: focused current-slice KG-eval unittest 79 OK, full
  KG-eval unittest 454 OK, main repo unittest 252 OK, guide/template checks,
  refreshed broad reports, default main KG acceptance
  `passed_with_explicit_limits`, strict main KG acceptance exits 1 only for
  known limits, full Ruff check and format-check, and `git diff --check`.
  Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates. Reviewer gate passed 3/3 after blocker
  fixes: `Curie`, `Erdos`, and `Hume` returned `RELEASE_DECISION: AGREE`.
  This slice was committed and pushed on `complete-slice-1` as `8fc5a55`
  (`Harden KG real-evidence preflight work orders`).
- 2026-06-28 restart-note cleanup: `.formowl/kg-eval/SESSION_RESTART.md`
  still had an older "Next Best Work" section saying broad validators needed
  real-root path-helper hardening. That target is complete, with tests covering
  `results/`, `inputs/test_*`, templates, and template-named artifacts under
  real roots. The restart note now treats that as historical and points the
  next action back to canonical dev-container verification plus real
  operator/user-supplied evidence for the four failed gates. Host consistency
  checks passed: `git diff --check`, operator guide `--check`, submission
  template `--check-template`, and focused work-order unittest 19 OK.
- 2026-06-28 historical blocked audit, superseded later the same day by user
  authorization and canonical verification: the same external blocker repeated
  across continuation turns, with canonical dev-container Docker verification
  rejected by the approval reviewer and Git commit/push blocked. This is no
  longer the current Docker/Git state for this run; it remains only as audit
  history. The four broad gates still require real operator/user-supplied
  evidence packets.
- 2026-06-28 resume authorization: the user explicitly authorized collecting
  failed-gate evidence, Docker/dev-container access, and Git commit/push.
  Durable KG goal status is active again for this run, and canonical
  dev-container verification plus the 3 Codex/GPT reviewer gate for the
  current work-order/preflight hardening slice have passed. Reviewer gate
  result: `Curie`, `Erdos`, and `Hume` returned `RELEASE_DECISION: AGREE`
  after blocker fixes. The slice was pushed as `8fc5a55` on
  `complete-slice-1`. The broad KG objective still remains incomplete until
  real operator/user-supplied artifacts and governed canonical packets make the
  four broad gates pass.
- 2026-06-28 post-push checkpoint: local `HEAD` and
  `origin/complete-slice-1` both point to `8fc5a55`
  (`Harden KG real-evidence preflight work orders`) with a clean worktree
  before this status-doc update. The next KG-owned work remains real
  operator/user-supplied evidence collection and governed packet validation for
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Do not
  treat work orders, candidate manifests, intake plans, or validation reports
  as acceptance evidence.
- 2026-06-28 candidate-runner canonical packet integrity: the controlled
  submission-manifest runners now snapshot all four canonical broad packet
  paths before subprocess execution and fail closed if candidate-only intake or
  validate-only assembler subprocesses exit with a canonical packet path
  created or changed. The output reports `canonical_packet_integrity`; this is
  final-state surface integrity, not a live transient-write audit. The tracked
  operator guide documents that boundary. Verification passed in the dev
  container: focused submission/guide unittest 51 OK, full KG-eval unittest
  456 OK, main repo unittest 252 OK, guide/template checks, refreshed broad
  reports, default KG acceptance `passed_with_explicit_limits`, strict KG
  acceptance exits 1 only for known limits, and full Ruff check/format-check.
  Reviewer gate passed 3/3 with `Sagan`, `Hooke`, and `Laplace`; a mistaken
  no-op `Banach` subagent is not counted. Broad KG-eval remains incomplete
  with `overall_passed=false`, 8 passed gates, and the same four failed gates.
- 2026-06-28 candidate-runner pre-existing canonical packet hazard guard: the
  controlled `real_evidence_submission_manifest.py
  --execute-candidate-intakes` and `--validate-candidate-manifests` runners
  now refuse to launch subprocesses if any canonical broad packet path is
  already a symlink, hardlink alias, non-regular file, or unreadable /
  metadata-unavailable surface. The refusal path returns
  `executed_gate_count=0`, reports `canonical_packet_baseline`, reads no
  response packet or candidate manifest contents, writes no candidate
  artifacts, promotes no evidence, and writes no canonical broad packets. The
  tracked operator guide documents the boundary. Canonical dev-container
  verification passed: focused submission/guide unittest 55 OK, full KG-eval
  unittest 460 OK, main repo unittest 252 OK, guide/template checks,
  refreshed broad reports, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance exits 1 only for known limits, full Ruff
  check/format-check, and `git diff --check`. Broad KG-eval remains
  incomplete with the same four failed real-evidence gates. Reviewer gate
  passed 3/3: `Wegener` agreed on engineering correctness after the canonical
  packet test helper was changed to preserve pre-existing path surfaces by
  rename; `Feynman` agreed on governance/safety; and `Kuhn` agreed on status
  honesty.
- 2026-06-28 governed approval-bridge hardening: added the non-evidence
  governance approval runner, focused tests, and tracked approval template.
  The runner validates an operator-filled approval manifest before any
  canonical packet update by binding the candidate validation report hash,
  candidate manifest hash, target gate, canonical packet, exact validate-only
  validation argv, exact approval scope / claim boundary, and human approver.
  Execute mode uses fixed assembler `--promote` argv, rechecks candidate
  manifest hash after the subprocess, verifies only the target canonical
  packet changed, and rolls back a newly created target packet on
  candidate-manifest drift. The four packet assemblers now promote through a
  temporary file plus atomic no-overwrite hard link; candidate validation
  reports include `candidate_manifest_sha256`; canonical packet surface checks
  reject hazardous parent components; and the operator guide documents the
  controlled approval flow. Canonical dev-container verification passed:
  focused approval/submission unittest 57 OK; approval-template,
  operator-guide, and submission-template checks; full KG-eval unittest
  470 OK; main repo unittest 252 OK; full Ruff check/format-check; refreshed
  broad reports; default KG acceptance `passed_with_explicit_limits`; strict
  KG acceptance exits 1 only for known limits. Real roots remain empty,
  canonical broad packets remain absent, and broad KG-eval remains incomplete
  with the same four failed gates. Reviewer gate is pending final 3 Codex/GPT
  re-review for this slice; do not claim the goal complete.
- 2026-06-28 governed approval-bridge reviewer-blocker follow-up:
  Bernoulli found a candidate-manifest TOCTOU blocker: post-subprocess rehash
  alone could miss a transient swap/restore before assembler read. The fix
  adds an approved `--assembly-manifest-sha256` guard to approved promotion
  argv and makes all four packet assemblers hash the manifest bytes they read
  before assembly/promotion. The operator guide and durable docs now state this
  boundary. Canonical dev-container verification after the fix passed:
  focused approval/assembler/operator-guide unittest 78 OK; full KG-eval
  unittest 474 OK; main repo unittest 252 OK; approval-template,
  operator-guide, and submission-template checks; full Ruff check/format-check;
  refreshed broad reports; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for known limits. Broad KG-eval remains
  incomplete with the same four failed gates; all four real roots remain empty
  and canonical broad packets remain absent. Reviewer gate passed 3/3:
  `Bernoulli` agreed after the TOCTOU blocker fix, `Popper` agreed after the
  final hash-guard delta, and `Dalton` agreed after durable docs/tracking were
  updated and staged.
