# Knowledge Graph Research Agent Goal

## Role

Knowledge Graph Research Agent.

Durable role definition: `docs/agent-roles.md`.

## Current Objective

Complete the FormOwl Knowledge Graph method exploration and acceptance work:
fill in external recent literature comparison, ontology integration method,
multi-user KG and KG fusion experiments, multimodal enterprise-data validation,
annotation/adjudication workflow through either legacy human evidence or a
four-professional-specialist LLM subagent panel, production adapter gate, and a
total acceptance suite that clearly marks passed and failed items.

Historical source: Codex session `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.

Status: `blocked` for the broad KG real-evidence acceptance objective. Current
repo-side tooling is synchronized, but four broad real-evidence gates still
require operator-supplied or public reproducible evidence before completion can
be claimed. Product-level production readiness, top-tier scientific validation,
raw access, canonical graph writes, autonomous business judgment, and
enterprise-scale latency/scalability remain outside any future completion
claim.

## Current Acceptance State

Do not treat the broad KG real-evidence acceptance objective as complete in the
current authority state. The stricter current state is blocked, and no broad
completion claim is supported until the four remaining gates have accepted
canonical packets and all authority reports are synchronized and passing.

Two different acceptance layers currently exist:

- Main-repo KG research acceptance slice:
  `scripts/kg_research_acceptance_suite.py` currently reports
  `passed_with_explicit_limits`. This means the method note, deterministic
  fixtures, scoped ontology contracts, candidate-only package boundary, metrics,
  ablations, and explicit limitations are present.
- Broad real-evidence KG acceptance:
  `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json` is the stricter
  recovery/real-evidence state for the user's full broad KG objective. It now
  has `overall_passed=false`, 8 passed gates, 4 failed gates, and remaining
  gates `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`.

Current broad real-evidence blockers:

- `fair_external_baseline_comparison`: real Microsoft GraphRAG, LightRAG, and
  HippoRAG package runs, answer-quality adjudication, graph-quality
  validation, and permission probes are absent.
- `annotation_adjudication_protocol`: the annotation packet is absent, and
  neither the legacy human route nor the four-specialist LLM subagent panel
  route has complete accepted evidence.
- `multimodal_semantic_validation`: real enterprise multimodal pilot,
  modality validation packets, adjudication, business-decision review, and
  cross-modal permission probes are absent.
- `production_adapter_paths`: non-synthetic deployment evidence, reviewed
  false-merge labels, permission probes, rollback smoke, and production audit
  artifacts are absent.

Current authority hashes, refreshed 2026-06-30 after #13 correction:

- gate status:
  `596eef5f887952b4e4666f7e6b970a9199d8d3148a630cd4491ac53f0faeca1a`
- objective audit:
  `86d550fd05bfb1ab1b453e805bcfe56827a476da43186bb32e962a0b41275039`

Current status tools:

- `kg_objective_completion_audit.py`: `objective_complete=false`, 5 proved
  requirements, 4 incomplete requirements.
- `real_evidence_preflight.py`:
  `preflight_state=blocked`, blocked gates
  `fair_external_baseline_comparison`, `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
- `real_evidence_collection_work_orders.py`:
  `work_order_state=collection_blocked_until_real_evidence_exists`,
  `work_order_count=4`.
- `real_evidence_gate_progress.py`: `gate_count=4`, all four gates at
  `missing_operator_response`.

The packaged `formowl_kg_eval summary` now exposes `authority_state` and fails
closed: it supports the broad completion claim only when total acceptance,
objective audit, preflight, work orders, progress, and tracked checklist are
all passing and synchronized.

The current Plan B route is four professional specialist LLM subagents, not a
generic or single LLM judge. Accepted artifacts must use
`four_specialist_llm_subagent_adjudication_v1` and include exactly four
distinct specialist subagents with the fixed professional roles for baseline
methodology, annotation adjudication, multimodal semantics, and production
governance. All four must independently return `PASS`, bind reviewed artifact
hashes, and have no blocking findings. This route remains LLM-subagent
adjudication and must not be represented as completed human adjudication.

`passed_with_explicit_limits` in the main repo KG method suite is a separate
product-level limit boundary. It records that production adapter readiness and
enterprise latency/scalability are not claimed by this broad KG real-evidence
completion.

## Returned For Rework

2026-06-27 review returned these claims/slices:

- The `Complete KG research acceptance gate` completion claim is rejected for
  the full KG objective. At that checkpoint, the stricter broad acceptance
  state was still `overall_passed=false` with four failed real-evidence gates;
  the current state is summarized above.
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
- Annotation/adjudication evidence where governance claims depend on reviewer
  behavior. Accepted routes are legacy human evidence or a
  four-professional-specialist LLM subagent panel. The current Plan B target is
  the LLM panel route; legacy human evidence remains validator-compatible only
  for backwards compatibility. The LLM route is not a generic or single-LLM
  judge: it must include exactly four distinct specialist subagents, cover
  `baseline_methodology`, `annotation_adjudication`, `multimodal_semantics`,
  and `production_governance`, use the fixed professional roles
  `external_baseline_methodologist`,
  `annotation_adjudication_protocol_specialist`,
  `multimodal_semantics_validation_specialist`, and
  `production_governance_adapter_specialist`, bind reviewed artifact hashes,
  have all four subagents independently return `PASS`, and must not claim human
  adjudication. Review-queue export alone is not completed adjudication
  evidence.
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
- 2026-06-28 candidate-intake execution runner checkpoint:
  `real_evidence_submission_manifest.py` now has an explicit
  `--execute-candidate-intakes` mode for operator-filled submission manifests.
  It validates the manifest first, requires existing response packets, rejects
  path-only execution mode, builds fixed argv for the four existing
  candidate-only intake helpers, runs them with `subprocess.run` and no shell,
  stops on the first failed intake, reports partial-execution policy, and
  never passes promotion flags. This execution mode may read operator response
  packet contents and write candidate artifacts through the existing intake
  helpers; it does not promote evidence, write canonical input packets, or
  count as an acceptance gate. The operator guide documents the runner and
  states that candidate artifacts from successful earlier intakes remain for
  operator review rather than being automatically promoted or rolled back.
  Verification passed: host focused submission/guide unittest 33 OK;
  dev-container focused submission/guide unittest 33 OK; dev-container full
  KG-eval unittest 435 OK; dev-container main repo unittest 252 OK; operator
  guide `--check`; submission template `--check-template`; changed-file Ruff
  check and format-check; refreshed `kg_total_acceptance_suite.py` and
  `real_evidence_preflight.py`; default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; all four real roots are empty and canonical broad
  packets are absent. GPT/Codex reviewer gate passed 3/3 with `Nash`, `Pauli`,
  and `Locke`. `Hegel` found a claim-honesty blocker in the module
  docstring/help text; it was fixed with focused assertions and re-reviewed by
  replacement reviewer `Locke` because the original Hegel agent could not
  accept follow-up input. Non-counted agents: `Pascal` no-op accidental spawn,
  `Sagan`/`Bernoulli`/`Arendt` accidentally shut down before decisions, and
  `Hegel` as blocker-only without final re-review.
