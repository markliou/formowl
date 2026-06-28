# Remaining KG Real-Evidence Operator Guide

Source report: `kg_real_evidence_collection_work_orders_v1`
Source report sha256: `12fa43d671d7073597f7aed4855e521371a7c1f1e1309b568f62c8c4cf6dd46d`

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
- work-order count: 4

Blocked gate ids:

- fair_external_baseline_comparison
- annotation_adjudication_protocol
- multimodal_semantic_validation
- production_adapter_paths

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
running any listed candidate-only intake command.

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
or changed.

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
a canonical packet path created or changed.

Optionally persist that validate-only result as an ignored non-evidence
report for manual governance review:

```sh
python3 real_evidence_submission_manifest.py --manifest work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json --validate-candidate-manifests --emit-candidate-validation-report work_packets/OPERATOR_CANDIDATE_VALIDATION_REPORT_candidate_validation_report.json
```

The persisted validation report is not evidence and does not authorize
promotion by itself. It is a review aid that records the validate-only
assembler result without writing canonical input packets.

## fair_external_baseline_comparison

- work order id: collect_fair_external_baseline_comparison
- requirement id: fair_external_baseline_validation
- collection status: missing_real_artifacts_and_packet
- canonical input packet: inputs/fair_external_baseline_run_packet.json
- required packet artifact id: fair_external_baseline_run_packet_v1
- required evidence kind: non_synthetic_external_baseline_run
- real artifact root: inputs/fair_baseline_real
- validator module: fair_external_baseline_run_validator.py
- assembler module: fair_external_baseline_packet_assembler.py

Current blockers:

- fair external baseline run packet missing
- real Microsoft GraphRAG/LightRAG/HippoRAG package runs are not present
- human answer-quality adjudication packet is not present
- graph-quality validation packet is not present
- permission leak probe results are not present

Required evidence and controls:

- required source lock sha256: addba921e9cc4ebc4ded09b26d23a25a29aeba4f0e15e4dacb711f29dcedb2da
- baseline package runs:
  - microsoft_graphrag
    - source id: microsoft_graphrag_paper
    - source id: microsoft_graphrag_repo
    - source id: microsoft_graphrag_docs
    - artifact field: package_lock_artifact
    - artifact field: config_artifact
    - artifact field: index_build_log_artifact
    - artifact field: query_run_log_artifact
    - artifact field: answer_output_artifact
    - artifact field: graph_output_artifact
    - artifact field: permission_probe_artifact
    - equalized hash: corpus_export_sha256
    - equalized hash: prompt_set_sha256
    - equalized hash: evaluation_question_set_sha256
    - equalized hash: access_policy_sha256
    - equalized hash: completion_model_budget_sha256
    - equalized hash: embedding_model_budget_sha256
    - equalized hash: ontology_mapping_sha256
  - lightrag
    - source id: lightrag_paper
    - source id: lightrag_repo
    - artifact field: package_lock_artifact
    - artifact field: config_artifact
    - artifact field: index_build_log_artifact
    - artifact field: query_run_log_artifact
    - artifact field: answer_output_artifact
    - artifact field: graph_output_artifact
    - artifact field: permission_probe_artifact
    - equalized hash: corpus_export_sha256
    - equalized hash: prompt_set_sha256
    - equalized hash: evaluation_question_set_sha256
    - equalized hash: access_policy_sha256
    - equalized hash: completion_model_budget_sha256
    - equalized hash: embedding_model_budget_sha256
    - equalized hash: ontology_mapping_sha256
  - hipporag
    - source id: hipporag_paper
    - source id: hipporag2_paper
    - source id: hipporag_repo
    - artifact field: package_lock_artifact
    - artifact field: config_artifact
    - artifact field: index_build_log_artifact
    - artifact field: query_run_log_artifact
    - artifact field: answer_output_artifact
    - artifact field: graph_output_artifact
    - artifact field: permission_probe_artifact
    - equalized hash: corpus_export_sha256
    - equalized hash: prompt_set_sha256
    - equalized hash: evaluation_question_set_sha256
    - equalized hash: access_policy_sha256
    - equalized hash: completion_model_budget_sha256
    - equalized hash: embedding_model_budget_sha256
    - equalized hash: ontology_mapping_sha256
