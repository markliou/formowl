#!/usr/bin/env python3
"""Focused tests for fair-baseline config artifact content binding."""

from __future__ import annotations

from copy import deepcopy
import unittest

import external_baseline_coverage_matrix as matrix


def write_result_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = matrix.RESULTS / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        matrix.json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return f"results/{relative_name}", matrix.sha256_file(path) or ""


def config_artifact_payload(
    baseline_id: str,
    row: dict,
    artifact_type: str,
    role: str,
) -> dict:
    fields = matrix.policy_config_fields(row)
    return {
        "artifact_type": artifact_type,
        "baseline_id": baseline_id,
        "config_role": role,
        "policy_config_fields_sha256": matrix.sha256_json(fields),
        **fields,
    }


def valid_config_policy() -> dict:
    shared_model_budget = "1234567890abcdef" * 4
    shared_embedding_budget = "234567890abcdef1" * 4
    shared_prompt_template = "34567890abcdef12" * 4
    shared_chunking = "4567890abcdef123" * 4
    shared_parser = "567890abcdef1234" * 4
    shared_retrieval = "67890abcdef12345" * 4
    shared_rerank = "7890abcdef123456" * 4
    shared_ontology_mapping = "890abcdef1234567" * 4
    per_baseline_configs = {}

    for index, baseline_id in enumerate(matrix.REQUIRED_BASELINES):
        row = {
            "config_source": "official_default",
            "package_version": f"1.0.{index}",
            "package_source_commit_or_release": f"release-{baseline_id}-1.0.{index}",
            "handicapped_for_comparison": False,
            "prompt_count": 4,
            "model_budget_sha256": shared_model_budget,
            "embedding_budget_sha256": shared_embedding_budget,
            "context_window_tokens": 8192,
            "retrieval_top_k": 8,
            "index_refresh_policy_id": "refresh_all_sources_v1",
            "prompt_template_sha256": shared_prompt_template,
            "chunking_policy_sha256": shared_chunking,
            "parser_policy_sha256": shared_parser,
            "retrieval_policy_sha256": shared_retrieval,
            "rerank_policy_sha256": shared_rerank,
            "graph_builder_config_sha256": f"{index + 1:064x}",
            "ontology_mapping_config_sha256": shared_ontology_mapping,
        }
        config_artifact, config_sha256 = write_result_artifact(
            f"test_config_policy/{baseline_id}_config.json",
            config_artifact_payload(
                baseline_id,
                row,
                "fair_baseline_effective_config_v1",
                "effective",
            ),
        )
        default_artifact, default_sha256 = write_result_artifact(
            f"test_config_policy/{baseline_id}_default.json",
            config_artifact_payload(
                baseline_id,
                row,
                "fair_baseline_package_default_config_v1",
                "official default",
            ),
        )
        row.update(
            {
                "config_artifact": config_artifact,
                "config_artifact_sha256": config_sha256,
                "package_default_config_artifact": default_artifact,
                "package_default_config_sha256": default_sha256,
            }
        )
        per_baseline_configs[baseline_id] = row

    policy_payload = {
        "artifact_type": "fair_baseline_config_fairness_policy_v1",
        "policy_id": "fair_policy_locked_graph_rag_v1",
        "baseline_ids": list(matrix.REQUIRED_BASELINES),
        "same_corpus_and_prompts_for_all_baselines": True,
        "same_access_policy_for_all_baselines": True,
        "same_completion_model_or_budget_policy": True,
        "same_embedding_model_or_budget_policy": True,
        "same_index_refresh_policy": True,
        "same_context_window_or_token_budget": True,
        "selective_prompt_omission_forbidden": True,
        "per_baseline_configs": per_baseline_configs,
    }
    policy_artifact, policy_sha256 = write_result_artifact(
        "test_config_policy/policy.json",
        policy_payload,
    )
    return {
        "policy_id": policy_payload["policy_id"],
        "baseline_ids": policy_payload["baseline_ids"],
        "policy_artifact": policy_artifact,
        "policy_artifact_sha256": policy_sha256,
    }


def validator_with_policy(policy: dict) -> dict:
    return {
        "metrics": {"prompt_count": 4},
        "baseline_config_fairness_policy": policy,
    }


