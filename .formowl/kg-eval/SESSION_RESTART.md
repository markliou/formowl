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

Goal status for the broad KG real-evidence acceptance objective is complete in
the current local authority state. Do not broaden this into a full product
production-readiness, top-tier scientific-validation, raw-access, or canonical
graph-write claim.

```text
完成 FormOwl Knowledge Graph 方法探索與驗收：補齊外部近期文獻比較、ontology 結合方法、不同使用者 KG 與 KG 融合實驗、多模態企業資料驗證、人工作業/標註/裁決流程、production adapter gate，並用總驗收套件清楚標示已通過與未通過項目。
```

## Current Restart Snapshot

This snapshot supersedes older "latest work" notes below when they conflict.

- Broad KG real-evidence acceptance is now clear: `overall_passed=true`, 12
  passed gates, 0 failed gates, and `remaining_gates=[]`.
- `.formowl/kg-eval/remaining_evidence_checklist.json` is synchronized with
  `.formowl/kg-eval/results/kg_total_acceptance_snapshot.json` and
  `.formowl/kg-eval/results/kg_objective_completion_audit.json`.
- Current hashes:
  - gate status:
    `9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba`
  - objective audit:
    `b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d`
- `kg_objective_completion_audit.py` reports `objective_complete=true`, 9
  proved requirements, and 0 incomplete requirements.
- `real_evidence_preflight.py` reports
  `preflight_state=validator_clear_for_all_broad_gates`, blocked gates `[]`,
  and the four historical real-evidence gates validator-clear.
- `real_evidence_collection_work_orders.py` reports
  `work_order_state=no_remaining_work_orders_all_broad_gates_clear` and
  `work_order_count=0`.
- `real_evidence_gate_progress.py` reports `gate_count=0` and
  `blocked_gate_ids=[]`.

Cleared broad real-evidence gates:

- `fair_external_baseline_comparison`: public reproducible evidence,
  validator-clear canonical packet, and four-specialist LLM subagent approval.
- `annotation_adjudication_protocol`: operator-private canonical packet,
  validator-clear status, and four-specialist LLM subagent approval without
  claiming completed human annotation.
- `multimodal_semantic_validation`: public reproducible enterprise multimodal
  evidence, validator-clear canonical packet, and four-specialist LLM subagent
  approval.
- `production_adapter_paths`: public reproducible production-adapter path
  evidence, validator-clear canonical packet, rollback/permission/audit
  evidence, and four-specialist LLM subagent approval.

Plan B result, updated 2026-06-28:

- The accepted Plan B route is
  `four_specialist_llm_subagent_adjudication_v1`, not a single generic LLM.
- The four fixed professional roles are:
  `external_baseline_methodologist`,
  `annotation_adjudication_protocol_specialist`,
  `multimodal_semantics_validation_specialist`, and
  `production_governance_adapter_specialist`.
- All four broad evidence packets that rely on Plan B now bind four distinct
  professional subagents, reviewed artifact hashes, prompt/rubric/output hashes,
  `PASS` decisions, and empty blocking findings.
- This remains LLM-subagent adjudication. It must not be represented as
  completed human adjudication.

Claim boundary:

- This clears the broad KG real-evidence acceptance objective.
- It does not claim full product production readiness, top-tier scientific
  validation, raw asset access, canonical graph writes, autonomous business
  judgment, or enterprise-scale latency/scalability.
- The main repo method suite may still report `passed_with_explicit_limits` for
  product-level limits such as `production_adapter_readiness` and
  `latency_scalability_enterprise_claims`; those limits are outside the broad
  KG real-evidence gate closure.

Current correction after user clarification:

- The durable LLM route is not "any LLM" or one generic LLM judge. Each accepted
  LLM adjudication artifact must use
  `four_specialist_llm_subagent_adjudication_v1`.
- That artifact must contain exactly four distinct professional specialist
  subagents covering `baseline_methodology`, `annotation_adjudication`,
  `multimodal_semantics`, and `production_governance`.
- Those specialties must use fixed professional roles:
  `external_baseline_methodologist`,
  `annotation_adjudication_protocol_specialist`,
  `multimodal_semantics_validation_specialist`, and
  `production_governance_adapter_specialist`.
- All four specialist subagents must independently return `PASS`, with empty
  blocking findings, professional role/model/run metadata, prompt/rubric/output
  hashes, and reviewed artifact hashes bound to the expected inputs.
- The panel must not claim human adjudication, and empty/missing real or
  candidate evidence still fails.

Current local implementation slice, updated 2026-06-28 after four-specialist
LLM panel route hardening:

- KG-eval now has a shared `four_specialist_llm_subagent_adjudication_v1`
  contract. It requires exactly four distinct specialist subagents covering
  `baseline_methodology`, `annotation_adjudication`, `multimodal_semantics`,
  and `production_governance`, with the fixed professional roles listed above.
  All four must independently return `PASS`, bind reviewed artifact hashes, use
  distinct run/prompt/output hashes, and avoid human-adjudication claims.
- The fair baseline, annotation, enterprise multimodal, and production adapter
  response-intake, packet-assembler, validator, work-order, preview-packet, and
  response-template surfaces now support the four-specialist LLM route as the
  current Plan B target. Legacy human evidence remains accepted only for
  backward compatibility where validators already support it.
- Main-repo KG acceptance wording now reports a neutral
  `review_adjudication_claim_boundary` item instead of treating completed human
  review as the target. The report still does not claim completed legacy human
  labels or completed four-specialist LLM panel decisions.
- Verification passed in the dev container: KG-eval unittest 577 OK; main repo
  unittest 252 OK; full Ruff check and format-check; response-template,
  operator-guide, submission-template, approval-template, and progress checks;
  refreshed total acceptance, objective audit, preflight, work orders, and gate
  progress. Main KG acceptance default remains `passed_with_explicit_limits`;
  strict still exits 1 only for the known
  `production_adapter_readiness`/`latency_scalability_enterprise_claims`
  limits.
- Broad KG-eval remains incomplete: `overall_passed=false`, 10 passed gates,
  and 2 failed gates. The remaining failed gates are still at
  `missing_operator_response` with empty remaining real roots, zero candidate
  manifests, zero clear validation reports, zero valid approvals, and absent
  remaining canonical broad packets.
- User-requested four-professional-subagent reviewer gate passed 4/4 for this
  slice: baseline methodology, annotation adjudication, multimodal semantics,
  and production governance reviewers all returned `RELEASE_DECISION: AGREE`
  with no blocking findings. This review result covers the Plan B route
  hardening only; it does not make the broad real-evidence gates pass.

Current local evidence state, updated 2026-06-28 after annotation promotion:

- `annotation_adjudication_protocol` is now validator-clear. The canonical
  packet exists at `inputs/human_annotation_results_v1.json` and binds
  operator-private annotation/adjudication material plus a four-specialist LLM
  subagent panel. It does not claim completed human annotation.
- The remaining broad failed gates are only `multimodal_semantic_validation`
  and `production_adapter_paths`.
- `kg_total_acceptance_snapshot.json` reports `passed_gate_count=10`,
  `failed_gate_count=2`, `overall_passed=false`, and
  `gate_status_sha256=7aaca410e3849053f895ec1cf7c03b5ced1b62cdad0e95030a56bfed42ac0468`.
- `kg_objective_completion_audit.json` reports `proved_requirement_count=7`,
  `incomplete_requirement_count=2`, and
  `audit_sha256=d6282bc8529c2f4dbf82dbf41789419a54c72b695fd79ae3f3e87254dea86ce2`.
- Next gate-changing work should target one of the two remaining response
  packets through `operator_private` or `public_reproducible` evidence mode,
  then run response preflight, candidate intake, validate-only assembly,
  governance approval, approved promotion, validators, and total acceptance.

Current local implementation slice, updated 2026-06-28 after operator
submission-manifest response-preflight runner:

- `real_evidence_submission_manifest.py --preflight-responses` now runs the
  four response-intake helper `--preflight-response` commands from a validated
  operator-filled submission manifest.
- The runner requires existing response packets, uses fixed manifest-derived
  argv with no shell, refuses pre-existing canonical broad-packet path hazards
  before subprocess launch, stops on the first failed response preflight, and
  fails closed if final-state canonical packet or response-output surfaces
  change.
- Claim boundary: it reads response-packet contents only through the existing
  preflight helpers, writes no candidate artifacts, writes no candidate
  manifest, promotes no evidence, writes no canonical broad packets, and does
  not count as an acceptance gate.
- Canonical dev-container verification passed:
  - focused submission/guide unittest ran 63 tests OK.
  - full KG-eval unittest ran 531 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide, submission-template, approval-template, response-template,
    and progress checks exited 0.
  - broad reports were refreshed; default main KG acceptance remains
    `passed_with_explicit_limits`, and strict main KG acceptance exits 1 only
    for known limits.
  - full Ruff check passed and Ruff format-check reported 207 files already
    formatted.
- Reviewer gate passed 3/3: `Huygens`, `Gauss`, and `Ohm` returned
  `RELEASE_DECISION: AGREE` after Huygens' direct canonical-drift test
  suggestion was implemented.
- Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed gates,
  and the same four failed gates. `real_evidence_gate_progress.py` still
  reports all four gates at `missing_operator_response`, with zero candidate
  manifests, zero clear validation reports, zero valid approvals, empty real
  roots, and absent canonical broad packets. No completion claim is supported.

Current local implementation slice, updated 2026-06-28 after operator
response-packet preflight:

- The four candidate-only response-intake CLIs now support
  `--preflight-response`:
  - `fair_baseline_response_intake.py`
  - `human_annotation_response_intake.py`
  - `enterprise_multimodal_response_intake.py`
  - `production_adapter_response_intake.py`
- Response preflight validates the operator response packet shape, work-packet
  binding, output-dir/operator-run-id binding, optional candidate-manifest
  output path, planned artifact surface, raw/internal field guards, and
  no-overwrite/parent-dir surfaces without writing candidate artifacts,
  candidate manifests, or canonical packets.
- Reviewer blocker fix: enterprise-multimodal and production-adapter intake now
  reject forged same-type work packets even when artifact-boundary booleans are
  false by comparing the generated work-packet state, roots, canonical target,
  collection plans, validator expectation, and `work_packet_sha256`.
- The submission-manifest intake plan now lists paired
  `preflight_command`/`preflight_argv` rows alongside the existing
  candidate-only intake commands. The tracked work orders and operator guide
  now direct operators to run response preflight before candidate intake.
- Claim boundary: this slice accepts no evidence, promotes no evidence, writes
  no canonical broad packets, does not run candidate validators during
  preflight, and does not count as an acceptance gate.
- Canonical dev-container verification passed:
  - focused response-intake/submission/work-order/operator-guide unittest ran
    162 tests OK.
  - full KG-eval unittest ran 524 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check`, submission template `--check-template`, refreshed
    broad reports, full Ruff check, Ruff format-check, and `git diff --check`
    exited 0.
- Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed gates,
  and the same four failed gates. `real_evidence_gate_progress.py` still
  reports all four gates at `missing_operator_response`, with zero candidate
  manifests, zero clear validation reports, zero valid approvals, empty real
  roots, and absent canonical broad packets. No completion claim is supported.
- Reviewer gate passed 3/3: `Euler` agreed on engineering correctness,
  `Nash` agreed after the enterprise/production work-packet binding blocker
  was fixed and re-reviewed, and `Beauvoir` agreed on status honesty.

Current local implementation slice, updated 2026-06-28 after operator
response-packet template generation:

- Added `real_evidence_response_packet_templates.py` and four tracked
  non-evidence response-packet templates:
  - `work_packets/fair_baseline_response_packet.template.json`
  - `work_packets/human_annotation_response_packet.template.json`
  - `work_packets/enterprise_multimodal_response_packet.template.json`
  - `work_packets/production_adapter_response_packet.template.json`
- The templates are operator-fillable starting shapes for the first missing
  response packets. They are generated from validator constants for required
  fair-baseline systems, enterprise modalities, and production adapter
  components where applicable.
- They deliberately carry `template_only`, `do_not_submit_as_evidence`,
  `gate_id`, false claim-boundary fields, and operator instructions. Focused
  tests prove all four templates are rejected by response-intake helpers as-is
  without candidate artifact, candidate manifest, or canonical packet writes.
- The tracked operator guide now lists the response templates and
  `python3 real_evidence_response_packet_templates.py --check-templates`.
- Canonical dev-container verification passed:
  - focused response-template/operator-guide unittest ran 11 tests OK.
  - full KG-eval unittest ran 517 tests OK.
  - main repo unittest ran 252 tests OK.
  - response-template, operator-guide, submission-template, approval-template,
    and progress checks exited 0.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Reviewer gate passed 3/3: `Euclid` agreed on engineering correctness,
  `Schrodinger` agreed on governance/safety, and `Franklin` agreed on status
  honesty.
- Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates. All four real roots remain empty and
  the four canonical broad packets remain absent. No completion claim is
  supported.

Current local implementation slice, updated 2026-06-28 after
enterprise-multimodal response-intake parity hardening:

- `enterprise_multimodal_response_intake.py` now rejects the same broader
  raw/internal field-name surface as the other hardened candidate-only intake
  paths, including backend connection-string, database/object-store, raw SQL,
  raw path, and worker scratch field names with otherwise benign values.
- Custody receipt construction, optional assembly-manifest hashing, custody
  write, and custody receipt hashing now run inside rollback handling. If
  custody hashing or custody write fails after candidate outputs are created,
  intake-created candidate artifacts and optional candidate manifests are
  removed.
- The enterprise work-order response contract and tracked operator guide now
  list output-dir binding, top-level/validation wrapper allowlisting,
  raw/internal field-name rejection, parent-dir preflight, after-open cleanup,
  rollback, and optional manifest custody hashing.
- Canonical dev-container verification passed:
  - focused enterprise-intake/work-order/operator-guide unittest ran 47 tests
    OK.
  - full KG-eval unittest ran 514 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check` and progress report `--check` exited 0.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Reviewer gate passed 3/3: `Socrates` agreed on engineering correctness,
  `Gibbs` agreed on governance/safety, and `Pascal` agreed on status honesty.
- Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates. All four real roots remain empty and
  the four canonical broad packets remain absent. No completion claim is
  supported.

Current local implementation slice, updated 2026-06-28 after gate-progress
report:

- Added `real_evidence_gate_progress.py` and focused tests for a compact,
  non-authoritative progress report over the four remaining real-evidence
  gates.
- The report maps each gate to an explicit collection stage:
  `missing_operator_response`,
  `candidate_artifacts_present_without_manifest`,
  `candidate_manifest_present_pending_validation`,
  `candidate_validation_failed_or_stale`,
  `candidate_validation_clear_pending_approval`,
  `approval_valid_pending_promotion`,
  `canonical_packet_present_needs_validator_clear`, or
  `canonical_packet_validator_clear`.
- It reads persisted preflight/work-order reports plus safe direct
  `work_packets/` surfaces for candidate manifests, candidate-validation
  reports, and approval manifests. It does not refresh preflight, read
  operator response packets, read candidate artifact contents, write candidate
  artifacts, promote evidence, write canonical packets, replace authoritative
  validators, or count as an acceptance gate.
- The tracked operator guide now includes the progress-report refresh and
  `--check` commands.
- Current refreshed progress still reports all four gates at
  `missing_operator_response`; candidate manifest count, clear validation
  count, valid approval count, and canonical validator clear count are all
  `0`. All four real roots remain empty and the four canonical broad packets
  remain absent.
- Canonical dev-container verification after reviewer blocker fixes passed:
  - focused progress/operator-guide unittest ran 20 tests OK.
  - full KG-eval unittest ran 512 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check` and progress report `--check` exited 0.
  - broad reports were refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`,
    `real_evidence_collection_work_orders.py`, and
    `real_evidence_gate_progress.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Reviewer gate passed 3/3: `Plato` agreed on status honesty after the
  stage-label docs were completed, `Carson` agreed after the
  candidate-manifest symlink/hardlink hash-current blocker was fixed, and
  `Russell` agreed after source-report contract withholding plus rejected
  approval-surface reporting were added.
- No completion claim is supported.

Current local implementation slice, updated 2026-06-28 after governed approval
promotion failure rollback:

- `real_evidence_governance_approval.py --execute-approved-promotion` now
  removes a target canonical broad packet if an approved promotion subprocess
  fails after creating that target packet.
- The rollback path is covered for nonzero subprocess return, subprocess
  `OSError`, and the assembler hard-link promotion window where the target
  canonical packet exists as a `hardlink_alias` before the temporary file is
  removed.
- The execution report now exposes `subprocess_error` and
  `rollback_after_failed_promotion` alongside the existing
  candidate-manifest-drift rollback result.
- The tracked operator guide now states that failed approved promotion removes
  the newly created target packet before reporting failure.
- Reviewer gate passed 3/3 for this slice after Pasteur's hardlink-alias
  rollback blocker was fixed and re-reviewed: `Chandrasekhar` agreed on
  engineering correctness, `Pasteur` agreed after the blocker fix, and
  `Locke` agreed on status honesty.
- Canonical dev-container verification passed in this resume after the
  hardlink-alias rollback fix:
  - focused approval/operator-guide/submission unittest ran 68 tests OK.
  - full KG-eval unittest ran 500 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check`, governance approval template `--check-template`,
    and submission template `--check-template` exited 0.
  - broad reports were refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Safety state after verification: all four `inputs/*_real` roots contain no
  files, the four canonical broad evidence packets remain absent, preflight
  reports no packet or artifact hazards, and broad KG-eval still shows
  `overall_passed=false`, 8 passed gates, and the same four failed gates.
- No completion claim is supported.

Current local implementation slice, updated 2026-06-28 after human annotation
response-intake hardening:

- `human_annotation_response_intake.py` now requires a top-level
  response-packet allowlist, `operator_run_id`, and output-dir final-segment
  binding before candidate artifacts are written.
- First-pass and adjudication response rows now reject unsupported fields and
  raw/internal field names such as raw paths, storage/database URIs, raw SQL,
  and worker scratch references.
- Candidate artifact writes now preflight parent directories, reject nested
  default real-root output dirs, clean up after-open partial writes, and roll
  back already-created candidate artifacts plus optional candidate manifests
  when assembly or validation execution raises after writes. A completed
  validate-only report with `passed=false` remains candidate-only evidence
  state, not canonical evidence.
- The intake now writes a non-authoritative response custody receipt that
  binds the operator response packet hash, candidate packet hash, emitted
  candidate artifact hashes, and optional candidate-manifest hash. This
  receipt is candidate-only and is not the canonical human annotation packet.
- The tracked operator guide now lists the hardened human response-intake
  controls for `annotation_adjudication_protocol`.
- Canonical dev-container verification passed in this resume:
  - focused human-intake/work-order/operator-guide unittest ran 48 tests OK.
  - full KG-eval unittest ran 482 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check` and submission template `--check-template`
    exited 0.
  - broad reports were refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`.
  - full Ruff check passed and Ruff format-check reports 203 files already
    formatted.
- Safety state after verification: all four `inputs/*_real` roots contain no
  files, the four canonical broad evidence packets remain absent, and broad
  KG-eval still shows `overall_passed=false`, 8 passed gates, and the same
  four failed gates. No completion claim is supported.
- Reviewer gate passed 3/3 for this slice: `Socrates` agreed on engineering
  correctness, `Gibbs` agreed on governance/safety after the validation-report
  wording was narrowed, and `Pascal` agreed on status honesty after the same
  wording update.

Current local implementation slice, updated 2026-06-28 after fair-baseline
response-intake hardening:

- `fair_baseline_response_intake.py` now requires response-packet top-level
  allowlisting, `operator_run_id`, and output-dir final-segment binding before
  candidate artifacts are written.
