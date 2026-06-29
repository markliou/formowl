# Remaining KG Real-Evidence Operator Guide

Source report: `kg_real_evidence_collection_work_orders_v1`
Source report sha256: `450bba39d16a510af8d59480929cdc036e1ad2c4e7c088591c1a0454bd38c4ae`

## Authority Boundary

This guide is not an acceptance artifact. It is generated from the
non-authoritative collection work-order report so an operator can
prepare real evidence without turning templates, fixtures, or
candidate artifacts into broad KG acceptance.

- accepts evidence: False
- promotes evidence: False
- writes assembly manifests: False
- writes canonical packets: False
- counts as acceptance gate: False
- manual governance approval is still required before any canonical
  input packet can affect acceptance.

## Current Blocked Gates

- work-order state: collection_blocked_until_real_evidence_exists
- preflight state: blocked
- total acceptance state: blocked
- work-order count: 2

Blocked gate ids:

- multimodal_semantic_validation
- production_adapter_paths

## Gate Progress Report

Use the progress report when you need a compact machine-readable
summary of the current remaining gate stages before or after candidate
intake. It reads persisted preflight/work-order reports plus safe
work-packet surfaces, but it does not refresh preflight, read
operator response packets, read candidate artifact contents, write
candidate artifacts, promote evidence, write canonical packets, or
count as an acceptance gate.

Refresh the progress report:

```sh
python3 real_evidence_gate_progress.py
```

Check whether the persisted progress report is current:

```sh
python3 real_evidence_gate_progress.py --check
```

The report stages are status labels only:

- `missing_operator_response`
- `candidate_artifacts_present_without_manifest`
- `candidate_manifest_present_pending_validation`
- `candidate_validation_failed_or_stale`
- `candidate_validation_clear_pending_approval`
- `approval_valid_pending_promotion`
- `canonical_packet_present_needs_validator_clear`
- `canonical_packet_validator_clear`

A gate still requires a
validator-accepted canonical packet and the total acceptance suite
before it can count as completed.

## Submission Manifest Preflight

Before running any candidate-only intake command, fill a copy of the
submission manifest template with the operator response-packet paths,
operator run ids, candidate output dirs, and work-packet manifest
outputs. Put each response packet directly under the matching ignored
`inputs/*_real/<operator_run_id>/operator_response_packet.json` path.
Operator-filled submission manifests and generated candidate manifests
under `work_packets/` are intentionally ignored by Git; keep the
tracked template, preview packets, and this guide as the portable
non-evidence handoff.
The preflight validates path and command contracts only; it does not
read response packet contents, write candidate artifacts, promote
evidence, or write canonical packets.

Tracked non-evidence response packet templates:

```text
work_packets/fair_baseline_response_packet.template.json
work_packets/human_annotation_response_packet.template.json
work_packets/enterprise_multimodal_response_packet.template.json
work_packets/production_adapter_response_packet.template.json
```

Check that the tracked response packet templates are current:

```sh
python3 real_evidence_response_packet_templates.py --check-templates
```

Use these only as starting points. Copy a template to the matching
`inputs/*_real/<operator_run_id>/operator_response_packet.json` path,
replace every `OPERATOR_*` placeholder with real reviewed values, and
remove `template_only`, `do_not_submit_as_evidence`, `gate_id`,
`claim_boundary`, and `operator_instructions` before candidate intake.
The templates are deliberately rejected by response-intake helpers as-is.

Tracked non-evidence template:

```text
work_packets/remaining_real_evidence_submission_manifest.template.json
```

Check that the tracked template is current:

```sh
python3 real_evidence_submission_manifest.py --check-template
```

Validate the operator-filled submission manifest before intake:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json
```

Do not pass generated `*_candidate_manifest.json` files or intake-plan
JSON files back into `--manifest`; those are downstream non-evidence
outputs, not operator-filled submission manifests.
Do not hardlink operator-filled manifests or response packets to
templates, fixtures, canonical packets, generated candidate manifests,
or other files. The preflight rejects hardlink aliases.

Optionally emit a non-evidence intake execution plan from the validated manifest:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --emit-intake-plan work_packets/OPERATOR_INTAKE_PLAN.json
```

The intake plan is ignored by Git and does not execute commands. Review it before
running any listed response preflight or candidate-only intake command.
It lists paired response-preflight commands and candidate-only intake
commands for the same operator response packet paths and output dirs.

