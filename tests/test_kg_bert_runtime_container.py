from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "containers" / "kg-bert-cpu" / "Dockerfile"
REQUIREMENTS = ROOT / "containers" / "kg-bert-requirements.txt"
CONTAINER_README = ROOT / "containers" / "kg-bert-cpu" / "README.md"
GPU_DOCKERFILE = ROOT / "containers" / "kg-bert-gpu" / "Dockerfile"
GPU_CONTAINER_README = ROOT / "containers" / "kg-bert-gpu" / "README.md"
RUNTIME_DOC = ROOT / "docs" / "kg-bert-runtime.md"


class KGBertRuntimeContainerTests(unittest.TestCase):
    def test_dockerfile_preserves_cpu_only_neural_runtime_boundary(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.12.11-slim-bookworm", dockerfile)
        self.assertIn("https://download.pytorch.org/whl/cpu", dockerfile)
        self.assertIn('"torch==2.5.1+cpu"', dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL_PROFILE=legacy_cpu_bert", dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL", dockerfile)
        self.assertIn("sentence-transformers/bert-base-nli-mean-tokens", dockerfile)
        self.assertNotIn("BAAI/bge-large-en-v1.5", dockerfile)
        self.assertNotIn("cuda_toolkit", dockerfile)
        self.assertNotIn("nvidia-cudnn", dockerfile)
        self.assertNotIn("pip install sentence-transformers", dockerfile)

    def test_neural_runtime_requirements_are_pinned(self) -> None:
        requirements = REQUIREMENTS.read_text(encoding="utf-8").splitlines()

        self.assertIn("sentence-transformers==3.3.1", requirements)
        self.assertIn("transformers==4.46.3", requirements)
        self.assertIn("tokenizers==0.20.3", requirements)
        for line in requirements:
            if line and not line.startswith("#"):
                self.assertIn("==", line)
        self.assertIn("containers/kg-bert-requirements.txt", DOCKERFILE.read_text())
        self.assertIn("containers/kg-bert-requirements.txt", GPU_DOCKERFILE.read_text())

    def test_gpu_dockerfile_preserves_cuda_runtime_boundary(self) -> None:
        dockerfile = GPU_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "ARG FORMOWL_KG_BERT_GPU_BASE=pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime",
            dockerfile,
        )
        self.assertIn("FROM ${FORMOWL_KG_BERT_GPU_BASE}", dockerfile)
        self.assertIn("ARG FORMOWL_KG_BERT_EXPECTED_TORCH_PREFIX=2.5.1", dockerfile)
        self.assertIn("ARG FORMOWL_KG_BERT_EXPECTED_CUDA=11.8", dockerfile)
        self.assertIn("torch.__version__.startswith(expected_torch_prefix)", dockerfile)
        self.assertIn("torch.version.cuda == expected_cuda", dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL_PROFILE=gpu_bge_large_en_v1_5", dockerfile)
        self.assertIn("FORMOWL_BERT_ABLATION_MODEL", dockerfile)
        self.assertIn("BAAI/bge-large-en-v1.5", dockerfile)
        self.assertIn("FORMOWL_KG_BERT_MIN_GPU_CLASS=gtx_1080_ti_11gb", dockerfile)
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
        self.assertIn("formowl-kg-bert-gpu:cu126-host", combined)
        self.assertIn("BAAI/bge-large-en-v1.5", combined)
        self.assertIn("sentence-transformers/bert-base-nli-mean-tokens", combined)
        self.assertIn("GTX 1080 Ti", combined)
        self.assertIn("kg_bert_ablation_bge_large_gpu_cu118.json", combined)
        self.assertIn("kg_bert_ablation_bge_large_gpu_cu126_host.json", combined)
        self.assertIn("--gpus all", combined)
        self.assertIn("kg_bert_ablation/run_ablation.py", combined)
        self.assertIn("candidate-only", combined)
        self.assertIn("must not write canonical graph/type state", combined)
        self.assertIn("must not grant raw asset access", combined)

    def test_active_gpu_commands_do_not_overwrite_historical_bert_artifacts(self) -> None:
        for path in (GPU_CONTAINER_README, RUNTIME_DOC):
            readme = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "--output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu",
                readme,
            )


if __name__ == "__main__":
    unittest.main()
