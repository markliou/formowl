# FormOwl KG Research Session Restart

Use this file as the short restart note for the Knowledge Graph Research Agent.
The long history remains in `HANDOFF.md`, but this file is the current concise
state.

## Startup

Read these before editing:

1. `AGENTS.md`
2. `docs/implementation-task-breakdown.md`
3. `docs/agent-roles.md`
4. `SPEC.md`
5. `RESOURCE_EXTRACTION_SPEC.md`
6. `README.md`
7. `.formowl/kg-eval/SESSION_RESTART.md`
8. Tail `.formowl/kg-eval/HANDOFF.md` if more history is needed.

## Goal

Goal mode is active. Do not mark complete.

```text
完成 FormOwl Knowledge Graph 方法探索與驗收：補齊外部近期文獻比較、ontology 結合方法、不同使用者 KG 與 KG 融合實驗、多模態企業資料驗證、人工作業/標註/裁決流程、production adapter gate，並用總驗收套件清楚標示已通過與未通過項目。
```

## Current Restart Snapshot

This snapshot supersedes older "latest work" notes below when they conflict.

- Goal tool status: `active`.
- Overall KG objective: incomplete. Do not mark complete.
- Total acceptance remains `overall_passed = false`.
- Current count remains 8 passed gates and 4 failed gates.
- Failed broad gates remain:
  - `fair_external_baseline_comparison`
  - `annotation_adjudication_protocol`
  - `multimodal_semantic_validation`
  - `production_adapter_paths`

Latest local implementation slice, updated 2026-06-28:

- Candidate intake execution-plan emission added to
  `real_evidence_submission_manifest.py`.
- `--emit-intake-plan work_packets/OPERATOR_INTAKE_PLAN.json` validates an
  operator-filled submission manifest and writes a non-evidence plan listing
  the exact four candidate-only response intake commands.
- The plan command itself does not execute intake, does not read response
  packet contents, writes no candidate artifacts, writes no canonical packets,
  promotes no evidence, and counts as no acceptance gate.
- Plan output is restricted to safe ignored `work_packets/*.json` paths and
  rejects templates, tracked preview packets, candidate manifests, tracked work
  packets, symlinks, non-JSON names, raw/absolute/dot paths, and existing
  outputs.
- Tests now snapshot real roots, canonical broad packets, and
  `work_packets/*_candidate_manifest.json` so plan emission cannot silently
  create candidate or canonical artifacts. Invalid-manifest plan emission
  exits without writing a plan file.
- The tracked operator guide documents the optional plan step and states that
  the plan is ignored by Git and does not execute commands.
- Dev-container verification passed:
  - focused submission/guide unittest 24 OK
  - full KG-eval unittest 421 OK
  - main repo unittest 252 OK
  - changed-file Ruff check and format check
  - operator guide `--check`
  - submission template `--check-template`
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and `latency_scalability_enterprise_claims`
- Broad KG-eval remains `overall_passed=false`, 8 passed gates, and the same
  four failed broad real-evidence gates.
- GPT/Codex reviewers `Boole`, `Maxwell`, and `Avicenna` returned
  `RELEASE_DECISION: AGREE` after Boole's candidate-manifest no-write coverage
  blocker was fixed and Maxwell's invalid-manifest no-plan-file hardening note
  was implemented.
- Antigravity Gemini review is blocked at 0/3: `agy --version` and
  `agy models` succeeded, but a bounded closed-book summary packet was rejected
  before execution by tenant policy as private repository-derived disclosure to
  an untrusted external reviewer service. No packet was sent and no workaround
  was attempted.

Previous execution checkpoint, updated 2026-06-28:

- `git fetch origin` found no newer `complete-slice-1` commit beyond
  `f3ba5f8` (`Route KG candidate validation to intake manifests`), and the
  worktree was clean before execution.
- Dev-container commands rerun against current state:
  - `python kg_total_acceptance_suite.py`
  - `python kg_objective_completion_audit.py`
  - `python real_evidence_preflight.py`
  - `python real_evidence_collection_work_orders.py`
  - full KG-eval unittest 417 OK
  - main repo unittest 252 OK
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance exited nonzero only for the known
    `production_adapter_readiness` failed item and
    `latency_scalability_enterprise_claims` blocked item.
- Refreshed broad KG-eval remains `overall_passed=false`, with 8 passed gates
  and the same four failed gates.
