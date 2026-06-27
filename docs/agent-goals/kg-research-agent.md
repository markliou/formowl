# Knowledge Graph Research Agent Goal

## Role

Knowledge Graph Research Agent.

Durable role definition: `docs/agent-roles.md`.

## Current Objective

Complete the FormOwl Knowledge Graph method exploration and acceptance work:
fill in external recent literature comparison, ontology integration method,
multi-user KG and KG fusion experiments, multimodal enterprise-data validation,
human operation / annotation / adjudication workflow, production adapter gate,
and a total acceptance suite that clearly marks passed and failed items.

Historical source: Codex session `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.

Status: `active`

## Current Acceptance State

Do not treat the current KG objective as complete.

Two different acceptance layers currently exist:

- Main-repo KG research acceptance slice:
  `scripts/kg_research_acceptance_suite.py` currently reports
  `passed_with_explicit_limits`. This means the method note, deterministic
  fixtures, scoped ontology contracts, candidate-only package boundary, metrics,
  ablations, and explicit limitations are present.
- Broad real-evidence KG acceptance:
  `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json` remains the
  stricter recovery/real-evidence state for the user's full KG objective.
  It currently has `overall_passed=false`, 8 passed gates, and 4 failed gates.

The four failed broad real-evidence gates are:

- `fair_external_baseline_comparison`
- `annotation_adjudication_protocol`
- `multimodal_semantic_validation`
- `production_adapter_paths`

The goal is complete only when the broad real-evidence acceptance state proves
all required gates, the main-repo acceptance suite has no failed or blocked
requirements under strict mode, the work board reflects that state, and the
configured reviewer gate has passed for every newly completed slice.

`passed_with_explicit_limits` is not a completion status for this durable goal.
It is a useful intermediate status that says known limits are explicitly
reported.

## Returned For Rework

2026-06-27 review returned these claims/slices:

- The `Complete KG research acceptance gate` completion claim is rejected for
  the full KG objective. The stricter broad acceptance state is still
  `overall_passed=false` with the four failed real-evidence gates listed above.
- The reviewed canonical graph commit workflow was returned for rework and the
  rework slice was completed on 2026-06-27. It now demonstrates incremental
  graph revisions that retain parent revision atoms, entities, and relations,
  and relation commits that can resolve against existing canonical endpoints
  under governance. This does not change the broad real-evidence acceptance
  state.
- Portability rework started on 2026-06-27: `.gitignore` now allows the
  sanitized `.formowl/kg-eval` harness, restart note, fixtures, templates, work
  orders, work-packet previews, and non-authoritative blocked-state snapshots
  under `snapshots/current_blocked/` to be committed. Generated runtime
  `results/`, long local `HANDOFF.md`, operator real roots under
  `inputs/*_real/`, and canonical real evidence packets remain ignored. This
  fixes the acceptance-authority portability gap; it does not make any broad
  real-evidence gate pass.

## Context Budget Rule

The user requested frequent compaction when executing this goal, even though it
can reduce conversational accuracy, because token budget is the limiting
resource. Treat this goal as compact-friendly work:

- Keep in-chat updates concise and avoid reprinting long artifacts.
- After each meaningful substep, record enough state in durable files to resume
  without relying on chat history.
- Update this goal file or the work-board note after each reviewer attempt,
  blocker, test/verification result, or acceptance-status change.
- Append to `docs/agent-goals/handoff-log.md` when the checkpoint affects a
  future session or another agent.
- Before a planned pause, external approval wait, or likely compaction, write a
  short checkpoint with current status, exact next action, verification state,
  and remaining blocker.

The agent cannot force the external environment to compact on demand, but it
should make every restart cheap and safe by checkpointing more often than usual.

## Abstract

This goal exists because FormOwl's knowledge graph layer must be more than a
method sketch. It must define and test an ontology-grounded, source-preserving,
permission-aware graph fusion workflow for heterogeneous enterprise resources,
including documents, tables, slides, audio/video meetings, images, mail,
project systems, wiki pages, and conversations.

The expected result is not a claim of production readiness by assertion. The
agent must produce reproducible evidence: literature-backed design choices,
baselines, evaluation fixtures, metrics, ablations, error analysis, and clear
limits. Any algorithmic package or LLM may only generate candidates or review
proposals; canonical graph, canonical type, user graph, and wiki state remain
governed outputs.

## Scope

Owned by this agent:

- Candidate graph extraction and preview semantics.
- Ontology/type governance, scoped alignment, and type lifecycle.
- Atom granularity policy, split/merge/coarsening behavior, and lifecycle
  mappings.
- Entity and relation resolution as permission-aware proposal workflows.
- Reviewed canonical graph commit behavior and lineage requirements.
- User graph assembly, effective graph views, graph-derived wiki semantics,
  and projection lineage.
- Evaluation harnesses, datasets, baselines, ablations, reviewer critiques,
  and reproducibility artifacts for KG quality and governance claims.

Not owned by this agent unless explicitly assigned:

- MCP transport implementation.
- Storage backend plumbing.
- Worker execution boundaries.
- Database migrations and production service operations.
- Real OpenProject or wiki backend adapter plumbing.

## Acceptance Criteria

The goal is not complete until current-state evidence proves all of the
following:

- A recent external literature and system comparison that justifies the chosen
  KG fusion, ontology, and evaluation approach, plus a fair external baseline
  protocol that is not self-defined by FormOwl alone.
- Real external baseline execution evidence for the selected baseline systems
  or packages, including locked sources, equalized configs, package/run
  manifests, answer-quality adjudication, graph-quality validation, and
  permission probes.
- A concrete ontology integration method that keeps core supertypes, scoped
  extension types, promoted types, and type alignment candidates separate.
- Experiments for different users, different private scopes, graph overlays,
  revocation, conflict surfacing, and cross-scope fusion without silent access
  grants or canonical merges. Deterministic fixtures are allowed as method
  evidence, but production-quality claims require real or replayable evidence
  packets.
- Multimodal enterprise-resource validation covering at least document/table,
  mail/conversation, project/wiki, and audio/video-style observations or
  fixtures. Claims about real enterprise validation require a validated real
  evidence packet, not only synthetic fixtures.
- Human review, annotation, adjudication, reviewer-disagreement, custody, and
  confusion-matrix evidence where governance claims depend on human judgment.
  Review-queue export alone is not completed human annotation.
- A production adapter gate that clearly separates candidate-only algorithm
  outputs from canonical graph/type mutations and backend service readiness,
  and also proves non-synthetic adapter-path evidence before any production
  readiness claim.
- Metrics for extraction quality, fusion quality, ontology/type alignment,
  provenance completeness, permission safety, latency, and scalability where
  applicable.
- Ablations for ontology guidance, policy gates, candidate review, and
  permission-aware filtering.
- Error analysis and explicit limitations.
- A total acceptance suite or checklist that marks each requirement as passed,
  failed, or blocked with evidence.
- No canonical evidence packet is created from templates, fixtures, sandbox
  paths, stale manifests, symlinks, hardlink aliases, unbound response packets,
  raw/internal paths, raw SQL, object-store/admin endpoints, or worker scratch
  paths.
- The reviewer gate in `docs/agent-goals/reviewer-gate.md` is satisfied for
  each newly completed KG implementation or research slice.

## Required Restart Procedure

At the start of every KG Research Agent session or after compaction, read the
normal repository startup files from `AGENTS.md`, then read:

1. `docs/agent-goals/kg-research-agent.md`
2. `docs/agent-goals/handoff-log.md`
3. `docs/agent-goals/reviewer-gate.md`
4. `.formowl/kg-eval/SESSION_RESTART.md`, if present
5. Tail `.formowl/kg-eval/HANDOFF.md`, if present
6. `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json`, if present
7. `.formowl/kg-eval/results/real_evidence_preflight.json`, if present
8. `.formowl/kg-eval/results/real_evidence_collection_work_orders.json`, if
   present

After reading, derive the active work from current files, not from chat memory.
If the main-repo goal file and `.formowl/kg-eval` disagree, use the stricter
state and update durable docs before claiming progress.

## Execution Rules For Future Sessions

- Work one broad failed gate or one reviewer blocker at a time.
- Do not redefine the objective around the easiest passing subset.
- Do not convert deterministic fixtures into real evidence.
- Do not promote these canonical broad packets unless real evidence exists and
  the corresponding validator accepts it:
  - `inputs/fair_external_baseline_run_packet.json`
  - `inputs/human_annotation_results_v1.json`
  - `inputs/enterprise_multimodal_validation_packet.json`
  - `inputs/production_adapter_evidence_packet.json`
- Candidate-only response intake helpers may write under `inputs/*_real/` only
  for operator-supplied candidate artifacts and must also preserve custody
  hashes. They must not make a broad gate pass by themselves.
- Before pausing, append the exact next action, reviewer state, verification
  state, and remaining failed gates to this file or `handoff-log.md`.

## Verification Baseline

Use the dev container as canonical evidence:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```

Add narrower focused test commands as work lands, but do not report host-only
checks as completion evidence.

For KG research acceptance, also run the strict command when evaluating
completion:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python scripts/kg_research_acceptance_suite.py --strict
```

For broad real-evidence KG acceptance, run the KG-eval acceptance and preflight
commands from `.formowl/kg-eval` in the dev container when those files are
present:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local \
  python kg_total_acceptance_suite.py
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local \
  python real_evidence_preflight.py
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local \
  python -m unittest discover -s . -p 'test_*.py'
```

## Reviewer Gate

Use the default cross-agent reviewer gate from
`docs/agent-goals/reviewer-gate.md`: 3 effective read-only Codex/GPT reviewers
per newly completed slice unless the user explicitly changes the count for that
slice.

Antigravity/Gemini through `agy` is disabled for the default FormOwl KG gate as
of 2026-06-28. Repeated bounded FormOwl KG packets were rejected before
execution by tenant policy, and a no-repository-content MCP route probe found
no Codex-exposed Antigravity/`agy` MCP tool or configured Antigravity MCP
server. Historical `agy` review/write records remain in this file for audit
context, but future KG resumes should not ask for Antigravity bounded-review
authorization or wait on `agy` unless the user explicitly re-enables it after a
policy, platform, or MCP configuration change.

Reviewer cost-control rules:

- Run local focused tests, canonical dev-container tests, and a self-audit
  before asking reviewers.
- Send reviewers a bounded packet for the exact slice, not the whole
  repository history.
- Use Codex/GPT reviewers across the highest-risk engineering,
  governance/safety, and research-method surfaces for the slice.
- If a reviewer finds a blocker, fix that blocker and return to the same
  reviewer before expanding to more reviewers.
- Do not count timed-out, errored, vague, no-op, duplicate, or wrong-scope
  reviews.

## Current Handoff Notes

- This file records the durable goal imported from session
  `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.
- On 2026-06-27, the user changed the reviewer gate from 9 effective reviewers
  to 6 effective reviewers: 3 Codex/GPT reviewers and 3 Antigravity Gemini
  reviewers through the local `agy` CLI.
- On 2026-06-28, after repeated tenant-policy rejections and an MCP route probe
  that found no Codex-exposed Antigravity/`agy` MCP tool, the default reviewer
  gate was changed to 3 Codex/GPT reviewers. `agy` is disabled for default
  reviewer gates and bounded write delegation unless the user explicitly
  re-enables it after policy, platform, or MCP configuration changes.
- The current session did not inherit that session-local goal automatically.
  Future sessions should read this file instead of relying on local Codex goal
  state.
- Keep `docs/implementation-task-breakdown.md` as the checkbox work board.
  This file records the objective, acceptance gates, and handoff state.
- 2026-06-27 update: scoped ontology/type governance contracts,
  `formowl_graph.ontology`, KG research acceptance suite,
  `scripts/kg_research_acceptance_suite.py`, and
  `docs/kg-research-method.md` are implemented. Dev-container verification
  passed: changed-file Ruff check and format check, focused ontology contract
  tests (4 OK), focused KG acceptance tests (4 OK), full unittest (246 OK),
  and the default acceptance script. The acceptance suite intentionally reports
  `production_adapter_readiness` as failed and
  `latency_scalability_enterprise_claims` as blocked, with no unexpected
  failed or blocked items. This completed the method/acceptance-harness slice,
  not the full KG objective.
- Reviewer gate status for the KG research acceptance-harness slice is complete at
  6/6. GPT/Codex reviewers `Kuhn`, `Goodall`, and `Pasteur` agreed after
  blocker fixes. Antigravity Gemini reviewers `Ada-Sandbox`,
  `Lamport-Sandbox`, and `Curie-Sandbox` agreed through the real local `agy`
  CLI using sandboxed, closed-book, bounded review packets authorized by the
  user. `Raman` found initial blockers and was replaced for re-review after
  being closed. Initial Antigravity attempts rejected by sandbox policy, the
  `Ada` timeout, and the aborted/timed-out `Ada-Retry` run do not count.
- 2026-06-27 historical update: the user requested that future resumes of this
  goal ask for Antigravity Gemini bounded-review authorization at the start of
  the run, not after local work is complete. This rule is superseded by the
  2026-06-28 gate-policy checkpoint: do not ask for Antigravity authorization
  during ordinary KG resumes unless the user explicitly re-enables `agy` after
  policy, platform, or MCP configuration changes.
- 2026-06-27 update: the user requested frequent compaction for this goal to
  conserve token budget. Use short, durable checkpoints in this file, the work
  board, and the handoff log so future compact/resume cycles recover state
  without large chat history.
- 2026-06-27 agy authorization checkpoint: the user requested that the
  Antigravity/Gemini reviewer permission problem be handled before continuing
  KG implementation. Standing scoped authorization is now recorded in the
  repo-local `use-agy-antigravity` skill, this goal file, and
  `docs/agent-goals/reviewer-gate.md`: Codex may run the local `agy` CLI with
  sandbox escalation and may send bounded read-only FormOwl KG reviewer
  packets, while still excluding secrets, credentials, raw private source
  payloads, raw backend paths, NAS/object-store admin endpoints, raw SQL,
  database dumps, worker scratch paths, local filesystem internals, and
  unrelated private data. If `agy` is slow, confirm it is still running and
  wait; if external-disclosure approval or tenant policy rejects execution,
  record the blocker and do not bypass it.
- 2026-06-27 bounded-write delegation checkpoint: the user also authorized
  Codex to ask Antigravity to write bounded code/docs slices to save Codex
  token budget. Future invocations must name exact owned files or directories,
  keep the workspace minimal, avoid unrelated changes, and leave Codex
  responsible for diff inspection, dev-container verification, durable docs,
  and final commit. Do not use `--dangerously-skip-permissions` without a
  separate exact approval.
- 2026-06-27 agy policy/write test result: local `agy` availability works
  (`agy --version` returned `1.0.13`, and `agy models` listed
  `Gemini 3.5 Flash (High)`). A minimal bounded FormOwl KG read-only reviewer
  packet was rejected before execution by tenant policy as external disclosure
  to an untrusted reviewer service; no packet was sent and no workaround was
  attempted. For write delegation, plain one-shot `--add-dir` was not reliable
  for intended workspace writes, but `--new-project --add-dir` successfully
  wrote to an empty intended workspace. Future bounded write delegation should
  use `--new-project --add-dir <smallest-scope>` and must be verified by Codex
  through local diff inspection and dev-container checks.
- 2026-06-27 method-slice checkpoint: current-state verification passed in the
  dev container: default KG research acceptance suite returned
  `passed_with_explicit_limits` with only expected
  `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked; focused KG acceptance tests
  ran 4 OK; focused ontology tests ran 4 OK; full
  `python -m unittest discover -s tests` ran 246 tests OK. The work-board KG
  Research Evaluation and Acceptance method-slice item is checked complete.
- 2026-06-27 correction checkpoint: this durable goal was previously marked
  `complete`, but current stricter evidence contradicts that. The broad
  `.formowl/kg-eval` acceptance snapshot still has `overall_passed=false` with
  failed gates for fair external baseline comparison, real human annotation,
  real enterprise multimodal validation, and production adapter paths. Treat
  the durable KG objective as `active` until those gates pass with real
  evidence and strict main-repo KG research acceptance has no failed or blocked
  requirements.
- 2026-06-27 portability checkpoint: the strict broad KG-eval harness is now
  intended to be tracked as non-sensitive acceptance authority. Runtime
  `results/` remain local ignored outputs; `snapshots/current_blocked/` carries
  non-authoritative blocked-state references that must not be treated as
  completion evidence without rerunning the dev-container commands. The commit
  must still exclude local long-form handoff history, operator real artifact
  roots, and canonical real evidence packets. Current state remains
  `overall_passed=false` with the same four failed gates.
- 2026-06-27 portability verification: canonical dev-container KG-eval
  unittest ran 360 tests OK; main repo unittest ran 246 tests OK; broad
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, and `real_evidence_collection_work_orders.py`
  all ran. Broad KG-eval remains `overall_passed=false` with 8 passed gates and
  4 failed gates. Main-repo KG acceptance default remains
  `passed_with_explicit_limits`; strict mode still fails as expected while
  `production_adapter_readiness` is failed and
  `latency_scalability_enterprise_claims` is blocked.
- 2026-06-27 portability reviewer checkpoint: Antigravity Gemini final-version
  reviews reached 3/3 AGREE after one useful blocker. The blocker was that
  tracking all `inputs/` and runtime `results/` could accidentally commit
  operator artifacts or stale passing result files. The final patch ignores
  arbitrary `inputs/`, runtime `results/`, real roots, canonical evidence
  packets, and long local handoff history, and tracks only fixtures plus
  non-authoritative blocked snapshots. No reviewer approval changes the broad
  KG completion state.
- 2026-06-27 canonical commit rework checkpoint: reviewed canonical graph commit
  workflow rework is complete. `commit_reviewed_candidates_to_canonical_graph`
  now carries same-scope committed parent graph membership forward, reconstructs
  parent candidate-to-canonical atom resolution for child relation commits,
  supports reviewed relation-only commits when endpoints resolve through the
  parent/current mapping, rejects empty commits, rejects corrupt parent relation
  endpoints before child writes, and still persists only through the governed
  canonical store path. Dev-container verification passed: changed-file Ruff
  check and format check, focused canonical workflow unittest 16 OK, full main
  repo unittest 252 OK, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance failed only on the known expected
  `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked items, and KG-eval unittest
  360 OK. Reviewer state: GPT/Codex `Kuhn-GPT`, `Goodall-GPT`, and
  `Pasteur-GPT` agreed on the final diff after Pasteur's blocker about
  parent entity/relation membership test coverage was fixed. Antigravity
  Gemini `Lamport-Sandbox`, `Ada-Sandbox`, and `Curie-Sandbox` agreed through
  real `agy` on the implementation diff; an attempted final re-review after
  the test-only blocker fix was rejected by sandbox/tenant data-egress policy,
  and no workaround was attempted. The broad KG objective remains `active`:
  `.formowl/kg-eval` still reports `overall_passed=false`, 8 passed gates, and
  4 failed gates for `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`.
- 2026-06-27 fair-baseline response-intake checkpoint: candidate-only
  `fair_baseline_response_intake.py` is implemented and wired into
  `real_evidence_collection_work_orders.py` for
  `fair_external_baseline_comparison`. It seals operator-supplied response JSON
  into candidate artifacts under `inputs/fair_baseline_real/<operator-run-id>`,
  can write a candidate assembly manifest under `work_packets/`, records
  response/candidate/artifact custody hashes, rejects raw/internal/template
  payloads, symlinks, unsafe output roots, overwrite attempts, and promotion
  arguments, and does not write
  `inputs/fair_external_baseline_run_packet.json`. Initial GPT reviewer
  blockers for unreceipted manifest hashes, post-write assembler failures,
  parent-file partial writes, and production-shaped test cleanup were fixed by
  custody-hashing the optional manifest, rolling back any intake-created files
  on assembler/custody-write failure, preflighting output parent directories,
  and moving tests under a test-marked real-root parent. Dev-container
  verification passed: KG-eval unittest 372 OK, main repo unittest 252 OK,
  changed-file Ruff check and format-check passed, and
  `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
  `real_evidence_collection_work_orders.py` were refreshed in the dev
  container. Broad KG-eval remains `overall_passed=false` with the same 8
  passed gates and 4 failed real-evidence gates; work orders are synchronized
  and non-authoritative with 4 collection work orders. Reviewer gate state:
  GPT/Codex reviewers `Poincare`, `Popper`, and `Carson` returned
  `RELEASE_DECISION: AGREE` after blocker fixes. Antigravity Gemini reviewers
  are blocked at 0/3 because tenant policy rejected both the code/diff bounded
  packet and a materially safer closed-book bounded summary through real
  `agy`; no workaround or alternate external channel was attempted.
- 2026-06-27 production-adapter response-intake checkpoint: candidate-only
  `production_adapter_response_intake.py` is implemented and wired into
  `real_evidence_collection_work_orders.py` for `production_adapter_paths`.
  It seals operator-supplied response JSON into candidate artifacts under
  `inputs/production_adapter_real/<operator-run-id>`, can write a candidate
  assembly manifest under `work_packets/`, records response/candidate/artifact
  and optional manifest custody hashes, rejects unsafe output roots,
  symlinks, overwrites, parent-file collisions, raw/internal/template payloads,
  duplicate/missing adapter components, and promotion arguments, and does not
  write `inputs/production_adapter_evidence_packet.json`. Dev-container
  verification passed so far: changed-file Ruff check and format-check,
  focused KG-eval unittest 27 OK, full KG-eval unittest 383 OK, main repo
  unittest 252 OK, and refreshed broad KG-eval reports. Broad KG-eval remains
  `overall_passed=false` with 8 passed gates and the same 4 failed
  real-evidence gates. GPT/Codex reviewer gate for this slice is 3/3 agreed:
  `Gauss`, `Archimedes`, and `Noether` initially found blockers for sandbox
  and nested output-dir acceptance, unsupported top-level response fields, a
  missing required-component regression test, and incomplete work-order side
  effect snapshots; those blockers were fixed and all three returned
  `RELEASE_DECISION: AGREE`. Antigravity Gemini reviewer gate is blocked at
  0/3: `agy --version` and `agy models` succeeded, but three bounded
  read-only review-packet attempts through real `agy` were rejected before
  execution by tenant policy as external data disclosure to an untrusted
  reviewer service, even with user authorization. No packet was sent, no Gemini
  reviewer ran, and no workaround or alternate external channel was attempted.
- 2026-06-27 enterprise-multimodal response-intake hardening checkpoint:
  candidate-only `enterprise_multimodal_response_intake.py` is hardened for
  `multimodal_semantic_validation` and remains wired into the collection work
  orders. It seals operator-supplied enterprise multimodal response JSON into
  candidate artifacts under
  `inputs/enterprise_multimodal_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`, records response/candidate/artifact,
  custody, and optional manifest hashes, rejects unsupported top-level fields,
  unsafe roots, nested default output dirs, sandbox/test paths by default,
  symlinks, overwrites, parent-file collisions, raw/internal/template payload
  values, raw/internal field names, and promotion arguments, and never writes
  `inputs/enterprise_multimodal_validation_packet.json`. Reviewer blockers for
  normal `OSError` rollback, after-open serialization/write partial files, and
  raw/internal field-name rejection were fixed. Dev-container verification
  passed: changed-file Ruff check and format-check, focused KG-eval unittest
  35 OK, full KG-eval unittest 396 OK, main repo unittest 252 OK, and refreshed
  broad KG-eval reports. Broad KG-eval remains `overall_passed=false`, with 8
  passed gates and the same 4 failed real-evidence gates. GPT/Codex reviewers
  `Aristotle`, `Huygens`, and `Lovelace` returned `RELEASE_DECISION: AGREE`
  after blocker fixes. Antigravity Gemini review is blocked at 0/3 because a
  bounded read-only `agy` review-packet attempt was rejected before execution
  by tenant policy as external data disclosure to an untrusted reviewer service;
  no packet was sent, no Gemini reviewer ran, and no workaround or alternate
  external channel was attempted.
- 2026-06-27 current-state re-execution checkpoint: after the user asked to
  execute the original agent's latest state, the dev-container verification was
  rerun without local code changes. `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
  `real_evidence_collection_work_orders.py` all ran in the dev container.
  Dev-container KG-eval unittest ran 396 tests OK, and main repo unittest ran
  252 tests OK. Default main-repo KG research acceptance still reports
  `passed_with_explicit_limits`; strict mode still exits nonzero only for the
  known `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item, with no unexpected
  failed or blocked requirement ids. Broad KG-eval remains
  `overall_passed=false`: the same four real-evidence gates are blocked by
  missing real artifacts and missing canonical input packets under
  `inputs/fair_external_baseline_run_packet.json`,
  `inputs/human_annotation_results_v1.json`,
  `inputs/enterprise_multimodal_validation_packet.json`, and
  `inputs/production_adapter_evidence_packet.json`. `inputs/*_real` roots are
  present but currently contain zero real or candidate artifacts according to
  preflight. The overall KG goal remains `active`.
- 2026-06-27 operator-guide checkpoint: added
  `.formowl/kg-eval/real_evidence_operator_guide.py`,
  `.formowl/kg-eval/test_real_evidence_operator_guide.py`, and the tracked
  generated guide
  `.formowl/kg-eval/work_packets/remaining_real_evidence_operator_guide.md`.
  The guide is generated from `real_evidence_collection_work_orders.py` and
  gives operators a human-readable checklist for the four remaining
  real-evidence gates, including current blockers, required artifacts,
  candidate-only intake commands, validation commands, and safety boundaries.
  It is explicitly non-authoritative: it accepts no evidence, promotes no
  packets, writes no canonical input packets, and does not count as an
  acceptance gate. Dev-container verification passed: focused operator-guide
  unittest 6 OK, full KG-eval unittest 402 OK, changed-file Ruff check and
  format check, refreshed broad KG-eval reports, main repo unittest 252 OK,
  default main KG acceptance `passed_with_explicit_limits`, and strict main KG
  acceptance still failed only on the known
  `production_adapter_readiness`/`latency_scalability_enterprise_claims`
  limits. Broad KG-eval remains `overall_passed=false` with the same four
  failed real-evidence gates.
- 2026-06-27 operator-guide sync checkpoint: added `--check` mode to
  `.formowl/kg-eval/real_evidence_operator_guide.py` so CI or future agents can
  fail fast when the tracked guide drifts from current work orders. The tracked
  guide now documents the check command. Focused operator-guide unittest now
  covers current-guide success and stale-guide failure without rewriting stale
  content. Dev-container verification passed: `python
  real_evidence_operator_guide.py --check`, focused operator-guide unittest 8
  OK, full KG-eval unittest 404 OK, changed-file Ruff check and format check,
  refreshed broad KG-eval reports, main repo unittest 252 OK, default main KG
  acceptance `passed_with_explicit_limits`, and strict main KG acceptance still
  failed only on the known limits. Broad KG-eval remains
  `overall_passed=false` with the same four failed real-evidence gates.
- 2026-06-27 submission-manifest preflight and skill-portability checkpoint:
  added `.formowl/kg-eval/real_evidence_submission_manifest.py`,
  `.formowl/kg-eval/test_real_evidence_submission_manifest.py`, and the tracked
  non-evidence template
  `.formowl/kg-eval/work_packets/remaining_real_evidence_submission_manifest.template.json`.
  The tool validates an operator-filled submission manifest before any
  candidate-only intake command runs, checking the exact four remaining gate
  ids, response packet types, response paths directly under the matching
  ignored `inputs/*_real/<operator_run_id>/` run directory, safe operator run
  ids, real-root output dirs, work-packet manifest outputs, and
  non-authoritative claim boundary. It reads no response-packet contents,
  writes no candidate artifacts, promotes no evidence, writes no canonical
  input packets, and does not count as an acceptance gate. The tracked operator
  guide now includes the preflight commands. The repo-local
  `$use-agy-antigravity` skill at `.agents/skills/use-agy-antigravity/SKILL.md`
  is explicitly the git-clone-portable home for KG `agy` authorization,
  reviewer, and bounded write-delegation rules. Template emit/check is
  restricted to the tracked `.template.json` path so it cannot overwrite
  arbitrary `work_packets/*.json` manifests. Dev-container verification
  passed: submission template `--check-template`, guide `--check`, focused
  submission/guide unittest 17 OK, full KG-eval unittest 413 OK, changed-file
  Ruff check and format check, refreshed broad KG-eval reports, main repo
  unittest 252 OK, and default main KG acceptance
  `passed_with_explicit_limits`; strict mode still fails only on the known
  `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item. Broad KG-eval remains
  `overall_passed=false`, 8 passed gates, and the same four failed broad
  real-evidence gates. Antigravity Gemini review for this slice is blocked at
  0/3: a bounded read-only `agy` reviewer packet containing only relevant
  paths, summaries, verification results, and claim boundaries was rejected
  before execution by tenant policy as external disclosure to an untrusted
  reviewer service. No packet was sent and no workaround or alternate external
  channel was attempted. Codex/GPT reviewers `Dalton`, `Galileo`, `Volta`, and
  `Feynman` returned `RELEASE_DECISION: AGREE`; Dalton's non-blocking
  template-output narrowing suggestion was implemented with a regression test.
- 2026-06-28 submission-manifest CLI and work-packet tracking hardening
  checkpoint: `real_evidence_submission_manifest.py --manifest` now validates
  the operator-filled manifest path before reading it. The path must be a safe
  repo-relative JSON file under `work_packets/`; templates, tracked
  preview-packet naming, absolute/raw/dot-segment paths, non-work-packet
  paths, and symlink components are rejected. `.gitignore` no longer
  re-includes arbitrary `work_packets/*.json` or `*_preview.json`; only the
  four fixed preview packets, the tracked submission template, and the tracked
  operator guide remain portable. The operator guide now states that
  operator-filled manifests and generated candidate manifests under
  `work_packets/` are intentionally ignored. This slice reads no response
  packet contents, writes no candidate artifacts, promotes no evidence, writes
  no canonical input packets, and does not count as an acceptance gate.
  Dev-container verification passed: submission template `--check-template`,
  operator guide `--check`, focused submission/guide unittest 20 OK, full
  KG-eval unittest 416 OK, main repo unittest 252 OK, changed-file Ruff check
  and format check, refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains `overall_passed=false`,
  8 passed gates, and the same four failed broad real-evidence gates;
  `inputs/*_real` has no files and the four canonical broad packets remain
  absent. GPT/Codex reviewers `Godel`, `Gibbs`, and `Ohm` returned
  `RELEASE_DECISION: AGREE` after blockers for dot-segment normalization and
  broad `*_preview.json` tracking were fixed. Antigravity bounded write
  delegation was attempted with `.formowl/kg-eval` as the write scope but was
  rejected before execution by tenant policy as private repository disclosure
  to an untrusted external Antigravity service; no packet was sent and no
  workaround or alternate external channel was attempted.
- 2026-06-28 candidate-manifest validation guidance checkpoint: collection
  work orders and the tracked operator guide now direct post-intake validation
  at the candidate manifests emitted by response intake under
  `work_packets/*_candidate_manifest.json`, not the non-evidence scaffold
  manifests under `work_orders/`. Scaffold generation remains documented only
  as optional shape inspection. `_common_commands` now fails closed if a gate
  has no response-intake candidate manifest mapping, instead of falling back to
  scaffold-backed validation. This slice writes no candidate artifacts,
  promotes no evidence, writes no canonical packets, and does not count as an
  acceptance gate. Dev-container verification passed: operator guide
  `--check`, focused work-order/guide unittest 26 OK, full KG-eval unittest
  417 OK, main repo unittest 252 OK, changed-file Ruff check and format check,
  refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains `overall_passed=false`,
  8 passed gates, and the same four failed broad real-evidence gates;
  `inputs/*_real` has no files and the four canonical broad packets remain
  absent. GPT/Codex reviewers `Bohr`, `Euler`, and `Lorentz` returned
  `RELEASE_DECISION: AGREE` after Lorentz's blocker about scaffold fallback
  was fixed. Antigravity review/write delegation remains blocked by tenant
  policy for bounded FormOwl KG repository disclosure; no packet was sent and
  no workaround or alternate external channel was attempted.
- 2026-06-28 current-state execution checkpoint: after the user asked to run
  the original agent's latest goal state, `git fetch origin` showed
  `complete-slice-1` and `origin/complete-slice-1` both at `f3ba5f8`
  (`Route KG candidate validation to intake manifests`) with a clean
  worktree. Dev-container verification was rerun against that current state:
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest 417 OK, main repo unittest 252 OK, default main KG
  acceptance `passed_with_explicit_limits`, and strict main KG acceptance
  exited nonzero only for the known `production_adapter_readiness` failed item
  and `latency_scalability_enterprise_claims` blocked item. Broad KG-eval still
  reports `overall_passed=false`, 8 passed gates, and the same 4 failed gates:
  `fair_external_baseline_comparison`, `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. The
  objective audit remains `objective_complete=false` with 5 proved
  requirements and 4 incomplete requirements. Preflight reports all four
  `inputs/*_real` roots have zero files, no candidate artifacts, and the four
  canonical broad packets remain absent. No goal completion claim is supported.
- 2026-06-28 candidate intake execution-plan checkpoint:
  `real_evidence_submission_manifest.py --emit-intake-plan` now turns a
  validated operator-filled submission manifest into an ignored, non-evidence
  `work_packets/*.json` intake plan. The plan records exact candidate-only
  response-intake argv/commands for the four remaining gates, but the planning
  command itself executes no intake, reads no response packet contents, writes
  no candidate artifacts, writes no canonical packets, promotes no evidence,
  and counts as no acceptance gate. Output guards reject templates, tracked
  preview packets, candidate manifests, tracked work packets, symlinks,
  non-JSON names, unsafe paths, and existing outputs. Tests now snapshot real
  roots, canonical broad packets, and `work_packets/*_candidate_manifest.json`
  and cover invalid-manifest plan emission without writing a plan. The operator
  guide documents the optional plan step. Dev-container verification passed:
  focused submission/guide unittest 24 OK, full KG-eval unittest 421 OK, main
  repo unittest 252 OK, changed-file Ruff check and format check, operator
  guide `--check`, submission template `--check-template`, refreshed broad
  reports, default main KG acceptance `passed_with_explicit_limits`, and strict
  main KG acceptance still exits nonzero only for known limits. Broad KG-eval
  remains `overall_passed=false`, 8 passed gates, and the same 4 failed broad
  real-evidence gates. GPT/Codex reviewers `Boole`, `Maxwell`, and `Avicenna`
  returned `RELEASE_DECISION: AGREE` after Boole's candidate-manifest
  no-write blocker was fixed and Maxwell's invalid-manifest no-plan-file
  hardening note was implemented. Antigravity Gemini review is blocked at 0/3:
  local `agy` availability succeeded, but the bounded closed-book summary
  reviewer packet was rejected before execution by tenant policy as private
  repository-derived disclosure to an untrusted external reviewer service. No
  packet was sent and no workaround or alternate external channel was
  attempted.
- 2026-06-28 agy MCP route and gate-policy checkpoint: at the user's request,
  Codex tested whether `agy` can be reached through MCP. Current Codex tool
  discovery exposes no Antigravity/`agy` MCP tool; Codex config has no
  Antigravity MCP server; Antigravity global `mcp_config.json` is empty; this
  repository has no `.agents/mcp_config.json`; `agy --help` exposes no MCP
  server subcommand; `agy plugin list` shows no imported plugins; and a
  no-repository-content `agy --new-project --print "/mcp"` probe from `/tmp`
  returned general MCP configuration guidance rather than an active server/tool
  list. Therefore the MCP route is currently unavailable from Codex. The
  default FormOwl KG reviewer gate is now 3 Codex/GPT reviewers only, and
  `agy` reviewer/write delegation is disabled unless the user explicitly
  re-enables it after policy, platform, or MCP configuration changes. This
  policy checkpoint does not change broad KG-eval acceptance:
  `overall_passed=false` with the same four failed real-evidence gates.
- 2026-06-28 current-state execution checkpoint after user requested execution:
  `git fetch origin` found no newer commit beyond `63df752`
  (`Document agy MCP route disablement`) on `complete-slice-1`, and the branch
  matched `origin/complete-slice-1`. Dev-container verification reran:
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest, operator guide `--check`, submission template
  `--check-template`, main repo unittest, default main KG acceptance, and
  strict main KG acceptance. Results: KG-eval reports exited 0; KG-eval
  unittest ran 421 tests OK; guide/template checks exited 0; main repo
  unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits (`production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked). Broad KG-eval remains
  incomplete: `overall_passed=false`, 8 passed gates, and 4 failed gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`). Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements. No goal completion claim is supported.
- 2026-06-28 follow-up execution checkpoint after user requested execution of
  the original agent's latest state: `git fetch origin` found no newer commit
  beyond `bf0fc2b` (`Record KG current verification run`) on
  `complete-slice-1`, and the branch matched `origin/complete-slice-1`.
  Dev-container verification reran without code changes:
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest, operator guide `--check`, submission template
  `--check-template`, main repo unittest, default main KG acceptance, and
  strict main KG acceptance. Results: KG-eval reports exited 0; KG-eval
  unittest ran 421 tests OK; guide/template checks exited 0; main repo
  unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits (`production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked). Full dev-container
  `ruff check python tests scripts .formowl/kg-eval` passed, while full
  `ruff format --check python tests scripts .formowl/kg-eval` still reports
  pre-existing formatting drift in 33 files and was not treated as evidence
  that the broad KG goal is complete. Refreshed broad KG-eval remains
  incomplete: `overall_passed=false`, 8 passed gates, and 4 failed gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`). Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements. Preflight reports all four real roots have no files, the four
  canonical broad packets are absent, and no packet/artifact hazards are
  present. No goal completion claim is supported.
- 2026-06-28 formatting cleanup checkpoint: the pre-existing full Ruff format
  drift from 33 Python/test/script files was mechanically formatted in the dev
  container. Verification passed after the cleanup: full Ruff lint and
  format-check, full KG-eval unittest 421 OK, main repo unittest 252 OK,
  operator guide `--check`, submission template `--check-template`, refreshed
  broad KG-eval reports, and default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for the known `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item. This cleanup created
  no evidence packets, wrote no real artifacts, and changed no acceptance gate:
  broad KG-eval remains `overall_passed=false` with the same four failed
  real-evidence gates.
- 2026-06-28 operator submission-manifest input hardening checkpoint:
  `real_evidence_submission_manifest.py --manifest` now rejects generated
  `*_candidate_manifest.json` and `*_intake_plan.json` files so downstream
  non-evidence outputs cannot be fed back as operator-filled submission
  manifests. The tracked operator guide documents that boundary, and focused
  tests cover both rejected names plus the guide warning. This slice reads no
  response packet contents, writes no candidate artifacts, promotes no
  evidence, writes no canonical packets, and counts as no acceptance gate.
  Verification passed: host focused submission/guide unittest 24 OK,
  dev-container focused submission/guide unittest 24 OK, guide `--check`,
  submission template `--check-template`, full KG-eval unittest 421 OK, main
  repo unittest 252 OK, full Ruff check and format-check, refreshed broad
  reports, and default main KG acceptance `passed_with_explicit_limits`.
  Strict main KG acceptance still exits nonzero only for known limits. Broad
  KG-eval remains incomplete with `overall_passed=false`, 8 passed gates, and
  the same four failed real-evidence gates; objective audit remains
  `objective_complete=false` with 5 proved and 4 incomplete requirements; all
  four real roots have no files and the four canonical broad packets remain
  absent. GPT/Codex reviewers `Dirac`, `Zeno`, and `Hypatia` returned
  `RELEASE_DECISION: AGREE`; Hypatia's non-blocking guide-warning assertion
  suggestion was implemented and re-reviewed with final `AGREE`.
- 2026-06-28 post-`27ff851` verification checkpoint: local Git state was clean
  at `27ff851` (`Harden KG submission manifest input guard`) on
  `complete-slice-1`, and `git status -sb` showed the branch matched
  `origin/complete-slice-1`. Dev-container verification reran
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest, operator guide `--check`, submission template
  `--check-template`, main repo unittest, full Ruff check and format-check,
  default main KG acceptance, and strict main KG acceptance. Results: KG-eval
  reports exited 0; KG-eval unittest ran 421 tests OK; guide/template checks
  exited 0; main repo unittest ran 252 tests OK; full Ruff check passed and
  format-check reported `200 files already formatted`; default main KG
  acceptance remains `passed_with_explicit_limits`; strict main KG acceptance
  still exits nonzero only for known limits. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and 4 failed gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`).
  Objective audit remains `objective_complete=false`, with 5 proved and 4
  incomplete requirements. Preflight reports all four real roots have no files,
  the four canonical broad packets are absent, and no packet/artifact hazards
  are present. Work-board unchecked engineering item count remains 9: 1
  KG-owned full real-evidence objective and 8 System Backbone/product-infra
  items. No goal completion claim is supported.
- 2026-06-28 submission-manifest hardlink-alias guard checkpoint:
  `real_evidence_submission_manifest.py --manifest` now rejects hardlink
  aliases for the operator-filled manifest input and required
  `response_packet` files before candidate intake. The check inspects only
  regular-file existence and link count; it still does not read response packet
  contents, write candidate artifacts, promote evidence, write canonical
  packets, or count as an acceptance gate. The tracked operator guide documents
  the hardlink boundary, and focused tests cover hardlink-alias manifest input,
  hardlink-alias response packets, and the guide warning. Verification passed:
  host focused submission/guide unittest 26 OK; dev-container focused
  submission/guide unittest 26 OK; guide `--check`; submission template
  `--check-template`; full KG-eval unittest 423 OK; main repo unittest 252 OK;
  full Ruff check and format-check; refreshed broad reports; and default main
  KG acceptance `passed_with_explicit_limits`. Strict main KG acceptance still
  exits nonzero only for known limits. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; objective audit remains `objective_complete=false` with
  5 proved and 4 incomplete requirements; all four real roots have no files
  and the four canonical broad packets remain absent. GPT/Codex reviewers
  `Confucius`, `Mendel`, and `Leibniz` returned `RELEASE_DECISION: AGREE`.
- 2026-06-28 canonical broad-packet path guard checkpoint: the four broad
  real-evidence validators now reject canonical input packet filesystem
  aliases before parsing. `fair_external_baseline_run_validator.py`,
  `human_annotation_adjudication_validator.py`,
  `enterprise_multimodal_validation_validator.py`, and
  `production_adapter_path_validator.py` reject direct symlinks, hardlink
  aliases (`st_nlink > 1`), and non-regular packet paths. The blocker is
  propagated through `validate_packet()` so reports stay failed with
  claim-boundary flags false. Added
  `.formowl/kg-eval/test_canonical_evidence_packet_path_guards.py` covering
  symlink, hardlink, and directory packet paths for all four validators; the
  helper preserves a pre-existing directory packet path instead of deleting it
  during cleanup. This slice reads no response-packet contents, writes no
  candidate artifacts, promotes no evidence, writes no canonical packets, and
  does not count as an acceptance gate. Verification passed: host focused
  validator unittest 107 OK; dev-container focused validator unittest 107 OK;
  full KG-eval unittest 426 OK; main repo unittest 252 OK; full Ruff check and
  format-check; operator guide `--check`; submission template
  `--check-template`; refreshed broad reports; and default main KG acceptance
  `passed_with_explicit_limits`. Strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; all four real roots remain empty and all four
  canonical broad packets remain absent. GPT/Codex reviewer gate passed 3/3:
  `Nietzsche`, `Bacon`, and `Copernicus`; `Nietzsche` initially blocked on
  destructive directory cleanup in the test helper, then agreed after the
  helper and directory coverage were fixed. A mistakenly spawned no-op
  `Averroes` reviewer is not counted.
- 2026-06-28 preflight canonical packet path-hazard checkpoint:
  `real_evidence_preflight.py` now detects symlink, hardlink, and non-regular
  canonical packet paths before refreshing broad acceptance or objective-audit
  reports. When such a hazard exists, preflight reports
  `canonical_packet_path_hazards`, skips total/audit/gate validator refreshes,
  leaves the affected gates blocked, and avoids reading or hashing the alias.
  Focused tests cover symlink, hardlink, and non-regular packet hazards,
  no-validator-run behavior under hazards, packet-surface state, and cleanup
  that preserves pre-existing packet paths. Verification passed in the dev
  container: focused
  preflight unittest 17 OK; full KG-eval unittest 428 OK; main repo unittest
  252 OK; full Ruff check and format-check; refreshed
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`;
  operator guide `--check`; submission template `--check-template`; and
  default main KG acceptance `passed_with_explicit_limits`. Strict main KG
  acceptance still exits nonzero only for the known
  `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item. Broad KG-eval remains
  incomplete with `overall_passed=false`, 8 passed gates, and the same four
  failed real-evidence gates; all four real roots are empty and all four
  canonical broad packets are absent. GPT/Codex reviewer gate passed 3/3:
  `Beauvoir`, `Dewey`, and `Rawls`. `Beauvoir` initially blocked on
  total/audit refresh running before preflight path-hazard handling; `Dewey`
  initially blocked on unsafe direct canonical test writes and incomplete
  no-validator-run coverage. Both blockers were fixed and re-reviewed with
  final `RELEASE_DECISION: AGREE`. A mistakenly spawned no-op `Laplace` agent
  is not counted.
