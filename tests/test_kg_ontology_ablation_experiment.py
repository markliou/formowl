from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ONTOLOGY_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "kg_bert_ablation"
    / "run_ontology_ablation.py"
)
CHART_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "kg_bert_ablation"
    / "render_benchmark_charts.py"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class KGOntologyAblationExperimentTests(unittest.TestCase):
    def test_hard_gate_blocks_same_surface_cross_type_false_positive(self) -> None:
        module = _load_module(ONTOLOGY_SCRIPT, "kg_ontology_ablation_run")
        pairs = [
            module.OntologyPair(
                pair_id="positive_org",
                source_family="test",
                left_label="ACME Corporation",
                right_label="ACME Corp",
                expected_same=True,
                left_core_supertype="Organization",
                right_core_supertype="Organization",
                label_basis="test_positive",
            ),
            module.OntologyPair(
                pair_id="negative_same_surface_cross_type",
                source_family="ontology_stress",
                left_label="Mercury",
                right_label="Mercury",
                expected_same=False,
                left_core_supertype="Organization",
                right_core_supertype="Product",
                label_basis="cross_type_same_surface_hard_negative",
            ),
        ]

        lexical_only = module.run_scored_ablation(
            pairs,
            run_id="lexical_only",
            algorithm="test",
            threshold=0.70,
            score_kind="lexical",
            ontology_mode="none",
        )
        hard_gate = module.run_scored_ablation(
            pairs,
            run_id="hard_gate",
            algorithm="test",
            threshold=0.70,
            score_kind="lexical",
            ontology_mode="hard_gate",
        )

        self.assertEqual(lexical_only["metrics"]["false_positive"], 1)
        self.assertEqual(hard_gate["metrics"]["false_positive"], 0)
        self.assertGreater(hard_gate["metrics"]["precision"], lexical_only["metrics"]["precision"])
        self.assertEqual(hard_gate["stress_metrics"]["true_negative"], 1)

    def test_report_and_svg_chart_preserve_candidate_only_boundary(self) -> None:
        module = _load_module(ONTOLOGY_SCRIPT, "kg_ontology_ablation_report")
        chart_module = _load_module(CHART_SCRIPT, "kg_benchmark_chart")
        pairs = [
            module.OntologyPair(
                pair_id="negative_same_surface_cross_type",
                source_family="ontology_stress",
                left_label="Effective Date",
                right_label="Effective Date",
                expected_same=False,
                left_core_supertype="Clause",
                right_core_supertype="MetadataField",
                label_basis="cross_type_same_surface_hard_negative",
            )
        ]
        run = module.run_scored_ablation(
            pairs,
            run_id="ontology_ablation_lexical_hard_gate_v1",
            algorithm="test",
            threshold=0.70,
            score_kind="lexical",
            ontology_mode="hard_gate",
        )
        report = module.build_report(
            started_at="2026-06-29T00:00:00+00:00",
            pairs=pairs,
            runs=[run],
            embedding_status={"status": "not_run"},
        )
        svg = chart_module.render_metric_chart(report, stress=True)

        self.assertEqual(report["artifact_id"], "formowl_kg_ontology_ablation_result_v1")
        self.assertTrue(report["claim_boundary"]["candidate_only"])
        self.assertFalse(report["claim_boundary"]["canonical_graph_write_allowed"])
        self.assertFalse(report["claim_boundary"]["canonical_type_write_allowed"])
        self.assertIn("Ontology Ablation Metrics", svg)
        self.assertIn("Candidate-only artifact", svg)
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