class ExternalBaselineConfigArtifactBindingTest(unittest.TestCase):
    def _status(self, policy: dict) -> dict:
        return matrix.baseline_config_fairness_policy_status(
            validator_with_policy(policy),
            4,
        )

    def _rewrite_policy_artifact(self, policy: dict, relative_name: str, mutate) -> dict:
        payload = matrix.load_artifact_dict(policy["policy_artifact"])
        mutate(payload)
        policy_artifact, policy_sha256 = write_result_artifact(relative_name, payload)
        return {
            **policy,
            "policy_artifact": policy_artifact,
            "policy_artifact_sha256": policy_sha256,
        }

    def _rewrite_config_artifact_in_policy(
        self,
        policy: dict,
        baseline_id: str,
        path_field: str,
        digest_field: str,
        relative_name: str,
        mutate,
        policy_relative_name: str,
    ) -> dict:
        policy_payload = matrix.load_artifact_dict(policy["policy_artifact"])
        row = policy_payload["per_baseline_configs"][baseline_id]
        artifact_payload = matrix.load_artifact_dict(row[path_field])
        mutate(artifact_payload)
        artifact, digest = write_result_artifact(relative_name, artifact_payload)
        row[path_field] = artifact
        row[digest_field] = digest
        policy_artifact, policy_sha256 = write_result_artifact(
            policy_relative_name,
            policy_payload,
        )
        return {
            **policy,
            "policy_artifact": policy_artifact,
            "policy_artifact_sha256": policy_sha256,
        }

    def test_valid_policy_requires_structured_config_artifacts(self) -> None:
        status = self._status(valid_config_policy())

        self.assertTrue(status["passed"])
        self.assertEqual(status["blockers"], [])

    def test_config_artifact_content_mismatch_with_policy_row_fails(self) -> None:
        policy = valid_config_policy()
        policy = self._rewrite_config_artifact_in_policy(
            policy,
            "microsoft_graphrag",
            "config_artifact",
            "config_artifact_sha256",
            "test_config_policy/microsoft_config_degraded_topk.json",
            lambda payload: payload.update({"retrieval_top_k": 1}),
            "test_config_policy/policy_with_degraded_effective_artifact.json",
        )

        status = self._status(policy)

        self.assertFalse(status["passed"])
        self.assertIn(
            "microsoft_graphrag effective config artifact field mismatch: retrieval_top_k",
            status["blockers"],
        )

    def test_equalized_tuning_artifact_missing_declared_hashes_fails(self) -> None:
        policy = valid_config_policy()

        def mutate_policy(payload: dict) -> None:
            row = payload["per_baseline_configs"]["lightrag"]
            row["config_source"] = "declared_tuned_equalized"
            fields = matrix.policy_config_fields(row)
            tuning_payload = {
                "artifact_type": "fair_baseline_equalized_tuning_config_v1",
                "baseline_id": "lightrag",
                "config_role": "equalized tuning",
                "policy_config_fields_sha256": matrix.sha256_json(fields),
                **fields,
            }
            tuning_payload.pop("retrieval_policy_sha256")
            tuning_artifact, tuning_sha256 = write_result_artifact(
                "test_config_policy/lightrag_equalized_tuning_missing_hash.json",
                tuning_payload,
            )
            row["equalized_tuning_artifact"] = tuning_artifact
            row["equalized_tuning_artifact_sha256"] = tuning_sha256

        policy = self._rewrite_policy_artifact(
            policy,
            "test_config_policy/policy_equalized_tuning_missing_hash.json",
            mutate_policy,
        )

        status = self._status(policy)

        self.assertFalse(status["passed"])
        self.assertIn(
            "lightrag equalized tuning config artifact missing field: retrieval_policy_sha256",
            status["blockers"],
        )

    def test_official_default_artifact_not_matching_package_version_or_policy_row_fails(
        self,
    ) -> None:
        policy = valid_config_policy()
        policy = self._rewrite_config_artifact_in_policy(
            policy,
            "hipporag",
            "package_default_config_artifact",
            "package_default_config_sha256",
            "test_config_policy/hipporag_default_wrong_version.json",
            lambda payload: payload.update({"package_version": "0.0.degraded"}),
            "test_config_policy/policy_default_wrong_version.json",
        )

        status = self._status(policy)

        self.assertFalse(status["passed"])
        self.assertIn(
            "hipporag official default config artifact field mismatch: package_version",
            status["blockers"],
        )

    def test_config_artifact_rejects_unsupported_shadow_settings(self) -> None:
        policy = valid_config_policy()
        policy = self._rewrite_config_artifact_in_policy(
            policy,
            "lightrag",
            "config_artifact",
            "config_artifact_sha256",
            "test_config_policy/lightrag_shadow_settings.json",
            lambda payload: payload.update({"actual_runtime_retrieval_top_k": 1}),
            "test_config_policy/policy_with_shadow_settings.json",
        )

        status = self._status(policy)

        self.assertFalse(status["passed"])
        self.assertIn(
            "lightrag effective config artifact has unsupported fields: actual_runtime_retrieval_top_k",
            status["blockers"],
        )

    def test_summary_policy_cannot_override_bound_artifact_payload(self) -> None:
        policy = valid_config_policy()
        mutated = deepcopy(policy)
        mutated["baseline_ids"] = ["microsoft_graphrag"]

        status = self._status(mutated)

        self.assertFalse(status["passed"])
        self.assertIn(
            "fair baseline config fairness policy summary mismatch: baseline_ids",
            status["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
