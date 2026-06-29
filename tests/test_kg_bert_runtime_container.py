from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "containers" / "kg-bert-cpu" / "Dockerfile"
REQUIREMENTS = ROOT / "containers" / "kg-bert-cpu" / "requirements.txt"
CONTAINER_README = ROOT / "containers" / "kg-bert-cpu" / "README.md"
GPU_DOCKERFILE = ROOT / "containers" / "kg-bert-gpu" / "Dockerfile"
GPU_REQUIREMENTS = ROOT / "containers" / "kg-bert-gpu" / "requirements.txt"
GPU_CONTAINER_README = ROOT / "containers" / "kg-bert-gpu" / "README.md"
RUNTIME_DOC = ROOT / "docs" / "kg-bert-runtime.md"


class KGBertRuntimeContainerTests(unittest.TestCase):
    def test_dockerfile_preserves_cpu_only_neural_runtime_boundary(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.12.11-slim-bookworm", dockerfile)
        self.assertIn("https://download.pytorch.org/whl/cpu", dockerfile)
        self.assertIn('"torch==2.5.1+cpu"', dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL", dockerfile)
        self.assertIn("sentence-transformers/bert-base-nli-mean-tokens", dockerfile)
        self.assertNotIn("cuda_toolkit", dockerfile)
        self.assertNotIn("nvidia-cudnn", dockerfile)
        self.assertNotIn("pip install sentence-transformers", dockerfile)

    def test_neural_runtime_requirements_are_pinned(self) -> None:
        requirements = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        gpu_requirements = GPU_REQUIREMENTS.read_text(encoding="utf-8").splitlines()

        self.assertIn("sentence-transformers==3.3.1", requirements)
        self.assertIn("transformers==4.46.3", requirements)
        self.assertIn("tokenizers==0.20.3", requirements)
        for line in requirements:
            if line and not line.startswith("#"):
                self.assertIn("==", line)
        self.assertEqual(requirements, gpu_requirements)

    def test_gpu_dockerfile_preserves_cuda_runtime_boundary(self) -> None:
        dockerfile = GPU_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("FROM pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime", dockerfile)
        self.assertIn('torch.__version__.startswith("2.5.1")', dockerfile)
        self.assertIn('torch.version.cuda == "11.8"', dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL", dockerfile)
        self.assertIn("sentence-transformers/bert-base-nli-mean-tokens", dockerfile)
        self.assertNotIn("torch==2.5.1+cpu", dockerfile)

    def test_docs_explain_build_run_and_candidate_only_boundary(self) -> None:
        combined = "\n".join(
            [
                CONTAINER_README.read_text(encoding="utf-8"),
                GPU_CONTAINER_README.read_text(encoding="utf-8"),
                RUNTIME_DOC.read_text(encoding="utf-8"),
            ]
        )

        self.assertIn("docker build", combined)
        self.assertIn("containers/kg-bert-cpu/Dockerfile", combined)
        self.assertIn("containers/kg-bert-gpu/Dockerfile", combined)
        self.assertIn("formowl-kg-bert-cpu:local", combined)
        self.assertIn("formowl-kg-bert-gpu:cu118", combined)
        self.assertIn("--gpus all", combined)
        self.assertIn("kg_bert_ablation/run_ablation.py", combined)
        self.assertIn("candidate-only", combined)
        self.assertIn("must not write canonical graph/type state", combined)
        self.assertIn("must not grant raw asset access", combined)


if __name__ == "__main__":
    unittest.main()