Before executing candidate-only intake, run each gate-specific
`--preflight-response` command in this guide against the exact
operator response packet and output surface. Response preflight reads
the response packet contents, validates the intake contract and planned
artifact surface, writes no candidate artifacts, writes no candidate
manifest, never passes a promotion flag, never writes canonical input
packets, and still does not count as an acceptance gate.

The validated submission manifest can also run the four response
preflight commands through one controlled non-evidence runner:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --preflight-responses
```

This response-preflight runner reads operator response-packet
contents through the existing intake preflight helpers, writes no
candidate artifacts, writes no candidate manifest, never passes a
promotion flag, never writes canonical input packets, and still does
not count as an acceptance gate. It stops on the first failed response
preflight and fails closed if a preflight helper leaves a final-state
candidate output surface or canonical packet surface changed.

After reviewing the validated manifest and optional plan, the same manifest
can execute the four candidate-only intake commands through the controlled
runner:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --execute-candidate-intakes
```

This execution mode reads operator response-packet contents and writes
candidate artifacts plus generated candidate manifests only. It stops on
the first failed intake, never passes a promotion flag, never writes canonical
input packets, and still does not count as an acceptance gate. Candidate
artifacts from earlier successful intake commands remain for operator
review and are not automatically promoted or rolled back by this runner.
The runner snapshots canonical input packet state and fails closed if
any candidate-only helper exits with a canonical packet path created
or changed. It also refuses to launch subprocesses when a canonical
input packet path is already a symlink, hardlink alias, non-regular
file, or unreadable surface.

After candidate manifests exist, validate them through the controlled
validate-only runner:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --validate-candidate-manifests
```

This validation mode reads emitted candidate manifests and their referenced
candidate artifacts through the existing assembler `--validate` commands.
It runs no response intake commands, writes no candidate artifacts, never
passes a promotion flag, never writes canonical input packets, and still
does not count as an acceptance gate.
The validate-only runner also fails closed if any assembler exits with
a canonical packet path created or changed. It refuses to launch
assembler subprocesses while any canonical input packet path is already
a symlink, hardlink alias, non-regular file, or unreadable surface.

Optionally persist that validate-only result as an ignored non-evidence
report for manual governance review:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --validate-candidate-manifests --emit-candidate-validation-report work_packets/OPERATOR_CANDIDATE_VALIDATION_REPORT_candidate_validation_report.json
```

The persisted validation report is not evidence and does not authorize
promotion by itself. It is a review aid that records the validate-only
assembler result without writing canonical input packets.

After manual governance review, fill an operator approval manifest
from the tracked non-evidence approval template. The approval manifest
must bind the candidate validation report hash, candidate manifest
hash, selected gate id, canonical packet target, and governance
approval controls.

Check that the tracked governance approval template is current:

```sh
python3 real_evidence_governance_approval.py --check-template
```

Tracked non-evidence approval template:

```text
work_packets/remaining_real_evidence_governance_approval.template.json
```

Validate the operator-filled approval manifest before any canonical
packet update:

```sh
python3 real_evidence_governance_approval.py --approval-manifest work_packets/OPERATOR_GOVERNANCE_APPROVAL.json
```

Only after that validation passes, the same approval manifest can execute
the approved canonical packet update through the governance runner:

```sh
python3 real_evidence_governance_approval.py --approval-manifest work_packets/OPERATOR_GOVERNANCE_APPROVAL.json --execute-approved-promotion
```

The approval manifest remains non-evidence and does not count as an
acceptance gate. The governance runner refuses stale hashes, unsupported
approvers, pre-existing canonical packet targets, canonical packet path
hazards, and validation reports that do not have a passing target gate
row. During execution, the runner passes the approved candidate
manifest hash to the assembler so the manifest bytes consumed for
promotion are bound to the governance approval. If execution fails
after creating the target canonical packet, the runner removes that
newly created target packet before reporting failure. After any successful
canonical packet update, rerun the specific broad validator and the
total acceptance reports.

## multimodal_semantic_validation

- work order id: collect_multimodal_semantic_validation
- requirement id: multimodal_enterprise_validation
- collection status: missing_real_artifacts_and_packet
- canonical input packet: inputs/enterprise_multimodal_validation_packet.json
- required packet artifact id: enterprise_multimodal_validation_packet_v1
- required evidence kind: real_enterprise_multimodal_validation
- real artifact root: inputs/enterprise_multimodal_real
- validator module: enterprise_multimodal_validation_validator.py
- assembler module: enterprise_multimodal_packet_assembler.py

Current blockers:

- enterprise multimodal validation packet missing
- real enterprise multimodal pilot manifest is not present
- enterprise spreadsheet/mail/meeting/video validation packets are not present
- multimodal human adjudication and cross-modal permission leak probe are not present