- Objective audit remains `objective_complete=false`, with 5 proved
  requirements and 4 incomplete requirements.
- Preflight reports all four `inputs/*_real` roots have zero files, no
  candidate artifacts, and the four canonical broad packets are absent.
- No completion claim is supported.

Latest completed local slice, updated 2026-06-27:

- Candidate-manifest validation guidance completed on 2026-06-28.
- `real_evidence_collection_work_orders.py` and the tracked operator guide now
  validate the candidate manifests emitted by response intake under
  `work_packets/*_candidate_manifest.json`.
- `work_orders/*_assembly_manifest.json` generation remains documented only as
  optional non-evidence scaffold inspection.
- `_common_commands` fails closed if a remaining gate lacks a response-intake
  candidate manifest mapping instead of falling back to scaffold validation.
- This slice writes no candidate artifacts, promotes no evidence, writes no
  canonical packets, and does not count as an acceptance gate.
- Dev-container verification passed:
  - operator guide `--check`
  - focused work-order/guide unittest 26 OK
  - full KG-eval unittest 417 OK
  - main repo unittest 252 OK
  - changed-file Ruff check and format check
  - refreshed broad KG-eval reports
  - main KG acceptance unchanged: default `passed_with_explicit_limits`
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same four failed real-evidence gates. `inputs/*_real` has no files and the
  four canonical broad packets remain absent.
- GPT/Codex reviewers `Bohr`, `Euler`, and `Lorentz` returned
  `RELEASE_DECISION: AGREE` after Lorentz's scaffold-fallback blocker was
  fixed.
- Antigravity remains blocked by tenant policy for bounded FormOwl KG
  repository disclosure; no packet was sent and no workaround was attempted.

Previous completed local slice, updated 2026-06-28:

- Submission-manifest CLI/work-packet tracking hardening completed on
  2026-06-28.
- `real_evidence_submission_manifest.py --manifest` validates the
  operator-filled manifest path before reading it. Accepted manifests must be
  safe repo-relative JSON files under `work_packets/`; templates, tracked
  preview-packet naming, absolute/raw/dot-segment paths, non-work-packet
  paths, and symlink components are rejected.
- `.gitignore` ignores arbitrary operator-generated `work_packets/*.json`
  outputs and only re-includes the four fixed preview packets, the tracked
  submission template, and the tracked operator guide.
- The operator guide states that operator-filled submission manifests and
  generated candidate manifests under `work_packets/` are intentionally
  ignored.
- This slice reads no response packet contents, writes no candidate artifacts,
  promotes no evidence, writes no canonical packets, and does not count as an
  acceptance gate.
- Dev-container verification passed:
  - submission template `--check-template`
  - operator guide `--check`
  - focused submission/guide unittest 20 OK
  - full KG-eval unittest 416 OK
  - main repo unittest 252 OK
  - changed-file Ruff check and format check
  - refreshed broad KG-eval reports
  - main KG acceptance unchanged: default `passed_with_explicit_limits`
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same four failed real-evidence gates. `inputs/*_real` has no files and the
  four canonical broad packets remain absent.
- GPT/Codex reviewers `Godel`, `Gibbs`, and `Ohm` returned
  `RELEASE_DECISION: AGREE` after blockers for dot-segment normalization and
  broad `*_preview.json` tracking were fixed.
- Antigravity bounded write delegation was attempted with `.formowl/kg-eval`
  as the write scope, but tenant policy rejected it before execution as
  private repository disclosure to an untrusted external Antigravity service.
  No packet was sent and no workaround was attempted.

Previous completed local slice, updated 2026-06-27:

- A tracked operator submission-manifest preflight now exists at
  `real_evidence_submission_manifest.py`.
- The tracked non-evidence template is
  `work_packets/remaining_real_evidence_submission_manifest.template.json`.
- Operators should fill a copy of that template, then run:
  - `python3 real_evidence_submission_manifest.py --check-template`
  - `python3 real_evidence_submission_manifest.py --manifest
    work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json`
- The preflight validates exact gate ids, response packet types, response
  paths directly under the matching ignored
  `inputs/*_real/<operator_run_id>/` run directory, operator run ids,
  candidate-only output dirs, work-packet manifest outputs, and
  non-authoritative claim boundaries before any intake command writes.
- It reads no response-packet contents, writes no candidate artifacts, promotes
  no evidence, writes no canonical input packets, and does not count as an
  acceptance gate.