- human answer adjudication:
  - human_answer_adjudication_results_v1
  - at least two distinct human independent first-pass reviewers
  - sealed submissions
  - adjudicator id
  - final adjudication hash
  - custody receipt hash
- graph quality validation:
  - human-reviewed graph-quality rows for every baseline
  - positive reviewed entity count
  - positive reviewed relation count
- permission probe evidence:
  - revoked_grant_content_denied
  - private_content_not_returned
  - raw_asset_access_denied
  - entity_match_does_not_grant_access
  - private_leak_count == 0
  - raw_asset_access_count == 0

Response intake contract:

- response packet type: fair_baseline_response_intake_v1
- work packet: work_packets/fair_baseline_run_work_packet_preview.json
- candidate output dir: inputs/fair_baseline_real/OPERATOR_RUN_ID
- candidate manifest output: work_packets/fair_external_baseline_comparison_candidate_manifest.json
- canonical packet not written: inputs/fair_external_baseline_run_packet.json
- writes canonical packet: False
- promotes evidence: False
- counts as acceptance gate: False

Required intake controls:

- operator supplied real package run artifacts for every baseline
- operator supplied non-synthetic run environment
- operator supplied human answer-quality adjudication
- operator supplied graph-quality validation
- operator supplied permission probes for every baseline
- candidate packet validates before any manual governance promotion
- intake custody receipt binds response packet, candidate packet, and artifact hashes

Candidate-only intake command:

Replace the operator placeholders with real response packet paths and
a unique operator run id. This command writes only candidate artifacts.

```sh
python3 fair_baseline_response_intake.py --work-packet work_packets/fair_baseline_run_work_packet_preview.json --response-packet OPERATOR_FAIR_BASELINE_RESPONSE_PACKET_JSON --output-dir inputs/fair_baseline_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/fair_external_baseline_comparison_candidate_manifest.json
```

Optional non-evidence scaffold command:

Use this only to inspect the expected assembly-manifest shape.
It is not the candidate manifest emitted by response intake.

```sh
python3 fair_external_baseline_assembly_manifest_generator.py --output work_orders/fair_external_baseline_comparison_assembly_manifest.json
```

Candidate manifest emitted by intake:

```text
work_packets/fair_external_baseline_comparison_candidate_manifest.json
```

Validation sequence after candidate artifacts exist:

validate_candidate_packet:
```sh
python3 fair_external_baseline_packet_assembler.py --assembly-manifest work_packets/fair_external_baseline_comparison_candidate_manifest.json --validate
```

