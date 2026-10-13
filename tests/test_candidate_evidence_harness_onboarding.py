from __future__ import annotations

from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_graph import (
    DEFAULT_CANDIDATE_EVIDENCE_HARNESS_SCHEMA_ID,
    DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID,
    DEFAULT_CANDIDATE_EVIDENCE_ONTOLOGY_POLICY_ID,
    build_default_candidate_evidence_harness_contract,
)


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_RETRIEVAL_DOCUMENTS = (
    ".formowl/kg-eval/SESSION_RESTART.md",
    "AGENTS.md",
    "README.md",
    "SPEC.md",
    "RESOURCE_EXTRACTION_SPEC.md",
    "docs/agent-roles.md",
    "docs/implementation-task-breakdown.md",
    "docs/agent-goals/kg-research-agent.md",
    "docs/kg-bert-runtime.md",
    "docs/kg-research-method.md",
    "docs/mail-ontology-native-factorial-design.md",
    "docs/multimodal-ontology-term-extraction-decision.md",
    "docs/ontology-v2-coordination-frames.md",
    "docs/ontology-v2-coordination-plan.md",
    "docs/ontology-v2-review-comments.md",
    "docs/workflows.md",
    "experiments/kg_bert_ablation/README.md",
    "experiments/kg_ontology_v2_coordination/CURRENT_RESULTS.md",
    "experiments/kg_ontology_v2_coordination/README.md",
)
DEFAULT_HARNESS_SCRIPTS = (
    "scripts/mail_full_pst_domain_hard_kg_fusion_eval.py",
    "scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py",
    "scripts/mail_full_pst_domain_hard_ontology_factorial_eval.py",
    "scripts/mail_full_pst_chatgpt_mcp_50000_eval.py",
)