- The operator guide now includes this submission-manifest preflight step.
- Template emit/check is now restricted to the tracked template path
  `work_packets/remaining_real_evidence_submission_manifest.template.json`, so
  it cannot overwrite arbitrary `work_packets/*.json` manifests.
- The repo-local `$use-agy-antigravity` skill was updated at
  `.agents/skills/use-agy-antigravity/SKILL.md` so the KG `agy`
  authorization/reviewer/bounded-write workflow is explicitly portable after
  git clone.
- Dev-container verification passed:
  - submission template `--check-template`
  - operator guide `--check`
  - focused submission/guide unittest 17 OK
  - full KG-eval unittest 413 OK
  - changed-file Ruff check and format-check
  - refreshed broad KG-eval reports
  - main repo unittest 252 OK
  - main KG acceptance unchanged: default `passed_with_explicit_limits`;
    strict fails only on known limits
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same four failed real-evidence gates.
- Codex/GPT reviewers `Dalton`, `Galileo`, `Volta`, and `Feynman` returned
  `RELEASE_DECISION: AGREE` with no blocking findings; Dalton's non-blocking
  template-output narrowing suggestion was implemented with a regression test.
- Antigravity Gemini review for this slice is blocked at 0/3: a bounded
  read-only `agy` reviewer packet containing only relevant paths, summaries,
  verification results, and claim boundaries was rejected before execution by
  tenant policy as external disclosure to an untrusted reviewer service. No
  packet was sent and no workaround or alternate external channel was
  attempted.

Previous completed local slice, updated 2026-06-27:

- A tracked operator-facing guide for the remaining four broad real-evidence
  gates now exists at
  `work_packets/remaining_real_evidence_operator_guide.md`.
- The guide is generated by `real_evidence_operator_guide.py` from
  `real_evidence_collection_work_orders.py`.
- It summarizes current blockers, required real artifacts, candidate-only
  intake commands, validation commands, and safety boundaries for:
  - `fair_external_baseline_comparison`
  - `annotation_adjudication_protocol`
  - `multimodal_semantic_validation`
  - `production_adapter_paths`
- The guide is non-authoritative: it accepts no evidence, promotes no packets,
  writes no canonical input packets, and does not count as an acceptance gate.
- `python3 real_evidence_operator_guide.py --check` verifies that the tracked
  guide is current with the generated work-order state and fails without
  rewriting stale guide content.
- Dev-container verification passed after adding the guide:
  - guide `--check`
  - focused operator-guide unittest 8 OK
  - full KG-eval unittest 404 OK
  - changed-file Ruff check and format-check
  - refreshed broad KG-eval reports
  - main repo unittest 252 OK
  - main KG acceptance unchanged: default `passed_with_explicit_limits`;
    strict fails only on known limits
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same four failed real-evidence gates.

Previous completed local slice, updated 2026-06-27:

- Enterprise multimodal response intake is hardened and wired into
  `real_evidence_collection_work_orders.py` as a candidate-only command for
  `multimodal_semantic_validation`.
- `enterprise_multimodal_response_intake.py` writes only candidate artifacts
  under `inputs/enterprise_multimodal_real/<operator-run-id>` and optional
  candidate manifests under `work_packets/`.
- The intake records response packet, candidate packet, artifact, custody, and
  optional manifest hashes; rejects unsupported top-level response fields,
  unsafe roots, nested default output dirs, sandbox/test paths by default,
  symlinks, overwrites, parent-file collisions, raw/internal/template payload
  values, raw/internal field names, and promotion arguments; and never writes
  `inputs/enterprise_multimodal_validation_packet.json`.
- It rolls back intake-created artifacts and optional manifests on assembler,
  validation, custody, serialization, or write failures, including failures
  after exclusive create/open.