- 2026-06-28 candidate-manifest validate-only runner checkpoint:
  `real_evidence_submission_manifest.py` now has an explicit
  `--validate-candidate-manifests` mode for post-intake validation. It
  validates the operator-filled submission manifest first, requires the four
  expected emitted `work_packets/*_candidate_manifest.json` files to exist as
  safe regular non-symlink/non-hardlink files, builds fixed argv for the
  existing assembler scripts with `--validate` only, runs them through
  `subprocess.run` without a shell, treats nonzero exit or
  `validation_report.passed != true` as failed, and reports summarized stdout
  without echoing assembled candidate packet contents. This validation mode
  reads candidate manifests and referenced candidate artifacts through the
  assemblers, but runs no response-intake commands, writes no candidate
  artifacts, promotes no evidence, passes no `--promote`, writes no canonical
  broad packets, and does not count as an acceptance gate. The tracked
  operator guide documents the command and claim boundary. Verification
  passed: host focused submission/guide unittest 41 OK; dev-container focused
  submission/guide unittest 41 OK; dev-container full KG-eval unittest 443 OK;
  dev-container main repo unittest 252 OK; operator guide `--check`;
  submission template `--check-template`; full Ruff check and format-check;
  refreshed broad reports; default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance exits 1 only for
  known limits `production_adapter_readiness` and
  `latency_scalability_enterprise_claims`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; objective audit remains `objective_complete=false`
  with 5 proved and 4 incomplete requirements; all four real roots are empty
  and all four canonical broad packets are absent. GPT/Codex reviewer gate
  passed 3/3 with `Einstein`, `Sartre`, and `Heisenberg`; all three suggested
  direct hardlink coverage for emitted candidate manifests, the test was added,
  and `Einstein` re-reviewed the final delta with `RELEASE_DECISION: AGREE`.
- 2026-06-28 candidate-validation report output checkpoint:
  `real_evidence_submission_manifest.py --validate-candidate-manifests` can now
  optionally persist its validate-only result with
  `--emit-candidate-validation-report` to an ignored
  `work_packets/*_candidate_validation_report.json` file for manual governance
  review. The output path must be a safe direct child of `work_packets/`, must
  use `_candidate_validation_report.json` naming, must not overwrite tracked
  work packets, templates, preview packets, candidate manifests, intake plans,
  or an existing file, and is written only after candidate manifest preflight
  passes. The report writer first writes a same-directory temporary file, then
  creates the final report with an atomic no-overwrite link and removes the
  temporary file, so an interrupted write leaves no final partial JSON report.
  Invalid operator manifests and missing emitted candidate manifests do not
  write a report; failed assembler validation after preflight may write a
  failure report as a non-evidence review aid. This slice writes no candidate
  artifacts, promotes no evidence, writes no canonical broad packets, and does
  not count as acceptance. Verification passed: host focused submission/guide
  unittest 48 OK; dev-container focused submission/guide unittest 48 OK;
  operator guide `--check`; submission template `--check-template`; full
  KG-eval unittest 450 OK; main repo unittest 252 OK; full Ruff check and
  format-check; refreshed broad reports; default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance exits 1 only for
  known limits `production_adapter_readiness` and
  `latency_scalability_enterprise_claims`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; objective audit remains `objective_complete=false` with
  5 proved and 4 incomplete requirements; all four real roots are empty and
  all four canonical broad packets are absent. Reviewer gate state:
  `Turing` returned `RELEASE_DECISION: AGREE`; `Cicero` returned
  `RELEASE_DECISION: AGREE` after blockers for nested report paths and partial
  final report writes were fixed; `Boyle` returned `RELEASE_DECISION: AGREE`
  after blockers for missing durable docs and stale checkpoint text were fixed.
  Reviewer gate passed 3/3. A mistaken no-op `McClintock` spawn is not counted.
- 2026-06-28 intake-plan output path-hardening checkpoint:
  `real_evidence_submission_manifest.py --emit-intake-plan` now rejects nested
  `work_packets/...` output paths; intake plans must be safe direct children of
  `work_packets/`, matching the ignored operator work-packet surface used by
  candidate-validation reports. Focused regression coverage was added to
  `test_real_evidence_submission_manifest.py`. This slice writes no candidate
  artifacts, promotes no evidence, writes no canonical broad packets, and does
  not count as acceptance. Verification passed: host focused
  `test_real_evidence_submission_manifest.py` 40 OK; dev-container focused
  submission-manifest test 40 OK; dev-container full KG-eval unittest 450 OK;
  dev-container main repo unittest 252 OK; refreshed broad reports; operator
  guide `--check`; submission template `--check-template`; default main KG
  acceptance `passed_with_explicit_limits`; strict main KG acceptance exits 1
  only for known limits `production_adapter_readiness` and
  `latency_scalability_enterprise_claims`; full Ruff check and format-check
  passed. Broad KG-eval remains incomplete with `overall_passed=false`, 8
  passed gates, and the same four failed real-evidence gates; objective audit
  remains `objective_complete=false` with 5 proved and 4 incomplete
  requirements; all four real roots are empty and all four canonical broad
  packets are absent. Reviewer gate passed 3/3: `Anscombe` agreed on
  engineering path safety, `Epicurus` agreed on governance and non-evidence
  boundaries, and `Ptolemy` agreed on durable docs/status honesty.
