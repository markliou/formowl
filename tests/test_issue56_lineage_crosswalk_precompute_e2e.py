from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_mail import SemanticPlanLimits, build_authorized_semantic_mail_session
from formowl_mail import hybrid as hybrid_module
from formowl_mail import issue56_sealed_source as sealed_source
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)
from test_issue56_node_backed_fallback_e2e import _contract_only_runtime
from test_issue56_sealed_source_loader_e2e import _loader_kwargs, _prepare_package


@dataclass
class _ManualMonotonicClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Issue56LineageCrosswalkPrecomputeEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()

    def setUp(self) -> None:
        self.inputs = build_semantic_poc_inputs()
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            self.session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        self._clear_crosswalk_cache()

    def tearDown(self) -> None:
        self._clear_crosswalk_cache()

    def test_precompute_matches_direct_cold_build_content_and_fingerprint(
        self,
    ) -> None:
        direct = hybrid_module.build_evidence_identity_lineage_crosswalk(
            session=self.session,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        self._clear_crosswalk_cache()

        precomputed = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
            session=self.session,
            effective_graph_view=self.inputs.effective_graph_view,
        )

        self.assertEqual(precomputed, direct)
        self.assertEqual(
            precomputed.crosswalk_fingerprint,
            direct.crosswalk_fingerprint,
        )
        self.assertEqual(
            precomputed.index_fingerprint,
            self.session.index.index_fingerprint,
        )
        self.assertEqual(
            precomputed.graph_revision_fingerprint,
            hybrid_module._graph_revision_fingerprint(
                self.inputs.effective_graph_view,
            ),
        )
        serialized = json.dumps(
            precomputed.to_safe_dict(),
            ensure_ascii=True,
            sort_keys=True,
        )
        for private_value in (
            "PO470002002",
            "ORIGIN-TAIWAN-01",
            "obs_issue56_semantic_current_body_1",
            "node_issue56_po_current",
            REQUESTER_USER_ID,
            WORKSPACE_ID,
        ):
            self.assertNotIn(private_value, serialized)

    def test_precompute_moves_crosswalk_cost_outside_tiny_query_budget_without_drift(
        self,
    ) -> None:
        query_text = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
        limits = SemanticPlanLimits(max_time_budget_ms=1)
        with patch.object(
            hybrid_module,
            "_MONOTONIC_CLOCK",
            _ManualMonotonicClock(),
        ):
            baseline = self._query(
                query_text=query_text,
                limits=limits,
            )
        self.assertEqual(baseline.status, "ok")
        self._clear_crosswalk_cache()

        real_builder = hybrid_module.build_evidence_identity_lineage_crosswalk
        cold_clock = _ManualMonotonicClock()

        def delayed_cold_builder(**kwargs):
            graph_snapshot = kwargs["graph_snapshot"]
            cache_key = (
                kwargs["session"].index.index_fingerprint,
                graph_snapshot.graph_revision_fingerprint,
            )
            with hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
                cache_hit = cache_key in hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE
            if not cache_hit:
                cold_clock.advance(0.002)
            return real_builder(**kwargs)

        cold_trace = hybrid_module.SemanticPhaseTrace()
        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", cold_clock),
            patch.object(
                hybrid_module,
                "build_evidence_identity_lineage_crosswalk",
                side_effect=delayed_cold_builder,
            ),
        ):
            cold = self._query(
                query_text=query_text,
                limits=limits,
                phase_trace=cold_trace,
            )

        self.assertEqual(cold.status, "no_answer")
        self.assertEqual(
            cold.warnings,
            ("semantic_query_time_budget_exhausted",),
        )
        self.assertEqual(
            cold_trace.to_safe_dict()["deadline_exhausted_phase"],
            "lineage_crosswalk",
        )

        self._clear_crosswalk_cache()
        precomputed = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
            session=self.session,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        warm_clock = _ManualMonotonicClock()
        warm_trace = hybrid_module.SemanticPhaseTrace()

        def delayed_on_cache_miss(**kwargs):
            graph_snapshot = kwargs["graph_snapshot"]
            cache_key = (
                kwargs["session"].index.index_fingerprint,
                graph_snapshot.graph_revision_fingerprint,
            )
            with hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
                cache_hit = cache_key in hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE
            if not cache_hit:
                warm_clock.advance(0.002)
            return real_builder(**kwargs)

        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", warm_clock),
            patch.object(
                hybrid_module,
                "build_evidence_identity_lineage_crosswalk",
                side_effect=delayed_on_cache_miss,
            ),
        ):
            warmed = self._query(
                query_text=query_text,
                limits=limits,
                phase_trace=warm_trace,
            )

        self.assertEqual(warmed.to_safe_dict(), baseline.to_safe_dict())
        self.assertEqual(
            warmed.lineage_audit.crosswalk_fingerprint,
            precomputed.crosswalk_fingerprint,
        )
        phase_outcomes = {
            entry["phase"]: entry["outcome"] for entry in warm_trace.to_safe_dict()["phases"]
        }
        self.assertEqual(phase_outcomes["lineage_crosswalk"], "completed")
        self.assertEqual(phase_outcomes["strong_rag"], "completed")
        self.assertIsNone(warm_trace.to_safe_dict()["deadline_exhausted_phase"])

    def test_graph_permission_and_index_revision_changes_miss_cache(self) -> None:
        evidence_hashes = hybrid_module._authorized_property_evidence_hashes
        with patch.object(
            hybrid_module,
            "_authorized_property_evidence_hashes",
            wraps=evidence_hashes,
        ) as resolve_evidence:
            base = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            base_build_calls = resolve_evidence.call_count
            repeated = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
                session=self.session,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            self.assertEqual(resolve_evidence.call_count, base_build_calls)
            self.assertEqual(repeated, base)

            changed_graph = replace(
                self.inputs.effective_graph_view,
                applied_grant_ids=["grant_issue56_changed_permission_projection"],
            )
            graph_changed = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
                session=self.session,
                effective_graph_view=changed_graph,
            )
            graph_build_calls = resolve_evidence.call_count
            self.assertGreater(graph_build_calls, base_build_calls)
            self.assertNotEqual(
                graph_changed.graph_revision_fingerprint,
                base.graph_revision_fingerprint,
            )

            changed_index_fingerprint = sha256_json(
                {
                    "base_index_fingerprint": self.session.index.index_fingerprint,
                    "revision": "synthetic_revision_2",
                }
            )
            changed_index = replace(
                self.session.index,
                index_fingerprint=changed_index_fingerprint,
                _integrity_fingerprint=hybrid_module._hybrid_index_integrity_fingerprint(
                    index_fingerprint=changed_index_fingerprint,
                    tokenizer_id=self.session.index.tokenizer_id,
                    profile_fingerprint=self.session.index.profile_fingerprint,
                    execution_component_fingerprint=(
                        self.session.index.execution_component_fingerprint
                    ),
                    candidates=self.session.index.candidates,
                ),
            )
            changed_session = replace(self.session, index=changed_index)
            index_changed = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
                session=changed_session,
                effective_graph_view=self.inputs.effective_graph_view,
            )

        self.assertGreater(resolve_evidence.call_count, graph_build_calls)
        self.assertEqual(index_changed.index_fingerprint, changed_index_fingerprint)
        self.assertNotEqual(
            index_changed.crosswalk_fingerprint,
            base.crosswalk_fingerprint,
        )
        with hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
            cache_keys = set(hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE)
        self.assertEqual(
            cache_keys,
            {
                (
                    self.session.index.index_fingerprint,
                    base.graph_revision_fingerprint,
                ),
                (
                    self.session.index.index_fingerprint,
                    graph_changed.graph_revision_fingerprint,
                ),
                (
                    changed_index_fingerprint,
                    base.graph_revision_fingerprint,
                ),
            },
        )

        mismatched_requester_view = replace(
            self.inputs.effective_graph_view,
            requester_user_id="user_issue56_other_requester",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph requester mismatch",
        ):
            hybrid_module.precompute_evidence_identity_lineage_crosswalk(
                session=self.session,
                effective_graph_view=mismatched_requester_view,
            )

    def test_sealed_source_loader_primes_crosswalk_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package = _prepare_package(Path(temp_dir))
            precomputed_crosswalks = []

            def capture_precompute(**kwargs):
                crosswalk = hybrid_module.precompute_evidence_identity_lineage_crosswalk(**kwargs)
                precomputed_crosswalks.append(crosswalk)
                return crosswalk

            with (
                patch.object(
                    hybrid_module,
                    "_load_pinned_issue56_runtime_components",
                    return_value=self.runtime,
                ),
                patch.object(
                    sealed_source,
                    "precompute_evidence_identity_lineage_crosswalk",
                    side_effect=capture_precompute,
                ) as precompute,
            ):
                loaded = sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

        precompute.assert_called_once_with(
            session=loaded.session,
            effective_graph_view=loaded.effective_graph_view,
        )
        cache_key = (
            loaded.index.index_fingerprint,
            loaded.graph_build.graph_revision_fingerprint,
        )
        with hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
            cached = hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE.get(cache_key)
        self.assertIsNotNone(cached)
        self.assertEqual(len(precomputed_crosswalks), 1)
        precomputed = precomputed_crosswalks[0]
        self.assertEqual(
            cached.crosswalk_fingerprint,
            precomputed.crosswalk_fingerprint,
        )
        self.assertEqual(cached.authorized_evidence_count, 456)
        safe_precompute = loaded.safe_binding["lineage_crosswalk_precompute"]
        self.assertEqual(
            safe_precompute,
            {
                "artifact_id": "formowl_issue56_lineage_crosswalk_precompute_safe_v1",
                "schema_version": 1,
                "status": "passed",
                "cache_status": "primed",
                "helper_invocation_count": 1,
                "elapsed_ms": safe_precompute["elapsed_ms"],
                "crosswalk_fingerprint": precomputed.crosswalk_fingerprint,
                "index_fingerprint": precomputed.index_fingerprint,
                "graph_revision_fingerprint": (precomputed.graph_revision_fingerprint),
                "cache_key_fingerprint": sha256_json(
                    {
                        "artifact_id": ("formowl_issue56_evidence_identity_lineage_cache_key_v1"),
                        "index_fingerprint": precomputed.index_fingerprint,
                        "graph_revision_fingerprint": (precomputed.graph_revision_fingerprint),
                    }
                ),
                "counts": {
                    "authorized_evidence_count": (precomputed.authorized_evidence_count),
                    "indexed_evidence_count": precomputed.indexed_evidence_count,
                    "occurrence_bound_evidence_count": (
                        precomputed.occurrence_bound_evidence_count
                    ),
                    "graph_node_bound_evidence_count": (
                        precomputed.graph_node_bound_evidence_count
                    ),
                    "graph_edge_bound_evidence_count": (
                        precomputed.graph_edge_bound_evidence_count
                    ),
                },
            },
        )
        self.assertGreaterEqual(safe_precompute["elapsed_ms"], 0.0)
        serialized = json.dumps(
            dict(loaded.safe_binding),
            ensure_ascii=True,
            sort_keys=True,
        )
        for private_value in (
            str(package.work_dir),
            "PO470002002",
            "obs_body_",
            REQUESTER_USER_ID,
            WORKSPACE_ID,
        ):
            self.assertNotIn(private_value, serialized)

    def _query(
        self,
        *,
        query_text: str,
        limits: SemanticPlanLimits,
        phase_trace=None,
    ):
        return self.session.query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
            allowed_relation_types=ALLOWED_RELATIONS,
            limits=limits,
            phase_trace=phase_trace,
        )

    @staticmethod
    def _clear_crosswalk_cache() -> None:
        with hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
            hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