run_gate_validator_after_manual_packet_review:
```sh
python3 fair_external_baseline_run_validator.py
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

- real artifacts must live under: inputs/fair_baseline_real
- canonical packet must be created only by the assembler:
  inputs/fair_external_baseline_run_packet.json
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
- operator must not claim:
  - production_ready
  - top_tier_scientific_validation
  - unreviewed_business_judgment
  - unreviewed_canonical_merge

## annotation_adjudication_protocol

- work order id: collect_annotation_adjudication_protocol
- requirement id: human_annotation_adjudication_protocol
- collection status: missing_real_artifacts_and_packet
- canonical input packet: inputs/human_annotation_results_v1.json
- required packet artifact id: human_annotation_results_v1
- required evidence kind: real_human_annotation_adjudication
- real artifact root: inputs/human_annotation_real
- validator module: human_annotation_adjudication_validator.py
- assembler module: human_annotation_packet_assembler.py

Current blockers:

- human annotation results packet missing
- two independent first-pass human submissions are not present
- adjudication-open receipt, final adjudication, confusion matrix, and custody receipt are not present

Required evidence and controls:

- required artifacts:
  - manifest_artifact
  - work_orders_artifact
  - at least two first_pass_submission_artifacts
  - adjudication_artifact
  - confusion_matrix_artifact
  - custody_receipt_artifact
- human controls:
  - two independent first-pass human reviewers
  - sealed first-pass submissions
  - human adjudicator distinct from first-pass reviewers
  - adjudication opened after first-pass seal
  - adjudication exactly covers sealed disagreement set
  - confusion matrix derived from first-pass consensus and final adjudication
  - custody receipt binds manifest, work orders, submissions, adjudication, and confusion matrix
- custody controls:
  - two independent first-pass submissions are sealed before adjudication
  - adjudicator is human and distinct from first-pass reviewers
  - confusion matrix is derived from sealed submissions and final adjudication
  - custody receipt binds every artifact hash

Response intake contract:

- response packet type: human_annotation_response_intake_v1
- work packet: work_packets/human_annotation_work_packet_preview.json
- candidate output dir: inputs/human_annotation_real/OPERATOR_RUN_ID
- candidate manifest output: work_packets/annotation_adjudication_protocol_candidate_manifest.json
- canonical packet not written: inputs/human_annotation_results_v1.json
- writes canonical packet: False
- promotes evidence: False
- counts as acceptance gate: False

Required intake controls:

- two independent first-pass human reviewer submissions
- human adjudicator distinct from first-pass reviewers
- at least one first-pass disagreement
- adjudication rows exactly cover disagreed items
- generated_by_llm == false for every submission and adjudication row
- template_source is null for every submission and adjudication row

Candidate-only intake command:

Replace the operator placeholders with real response packet paths and
a unique operator run id. This command writes only candidate artifacts.

```sh
python3 human_annotation_response_intake.py --work-packet work_packets/human_annotation_work_packet_preview.json --response-packet OPERATOR_RESPONSE_PACKET_JSON --output-dir inputs/human_annotation_real/OPERATOR_RUN_ID --assembly-manifest-output work_packets/annotation_adjudication_protocol_candidate_manifest.json
```

Optional non-evidence scaffold command:

Use this only to inspect the expected assembly-manifest shape.
It is not the candidate manifest emitted by response intake.

```sh
python3 human_annotation_assembly_manifest_generator.py --output work_orders/annotation_adjudication_protocol_assembly_manifest.json
```

Candidate manifest emitted by intake:

```text
work_packets/annotation_adjudication_protocol_candidate_manifest.json
```

Validation sequence after candidate artifacts exist:

validate_candidate_packet:
```sh
python3 human_annotation_packet_assembler.py --assembly-manifest work_packets/annotation_adjudication_protocol_candidate_manifest.json --validate
```

run_gate_validator_after_manual_packet_review:
```sh
python3 human_annotation_adjudication_validator.py
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

- real artifacts must live under: inputs/human_annotation_real
- canonical packet must be created only by the assembler:
  inputs/human_annotation_results_v1.json
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
- operator must not claim:
  - synthetic_label_generation
  - template_as_human_evidence
  - production_ready
  - top_tier_scientific_validation

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
  - human_adjudication_artifact
  - business_decision_review_artifact
  - permission_probe_artifact
- controls:
  - real enterprise pilot manifest
  - no synthetic/demo source rows
  - no text-proxy-only source rows
  - FormOwl locator bound to asset id
  - validation rows bound to source asset hashes
  - human adjudication covers every validation row exactly
  - business decision review is human-reviewed and non-autonomous
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

- operator supplied pilot manifest artifact
- operator supplied validation artifacts for every required modality
- operator supplied human adjudication artifact
- operator supplied business decision review artifact
- operator supplied permission probe artifact
- candidate packet validates before any manual governance promotion
- intake custody receipt binds response packet, candidate packet, and artifact hashes
- intake custody receipt binds optional assembly manifest hash when emitted

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
- human-reviewed false-merge labels are not present
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
  - non-synthetic human-approved deployment manifest
  - manifest adapter stack digest bound to component artifacts
  - permission filters enabled on every adapter component
  - canonical writes disabled on adapter evidence path
  - human-reviewed false-merge labels for RapidFuzz and Splink
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

- operator supplied non-synthetic deployment manifest
- operator supplied component artifacts for every required adapter
- operator supplied human-reviewed false-merge labels for candidate adapters
- operator supplied audit trail with every required action
- operator supplied permission probe artifact
- operator supplied rollback smoke artifact
- candidate packet validates before any manual governance promotion
- intake custody receipt binds response packet, candidate packet, and artifact hashes

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