- 2026-06-28 work-order disappeared-file contract hardening checkpoint:
  following the real-root churn preflight hardening, collection work orders now
  require every per-gate preflight row to expose `disappeared_file_count` as a
  non-bool integer and to keep it at `0` before normal work orders are emitted.
  The work-order `preflight_snapshot` now includes
  `real_root_disappeared_file_count`, and disappeared real-root files fail
  closed as preflight contract drift instead of appearing as clean missing
  evidence. Reviewer blocker fix: real-root scanning now uses `lstat()` before
  file-type classification, so a path that disappears before the old
  `is_file()` check is reported through `disappeared_file_count` instead of
  being silently treated as clean absence. The tracked operator guide remains
  synchronized after the work-order report schema/hash changed. This accepts no
  evidence, writes no candidate artifacts, promotes no evidence, writes no
  canonical broad packets, and does not count as acceptance. Canonical
  dev-container verification passed: focused current-slice KG-eval unittest
  79 OK, full KG-eval unittest 454 OK, main repo unittest 252 OK,
  guide/template checks, refreshed broad reports, default main KG acceptance
  `passed_with_explicit_limits`, strict main KG acceptance exits 1 only for
  known limits, full Ruff check and format-check, and `git diff --check`.
  Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Reviewer gate passed 3/3 after
  blocker fixes: `Curie`, `Erdos`, and `Hume` returned
  `RELEASE_DECISION: AGREE`. This slice was committed and pushed on
  `complete-slice-1` as `8fc5a55`
  (`Harden KG real-evidence preflight work orders`). Follow-up status-doc
  checkpoints may sit on top of that reviewed hardening slice.
- 2026-06-28 restart-note cleanup checkpoint: the older
  `.formowl/kg-eval/SESSION_RESTART.md` "Next Best Work" section incorrectly
  still pointed at validator real-root path-helper hardening. That validator
  hardening is already complete and covered for `results/`, `inputs/test_*`,
  templates, and template-named artifacts under real roots. The restart note
  now marks it historical and names the actual next action as canonical
  dev-container verification plus real operator/user-supplied evidence for the
  four failed broad gates. Host consistency checks passed: `git diff --check`,
  operator guide `--check`, submission template `--check-template`, and
  focused work-order unittest 19 OK.
- 2026-06-28 historical blocked audit checkpoint, superseded later the same
  day by user authorization and canonical verification: after repeated
  continuation turns, canonical dev-container Docker verification had been
  rejected by the approval reviewer and Git commit/push could not proceed.
  This is no longer the current Docker/Git state for this run; it remains only
  as audit history. The four broad gates still require real
  operator/user-supplied evidence packets.
- 2026-06-28 resume authorization checkpoint: the user explicitly authorized
  collecting failed-gate evidence, Docker/dev-container access, and Git
  commit/push. The prior Docker/Git approval blocker is cleared for this run,
  and canonical dev-container verification plus the 3 Codex/GPT reviewer gate
  for the current hardening slice have passed. The slice was pushed as
  `8fc5a55` on `complete-slice-1`. The broad KG objective is still incomplete:
  collecting failure evidence from reports is allowed, but passing the four
  broad gates still requires real operator/user-supplied artifacts and governed
  canonical packets accepted by the validators.
- 2026-06-28 candidate-runner canonical packet integrity checkpoint:
  `real_evidence_submission_manifest.py --execute-candidate-intakes` and
  `--validate-candidate-manifests` now snapshot the four canonical broad input
  packet paths before running candidate-only subprocesses and fail closed if a
  subprocess exits with a canonical packet path created or changed. The output
  includes `canonical_packet_integrity`, marks the affected row failed, keeps
  `overall_success=false`, and stops immediately on final-state canonical
  packet drift. This is not a live audit of transient write-and-restore
  behavior, and the operator guide now scopes that limitation explicitly. This
  slice accepts no evidence, promotes no evidence, writes no canonical broad
  packets, and does not make any broad gate pass. Canonical dev-container
  verification passed: focused submission/guide unittest 51 OK, full KG-eval
  unittest 456 OK, main repo unittest 252 OK, operator guide `--check`,
  submission template `--check-template`, refreshed
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, and `real_evidence_collection_work_orders.py`,
  default main KG acceptance `passed_with_explicit_limits`, strict main KG
  acceptance exits 1 only for known limits, and full Ruff check/format-check.
  Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates. Reviewer gate passed 3/3:
  `Sagan`, `Hooke`, and `Laplace` returned `RELEASE_DECISION: AGREE`; a
  mistaken no-op `Banach` subagent is not counted.
- 2026-06-28 candidate-runner pre-existing canonical packet hazard checkpoint:
  `real_evidence_submission_manifest.py --execute-candidate-intakes` and
  `--validate-candidate-manifests` now inspect the canonical broad packet
  baseline before launching any intake or validate-only subprocess. If any
  canonical packet path is already a symlink, hardlink alias, non-regular file,
  or unreadable / metadata-unavailable surface, the runner fails closed with
  `executed_gate_count=0`, reports `canonical_packet_baseline`, reads no
  response packet or candidate manifest contents, writes no candidate
  artifacts, promotes no evidence, and writes no canonical broad packets. The
  tracked operator guide documents the boundary. Canonical dev-container
  verification passed: focused submission/guide unittest 55 OK, full KG-eval
  unittest 460 OK, main repo unittest 252 OK, operator guide `--check`,
  submission template `--check-template`, refreshed
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, and `real_evidence_collection_work_orders.py`,
  default main KG acceptance `passed_with_explicit_limits`, strict main KG
  acceptance exits 1 only for known limits, full Ruff check/format-check, and
  `git diff --check`. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed gates.
  Reviewer gate passed 3/3: `Wegener` agreed on engineering correctness after
  the canonical packet test helper was changed to preserve pre-existing path
  surfaces by rename; `Feynman` agreed on governance/safety; and `Kuhn` agreed
  on status honesty. No goal completion claim is supported.