Required evidence and controls:

- required modalities:
  - spreadsheet
  - mail
  - meeting_audio
  - video_ocr
- required artifacts:
  - pilot_manifest_artifact
  - validation_artifacts for every modality
  - human_adjudication_artifact or llm_subagent_adjudication_artifact
  - business_decision_review_artifact
  - permission_probe_artifact
- controls:
  - real enterprise pilot manifest
  - no synthetic/demo source rows
  - no text-proxy-only source rows
  - FormOwl locator bound to asset id
  - validation rows bound to source asset hashes
  - four-specialist LLM subagent panel covers every validation row exactly; legacy human adjudication remains accepted only for backwards compatibility
  - LLM subagent panel uses professional roles external_baseline_methodologist, annotation_adjudication_protocol_specialist, multimodal_semantics_validation_specialist, production_governance_adapter_specialist
  - business decision review is four-specialist LLM-subagent-reviewed and non-autonomous; legacy human review remains accepted only for backwards compatibility
  - permission probe denies revoked grants, private content, raw asset access, and entity-match-as-access

Response intake contract:

- response packet type: enterprise_multimodal_response_intake_v1
- work packet: work_packets/enterprise_multimodal_collection_packet_preview.json
- candidate output dir: inputs/enterprise_multimodal_real/OPERATOR_RUN_ID
- candidate manifest output: work_packets/multimodal_semantic_validation_candidate_manifest.json
- canonical packet not written: inputs/enterprise_multimodal_validation_packet.json
- writes canonical packet: False
- promotes evidence: False
- counts as acceptance gate: False

Required intake controls:

- operator_run_id matches the candidate output directory final segment
- candidate output dir is exactly inputs/enterprise_multimodal_real/<operator_run_id> outside tests
- response packet top-level fields and validation wrapper fields are allowlisted
- public reproducible mode is allowed only with a hash-bound public evidence manifest
- raw/internal field names are rejected throughout response payloads
- candidate artifact parent directories are preflighted before writes
- after-open partial output writes are cleaned up
- created candidate artifacts and optional candidate manifests are rolled back when assembly, validation, custody hashing, or custody write raises after writes
- operator supplied pilot manifest artifact
- operator supplied validation artifacts for every required modality
- operator supplied four-specialist LLM subagent adjudication artifact with fixed professional roles
- legacy human adjudication artifact remains accepted only for backwards compatibility
- operator supplied business decision review artifact
- operator supplied permission probe artifact
- candidate packet validates before any manual governance promotion
- intake custody receipt binds response packet, candidate packet, and artifact hashes
- intake custody receipt binds optional assembly manifest hash when emitted

Response packet preflight command:

Run this first with the final operator response packet and output
surface. It writes no candidate artifacts, no candidate manifest, and
no canonical packet.

```sh
python3 enterprise_multimodal_response_intake.py --work-packet work_packets/enterprise_multimodal_collection_packet_preview.json --response-packet OPERATOR_ENTERPRISE_RESPONSE_PACKET_JSON --output-dir inputs/enterprise_multimodal_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/multimodal_semantic_validation_candidate_manifest.json --preflight-response
```

Candidate-only intake command:

Replace the operator placeholders with real response packet paths and
a unique operator run id. This command writes only candidate artifacts.

```sh
python3 enterprise_multimodal_response_intake.py --work-packet work_packets/enterprise_multimodal_collection_packet_preview.json --response-packet OPERATOR_ENTERPRISE_RESPONSE_PACKET_JSON --output-dir inputs/enterprise_multimodal_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/multimodal_semantic_validation_candidate_manifest.json
```

Optional non-evidence scaffold command:

Use this only to inspect the expected assembly-manifest shape.
It is not the candidate manifest emitted by response intake.

```sh
python3 enterprise_multimodal_assembly_manifest_generator.py --output work_orders/multimodal_semantic_validation_assembly_manifest.json
```

Candidate manifest emitted by intake:

```text
work_packets/multimodal_semantic_validation_candidate_manifest.json
```

Validation sequence after candidate artifacts exist:

validate_candidate_packet:
```sh
python3 enterprise_multimodal_packet_assembler.py --assembly-manifest work_packets/multimodal_semantic_validation_candidate_manifest.json --validate
```

run_gate_validator_after_manual_packet_review:
```sh
python3 enterprise_multimodal_validation_validator.py
```

rerun_total_acceptance:
```sh
python3 kg_total_acceptance_suite.py
```

rerun_objective_audit:
```sh
python3 kg_objective_completion_audit.py
```

