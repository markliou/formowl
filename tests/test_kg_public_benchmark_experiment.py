from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "kg_bert_ablation"
    / "run_public_benchmark.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("kg_public_benchmark_run", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load public benchmark runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class KGPublicBenchmarkExperimentTests(unittest.TestCase):
    def test_pair_builders_create_labeled_contract_and_financial_pairs(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            _write_cuad_zip(cache_dir / "cuad_data.zip")
            _write_sec_json(cache_dir / "sec_company_tickers.json")
            _write_fiqa_zip(cache_dir / "fiqa_beir.zip")

            pairs = module.build_benchmark_pairs(cache_dir=cache_dir, pair_limit=1000)

        self.assertEqual(len(pairs), 1000)
        source_families = {pair.source_family for pair in pairs}
        self.assertEqual(
            source_families,
            {"contract_document", "financial_report", "financial_qa"},
        )
        self.assertTrue(any(pair.expected_same for pair in pairs))
        self.assertTrue(any(not pair.expected_same for pair in pairs))
        self.assertTrue(
            all(
                pair.core_supertype in {"Clause", "Organization", "FinancialAnswer"}
                for pair in pairs
            )
        )

    def test_report_preserves_candidate_only_and_large_benchmark_boundaries(self) -> None:
        module = _load_module()
        manifest = {
            "artifact_id": "manifest",
            "minimum_pair_count_for_model_selection": 1000,
            "recommended_pair_count_for_stakeholder_claim": 5000,
        }
        pairs = [
            module.BenchmarkPair(
                pair_id=f"pair_{index}",
                source_id="source",
                source_family="contract_document",
                left_label="effective date clause",
                right_label="this agreement starts on January 1",
                expected_same=True,
                core_supertype="Clause",
                label_basis="test",
            )
            for index in range(1000)
        ]
        run = module.run_lexical(pairs, threshold=0.70)

        report = module.build_report(
            started_at="2026-06-29T00:00:00+00:00",
            manifest=manifest,
            source_locks={"locks": {}},
            pairs=pairs,
            runs=[run],
        )

        self.assertTrue(report["claim_boundary"]["candidate_only"])
        self.assertFalse(report["claim_boundary"]["canonical_graph_write_allowed"])
        self.assertFalse(report["claim_boundary"]["raw_access_allowed"])
        self.assertTrue(report["claim_boundary"]["large_benchmark_executed"])
        self.assertFalse(report["claim_boundary"]["stakeholder_grade_claim"])
        self.assertFalse(report["dataset"]["pair_manifest_full_stored"])
        self.assertEqual(report["dataset"]["pair_count"], 1000)


def _write_cuad_zip(path: Path) -> None:
    rows = []
    for index in range(600):
        rows.append(
            {
                "title": f"contract_{index}",
                "paragraphs": [
                    {
                        "qas": [
                            {
                                "id": f"qa_{index}",
                                "question": f"What is clause category {index % 17}?",
                                "answers": [
                                    {
                                        "text": f"Clause text for category {index % 17} and contract {index}.",
                                        "answer_start": 0,
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        )
    payload = {"data": rows}
    with ZipFile(path, "w") as archive:
        archive.writestr("train_separate_questions.json", json.dumps(payload))
        archive.writestr("test.json", json.dumps({"data": []}))


def _write_sec_json(path: Path) -> None:
    rows = {
        str(index): {
            "cik_str": 1000000 + index,
            "ticker": f"T{index}",
            "title": f"COMPANY {index} INC",
        }
        for index in range(600)
    }
    path.write_text(json.dumps(rows), encoding="utf-8")


def _write_fiqa_zip(path: Path) -> None:
    corpus_rows = [
        {
            "_id": f"doc_{index}",
            "title": f"Company cash flow note {index}",
            "text": f"Financial answer text for revenue and margin topic {index}.",
        }
        for index in range(600)
    ]
    query_rows = [
        {
            "_id": f"query_{index}",
            "text": f"How should I read margin topic {index}?",
        }
        for index in range(300)
    ]
    qrel_lines = ["query-id\tcorpus-id\tscore"]
    for index in range(300):
        qrel_lines.append(f"query_{index}\tdoc_{index}\t1")
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "fiqa/corpus.jsonl",
            "\n".join(json.dumps(row) for row in corpus_rows),
        )
        archive.writestr(
            "fiqa/queries.jsonl",
            "\n".join(json.dumps(row) for row in query_rows),
        )
        archive.writestr("fiqa/qrels/test.tsv", "\n".join(qrel_lines))


if __name__ == "__main__":
    unittest.main()
