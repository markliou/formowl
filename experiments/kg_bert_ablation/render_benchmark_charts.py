#!/usr/bin/env python3
"""Render KG benchmark metric charts as dependency-free SVG files."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("experiments/kg_bert_ablation/results/charts")
METRICS = ("accuracy", "precision", "recall", "f1")
COLORS = ("#2563eb", "#059669", "#dc2626", "#7c3aed", "#ea580c", "#0891b2")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for artifact in args.artifacts:
        artifact_path = artifact if artifact.is_absolute() else ROOT / artifact
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        chart_path = output_dir / f"{artifact_path.stem}_metrics.svg"
        chart_path.write_text(render_metric_chart(payload), encoding="utf-8")
        written.append(str(chart_path.relative_to(ROOT)))
        if payload.get("artifact_id") == "formowl_kg_ontology_ablation_result_v1":
            stress_path = output_dir / f"{artifact_path.stem}_ontology_stress.svg"
            stress_path.write_text(render_metric_chart(payload, stress=True), encoding="utf-8")
            written.append(str(stress_path.relative_to(ROOT)))
    print(json.dumps({"written": written}, indent=2, sort_keys=True))
    return 0


def render_metric_chart(payload: dict[str, Any], *, stress: bool = False) -> str:
    runs = [
        run
        for run in payload.get("runs", [])
        if run.get("status") == "completed" and run.get("metrics")
    ]
    if stress:
        runs = [run for run in runs if run.get("stress_metrics")]
    metric_key = "stress_metrics" if stress else "metrics"
    title = _chart_title(payload, stress=stress)
    width = 1180
    height = 680
    margin_left = 90
    margin_right = 40
    margin_top = 86
    margin_bottom = 170
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    group_width = plot_width / len(METRICS)
    bar_gap = 8
    bar_width = max(10, (group_width - 36 - (len(runs) - 1) * bar_gap) / max(1, len(runs)))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        "<style>",
        "text{font-family:Arial,sans-serif;fill:#111827}",
        ".axis{stroke:#374151;stroke-width:1}",
        ".grid{stroke:#e5e7eb;stroke-width:1}",
        ".label{font-size:14px}",
        ".small{font-size:12px;fill:#4b5563}",
        ".title{font-size:24px;font-weight:700}",
        ".value{font-size:12px;font-weight:700}",
        "</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text class="title" x="{margin_left}" y="42">{html.escape(title)}</text>',
    ]
    for tick in range(0, 11):
        y = margin_top + plot_height - (tick / 10) * plot_height
        value = tick / 10
        parts.append(
            f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" '
            f'x2="{width - margin_right}" y2="{y:.2f}"/>'
        )
        parts.append(
            f'<text class="small" x="{margin_left - 46}" y="{y + 4:.2f}">' f"{value:.1f}</text>"
        )
    parts.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" '
        f'x2="{margin_left}" y2="{margin_top + plot_height}"/>'
    )
    parts.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_height}" '
        f'x2="{width - margin_right}" y2="{margin_top + plot_height}"/>'
    )

    for metric_index, metric in enumerate(METRICS):
        group_x = margin_left + metric_index * group_width
        label_x = group_x + group_width / 2
        parts.append(
            f'<text class="label" text-anchor="middle" x="{label_x:.2f}" '
            f'y="{height - margin_bottom + 42}">{metric}</text>'
        )
        for run_index, run in enumerate(runs):
            metrics = run[metric_key]
            value = float(metrics[metric])
            x = group_x + 18 + run_index * (bar_width + bar_gap)
            bar_height = value * plot_height
            y = margin_top + plot_height - bar_height
            color = COLORS[run_index % len(COLORS)]
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
                f'height="{bar_height:.2f}" fill="{color}" rx="2"/>'
            )
            parts.append(
                f'<text class="value" text-anchor="middle" x="{x + bar_width / 2:.2f}" '
                f'y="{max(margin_top + 14, y - 6):.2f}">{value:.3f}</text>'
            )

    legend_y = height - 92
    for index, run in enumerate(runs):
        x = margin_left + (index % 2) * 520
        y = legend_y + (index // 2) * 26
        color = COLORS[index % len(COLORS)]
        label = _short_run_label(run)
        parts.append(f'<rect x="{x}" y="{y - 12}" width="14" height="14" fill="{color}" rx="2"/>')
        parts.append(f'<text class="small" x="{x + 22}" y="{y}">{html.escape(label)}</text>')

    boundary = _boundary_label(payload)
    parts.append(
        f'<text class="small" x="{margin_left}" y="{height - 22}">'
        f"{html.escape(boundary)}</text>"
    )
    parts.append("</svg>\n")
    return "\n".join(parts)


def _chart_title(payload: dict[str, Any], *, stress: bool) -> str:
    artifact_id = payload.get("artifact_id", "kg_benchmark")
    if artifact_id == "formowl_kg_ontology_ablation_result_v1":
        suffix = "Cross-Type Hard Negatives" if stress else "Full Dataset"
        return f"Ontology Ablation Metrics ({suffix})"
    if artifact_id == "formowl_kg_public_enterprise_benchmark_result_v1":
        pair_count = payload.get("dataset", {}).get("pair_count", "?")
        return f"Public Enterprise KG Benchmark ({pair_count} pairs)"
    return str(artifact_id)


def _short_run_label(run: dict[str, Any]) -> str:
    run_id = str(run.get("run_id", "run"))
    replacements = {
        "public_enterprise_lexical_baseline_v1": "Lexical baseline",
        "public_enterprise_bge_embedding_v1": "BGE large GPU",
        "ontology_ablation_lexical_only_v1": "Lexical only",
        "ontology_ablation_lexical_hard_gate_v1": "Lexical + ontology hard gate",
        "ontology_ablation_bge_only_v1": "BGE only",
        "ontology_ablation_bge_hard_gate_v1": "BGE + ontology hard gate",
        "ontology_ablation_bge_soft_score_v1": "BGE + ontology soft score",
    }
    return replacements.get(run_id, run_id)


def _boundary_label(payload: dict[str, Any]) -> str:
    boundary = payload.get("claim_boundary", {})
    if boundary.get("stakeholder_grade_claim") is False:
        return "Candidate-only artifact; no canonical graph/type writes; no raw access grants; not stakeholder-grade unless explicitly marked."
    return "Candidate-only artifact; no canonical graph/type writes; no raw access grants."


if __name__ == "__main__":
    raise SystemExit(main())