- Dev-container verification after reviewer fixes passed:
  - changed-file Ruff check and format-check
  - focused KG-eval unittest 35 OK
  - full KG-eval unittest 396 OK
  - main repo unittest 252 OK
  - refreshed `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same 4 failed gates. This slice does not make
  `multimodal_semantic_validation` pass.
- GPT/Codex reviewers `Aristotle`, `Huygens`, and `Lovelace` returned
  `RELEASE_DECISION: AGREE` after blocker fixes for OSError/TypeError
  partial-write rollback and raw/internal field-name rejection.
- Antigravity Gemini review is blocked at 0/3: `agy --version` and
  `agy models` succeeded, but a bounded read-only review-packet attempt
  through real `agy` was rejected before execution by tenant policy as
  external data disclosure to an untrusted reviewer service, even with user
  authorization. No packet was sent and no workaround was attempted.

Previous completed local slice, updated 2026-06-27:

- Production adapter response intake is implemented and wired into
  `real_evidence_collection_work_orders.py` as a candidate-only command for
  `production_adapter_paths`.
- `production_adapter_response_intake.py` writes only candidate artifacts under
  `inputs/production_adapter_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`.
- The intake records response packet, candidate packet, artifact, custody, and
  optional manifest hashes; rejects unsafe roots, nested default output dirs,
  sandbox/test paths by default, symlinks, overwrites, parent-file collisions,
  raw/internal/template payloads, unsupported top-level response fields,
  duplicate/missing adapter components, and promotion arguments; and never
  writes `inputs/production_adapter_evidence_packet.json`.
- Dev-container verification after reviewer fixes passed:
  - changed-file Ruff check and format-check
  - focused KG-eval unittest 30 OK
  - full KG-eval unittest 386 OK
  - main repo unittest 252 OK
  - refreshed `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and the
  same 4 failed gates. This slice does not make `production_adapter_paths`
  pass.
- GPT/Codex reviewers `Gauss`, `Archimedes`, and `Noether` returned
  `RELEASE_DECISION: AGREE` after blocker fixes.
- Antigravity Gemini review is blocked at 0/3: `agy --version` and
  `agy models` succeeded, but three bounded read-only review-packet attempts
  through real `agy` were rejected before execution by tenant policy as
  external data disclosure to an untrusted reviewer service, even with user
  authorization. No packet was sent and no workaround was attempted.

Latest completed hardening stop point, updated 2026-06-26:

- Human annotation response intake is implemented and wired into
  `.formowl/kg-eval/real_evidence_collection_work_orders.py` as a
  candidate-only command for `annotation_adjudication_protocol`.
- `.formowl/kg-eval/kg_total_acceptance_suite.py` now requires empty blockers
  for the fair-baseline and human-annotation broad gates, matching the
  multimodal and production gates.
- `.formowl/kg-eval/human_annotation_response_intake.py` is hardened so it:
  - rejects planned output paths that already exist or are symlinks, including
    broken symlinks;
  - writes JSON with exclusive create;
  - records the response packet SHA256 in the custody receipt;
  - rejects `--promote`;
  - writes only candidate artifacts under
    `inputs/human_annotation_real/<operator-run-id>` and optional manifests
    under `work_packets/`;
  - returns only a candidate validation summary, not a full authoritative gate
    report.
- `.formowl/kg-eval/human_annotation_adjudication_validator.py` now rejects a
  symlinked canonical `inputs/human_annotation_results_v1.json`.
- `.formowl/kg-eval/human_annotation_adjudication_validator.py` now requires
  strong 64-hex `custody.response_packet_sha256`, so a canonical human
  annotation packet cannot pass without binding the operator response packet.
- `.formowl/kg-eval/test_human_annotation_adjudication_validator.py` now has
  regression coverage for missing and weak `response_packet_sha256` values.

Verification after the response-hash binding fix:

- Host focused:
  `python3 -m unittest test_human_annotation_adjudication_validator.py test_human_annotation_response_intake.py test_real_evidence_collection_work_orders.py test_recovered_total_acceptance.py`
  ran 68 tests OK.
- Host full KG-eval:
  `python3 -m unittest discover -s . -p 'test_*.py'` ran 351 tests OK.
- Dev-container reports refreshed:
  - `python kg_total_acceptance_suite.py`
  - `python kg_objective_completion_audit.py`
  - `python real_evidence_preflight.py`
  - `python real_evidence_collection_work_orders.py`
- Dev-container KG-eval:
  `docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local python -m unittest discover -s . -p 'test_*.py'`
  ran 351 tests OK.
- Dev-container main repo:
  `docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local python -m unittest discover -s tests`
  ran 238 tests OK.
- Dev-container Ruff check and format-check passed for affected KG-eval files.
- Broad real roots were empty and canonical broad packets were absent.

Reviewer gate status for this hardening item:

- Complete for this item: 9 effective read-only reviewers agreed.
- Final approving reviewers:
  - Lorentz
  - Volta
  - Hooke
  - Ampere
  - McClintock
  - Kant
  - Galileo
  - Socrates
  - Kierkegaard