class CandidateEvidenceHarnessOnboardingTests(unittest.TestCase):
    def test_default_contract_is_explicit_and_cross_domain(self) -> None:
        contract = build_default_candidate_evidence_harness_contract()

        self.assertEqual(contract.schema_id, DEFAULT_CANDIDATE_EVIDENCE_HARNESS_SCHEMA_ID)
        self.assertEqual(contract.method_id, DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID)
        self.assertEqual(contract.ontology_policy, "capped_additive_rerank")
        self.assertEqual(
            contract.text_policy,
            "unicode+protected_ascii+jieba+corpus_bound_sentencepiece",
        )
        self.assertEqual(contract.candidate_admission_policy, "frozen_profile")
        self.assertEqual(contract.query_token_source, "index_owned_text_policy_runtime")
        self.assertEqual(contract.ablation_entrypoint, "retrieve_ablation")
        self.assertTrue(contract.text_policy_binding_required)
        self.assertFalse(contract.regex_only_default_allowed)
        self.assertFalse(contract.parser_chunk_cardinality_allowed)
        self.assertFalse(contract.lexical_transitive_closure_allowed)
        self.assertFalse(contract.ontology_hard_pruning_allowed)
        self.assertFalse(contract.canonical_write_allowed)
        for source_shape in (
            "finance_record",
            "quality_record",
            "pdf_page_or_section",
            "ppt_slide",
            "table_row",
            "image_ocr_region",
            "application_event",
        ):
            self.assertIn(source_shape, contract.supported_source_shapes)

    def test_every_active_retrieval_document_onboards_the_same_default(self) -> None:
        for relative_path in ACTIVE_RETRIEVAL_DOCUMENTS:
            with self.subTest(relative_path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                normalized = " ".join(text.lower().split())
                self.assertIn("default candidate evidence retrieval", normalized)
                self.assertIn("logical source item", normalized)
                self.assertIn("ontology", normalized)
                self.assertIn("candidateevidencetextpolicyruntime", normalized)
                self.assertIn("query text only", normalized)
                self.assertIn("runtime id", normalized)
                self.assertIn("implementation hash", normalized)
                self.assertIn("free-form", normalized)
                self.assertIn("hash", normalized)
                self.assertIn("context", normalized)
                self.assertIn("time", normalized)
                self.assertIn("admissib", normalized)
                self.assertIn("retrieve_ablation", normalized)
                self.assertIn("raw query text", normalized)
                self.assertIn("control intent", normalized)
                self.assertIn("runtime-produced tokens", normalized)
                self.assertIn("candidateevidenceaccessbinding", normalized)
                self.assertIn("frozenset", normalized)
                self.assertIn("actual boolean", normalized)
                self.assertTrue(
                    "capped additive" in normalized
                    or "hard-pruning" in normalized
                    or "hard pruning" in normalized
                )
                self.assertIn("ablation", normalized)

    def test_future_retrieval_documents_cannot_bypass_onboarding_inventory(self) -> None:
        required_paths = set(ACTIVE_RETRIEVAL_DOCUMENTS)
        trigger_phrases = (
            "candidate evidence",
            "candidate kg",
            "kg fusion",
            "logical source item",
            "ontology hard",
            "regex-only",
        )
        excluded_roots = (
            ROOT / "docs" / "archive",
            ROOT / "experiments" / "kg_bert_ablation" / "results",
            ROOT / "experiments" / "kg_ontology_v2_coordination" / "results",
        )
        excluded_files = {
            ROOT / "docs" / "agent-goals" / "handoff-log.md",
        }
        discovered: set[str] = set()
        for path in ROOT.rglob("*.md"):
            if path in excluded_files or any(
                root == path or root in path.parents for root in excluded_roots
            ):
                continue
            text = path.read_text(encoding="utf-8").lower()
            if any(phrase in text for phrase in trigger_phrases):
                discovered.add(path.relative_to(ROOT).as_posix())

        self.assertEqual(
            discovered,
            required_paths,
            "update the onboarding inventory and rewrite the new retrieval document",
        )

    def test_default_harnesses_import_and_require_the_canonical_contract(self) -> None:
        for relative_path in DEFAULT_HARNESS_SCRIPTS:
            with self.subTest(relative_path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(
                    "build_default_candidate_evidence_harness_contract",
                    source,
                )
                self.assertIn(
                    "require_default_candidate_evidence_harness_contract",
                    source,
                )
                self.assertIn("HARNESS_CONTRACT", source)

        kg_source = (ROOT / DEFAULT_HARNESS_SCRIPTS[0]).read_text(encoding="utf-8")
        ontology_source = (ROOT / DEFAULT_HARNESS_SCRIPTS[1]).read_text(encoding="utf-8")
        factorial_source = (ROOT / DEFAULT_HARNESS_SCRIPTS[2]).read_text(encoding="utf-8")
        chatgpt_50000_source = (ROOT / DEFAULT_HARNESS_SCRIPTS[3]).read_text(encoding="utf-8")
        self.assertIn("DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID", kg_source)
        self.assertIn("CandidateEvidenceTextPolicyBinding", kg_source)
        self.assertIn("CandidateEvidenceTextPolicyRuntime", kg_source)
        self.assertIn("text_policy_runtime=text_policy_runtime", kg_source)
        self.assertNotIn("query_policy_binding_hash=", kg_source)
        self.assertNotIn("query_tokens=", kg_source)
        self.assertIn("**_retrieval_scope(kg_index)", kg_source)
        self.assertIn(
            "DEFAULT_CANDIDATE_EVIDENCE_ONTOLOGY_POLICY_ID",
            ontology_source,
        )
        self.assertIn("text_policy_runtime=kg_index.text_policy_runtime", ontology_source)
        self.assertNotIn("query_policy_binding_hash=", ontology_source)
        self.assertNotIn("query_tokens=", ontology_source)
        self.assertIn("**kg_eval._retrieval_scope(kg_index)", ontology_source)
        self.assertIn("DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID", factorial_source)
        self.assertIn("retrieve_ablation(", factorial_source)
        self.assertNotIn("query_policy_binding_hash=", factorial_source)
        self.assertIn("**kg_eval._retrieval_scope(kg_index)", factorial_source)
        self.assertIn("kg_index.evidence_index.retrieve(", chatgpt_50000_source)
        self.assertIn("ontology_index.evidence_index.retrieve(", chatgpt_50000_source)
        self.assertIn("query_text=query_text", chatgpt_50000_source)
        self.assertIn("access_binding=access_binding", chatgpt_50000_source)
        self.assertIn("**kg_eval._retrieval_scope(kg_index)", chatgpt_50000_source)
        self.assertNotIn("kg_eval._query_tokens(", chatgpt_50000_source)
        self.assertNotIn("kg_eval._rank_components(", chatgpt_50000_source)
        self.assertNotIn("kg_eval._evidence_from_components(", chatgpt_50000_source)
        self.assertNotIn(
            "ontology_eval._rank_components_with_ontology(",
            chatgpt_50000_source,
        )

    def test_readme_onboarding_command_uses_the_repository_test_paths(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("PYTHONPATH=tests:python python -m unittest", readme)
        self.assertIn("test_candidate_evidence_hardness", readme)
        self.assertIn("test_candidate_evidence_harness_onboarding", readme)

    def test_default_policy_ids_are_not_duplicated_as_string_literals_in_harnesses(
        self,
    ) -> None:
        for relative_path in DEFAULT_HARNESS_SCRIPTS:
            with self.subTest(relative_path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn(f'"{DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID}"', source)
                self.assertNotIn(
                    f'"{DEFAULT_CANDIDATE_EVIDENCE_ONTOLOGY_POLICY_ID}"',
                    source,
                )


if __name__ == "__main__":
    unittest.main()