rerun_preflight:
```sh
python3 real_evidence_preflight.py
```

Manual follow-up:

- manual governance approval is required outside this work-order generator before any canonical packet update can affect acceptance

Safety rules:

- real artifacts must live under: inputs/enterprise_multimodal_real
- canonical packet must be created only by the assembler:
  inputs/enterprise_multimodal_validation_packet.json
- assembly manifest must not live under real root: True
- forbidden sources:
  - templates/
  - inputs/test_*
  - results/
  - symlinks
  - malformed JSON
  - raw filesystem paths
  - NAS/SMB/NFS/WebDAV paths
  - object-store or database URIs
  - worker scratch paths
  - lost /tmp artifacts
- accepted evidence source modes:
  - operator_private
  - public_reproducible
- public reproducible mode requirements:
  - response packet may set evidence_source_mode == public_reproducible
  - public mode must include public_evidence_manifest_artifact in the response packet
  - public evidence manifest must use public_reproducible_evidence_sources_v1
  - every public source must bind https URL, license, version/snapshot, retrieval timestamp, source content hash, archive hash, and derived artifact hashes
  - single raw URLs or unpinned web pages are not accepted as evidence
  - public manifest covered_artifact_sha256s must cover the final candidate packet artifact hashes expected by the authoritative validator
- operator must not claim:
  - financial_advice_or_autonomous_business_judgment
  - production_ready
  - top_tier_scientific_validation
  - raw_asset_access

## production_adapter_paths

- work order id: collect_production_adapter_paths
- requirement id: production_adapter_gate
- collection status: missing_real_artifacts_and_packet
- canonical input packet: inputs/production_adapter_evidence_packet.json
- required packet artifact id: production_adapter_evidence_packet_v1
- required evidence kind: non_synthetic_production_adapter_validation
- real artifact root: inputs/production_adapter_real
- validator module: production_adapter_path_validator.py
- assembler module: production_adapter_packet_assembler.py

Current blockers:

- production adapter evidence packet missing
- non-synthetic production deployment validation is not present
- human or LLM-subagent-reviewed false-merge labels are not present
- permission probes, rollback smoke, and production audit artifacts are not present

Required evidence and controls:

- required components:
  - postgres_metadata_store
  - pgvector_index
  - retrieval_gateway
  - semantic_gateway
  - rapidfuzz_candidate_adapter
  - splink_candidate_adapter
  - wiki_projection_adapter
- required artifacts:
  - deployment_manifest_artifact
  - adapter_artifacts for every required component
  - human_false_merge_label_artifact
  - audit_trail_artifact
  - permission_probe_artifact
  - rollback_smoke_artifact
- required audit actions:
  - deploy_started
  - migration_applied
  - grant_check_before_content
  - revoked_grant_blocks_content
  - private_candidate_redacted
  - entity_match_without_grant_denied
  - raw_asset_read_guard_rejected
  - canonical_merge_guard_rejected
  - wiki_projection_draft_not_published
  - rollback_smoke_completed
  - deploy_completed
- controls:
  - non-synthetic four-specialist LLM-subagent-approved deployment manifest; legacy human approval remains accepted only for backwards compatibility
  - manifest adapter stack digest bound to component artifacts
  - permission filters enabled on every adapter component
  - canonical writes disabled on adapter evidence path
  - four-specialist LLM-subagent-reviewed false-merge labels for RapidFuzz and Splink; legacy human review remains accepted only for backwards compatibility
  - LLM subagent panel uses professional roles external_baseline_methodologist, annotation_adjudication_protocol_specialist, multimodal_semantics_validation_specialist, production_governance_adapter_specialist
  - one request id, one resource ref, and one policy id across audit rows
  - revoked grant audit row binds grant_state == revoked
  - deny guards for private candidates, entity match without grant, raw asset reads, and canonical merge without review
  - wiki projection remains draft-only
  - rollback smoke verifies migration rollback, partial-failure rollback, append-only audit, and idempotent retry
  - no raw/internal values, including driver-qualified database URIs

Response intake contract:

- response packet type: production_adapter_response_intake_v1
- work packet: work_packets/production_adapter_collection_packet_preview.json
- candidate output dir: inputs/production_adapter_real/OPERATOR_RUN_ID
- candidate manifest output: work_packets/production_adapter_paths_candidate_manifest.json
- canonical packet not written: inputs/production_adapter_evidence_packet.json
- writes canonical packet: False
- promotes evidence: False
- counts as acceptance gate: False

Required intake controls:

- operator_run_id matches the candidate output directory final segment
- candidate output dir is exactly inputs/production_adapter_real/<operator_run_id> outside tests
- response packet top-level fields and adapter wrapper fields are allowlisted
- public reproducible mode is allowed only with a hash-bound public evidence manifest
- raw/internal field names are rejected throughout response payloads
- candidate artifact parent directories are preflighted before writes
- after-open partial output writes are cleaned up
- created candidate artifacts and optional candidate manifests are rolled back when assembly or validation raises after writes
- operator supplied non-synthetic deployment manifest
- operator supplied component artifacts for every required adapter
- operator supplied four-specialist LLM-subagent-reviewed false-merge labels with fixed professional roles for candidate adapters
- legacy human-reviewed false-merge labels remain accepted only for backwards compatibility
- operator supplied audit trail with every required action
- operator supplied permission probe artifact
- operator supplied rollback smoke artifact
- candidate packet validates before any manual governance promotion
- intake custody receipt binds response packet, candidate packet, and artifact hashes
- intake custody receipt binds optional assembly manifest hash when emitted

Response packet preflight command:

Run this first with the final operator response packet and output
surface. It writes no candidate artifacts, no candidate manifest, and
no canonical packet.

```sh
python3 production_adapter_response_intake.py --work-packet work_packets/production_adapter_collection_packet_preview.json --response-packet OPERATOR_PRODUCTION_ADAPTER_RESPONSE_PACKET_JSON --output-dir inputs/production_adapter_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/production_adapter_paths_candidate_manifest.json --preflight-response
```

Candidate-only intake command:

Replace the operator placeholders with real response packet paths and
a unique operator run id. This command writes only candidate artifacts.

```sh
python3 production_adapter_response_intake.py --work-packet work_packets/production_adapter_collection_packet_preview.json --response-packet OPERATOR_PRODUCTION_ADAPTER_RESPONSE_PACKET_JSON --output-dir inputs/production_adapter_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/production_adapter_paths_candidate_manifest.json
```

Optional non-evidence scaffold command:

Use this only to inspect the expected assembly-manifest shape.
It is not the candidate manifest emitted by response intake.

```sh
python3 production_adapter_assembly_manifest_generator.py --output work_orders/production_adapter_paths_assembly_manifest.json
```

Candidate manifest emitted by intake:

```text
work_packets/production_adapter_paths_candidate_manifest.json
```

Validation sequence after candidate artifacts exist:

validate_candidate_packet:
```sh
python3 production_adapter_packet_assembler.py --assembly-manifest work_packets/production_adapter_paths_candidate_manifest.json --validate
```

run_gate_validator_after_manual_packet_review:
```sh
python3 production_adapter_path_validator.py
```

rerun_total_acceptance:
```sh
python3 kg_total_acceptance_suite.py
```

rerun_objective_audit:
```sh
python3 kg_objective_completion_audit.py
```

rerun_preflight:
```sh
python3 real_evidence_preflight.py
```

Manual follow-up:

- manual governance approval is required outside this work-order generator before any canonical packet update can affect acceptance

Safety rules:

- real artifacts must live under: inputs/production_adapter_real
- canonical packet must be created only by the assembler:
  inputs/production_adapter_evidence_packet.json
- assembly manifest must not live under real root: True
- forbidden sources:
  - templates/
  - inputs/test_*
  - results/
  - symlinks
  - malformed JSON
  - raw filesystem paths
  - NAS/SMB/NFS/WebDAV paths
  - object-store or database URIs
  - worker scratch paths
  - lost /tmp artifacts
- accepted evidence source modes:
  - operator_private
  - public_reproducible
- public reproducible mode requirements:
  - response packet may set evidence_source_mode == public_reproducible
  - public mode must include public_evidence_manifest_artifact in the response packet
  - public evidence manifest must use public_reproducible_evidence_sources_v1
  - every public source must bind https URL, license, version/snapshot, retrieval timestamp, source content hash, archive hash, and derived artifact hashes
  - single raw URLs or unpinned web pages are not accepted as evidence
  - public manifest covered_artifact_sha256s must cover the final candidate packet artifact hashes expected by the authoritative validator
- operator must not claim:
  - full_product_production_ready
  - top_tier_scientific_validation
  - canonical_write
  - raw_access

## Regeneration

Regenerate this guide from current work orders with:

```sh
python3 real_evidence_operator_guide.py
```

Check whether the tracked guide is current with:

```sh
python3 real_evidence_operator_guide.py --check
```

Then rerun the authoritative KG-eval validators. This guide remains
operator guidance only.