- McClintock initially found the response-packet binding blocker; it was fixed
  by requiring `custody.response_packet_sha256` in the authoritative validator,
  then McClintock returned `RELEASE_DECISION: AGREE`.

Immediate next action:

1. Continue the overall KG objective from the four still-failing real-evidence
   gates:
   - `fair_external_baseline_comparison`
   - `annotation_adjudication_protocol`
   - `multimodal_semantic_validation`
   - `production_adapter_paths`
2. Strongest next target: collect and validate real evidence for one broad
   gate. For human annotation, this means actual operator response packets,
   candidate artifact assembly, manual governance promotion to
   `inputs/human_annotation_results_v1.json`, and total acceptance validation.
3. Keep `annotation_adjudication_protocol` failed until actual human response
   evidence is supplied, sealed, manually promoted, and validated.
4. Do not mark the overall KG goal complete until the total acceptance suite
   proves all objective requirements.

Latest completed hardening stop point, updated 2026-06-25 07:44 CST:

- The broad real-root hardening item has passed its 9-reviewer release gate.
- The four broad validators now reject real-root `templates/`,
  `*.template.json`, sandbox/test path parts, and symlink components before
  hashing/loading; they also re-check resolved real-root-relative path parts.
- The four packet assemblers now reject `validator_fixture`,
  `assembler_test`, `preflight_test`, `test_*`, and `*_test` path parts by
  default. Structural tests must explicitly pass `allow_test_artifacts=True`.
- Each `promote_packet(..., allow_test_artifacts=True)` now rejects the
  canonical output path and existing hardlink aliases to the canonical packet
  with `"test artifact packets cannot be promoted to canonical input"`.
- `.formowl/kg-eval/real_evidence_preflight.py` now keeps a real root blocked
  when `test_or_sandbox_file_count > 0`, even if candidate artifacts are also
  present.
- Added hardlink-alias regression tests so fixture/test packets cannot mutate
  canonical input through a filesystem alias.
- Verification after the final hardlink fix:
  - Host supplemental focused assembler suite: 57 tests OK.
  - Host supplemental full KG-eval suite: 332 tests OK.
  - Dev-container focused assembler suite: 57 tests OK.
  - Dev-container full KG-eval suite: 332 tests OK.
  - Dev-container main repo suite: 238 tests OK.
  - Dev-container Ruff check on affected assembler files/tests: passed.
  - Dev-container Ruff format-check on affected assembler files/tests: passed.
  - No leftover canonical packets or hardlink aliases were found under
    `.formowl/kg-eval/inputs`.

Reviewer gate status for this hardening item:

- Complete for this item: 9 effective read-only reviewers agreed.
- Final approving reviewers:
  - Lovelace
  - Goodall
  - Curie
  - Hilbert
  - Mendel
  - Locke
  - Raman
  - Leibniz
  - Mencius
- Leibniz initially found the hardlink-alias canonical-promotion blocker; it
  was fixed and Leibniz re-reviewed with `RELEASE_DECISION: AGREE`.

Required follow-up:

1. Do not redo this hardening item unless new evidence appears.
2. Continue the overall KG objective from the four still-failing broad
   real-evidence gates:
   - `fair_external_baseline_comparison`
   - `annotation_adjudication_protocol`
   - `multimodal_semantic_validation`
   - `production_adapter_paths`
3. Do not mark the overall KG goal complete until those gates have real
   evidence and the total acceptance suite passes.

## Current Acceptance State

From `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json`:

- `overall_passed = false`
- `passed_gate_count = 8`
- `failed_gate_count = 4`
- Failed gates:
  - `fair_external_baseline_comparison`
  - `annotation_adjudication_protocol`
  - `multimodal_semantic_validation`
  - `production_adapter_paths`

## Portability Checkpoint

Updated 2026-06-27:

- The sanitized KG-eval harness is intended to be tracked in Git so the broad
  acceptance state can be reproduced across machines.
- Track source scripts, tests, templates, fixture inputs, work orders, preview
  packets, this restart note, and non-authoritative blocked-state snapshots
  under `snapshots/current_blocked/`.
- Keep runtime `results/`, `.formowl/kg-eval/HANDOFF.md`, `inputs/*_real/`,
  and the four canonical real evidence packets ignored unless a future governed
  evidence process explicitly changes that.