- 2026-06-28 governed approval-bridge checkpoint:
  added `.formowl/kg-eval/real_evidence_governance_approval.py`, focused
  tests, and the tracked non-evidence approval template
  `.formowl/kg-eval/work_packets/remaining_real_evidence_governance_approval.template.json`.
  The bridge validates an operator-filled approval manifest under
  `work_packets/` before any canonical packet update: exact manifest type and
  fields, human approver id, exact approval scope and claim boundary, current
  candidate validation report hash, current candidate manifest hash, a passing
  target-gate validation row with exact validate-only assembler argv, safe
  report/manifest names, missing target canonical packet, and hazard-free
  canonical packet baseline. Execute mode uses fixed assembler `--promote`
  argv plus `--assembly-manifest-sha256` so the manifest bytes consumed by the
  assembler must match the approved candidate-manifest hash; it also rehashes
  the candidate manifest after the subprocess, checks that only the target
  canonical packet changed, and rolls back a newly created target packet on
  candidate-manifest drift. The four broad packet assemblers now use
  temporary-file plus atomic no-overwrite hard-link promotion and reject
  mismatched approved manifest bytes before assembly or promotion. Candidate
  validation reports now include `candidate_manifest_sha256`, and canonical
  packet surface checks reject hazardous parent components. The tracked
  operator guide documents the approval validation and
  `--execute-approved-promotion` flow. Canonical dev-container verification
  passed: focused approval/assembler/operator-guide unittest 78 OK;
  approval-template,
  operator-guide, and submission-template checks; full KG-eval unittest
  474 OK; main repo unittest 252 OK; full Ruff check and format-check;
  refreshed broad reports; default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance exits 1 only for
  known limits. All four real roots remain empty and the four canonical broad
  packets remain absent. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed gates;
  objective audit remains `objective_complete=false` with 5 proved and
  4 incomplete requirements. Reviewer gate passed 3/3 after Bernoulli's
  candidate-manifest TOCTOU blocker was fixed and re-reviewed:
  `Bernoulli`, `Popper`, and `Dalton` returned `RELEASE_DECISION: AGREE`.
  No goal completion claim is supported.
- 2026-06-28 human annotation response-intake hardening checkpoint:
  `human_annotation_response_intake.py` now requires response-packet top-level
  allowlisting, `operator_run_id` binding to the candidate output directory,
  unsupported nested field rejection, raw/internal field-name rejection, parent
  directory preflight, nested default real-root output-dir rejection, partial
  write cleanup, and rollback of already-created candidate artifacts plus
  optional candidate manifests when assembly or validation execution raises
  after writes. A completed validate-only report with `passed=false` remains
  candidate-only evidence state, not canonical evidence.
  It also emits a non-authoritative response custody receipt binding the
  operator response packet hash, candidate packet hash, candidate artifact
  hashes, and optional candidate-manifest hash. The tracked operator guide now
  lists these controls for `annotation_adjudication_protocol`. Canonical
  dev-container verification passed: focused human-intake/work-order/operator
  guide unittest 48 OK, full KG-eval unittest 482 OK, main repo unittest
  252 OK, operator guide `--check`, submission template `--check-template`,
  refreshed broad reports, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance exits 1 only for known limits, full Ruff check and
  format-check, and `git diff --check`. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed gates; all
  four real roots remain empty and canonical broad packets remain absent.
  Reviewer gate passed 3/3: `Socrates` agreed on engineering correctness,
  `Gibbs` agreed on governance/safety after the validation-report wording was
  narrowed, and `Pascal` agreed on status honesty after the same wording
  update. No goal completion claim is supported.
- 2026-06-28 fair-baseline response-intake hardening checkpoint:
  `fair_baseline_response_intake.py` now requires response-packet top-level
  allowlisting, `operator_run_id` binding to the candidate output directory,
  baseline-run and adjudication/graph-quality/permission-probe wrapper-field
  allowlisting, raw/internal field-name rejection throughout the response
  payload, parent directory preflight, default real-root output-dir
  restriction to `inputs/fair_baseline_real/<operator_run_id>`, after-open
  partial write cleanup, and rollback of already-created candidate artifacts
  plus optional candidate manifests when assembly or validation execution
  raises after writes. It emits only non-authoritative candidate artifacts and
  a response custody receipt binding response packet, candidate packet,
  candidate artifact, and optional candidate-manifest hashes. The tracked
  operator guide lists the controls for `fair_external_baseline_comparison`.
  Canonical dev-container verification passed: focused
  fair-intake/work-order/operator-guide unittest 46 OK, full KG-eval unittest
  490 OK, main repo unittest 252 OK,
  guide/submission-template/approval-template checks,
  refreshed broad reports, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance exits 1 only for known limits, full Ruff
  check/format-check, and `git diff --check`. Broad KG-eval remains incomplete
  with `overall_passed=false`, 8 passed gates, and the same four failed gates;
  all four real roots are empty and canonical broad packets are absent.
  Reviewer gate passed 3/3 after blocker fixes: `Arendt` agreed on engineering
  correctness after the final delta, `Confucius` agreed on governance/safety
  after the work-order report stopped emitting an absolute local workspace
  path, and `Lorentz` agreed on status honesty after the operator
  guide/control inventory listed parent-dir preflight, after-open cleanup, and
  rollback controls. No goal completion claim is supported.