- Baseline-run rows, human-answer adjudication rows, graph-quality rows, and
  permission-probe rows reject unsupported wrapper fields, and raw/internal
  field names are rejected throughout the response payload.
- Candidate artifact writes now preflight parent directories, reject nested
  default real-root output dirs outside tests, clean up after-open partial
  writes, and roll back already-created candidate artifacts plus optional
  candidate manifests when assembly or validation execution raises after
  writes.
- The intake still writes only non-authoritative candidate artifacts and a
  response custody receipt that binds the operator response packet hash,
  candidate packet hash, emitted candidate artifact hashes, and optional
  candidate-manifest hash. This receipt is candidate-only and is not the
  canonical fair-baseline packet.
- The tracked operator guide now lists the hardened fair-baseline response
  intake controls for `fair_external_baseline_comparison`.
- Canonical dev-container verification passed in this resume:
  - focused fair-intake/work-order/operator-guide unittest ran 46 tests OK.
  - full KG-eval unittest ran 490 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check`, submission template `--check-template`, and
    governance approval template `--check-template` exited 0.
  - broad reports were refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Safety state after verification: all four `inputs/*_real` roots contain no
  files, the four canonical broad evidence packets remain absent, and broad
  KG-eval still shows `overall_passed=false`, 8 passed gates, and the same
  four failed gates. No completion claim is supported.
- Reviewer gate passed 3/3 after blocker fixes: `Arendt` agreed on
  engineering correctness after the final delta, `Confucius` agreed on
  governance/safety after the work-order report stopped emitting an absolute
  local workspace path, and `Lorentz` agreed on status honesty after the
  operator guide/control inventory listed parent-dir preflight, after-open
  cleanup, and rollback controls.

Current local implementation slice, updated 2026-06-28 after production-adapter
response-intake parity hardening:

- `production_adapter_response_intake.py` now rejects raw/internal field names
  throughout operator-supplied artifact payloads, including database,
  object-store, raw SQL, bucket/object key, backend connection-string, and
  worker scratch field names whose values are otherwise benign.
- Candidate artifact writes now remove files created by exclusive open if JSON
  serialization or writing fails after open, preventing empty or partial
  candidate artifacts from remaining after a failed intake.
- Raw `OSError` write failures from the intake write path are caught by the
  rollback scope, so earlier candidate artifacts and optional candidate
  manifests are cleaned up instead of being left behind.
- `OSError` failures while building the custody receipt from artifact or
  optional manifest hashes are also caught by the rollback scope, so already
  created candidate outputs are not left behind if custody construction fails.
- Focused tests now cover raw/internal field-name rejection, assembler-failure
  rollback of already-created artifacts and optional manifests, backend
  connection-string field-name rejection, raw `OSError` rollback,
  custody-phase hash failure rollback, and after-open OSError/TypeError
  cleanup.
- The production work-order response contract and tracked operator guide now
  list output-dir binding, top-level/adapter wrapper allowlisting, parent-dir
  preflight, after-open cleanup, rollback, raw/internal field-name rejection,
  and optional manifest custody hashing.
- Canonical dev-container verification passed in this resume:
  - focused production-intake/work-order/operator-guide unittest ran
    47 tests OK.
  - full KG-eval unittest ran 497 tests OK.
  - main repo unittest ran 252 tests OK.
  - operator guide `--check`, submission template `--check-template`, and
    governance approval template `--check-template` exited 0.
  - broad reports were refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
  - full Ruff check passed, Ruff format-check passed, and `git diff --check`
    exited 0.
- Safety state after verification: all four `inputs/*_real` roots contain no
  files, the four canonical broad evidence packets remain absent, and broad
  KG-eval still shows `overall_passed=false`, 8 passed gates, and the same
  four failed gates. No completion claim is supported.
- Reviewer gate passed 3/3:
  - Heisenberg agreed on status honesty after the restart note stopped
    claiming commit/push readiness.
  - Curie agreed after backend connection-string field-name rejection was
    added.
  - Raman agreed after raw write and custody-phase rollback gaps were fixed.

Current local implementation slice, updated 2026-06-28 after governed
approval-bridge hardening:

- Added `real_evidence_governance_approval.py`, focused tests, and the tracked
  non-evidence approval template
  `work_packets/remaining_real_evidence_governance_approval.template.json`.
- The approval runner validates an operator-filled approval manifest under
  `work_packets/` before any canonical packet update. Validation requires the
  exact manifest type and field set, a human approver id, exact
  `approval_scope` and `claim_boundary`, current candidate validation report
  hash, current candidate manifest hash, a passing target-gate row, exact
  validate-only assembler argv, safe report/manifest naming, a missing target
  canonical packet, and a hazard-free canonical packet baseline.
- Execute mode uses fixed assembler argv with `--promote` and
  `--assembly-manifest-sha256 <approved-candidate-manifest-sha256>`, so the
  manifest bytes consumed by the assembler must match the human-reviewed
  approval. It still rehashes the candidate manifest after the subprocess,
  checks that only the target canonical packet changed, and rolls back a newly
  created target packet when candidate-manifest drift is detected.
- The four packet assemblers now promote through a temporary file plus atomic
  no-overwrite hard link instead of direct `write_text()`, and their CLI
  manifest loaders reject bytes that do not match an optional approved
  `--assembly-manifest-sha256` guard before any assembly or promotion.
- `real_evidence_submission_manifest.py --validate-candidate-manifests` now
  records `candidate_manifest_sha256` in each candidate validation report row,
  and canonical packet surface checks now reject parent symlinks, missing
  parents, metadata-unavailable parents, and non-directory parents.
- The tracked operator guide documents the approval-template check,
  validation, and `--execute-approved-promotion` flow without exposing raw
  assembler `--promote` as the normal operator path.
- Canonical dev-container verification passed in this resume:
  - focused approval/assembler/operator-guide unittest ran 78 tests OK after
    the approved-manifest hash guard fix.
  - approval template, operator guide, and submission template checks exited 0.
  - full KG-eval unittest ran 474 tests OK.
  - main repo unittest ran 252 tests OK.
  - full Ruff check passed.
  - full Ruff format-check passed with 203 files already formatted.
  - broad reports refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`.
- Safety state after verification: all four `inputs/*_real` roots contain no
  files, and the four canonical broad evidence packets remain absent.
- Refreshed broad KG-eval still shows `overall_passed=false`, 8 passed gates,
  and the same four failed gates. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
- Reviewer gate passed 3/3 for this approval bridge slice after Bernoulli's
  candidate-manifest TOCTOU blocker was fixed and re-reviewed. Final agreeing
  reviewers: `Bernoulli`, `Popper`, and `Dalton`.
- No completion claim is supported.

Current local implementation slice, updated 2026-06-28 after candidate-runner
pre-existing canonical packet hazard hardening:

- `real_evidence_submission_manifest.py --execute-candidate-intakes` and
  `--validate-candidate-manifests` now inspect the canonical broad packet
  baseline before launching intake or validate-only subprocesses.
- If any canonical packet path is already a symlink, hardlink alias,
  non-regular file, or unreadable / metadata-unavailable surface, the runner
  fails closed with `executed_gate_count=0`.
- The refusal path reports `canonical_packet_baseline`, reads no response
  packet or candidate manifest contents, writes no candidate artifacts,
  promotes no evidence, and writes no canonical broad packets.
- The tracked operator guide documents this boundary.
- Canonical dev-container verification passed:
  - focused submission/guide unittest ran 55 tests OK.
  - full KG-eval unittest ran 460 tests OK.
  - main repo unittest ran 252 tests OK.
  - broad reports refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - `real_evidence_operator_guide.py --check` exited 0.
  - `real_evidence_submission_manifest.py --check-template` exited 0.
  - full Ruff check passed.
  - full Ruff format-check passed with 201 files already formatted.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
  - `git diff --check` exited 0.
- Refreshed broad KG-eval still shows `overall_passed=false`, 8 passed gates,
  and the same four failed gates. No completion claim is supported.
- Reviewer gate passed 3/3: `Wegener` agreed on engineering correctness after
  the canonical packet test helper was changed to preserve pre-existing path
  surfaces by rename; `Feynman` agreed on governance/safety; and `Kuhn` agreed
  on status honesty.

Current local implementation slice, updated 2026-06-28 after candidate-runner
canonical packet integrity hardening:

- `real_evidence_submission_manifest.py --execute-candidate-intakes` and
  `--validate-candidate-manifests` now snapshot the four canonical broad input
  packet paths before running subprocesses.
- If a candidate-only intake helper or validate-only assembler subprocess exits
  with a canonical packet path created or changed, the runner reports
  `canonical_packet_integrity`, marks the row failed, sets
  `overall_success=false`, and stops immediately.
- This is final-state surface integrity, not a live audit of transient
  write-and-restore behavior; the tracked operator guide documents that
  boundary.
- This slice accepts no evidence, promotes no evidence, writes no canonical
  broad packets, and does not count as acceptance.
- Canonical dev-container verification passed:
  - focused submission/guide unittest ran 51 tests OK.
  - full KG-eval unittest ran 456 tests OK.
  - main repo unittest ran 252 tests OK.
  - broad reports refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - `real_evidence_operator_guide.py --check` exited 0.
  - `real_evidence_submission_manifest.py --check-template` exited 0.
  - full Ruff check passed.
  - full Ruff format-check passed with 201 files already formatted.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits.
- Reviewer gate passed 3/3: `Sagan`, `Hooke`, and `Laplace` returned
  `RELEASE_DECISION: AGREE`; mistaken no-op `Banach` is not counted.
- Refreshed broad KG-eval still shows `overall_passed=false`, 8 passed gates,
  and the same four failed gates. No completion claim is supported.

Current local implementation slice, updated 2026-06-28 after work-order
disappeared-file contract hardening:

- Follow-up work-order contract hardening now threads
  `disappeared_file_count` into `real_evidence_collection_work_orders.py`.
  Per-gate preflight contract checks now require the field to be a non-bool
  integer and require `disappeared_file_count == 0` before the work-order
  report treats current missing evidence as cleanly visible. Normal work
  orders are withheld if a preflight row has disappeared real-root files,
  missing/malformed disappeared-file counts, or any other per-gate contract
  drift.
- The work-order `preflight_snapshot` now includes
  `real_root_disappeared_file_count`, and the tracked operator guide was
  regenerated after the work-order report schema/hash changed.
- Reviewer blocker fix: real-root scanning now uses `lstat()` before file-type
  classification, so a path that disappears before the old `is_file()` check
  is reported through `disappeared_file_count` instead of being silently
  treated as clean absence.
- This follow-up accepts no evidence, writes no candidate artifacts, promotes
  no evidence, writes no canonical broad packets, and does not count as
  acceptance.
- Canonical dev-container verification for this follow-up has now passed:
  - focused current-slice KG-eval unittest ran 79 tests OK.
  - full KG-eval unittest ran 454 tests OK.
  - main repo unittest ran 252 tests OK.
  - broad reports refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - `real_evidence_operator_guide.py --check` exited 0.
  - `real_evidence_submission_manifest.py --check-template` exited 0.
  - full Ruff check passed.
  - full Ruff format-check passed with 201 files already formatted.
  - default main KG acceptance remains `passed_with_explicit_limits`.
  - strict main KG acceptance exits 1 only for known failed / blocked limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`.
  - `git diff --check` exited 0.
- Refreshed broad KG-eval still shows `overall_passed=false`, 8 passed gates,
  and the same four failed gates. Work-board unchecked engineering item count
  remains 9.
- Reviewer gate passed 3/3 after blocker fixes: `Curie` agreed on engineering
  correctness after the `lstat()` disappearance-race fix, `Erdos` agreed on
  governance/safety and durable status after docs were updated, and `Hume`
  agreed on durable status honesty.
- The slice was committed and pushed on `complete-slice-1` as `8fc5a55`
  (`Harden KG real-evidence preflight work orders`). Follow-up status-doc
  checkpoints may sit on top of that reviewed hardening slice.
- No completion claim is supported.

The older checkpoints below are historical pre-authorization state unless they
are repeated in the current verified slice above.

- `real_evidence_preflight.py` now treats files that disappear during
  `inputs/*_real` scanning as unstable non-evidence. The scanner records
  `disappeared_file_count` and `disappeared_file_paths`, does not count those
  paths as files or candidate artifacts, keeps `root_ready=false`, and marks
  the hazard summary non-clear.
- This prevents a concurrent operator/test cleanup race from crashing preflight
  or accidentally accepting a transient file as evidence.
- This slice accepts no evidence, writes no candidate artifacts, promotes no
  evidence, writes no canonical broad packets, and does not count as
  acceptance.
- Host-level verification in this resume:
  - focused `test_real_evidence_preflight.py` ran 18 tests OK.
  - focused `test_real_evidence_submission_manifest.py` ran 41 tests OK.
  - full KG-eval unittest ran 452 tests OK.
  - main repo unittest ran 252 tests OK with `PYTHONPATH=python`.
  - broad reports refreshed with `kg_total_acceptance_suite.py`,
    `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`.
  - `real_evidence_operator_guide.py --check` exited 0.
  - `real_evidence_submission_manifest.py --check-template` exited 0.
  - host main KG acceptance default remains `passed_with_explicit_limits`;
    strict exits 1 only for the known `production_adapter_readiness` failed
    item and `latency_scalability_enterprise_claims` blocked item.
- Refreshed broad KG-eval reports still show the same blocked state:
  8 passed gates, 4 failed gates, empty real roots, absent canonical broad
  evidence packets, and zero disappeared-file hazards in the current scan.
- Host `ruff` is unavailable and dev-container/Git/network escalations were
  rejected by the environment in this resume, so canonical dev-container
  verification, commit, push, and reviewer gate remain pending.
- No completion claim is supported.

Historical blocked audit, updated 2026-06-28:

- The same external blocker has repeated across continuation turns. Canonical
  dev-container Docker verification was rejected by the approval reviewer and
  may not be worked around. Reviewer gate and commit/push cannot proceed
  without canonical verification plus escalated Git/network access. The four
  broad real-evidence gates also still require real operator/user-supplied
  evidence packets.
- Host-only checks are clean but are supplemental only under repo rules.
- Resume only after the user/environment provides the required Docker/Git
  permissions and real evidence artifacts, or explicitly changes the
  verification policy.

Resume authorization and post-push state, updated 2026-06-28:

- The user explicitly authorized collecting failed-gate evidence,
  Docker/dev-container access, and Git commit/push. Treat the prior Docker/Git
  approval blocker as cleared for this run.
- The current hardening slice has passed canonical dev-container verification,
  passed the configured 3 Codex/GPT reviewer gate, and was pushed as `8fc5a55`
  on `complete-slice-1`.
- The broad KG objective remains incomplete. Report-based failed-gate evidence
  may be collected, but the four broad gates still cannot pass without real
  operator/user-supplied artifacts and governed canonical packets accepted by
  validators.

Current local implementation slice, updated 2026-06-28 after intake-plan
partial-write hardening:

- `real_evidence_submission_manifest.py --emit-intake-plan` now writes the
  ignored non-evidence intake plan through the same temporary-file plus atomic
  no-overwrite link pattern used for candidate-validation reports.
- Interrupted intake-plan writes no longer leave a final partial JSON plan or
  a temporary partial file for operators to follow.
- This slice writes no candidate artifacts, promotes no evidence, writes no
  canonical broad packets, and does not count as acceptance.
- Host-level verification in this resume:
  - focused `test_real_evidence_submission_manifest.py` ran 41 tests OK.
  - full KG-eval unittest ran 451 tests OK.
  - main repo unittest ran 252 tests OK with `PYTHONPATH=python`.
  - `real_evidence_operator_guide.py --check` exited 0 after regeneration.
  - `real_evidence_submission_manifest.py --check-template` exited 0.
  - host main KG acceptance default remains `passed_with_explicit_limits`.
  - host main KG acceptance strict exits 1 for the known
    `production_adapter_readiness` failed item and
    `latency_scalability_enterprise_claims` blocked item.
- Host `ruff` is unavailable and dev-container/Git/network escalations were
  rejected by the environment in this resume, so canonical dev-container
  verification, commit, push, and reviewer gate remain pending.
- Refreshed broad KG-eval reports still show the same blocked state:
  8 passed gates, 4 failed gates, empty real roots, and absent canonical broad
  evidence packets.
- No completion claim is supported.

Status-only resume checkpoint, updated 2026-06-28 after the user asked for
remaining engineering-item count:

- Branch `complete-slice-1` is aligned with `origin/complete-slice-1`, and the
  worktree was clean before this checkpoint update.
- Work-board unchecked engineering item count remains 9: 1 KG-owned full
  real-evidence objective and 8 System Backbone/product-infra items.
- Dev-container verification completed in this resume:
  - KG-eval unittest ran 450 tests OK.
  - Main repo unittest ran 252 tests OK.
- A later dev-container report refresh command was rejected by the approval
  reviewer because it required unsandboxed Docker socket access with workspace
  writes. Do not treat that rejection as a test failure; treat it as an
  environment permission limit for this resume.
- Sandbox host-level supplemental report commands exited 0 and still show the
  same blocked state. These are not canonical completion evidence.
- Host `ruff` is unavailable in this environment, so lint/format was not
  rerun in this resume. Use the previous dev-container Ruff pass below as the
  latest canonical lint evidence.
- Safety checks found no files under the four `inputs/*_real` roots and no
  canonical broad evidence packets.
- No completion claim is supported.

Current execution checkpoint, updated 2026-06-28 after intake-plan output path
hardening:

- Local Git state has an intake-plan output path guard slice staged for review
  on `complete-slice-1`.
- `real_evidence_submission_manifest.py --emit-intake-plan` now rejects nested
  `work_packets/...` output paths; intake plans must be safe direct children of
  `work_packets/`, matching the ignored operator work-packet surface used by
  candidate-validation reports.
- Focused tests now cover nested intake-plan output rejection.
- This slice writes no candidate artifacts, promotes no evidence, writes no
  canonical broad packets, and does not count as acceptance.
- Dev-container KG-eval commands rerun against current state:
  - `python kg_total_acceptance_suite.py`
  - `python kg_objective_completion_audit.py`
  - `python real_evidence_preflight.py`
  - `python real_evidence_collection_work_orders.py`
  - `python -m unittest discover -s . -p 'test_*.py'`
  - `python real_evidence_operator_guide.py --check`
  - `python real_evidence_submission_manifest.py --check-template`
- Dev-container main-repo commands rerun against current state:
  - `python -m unittest discover -s tests`
  - `python scripts/kg_research_acceptance_suite.py`
  - `python scripts/kg_research_acceptance_suite.py --strict`
  - `ruff check python tests scripts .formowl/kg-eval`
  - `ruff format --check python tests scripts .formowl/kg-eval`
- Verification result:
  - KG-eval reports exited 0.
  - KG-eval unittest ran 450 tests OK.
  - Focused `test_real_evidence_submission_manifest.py` ran 40 tests OK in the
    dev container.
  - Operator guide check and submission-template check exited 0.
  - Main repo unittest ran 252 tests OK.
  - Default main KG acceptance remains `passed_with_explicit_limits`.
  - Strict main KG acceptance still exits nonzero for known limits:
    `production_adapter_readiness` failed and
    `latency_scalability_enterprise_claims` blocked.
  - Full Ruff lint passed.
  - Full Ruff format-check passed: `201 files already formatted`.
- Refreshed broad KG-eval remains incomplete:
  `overall_passed=false`, `passed_gate_count=8`, `failed_gate_count=4`.
  Failed gates remain exactly:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
- Objective audit remains `objective_complete=false`, with 5 proved
  requirements and 4 incomplete requirements.
- Real-evidence preflight reports all four remaining gates blocked:
  fair baseline has 5 blockers, human annotation has 3, multimodal has 4, and
  production adapter has 4.
- All four real roots have no files, the four canonical broad packets are
  absent, and preflight reports no packet or artifact hazards.
- Work-board unchecked engineering item count remains 9: 1 KG-owned full
  real-evidence objective and 8 System Backbone/product-infra items.
- Reviewer gate passed 3/3: `Anscombe` agreed on engineering path safety,
  `Epicurus` agreed on governance and non-evidence boundaries, and `Ptolemy`
  agreed on durable docs/status honesty.
- No completion claim is supported.

Previous local implementation slice, updated 2026-06-28 after candidate-intake
execution runner hardening:

- `real_evidence_submission_manifest.py` now supports explicit
  `--execute-candidate-intakes` for a validated operator-filled submission
  manifest.
- The runner validates the manifest first, requires existing response packets,
  rejects path-only execution mode, builds fixed argv for the four existing
  candidate-only intake helpers, runs them with `subprocess.run` and no shell,
  stops on the first failed intake, and reports partial-execution policy.
- This execution mode may read operator response packet contents and write
  candidate artifacts through the existing intake helpers. It never passes
  promotion flags, promotes evidence, writes canonical broad packets, or counts
  as an acceptance gate.
- Candidate artifacts from earlier successful intake commands remain for
  operator review; this runner does not automatically promote or roll them
  back.
- The tracked operator guide documents the controlled runner and states that
  manual governance plus validator acceptance remain required before any broad
  gate can pass.
- Verification passed:
  - host focused submission/guide unittest 33 OK
  - dev-container focused submission/guide unittest 33 OK
  - dev-container full KG-eval unittest 435 OK
  - dev-container main repo unittest 252 OK
  - dev-container operator guide `--check`
  - dev-container submission template `--check-template`
  - dev-container changed-file Ruff check and format-check
  - refreshed `kg_total_acceptance_suite.py` and `real_evidence_preflight.py`
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. All four real roots remain
  empty and the four canonical broad packets remain absent.
- GPT/Codex reviewer gate passed 3/3 with `Nash`, `Pauli`, and `Locke`.
  `Hegel` found a blocker in the module docstring/help claim boundary; it was
  fixed with focused assertions and re-reviewed by replacement reviewer
  `Locke` because the original Hegel agent could not accept follow-up input.
  Non-counted agents: `Pascal` was a no-op accidental spawn; `Sagan`,
  `Bernoulli`, and `Arendt` were accidentally shut down before returning
  decisions; `Hegel` is blocker-only without final re-review.

Most recent local implementation slice, updated 2026-06-28 after candidate-manifest
validate-only runner hardening:

- `real_evidence_submission_manifest.py` now supports explicit
  `--validate-candidate-manifests` after candidate-only intake.
- The runner validates the operator-filled submission manifest first, requires
  the four expected emitted `work_packets/*_candidate_manifest.json` files to
  exist as safe regular non-symlink/non-hardlink files, builds fixed argv for
  the four existing assembler scripts in `--validate` mode only, runs them via
  `subprocess.run` with no shell, treats nonzero exit or
  `validation_report.passed != true` as failed, and summarizes stdout without
  echoing assembled candidate packet contents.
- This validation mode reads candidate manifests and referenced candidate
  artifacts through the assemblers. It runs no response-intake commands, writes
  no candidate artifacts, passes no `--promote`, promotes no evidence, writes
  no canonical broad packets, and does not count as an acceptance gate.
- The tracked operator guide documents the post-intake validation command and
  the claim boundary.
- Verification passed:
  - host focused submission/guide unittest 41 OK
  - dev-container focused submission/guide unittest 41 OK
  - dev-container full KG-eval unittest 443 OK
  - dev-container main repo unittest 252 OK
  - dev-container operator guide `--check`
  - dev-container submission template `--check-template`
  - dev-container full Ruff check and format-check
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance exits 1 only for known limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  All four real roots remain empty and the four canonical broad packets remain
  absent.
- GPT/Codex reviewer gate passed 3/3 with `Einstein`, `Sartre`, and
  `Heisenberg`. All three suggested direct hardlink coverage for emitted
  candidate manifests; the test was added and `Einstein` re-reviewed the final
  delta with `RELEASE_DECISION: AGREE`.

Latest local implementation slice, updated 2026-06-28 after preflight
canonical packet path-hazard hardening:

- `real_evidence_preflight.py` now detects symlink, hardlink, and non-regular
  canonical packet paths before refreshing total acceptance, objective audit,
  or per-gate validators.
- If any canonical packet path hazard exists, preflight reports
  `canonical_packet_path_hazards`, skips the total/audit/validator refreshes,
  leaves broad gates blocked, and avoids reading or hashing the alias packet
  path.
- `test_real_evidence_preflight.py` covers symlink, hardlink, and non-regular
  canonical packet hazards, no-validator-run behavior under hazards,
  packet-surface state, and cleanup that preserves pre-existing packet paths.
- This slice accepts no evidence, writes no candidate artifacts, promotes no
  packets, writes no canonical broad packets, and does not count as an
  acceptance gate.
- Verification passed:
  - dev-container focused preflight unittest 17 OK
  - dev-container full KG-eval unittest 428 OK
  - dev-container main repo unittest 252 OK
  - dev-container full Ruff check and format-check
  - dev-container `real_evidence_operator_guide.py --check`
  - dev-container `real_evidence_submission_manifest.py --check-template`
  - refreshed broad reports:
    `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
    `real_evidence_preflight.py`, and
    `real_evidence_collection_work_orders.py`
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Objective audit remains
  `objective_complete=false`; all four real roots have no files, and the four
  canonical broad packets remain absent.
- GPT/Codex reviewer gate passed 3/3: `Beauvoir`, `Dewey`, and `Rawls`.
  `Beauvoir` initially blocked on total/audit refresh running before preflight
  path-hazard handling; `Dewey` initially blocked on unsafe direct canonical
  test writes and incomplete no-validator-run coverage. Both blockers were
  fixed and re-reviewed with final `RELEASE_DECISION: AGREE`. A mistakenly
  spawned no-op `Laplace` agent is not counted.

Latest local implementation slice, updated 2026-06-28:

- The four broad real-evidence validators now reject canonical input packet
  filesystem aliases before JSON parsing:
  `fair_external_baseline_run_validator.py`,
  `human_annotation_adjudication_validator.py`,
  `enterprise_multimodal_validation_validator.py`, and
  `production_adapter_path_validator.py`.
- Canonical packet inputs reject direct symlinks, hardlink aliases
  (`st_nlink > 1`), and non-regular files. The blocker is propagated through
  `validate_packet()` so reports remain failed with all claim-boundary flags
  false.
- Added `test_canonical_evidence_packet_path_guards.py`, covering symlink,
  hardlink, and directory canonical packet paths for all four validators. The
  test helper now preserves any pre-existing directory at a canonical packet
  path instead of deleting it during cleanup.
- This slice reads no response packet contents beyond the canonical packet
  path check, writes no candidate artifacts, promotes no evidence, writes no
  canonical packets, and counts as no acceptance gate.
- Verification passed:
  - host focused validator unittest 107 OK
  - dev-container focused validator unittest 107 OK
  - dev-container full KG-eval unittest 426 OK
  - dev-container main repo unittest 252 OK
  - dev-container full Ruff check and format-check
  - dev-container guide `--check`
  - dev-container submission template `--check-template`
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and
    `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  All four real roots still have no files, and the four canonical broad
  packets remain absent.
- GPT/Codex reviewer gate passed 3/3: `Nietzsche`, `Bacon`, and
  `Copernicus`. `Nietzsche` initially blocked on destructive directory cleanup
  in the test helper; the helper was fixed, directory coverage was added, and
  `Nietzsche` re-reviewed with `RELEASE_DECISION: AGREE`. A mistakenly spawned
  no-op reviewer `Averroes` is not counted.

Previous local implementation slice, updated 2026-06-28:

- Operator submission-manifest preflight now rejects hardlink aliases for the
  operator-filled `--manifest` input and for required
  `response_packet` files. Existing file checks inspect only regular-file
  existence and link count; they still do not read response packet contents.
- The tracked operator guide now warns that hardlinked operator manifests or
  response packets are rejected.
- Focused tests cover hardlink-alias manifest input and response packet
  rejection, and assert the guide warning stays present.
- This slice writes no candidate artifacts, promotes no evidence, writes no
  canonical packets, and counts as no acceptance gate.
- Verification passed:
  - host focused submission/guide unittest 26 OK
  - dev-container focused submission/guide unittest 26 OK
  - dev-container guide `--check`
  - dev-container submission template `--check-template`
  - dev-container full KG-eval unittest 423 OK
  - dev-container main repo unittest 252 OK
  - dev-container full Ruff check and format-check
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  All four real roots still have no files, and the four canonical broad
  packets remain absent.
- GPT/Codex reviewers `Confucius`, `Mendel`, and `Leibniz` returned
  `RELEASE_DECISION: AGREE`.

Previous local implementation slice, updated 2026-06-28:

- Operator submission-manifest input hardening now rejects generated
  `*_candidate_manifest.json` and `*_intake_plan.json` files as `--manifest`
  inputs. Those files are downstream non-evidence outputs and must not be fed
  back as operator-filled submission manifests.
- The tracked operator guide now warns operators not to pass candidate
  manifests or intake plans to `--manifest`.
- Focused tests cover both rejected names and assert the guide warning stays
  present.
- This slice reads no response packet contents, writes no candidate artifacts,
  promotes no evidence, writes no canonical packets, and counts as no
  acceptance gate.
- Verification passed:
  - host focused submission/guide unittest 24 OK
  - dev-container focused submission/guide unittest 24 OK
  - dev-container guide `--check`
  - dev-container submission template `--check-template`
  - dev-container full KG-eval unittest 421 OK
  - dev-container main repo unittest 252 OK
  - dev-container full Ruff check and format-check
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and `latency_scalability_enterprise_claims`
- Broad KG-eval remains incomplete: `overall_passed=false`, 8 passed gates,
  and the same four failed real-evidence gates. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  All four real roots still have no files, and the four canonical broad
  packets remain absent.
- GPT/Codex reviewers `Dirac`, `Zeno`, and `Hypatia` returned
  `RELEASE_DECISION: AGREE`. Hypatia's non-blocking guide-warning assertion
  suggestion was implemented and re-reviewed with final `AGREE`.

Previous local implementation slice, updated 2026-06-28:

- Follow-up format cleanup removed the pre-existing full Ruff format drift in
  33 Python/test/script files. This was a mechanical formatting cleanup only:
  it did not create evidence packets, did not write real artifacts, and did
  not change broad KG acceptance state.
- Dev-container verification after formatting passed:
  - `ruff check python tests scripts .formowl/kg-eval`
  - `ruff format --check python tests scripts .formowl/kg-eval`
  - full KG-eval unittest 421 OK
  - main repo unittest 252 OK
  - operator guide `--check`
  - submission template `--check-template`
  - refreshed broad KG-eval reports
  - default main KG acceptance `passed_with_explicit_limits`
  - strict main KG acceptance still exits nonzero only for known limits:
    `production_adapter_readiness` and `latency_scalability_enterprise_claims`
- Broad KG-eval remains `overall_passed=false`, 8 passed gates, and the same
  four failed broad real-evidence gates.

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
- Agy MCP route test, updated 2026-06-28: Codex tool discovery exposes no
  Antigravity/`agy` MCP tool; Codex config has no Antigravity MCP server;
  Antigravity global `mcp_config.json` is empty; this repo has no
  `.agents/mcp_config.json`; `agy --help` has no MCP server subcommand;
  `agy plugin list` has no imported plugins; and a no-repository-content
  `agy --new-project --print "/mcp"` probe from `/tmp` returned general MCP
  configuration guidance rather than an active server/tool list. Current
  conclusion: Antigravity can use MCP tools inside Antigravity sessions, but
  Codex currently has no MCP path to call Antigravity/`agy`.
- Default reviewer gate, updated 2026-06-28: use 3 Codex/GPT reviewers for
  newly completed slices unless the user explicitly changes the gate. Do not
  ask for Antigravity bounded-review authorization, and do not use `agy`
  reviewer/write delegation by default unless the user explicitly re-enables it
  after policy, platform, or MCP configuration changes.

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

Continue the remaining real-evidence gates. Historical validator path-helper
hardening is complete: the four broad validators reject canonical packet
artifact refs outside their expected `inputs/*_real` roots, including
`results/`, `inputs/test_*`, templates, and template-named artifacts under real
roots.

Current high-priority target:

- Canonical dev-container verification and the 3 Codex/GPT reviewer gate have
  passed for the current enterprise-multimodal response-intake parity hardening
  slice. The current run may commit and push this reviewed slice.
- The four broad real-evidence gates still require real operator/user-supplied
  artifacts and canonical packets accepted by their validators.
- Do not leave fake passing artifacts under `inputs/*_real/`, and do not
  promote templates, fixtures, work orders, candidate manifests, intake plans,
  or validation reports into canonical evidence packets.

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