- Do not treat `snapshots/current_blocked/` as completion evidence without
  rerunning the KG-eval commands in the dev container against the current
  workspace.
- This checkpoint does not make any broad real-evidence gate pass.

Verification after the portability checkpoint:

- Dev-container KG-eval unittest ran 360 tests OK.
- Dev-container main repo unittest ran 246 tests OK.
- `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, and `real_evidence_collection_work_orders.py`
  ran in the dev container.
- Broad KG-eval remains `overall_passed=false`, with 8 passed gates and 4
  failed gates.
- Main-repo KG acceptance default remains `passed_with_explicit_limits`; strict
  mode fails as expected on known readiness limits.

## Latest Completed Work

Most recent KG-eval hardening:

- Strengthened `.formowl/kg-eval/fair_external_baseline_run_validator.py` so
  fair-baseline run artifacts are no longer accepted by path/hash alone.
- Each per-baseline run artifact must now be JSON content with the expected
  `artifact_type`, baseline/source-lock/source-id/package/source/version
  bindings, real-run flags, run manifest binding, and type-specific evidence:
  package lock resolved hash, config equalized hashes, index/query completion,
  answer counts, graph entity/relation counts, and permission-probe zero leaks.
- Updated `.formowl/kg-eval/remaining_evidence_checklist.json` and
  `.formowl/kg-eval/real_evidence_collection_work_orders.py` so operator work
  orders list the required run artifact content contract.
- Added focused validator tests for generic JSON, non-JSON run logs, config
  mismatch, source-lock mismatch, and permission-probe leak artifacts.
- Refreshed:
  - `.formowl/kg-eval/results/fair_external_baseline_run_validator.json`
  - `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json`
  - `.formowl/kg-eval/results/kg_objective_completion_audit.json`
  - `.formowl/kg-eval/results/real_evidence_preflight.json`
  - `.formowl/kg-eval/results/real_evidence_collection_work_orders.json`

Acceptance remains blocked:

- `overall_passed = false`
- `passed_gate_count = 8`
- `failed_gate_count = 4`
- Failed gates remain:
  - `fair_external_baseline_comparison`
  - `annotation_adjudication_protocol`
  - `multimodal_semantic_validation`
  - `production_adapter_paths`

Latest verification:

- Host focused:
  - `python3 -m unittest test_fair_external_baseline_run_validator.py test_fair_external_baseline_packet_assembler.py test_real_evidence_collection_work_orders.py`
    ran 51 tests OK.
- Host full KG-eval:
  - `python3 -m unittest discover -s . -p 'test_*.py'` ran 303 tests OK.
- Dev container:
  - `docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local python -m unittest discover -s . -p 'test_*.py'`
    ran 303 tests OK.
  - `docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local python -m unittest discover -s tests`
    ran 238 tests OK.
  - Dev-container `ruff check` and `ruff format --check` passed for changed
    KG-eval files.

## Previous Completed Work

The latest completed KG-eval work is non-evidence assembly-manifest scaffolding
for all four remaining broad gates.

Existing fair-baseline scaffold:

- `.formowl/kg-eval/fair_external_baseline_assembly_manifest_generator.py`
- `.formowl/kg-eval/test_fair_external_baseline_assembly_manifest_generator.py`
- `.formowl/kg-eval/work_orders/fair_external_baseline_comparison_assembly_manifest.json`

New remaining-gate scaffolds:

- `.formowl/kg-eval/human_annotation_assembly_manifest_generator.py`
- `.formowl/kg-eval/enterprise_multimodal_assembly_manifest_generator.py`
- `.formowl/kg-eval/production_adapter_assembly_manifest_generator.py`
- `.formowl/kg-eval/test_remaining_assembly_manifest_generators.py`
- `.formowl/kg-eval/work_orders/annotation_adjudication_protocol_assembly_manifest.json`
- `.formowl/kg-eval/work_orders/multimodal_semantic_validation_assembly_manifest.json`
- `.formowl/kg-eval/work_orders/production_adapter_paths_assembly_manifest.json`

Also updated:

- `.formowl/kg-eval/human_annotation_packet_assembler.py`
- `.formowl/kg-eval/real_evidence_collection_work_orders.py`
- `.formowl/kg-eval/test_real_evidence_collection_work_orders.py`

Also refreshed:

- `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json`
- `.formowl/kg-eval/results/kg_objective_completion_audit.json`
- `.formowl/kg-eval/results/real_evidence_preflight.json`
- `.formowl/kg-eval/results/real_evidence_collection_work_orders.json`

## Claim Boundary

The scaffolds are intentionally non-evidence. They must not be treated as real
package execution, real human annotation/adjudication, real enterprise
multimodal validation, graph-quality validation, permission leak probing,
production readiness, or top-tier validation.

They must not:

- write `inputs/fair_external_baseline_run_packet.json`
- write `inputs/human_annotation_results_v1.json`
- write `inputs/enterprise_multimodal_validation_packet.json`
- write `inputs/production_adapter_evidence_packet.json`
- write real artifacts under `inputs/*_real/*`
- mark any of the four remaining broad gates as passed

Expected fair-baseline source lock:

```text
addba921e9cc4ebc4ded09b26d23a25a29aeba4f0e15e4dacb711f29dcedb2da
```

Fair-baseline remains red because:

- `inputs/fair_external_baseline_run_packet.json` is absent
- `inputs/fair_baseline_real/` has zero real package-run artifacts
- real Microsoft GraphRAG, LightRAG, and HippoRAG package runs are absent
- human answer-quality adjudication is absent
- graph-quality validation is absent
- permission leak probes are absent
- `source_lock_bound = false` until a real canonical packet binds the expected
  source lock

## Verification Already Completed

Host:

- `python3 -m unittest test_fair_external_baseline_assembly_manifest_generator.py test_real_evidence_collection_work_orders.py`
  ran 21 tests OK.
- `python3 -m unittest test_remaining_assembly_manifest_generators.py test_real_evidence_collection_work_orders.py`
  ran 22 tests OK.
- `python3 -m unittest discover -s . -p 'test_*.py'` ran 299 tests OK.

Dev container:

- `docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local python -m unittest discover -s . -p 'test_*.py'`
  ran 299 tests OK.
- `docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local python -m unittest discover -s tests`
  ran 238 tests OK.
- Dev-container `ruff check` and `ruff format --check` passed for changed
  KG-eval Python files.

Independent review:

- Dirac reviewed the fair-baseline scaffold plan read-only.
- Accepted review risks were implemented in tests: output-root safety, no
  canonical packet writes, no real artifact writes, exact assembler shape,
  source-lock/source-id binding, placeholder rejection, and total gate remains
  red.
- Bohr reviewed the remaining-gate scaffold plan read-only. His blockers were
  addressed by adding coverage for the three new generators, updating the
  work-order tests for all four scaffold commands, and explicitly testing that
  false/withheld claim boundaries are deliberate non-evidence behavior.

## Next Best Work

Continue the remaining real-evidence gates. Before collecting real evidence,
harden the broad-gate validators so canonical passing packets cannot reference
non-real-root artifacts.

Current high-priority hardening target:

- Inspect and patch the broad validators:
  - `.formowl/kg-eval/fair_external_baseline_run_validator.py`
  - `.formowl/kg-eval/human_annotation_adjudication_validator.py`
  - `.formowl/kg-eval/enterprise_multimodal_validation_validator.py`
  - `.formowl/kg-eval/production_adapter_path_validator.py`
- Their path helpers currently allow `inputs` and `results` generally. The
  assemblers enforce `inputs/*_real`, but canonical validators should also
  reject packet artifact refs outside the expected real roots.
- Add focused tests proving default/canonical validation rejects `results/`,
  `inputs/test_*`, templates, and other non-real-root artifact refs with clear
  blockers.
- Keep test fixtures from being mistaken for real evidence. Do not leave fake
  passing artifacts under `inputs/*_real/`.

Good next steps:

1. Stop adding scaffold-only work unless the operator flow is missing a
   concrete real-evidence intake contract.
2. Begin collecting and binding real evidence under the appropriate real input
   roots, but only with real user/operator-supplied artifacts:
   - `inputs/fair_baseline_real/`
   - `inputs/human_annotation_real/`
   - `inputs/enterprise_multimodal_real/`
   - `inputs/production_adapter_real/`
3. Use the work-order commands to assemble candidate packets validate-only
   before any promotion.
4. Refresh results in dependency order after changes:
   - specific validator
   - `kg_total_acceptance_suite.py`
   - `kg_objective_completion_audit.py`
   - `real_evidence_preflight.py`
   - `real_evidence_collection_work_orders.py`
5. Run dev-container tests before reporting completion.