- 2026-06-28 production-adapter response-intake parity hardening checkpoint:
  `production_adapter_response_intake.py` now matches the current hardened
  response-intake baseline for raw/internal field names and after-open partial
  writes. Operator-supplied production adapter artifact payloads recursively
  reject raw/internal field names such as raw paths, backend connection
  strings, database/object-store locators, raw SQL, bucket/object keys, and
  worker scratch fields even when the submitted value is otherwise benign.
  `_write_json()` now removes the just-created output if JSON serialization or
  writing fails after exclusive open, and raw `OSError` write or custody-hash
  failures are caught by the intake rollback path so earlier candidate
  artifacts are not left behind. Focused tests cover raw/internal field-name
  rejection, backend connection-string field-name rejection,
  assembler-failure rollback, raw `OSError` rollback, custody-phase hash
  failure rollback, and after-open OSError/TypeError cleanup.
  `real_evidence_collection_work_orders.py`
  and the tracked operator guide now list the production adapter intake
  controls for output-dir binding, top-level/adapter wrapper allowlisting,
  raw/internal field-name rejection, parent-dir preflight, after-open cleanup,
  rollback, and optional manifest custody hashing. Canonical dev-container
  verification passed: focused production-intake/work-order/operator-guide
  unittest 47 OK; full KG-eval unittest 497 OK; main repo unittest 252 OK;
  operator guide, submission-template, and approval-template checks; refreshed
  broad reports; default KG acceptance `passed_with_explicit_limits`; strict
  KG acceptance exits 1 only for known limits; full Ruff check and
  format-check; and `git diff --check`. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed gates; all
  real roots are empty and the four canonical broad packets are absent.
  Reviewer gate passed 3/3: `Heisenberg` agreed on status honesty after the
  restart note stopped claiming commit/push readiness, `Curie` agreed after
  backend connection-string field-name rejection was added, and `Raman` agreed
  after raw write and custody-phase rollback gaps were fixed. No goal
  completion claim is supported.
- 2026-06-28 governed approval promotion failure rollback checkpoint:
  `real_evidence_governance_approval.py --execute-approved-promotion` now
  removes a target canonical broad packet if an approved promotion subprocess
  fails after creating that target packet. The rollback is covered for
  nonzero subprocess returns, subprocess `OSError`, and Pasteur's
  hardlink-alias blocker: if an assembler fails after linking its temporary
  file to the canonical target but before unlinking the temporary file, the
  newly created target `hardlink_alias` is now removed. The execution report
  exposes `subprocess_error` plus `rollback_after_failed_promotion` alongside
  the existing candidate-manifest-drift rollback result. The tracked operator
  guide documents that failed approved promotion removes the newly created
  target packet before reporting failure. Canonical dev-container verification
  passed after the hardlink fix: focused approval/operator-guide/submission
  unittest 68 OK, full KG-eval unittest 500 OK, main repo unittest 252 OK,
  operator guide and template checks, refreshed broad reports, default KG
  acceptance `passed_with_explicit_limits`, strict KG acceptance exits 1 only
  for known limits, full Ruff check/format-check, and `git diff --check`.
  Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed real-evidence gates; all real roots are
  empty, all four canonical broad packets are absent, and preflight reports no
  packet or artifact hazards. Reviewer gate passed 3/3 after Pasteur's
  hardlink-alias rollback blocker was fixed and re-reviewed:
  `Chandrasekhar`, `Pasteur`, and `Locke` returned
  `RELEASE_DECISION: AGREE`. No goal completion claim is supported.
- 2026-06-28 gate-progress report checkpoint:
  added `.formowl/kg-eval/real_evidence_gate_progress.py`, focused tests, and
  operator-guide documentation for a compact non-authoritative progress report
  over the four remaining real-evidence gates. The report maps each gate to a
  collection stage such as `missing_operator_response`,
  `candidate_artifacts_present_without_manifest`,
  `candidate_manifest_present_pending_validation`,
  `candidate_validation_failed_or_stale`,
  `candidate_validation_clear_pending_approval`,
  `approval_valid_pending_promotion`,
  `canonical_packet_present_needs_validator_clear`, or
  `canonical_packet_validator_clear`. It reads persisted preflight/work-order
  reports plus safe `work_packets/` surfaces for candidate manifests,
  candidate-validation reports, and approval manifests. It does not refresh
  preflight, read operator response packets, read candidate artifact contents,
  write candidate artifacts, promote evidence, write canonical packets,
  replace validators, or count as acceptance. Current refreshed progress is
  still fully blocked:
  all four gates are `missing_operator_response`; candidate manifest,
  candidate-validation-clear, valid-approval, and canonical-validator-clear
  counts are all `0`; real roots remain empty; and canonical broad packets are
  absent. Canonical dev-container verification after reviewer blocker fixes
  passed: focused progress/operator-guide unittest 20 OK, full KG-eval
  unittest 512 OK, main repo unittest 252 OK, operator guide and progress
  checks, refreshed broad reports, default KG acceptance
  `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
  limits, full Ruff check/format-check, and `git diff --check`. Reviewer gate
  passed 3/3: `Plato` agreed on status honesty after the stage-label docs were
  completed, `Carson` agreed after the candidate-manifest symlink/hardlink
  hash-current blocker was fixed, and `Russell` agreed after source-report
  contract withholding plus rejected approval-surface reporting were added.
  This makes the remaining state easier to audit but does not make any broad
  gate pass. No goal completion claim is supported.
- 2026-06-28 enterprise-multimodal response-intake parity hardening
  checkpoint: `enterprise_multimodal_response_intake.py` now rejects the same
  broader raw/internal field-name surface as the other hardened response
  intake paths, including backend connection-string, database/object-store,
  raw SQL, raw path, and worker scratch field names with otherwise benign
  values. Custody receipt construction, optional assembly-manifest hashing,
  custody write, and custody receipt hashing now sit inside rollback handling,
  so candidate artifacts and optional candidate manifests are removed if
  custody hashing or custody write fails after writes. The enterprise
  work-order response contract and tracked operator guide now list output-dir
  binding, top-level/validation wrapper allowlisting, raw/internal field-name
  rejection, parent-dir preflight, after-open cleanup, rollback, and optional
  manifest custody hashing. Canonical dev-container verification passed:
  focused enterprise-intake/work-order/operator-guide unittest 47 OK, full
  KG-eval unittest 514 OK, main repo unittest 252 OK, guide/progress checks,
  full Ruff check/format-check, and `git diff --check`. Broad KG-eval remains
  incomplete with `overall_passed=false`, 8 passed gates, and the same four
  failed real-evidence gates; all real roots are empty and canonical broad
  packets are absent. Reviewer gate passed 3/3: `Socrates`, `Gibbs`, and
  `Pascal` returned `RELEASE_DECISION: AGREE`. This hardening does not make
  `multimodal_semantic_validation` pass, and no goal completion claim is
  supported.
- 2026-06-28 operator response-packet template checkpoint:
  added `.formowl/kg-eval/real_evidence_response_packet_templates.py`,
  focused tests, and four tracked non-evidence response-packet templates under
  `work_packets/` for the remaining gates. The templates are operator-fillable
  starting shapes for the first missing response packets and are generated from
  validator constants for required fair-baseline systems, enterprise
  modalities, and production adapter components where applicable. They carry
  `template_only`, `do_not_submit_as_evidence`, false claim-boundary fields,
  and operator instructions, and focused tests prove all four templates are
  rejected by response-intake helpers as-is without candidate artifact,
  candidate manifest, or canonical packet writes. The tracked operator guide
  now lists the response templates and `--check-templates` command. Canonical
  dev-container verification passed: focused response-template/operator-guide
  unittest 11 OK, full KG-eval unittest 517 OK, main repo unittest 252 OK,
  response-template/operator-guide/submission-template/approval-template/
  progress checks, full Ruff check/format-check, and `git diff --check`.
  Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates; all real roots are empty and
  canonical broad packets are absent. Reviewer gate passed 3/3: `Euclid`,
  `Schrodinger`, and `Franklin` returned `RELEASE_DECISION: AGREE`. This
  template slice does not make any broad gate pass, and no goal completion
  claim is supported.
- 2026-06-28 operator response-packet preflight checkpoint:
  the four candidate-only response-intake CLIs now support
  `--preflight-response`, which validates final operator response packet
  shape, work-packet binding, output-dir/operator-run-id binding, optional
  candidate-manifest output path, planned artifact surfaces, raw/internal
  field guards, and no-overwrite/parent-dir surfaces without writing candidate
  artifacts, candidate manifests, or canonical broad packets. The
  enterprise-multimodal and production-adapter paths now reject forged
  same-type work packets even when artifact-boundary booleans are false by
  comparing the generated work-packet state, roots, canonical target,
  collection plans, validator expectation, and `work_packet_sha256`. The
  submission-manifest intake plan now lists paired response-preflight commands
  beside candidate-only intake commands, and the tracked work orders/operator
  guide instruct operators to run preflight before intake. Claim boundary: the
  slice accepts no evidence, promotes no evidence, does not run candidate
  validators during preflight, writes no canonical broad packets, and does not
  count as acceptance. Canonical dev-container verification passed: focused
  response-intake/submission/work-order/operator-guide unittest 162 OK, full
  KG-eval unittest 524 OK, main repo unittest 252 OK, operator guide
  `--check`, submission template `--check-template`, refreshed broad reports,
  full Ruff check, Ruff format-check, and `git diff --check`. Broad KG-eval
  remains incomplete with `overall_passed=false`, 8 passed gates, and the same
  four failed real-evidence gates; progress still shows all four at
  `missing_operator_response`, with empty real roots and absent canonical broad
  packets. Reviewer gate passed 3/3: `Euler` agreed on engineering
  correctness, `Nash` agreed after the enterprise/production work-packet
  binding blocker was fixed and re-reviewed, and `Beauvoir` agreed on status
  honesty. No completion claim is supported.
- 2026-06-28 submission-manifest response-preflight runner checkpoint:
  `real_evidence_submission_manifest.py --preflight-responses` now provides a
  single controlled non-evidence runner over the four response-intake helper
  preflights. It validates the operator-filled submission manifest first,
  requires existing response packets, builds fixed `--preflight-response` argv,
  runs helpers without a shell, refuses pre-existing canonical broad-packet
  path hazards before subprocess launch, stops on the first failed preflight,
  and fails closed on final-state canonical packet or response-output surface
  drift. It reads response-packet contents only through the existing preflight
  helpers, writes no candidate artifacts, writes no candidate manifest,
  promotes no evidence, writes no canonical broad packets, and does not count
  as an acceptance gate. Canonical dev-container verification passed: focused
  submission/guide unittest 63 OK, full KG-eval unittest 531 OK, main repo
  unittest 252 OK, operator guide/submission-template/governance-approval
  template/response-template/progress checks, refreshed broad reports, default
  main KG acceptance `passed_with_explicit_limits`, strict main KG acceptance
  exits 1 only for known limits, and full Ruff check/format-check. Reviewer
  gate passed 3/3: `Huygens`, `Gauss`, and `Ohm` returned
  `RELEASE_DECISION: AGREE` after Huygens' direct canonical-drift test
  suggestion was implemented. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed
  real-evidence gates; progress still shows all four at
  `missing_operator_response`, with zero candidate manifests, zero clear
  validation reports, zero valid approvals, empty real roots, and absent
  canonical broad packets. No goal completion claim is supported.
- 2026-06-28 blocked audit after `1e2010f`: current-state inspection found no
  files under the four ignored `inputs/*_real/` roots, no operator-filled
  submission/candidate/approval surfaces under `work_packets/`, and no
  canonical broad evidence packets. `real_evidence_gate_progress.json` still
  reports four gates at `missing_operator_response`, with zero candidate
  manifests, zero clear candidate-validation reports, zero valid approvals,
  and zero canonical validator clears. The repeated blocker is now concrete:
  broad KG completion is blocked on external operator/user evidence, not on
  more repository-side implementation. Next action after evidence arrives is
  to validate an operator-filled submission manifest, run
  `--preflight-responses`, run `--execute-candidate-intakes`, run
  `--validate-candidate-manifests`, validate an approval manifest, execute
  approved promotion, then rerun the broad validators and total acceptance.
- 2026-06-28 Plan B LLM-assisted provisional adjudication attempt: at the
  user's request, Codex opened four read-only specialist subagents, one per
  failed broad gate. Gate rule was strict: all four had to return
  `PROVISIONAL_DECISION: PASS`, and provisional LLM adjudication could not be
  represented as completed human adjudication. Results were 0/4 PASS:
  `Halley` blocked `fair_external_baseline_comparison`, `Sartre` blocked
  `annotation_adjudication_protocol`, `Erdos` blocked
  `multimodal_semantic_validation`, and `Avicenna` blocked
  `production_adapter_paths`. All four found the same material blocker: there
  is no real or candidate evidence to adjudicate; only templates/previews and
  empty real roots are present. Therefore Plan B is also blocked until at
  least operator/user response packets or candidate artifacts exist. The
  original human/real-evidence gates remain failed.
- 2026-06-28 broad KG real-evidence completion checkpoint, retracted
  2026-06-30: this historical note previously recorded a local 12/12 state,
  `overall_passed=true`, hashes
  `9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba` and
  `b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d`,
  `validator_clear_for_all_broad_gates`, zero work orders, and zero progress
  gates. Treat that note as stale and superseded by the current 2026-06-30
  #13 authority correction at the top of this file. It is not current
  authority and supports no broad completion claim.
- 2026-06-29 packaging handoff checkpoint: the broad KG research-evaluation
  result now has a packaged integration facade. `python/formowl_kg_eval/`
  exposes `build_acceptance_summary()`, `run_kg_eval_command()`, and the
  `formowl-kg-eval` console script. Downstream system work should consume
  `formowl-kg-eval summary` or the package API instead of importing
  `.formowl/kg-eval` scripts. `docs/kg-eval-package.md` records the package
  contract, CLI, Python API, claim boundary, and System Backbone integration
  guidance.
- 2026-06-29 candidate-generation capability profile checkpoint:
  `python/formowl_graph/capabilities.py` now declares stable KG
  candidate-generation profiles for heterogeneous remote workers:
  deterministic low-spec CPU generation, local SentenceTransformer or
  BERT-family embedding generation, and accelerated neural generation for
  BERT-family NER/relation extraction, local LLM graph extraction, multimodal
  semantic adapters, and large embedding batches. `formowl_kg_eval summary`
  exposes these profiles under `candidate_generation_capabilities` for System
  Backbone worker routing. This restores BERT/SentenceTransformer as an
  optional adapter slot; it does not claim default BERT inference is running,
  and neural adapters remain candidate-only with no canonical graph/type write
  authority and no raw-access authority. Dev-container verification passed:
  focused capability tests 5 OK, focused KG-eval package tests 4 OK, full main
  repo unittest 261 OK, full Ruff check and format-check passed, and
  `python -m formowl_kg_eval summary` shows the three profiles. Next work after
  pushing this branch is a separate BERT ablation experiment branch that
  preserves BERT vs non-BERT benchmark artifacts for stakeholder review.
- 2026-06-29 BERT ablation experiment checkpoint on branch
  `kg-bert-ablation-experiment`: the experiment branch now includes a large
  public enterprise benchmark source manifest at
  `experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json`.
  It selects mail/conversation, office document, financial QA, SEC financial
  report, and contract-document source families, sets the minimum model
  selection target to 10,000 labeled pairs, and sets the
  stakeholder-facing evidence target to 50,000 pairs. This is a selected
  source/sampling plan, not a completed large benchmark result. The ablation
  harness now binds result artifacts to the manifest hash, preserves the
  legacy CPU neural profile `legacy_cpu_bert` /
  `sentence-transformers/bert-base-nli-mean-tokens`, and changes the GPU
  default profile to `gpu_bge_large_en_v1_5` / `BAAI/bge-large-en-v1.5` with a
  one-NVIDIA-GeForce-GTX-1080-Ti / 11GB-VRAM local floor. The BGE profile uses
  preliminary threshold 0.62; the legacy CPU BERT profile keeps threshold
  0.70. CPU and GPU Dockerfile env defaults and docs match this split, and
  `formowl_kg_eval summary` exposes the same routing contract to the System
  Backbone Agent. Canonical dev-container verification passed: focused
  ablation tests 6 OK, focused candidate capability tests 5 OK, focused runtime
  container tests 4 OK, full main-repo unittest 273 OK, Ruff check passed,
  Ruff format-check passed, and package summary smoke passed. The refreshed
  default-dev-container artifacts record BGE as the default GPU profile but
  `blocked_missing_dependency` for neural execution because the lightweight dev
  container intentionally does not include `sentence_transformers` or torch.
  The actual host GPU artifact
  `experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json`
  completed with `model_device=cuda:0`, two visible GTX 1080 Ti devices,
  threshold 0.62, precision 1.0, recall 0.9, F1 0.947368, and accuracy 0.9375
  on the small 16-pair fixture. This supports only a small-fixture improvement
  over the old BERT+type-gate artifact; do not claim stakeholder-grade model
  selection until the public enterprise benchmark manifest is executed.
  Reviewer gate passed 3/3: `Descartes` agreed on engineering correctness
  after stale active artifact paths were fixed and covered by regression tests,
  `Boole` agreed on governance/safety, and `Lagrange` agreed on research
  method/benchmark validity. Final verification after reviewer fixes: full
  main-repo unittest 273 OK, Ruff check passed, Ruff format-check passed, and
  JSON artifacts parsed.
- 2026-06-29 public enterprise BGE benchmark checkpoint: the first large
  model-selection run completed at
  `experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json`.
  The run used 10,000 candidate pairs: 7,000 CUAD contract-document pairs and
  3,000 SEC financial-report/company pairs. Lexical baseline scored accuracy
  0.5216, precision 0.940367, recall 0.041198, F1 0.078937, and 3,766.652
  pairs/s. BGE large GPU with `BAAI/bge-large-en-v1.5`, threshold 0.62, single
  GTX 1080 Ti batch size 8, `sentence-transformers=3.3.1`, and
  `torch=2.10.0+cu126` scored accuracy 0.7183, precision 0.931627, recall
  0.468248, F1 0.623245, and 23.874 pairs/s end-to-end including model
  load/cache. Deltas versus lexical: accuracy +0.196700, F1 +0.544308, recall
  +0.427050, precision -0.008740. The batch-size-32 attempt failed with a CUDA
  illegal memory access around 60%; the batch-size-8 rerun completed. Claim
  boundary: model-selection evidence only, candidate-only, no canonical
  graph/type writes, no raw-access grants, no 50,000-pair stakeholder-grade
  claim, and FiQA/Enron/RVL-CDIP are source-locked but not yet labeled pairs in
  this runner.
- 2026-06-29 50,000-pair and ontology-ablation checkpoint: the stakeholder-size
  public enterprise BGE benchmark completed at
  `experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json`.
  The run used 50,000 candidate pairs: 22,500 CUAD contract-document pairs,
  15,000 SEC financial-report/company pairs, and 12,500 BEIR FiQA
  financial-QA pairs; 24,837 positives and 25,163 negatives. Lexical baseline
  scored accuracy 0.5225, precision 0.921930, recall 0.042316, F1 0.080918,
  and 4,915.593 pairs/s. BGE large GPU scored accuracy 0.79986, precision
  0.945935, recall 0.633289, F1 0.758664, and 63.851 pairs/s. Deltas versus
  lexical: accuracy +0.277360, F1 +0.677746, recall +0.590973, precision
  +0.024005. The chart is
  `experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg`.
  The ontology ablation completed at
  `experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json`.
  It used 20,000 pairs, including 10,000 cross-type stress negatives. BGE-only
  scored accuracy 0.3999, precision 0.235272, recall 0.631759, F1 0.342860,
  and 10,000 stress false positives; BGE plus hard or soft ontology guidance
  scored accuracy 0.8999, precision 0.946493, recall 0.631759, F1 0.757744,
  and 0 stress false positives. Ontology charts are
  `experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg`
  and
  `experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg`.
  Claim boundary: both runs remain candidate-only; they support the BGE neural
  profile and ontology-aware matching algorithm, but do not authorize canonical
  graph/type writes, raw-access grants, production latency claims, or completed
  human adjudication claims.
- 2026-06-29 benchmark package API checkpoint: the experiment artifacts now
  have a stable package surface for the System Backbone Agent.
  `python/formowl_kg_eval/benchmarks.py` exposes `build_benchmark_summary()`
  and `summarize_benchmark_artifact()`; `formowl-kg-eval summary` includes
  `kg_benchmark_results`; and `formowl-kg-eval benchmarks` emits a
  benchmark-only redacted JSON summary with metrics, deltas, claim boundaries,
  and repo-relative SVG chart paths. The API intentionally omits per-pair
  samples and raw labels from the large artifacts. This remains candidate-only
  research evidence and does not create production gateway, canonical graph,
  canonical type, raw-access, production-latency, or completed
  human-adjudication authority.
  Reviewer gate passed 3/3: engineering reviewer `Bacon` initially blocked
  because benchmark JSON/chart artifacts were untracked, and re-reviewer
  `Ramanujan` agreed after those artifacts were staged for commit; governance
  reviewer `Halley` initially blocked raw workspace/path exposure through the
  package facade, and re-reviewer `Epicurus` agreed after top-level
  `kg_eval_workspace` export was removed, command stdout/stderr redaction was
  added, tests were strengthened, and docs clarified that `summary` and
  `benchmarks` are the product integration surfaces; research-method reviewer
  `Chandrasekhar` agreed with no blocking findings.
- 2026-07-07 #21 full-PST mail KG ablation checkpoint:
  checkpoint S's hard-domain full-PST baseline was rescored without BERT using
  preserved intermediate data. The non-BERT candidate KG arm links body
  observations by thread and bounded domain/conflict terms; the ontology-guided
  arm additionally uses formal FormOwl `TypeDefinition` and `TypeMapping`
  contracts, a hash-bound ontology revision, and business-function lens to
  closed-core-supertype mappings as candidate scoring/gating only. Neither arm
  reparses the PST, uses neural packages, writes canonical graph/type state,
  grants raw access, writes user graphs, or projects wiki state. Latest
  preserved-workdir results: baseline retrieval 20/100, non-BERT candidate KG
  30/100, ontology-guided non-BERT candidate KG 29/100. The ontology arm is a
  negative ablation result, not a quality win: positive cases fell from 20/80
  to 19/80 versus pure KG, no-match cases stayed 0/10, and permission-denied
  cases stayed 10/10. Canonical dev-container verification passed for focused
  KG tests 9 OK, focused ontology-ablation tests 9 OK, touched-file Ruff
  check/format-check, and saved-report validation for both container-generated
  public reports with `blockers=[]`; full unittest ran 573 OK in 835.841s;
  full Ruff check/format-check passed with 217 files already formatted. The
  #21 reviewer gate passed 6/6 with read-only reviewers `Rawls`, `Galileo`,
  `Pascal`, `Plato`, `Chandrasekhar`, and `Confucius`; all returned
  `RELEASE_DECISION: AGREE` with no blocking findings. This checkpoint does
  not change the broad real-evidence KG acceptance blockers or support a broad
  completion claim.
- 2026-07-07 #21 ontology-native factorial redesign checkpoint:
  after the user challenged the negative ontology result as unfairly KG-first,
  the next active mail-evidence research goal is to redesign and rerun the
  hard-domain comparison with ontology-native encoding. The pre-registration
  draft is `docs/mail-ontology-native-factorial-design.md`. It records the
  four math/research subagent design positions (`Jason`, `Maxwell`,
  `Hypatia`, and `Planck`) and replaces the earlier KG-first 326 ordered
  operator search with a staged 332-entry design: 324 ontology-native arms
  across type inventory, corpus encoder, query encoder, scoring/gating mode,
  and candidate-pool size, plus 8 controls. The intended representation builds
  typed segment, entity, mail-frame, value, and message-context nodes before
  graph fusion, and ranks compact typed proof neighborhoods instead of large
  thread/domain components. This is a design checkpoint only: no ontology-native
  experiment result is claimed yet. Next action is to pass the design audit,
  implement the pre-registered harness over the preserved `.test-tmp`
  full-PST work directory without deleting intermediates, run the 332 entries,
  validate only hash/status/count/timing public reports, share redacted results
  back to the four design reviewers, and rerun if they find a stronger fair
  design. Claim boundaries remain candidate-only with no canonical graph/type
  writes, no user graph writes, no raw access, no wiki projection, and no broad
  KG real-evidence completion claim.
