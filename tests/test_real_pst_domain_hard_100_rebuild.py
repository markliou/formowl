from __future__ import annotations

from types import SimpleNamespace
import time
import unittest

import _paths
from formowl_contract import Observation, PermissionScope
from formowl_ingestion.storage import ObservationStore

import scripts.real_pst_domain_hard_100_rebuild as rebuild


NOW = "2026-07-22T00:00:00+00:00"


class RealPstDomainHard100RebuildTests(unittest.TestCase):
    def test_execution_fingerprint_source_set_binds_lock_and_rebuild_runners(self) -> None:
        self.assertIn(
            "scripts/real_pst_domain_hard_100_lock.py",
            rebuild.SOURCE_FILES,
        )
        self.assertIn(
            "scripts/real_pst_domain_hard_100_rebuild.py",
            rebuild.SOURCE_FILES,
        )

    def test_remap_preserves_prompts_and_maps_old_segments_without_approximation(self) -> None:
        temp_dir = _paths.fresh_test_dir("real-pst-domain-hard-100-rebuild-remap")
        source_store = ObservationStore(temp_dir)
        old_a = _observation(
            "obs_old_a",
            occurrence_id="occurrence_a",
            index=1,
            text="Target paragraph alpha",
        )
        old_b = _observation(
            "obs_old_b",
            occurrence_id="occurrence_b",
            index=2,
            text="Target paragraph beta",
        )
        source_store.create(old_a)
        source_store.create(old_b)
        bundle = _bundle(
            [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_a",
                    index=1,
                    text="Header\n\nTarget paragraph alpha\n\nTail",
                ),
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_b",
                    index=2,
                    text="Target paragraph beta",
                ),
            ]
        )
        source_manifest = _manifest()

        mapped = rebuild.remap_frozen_manifest(
            source_manifest,
            source_observation_store=source_store,
            bundle=bundle,
        )

        self.assertEqual(mapped.mapping["obs_old_a"], "obs_new_a")
        self.assertEqual(mapped.mapping["obs_old_b"], "obs_new_b")
        self.assertEqual(
            mapped.strategy_counts,
            {
                "same_index_content_hash": 1,
                "same_occurrence_substring_overlap": 1,
            },
        )
        self.assertEqual(
            mapped.immutable_case_hash,
            rebuild.sha256_json(
                [
                    {field: case.get(field) for field in rebuild.IMMUTABLE_CASE_FIELDS}
                    for case in source_manifest["cases"]
                ]
            ),
        )
        self.assertEqual(
            [case["query_text"] for case in mapped.payload["cases"]],
            [case["query_text"] for case in source_manifest["cases"]],
        )
        self.assertEqual(
            mapped.payload["cases"][0]["required_source_observation_ids"],
            ["obs_new_a", "obs_new_b"],
        )

    def test_remap_fails_closed_when_source_text_cannot_be_located(self) -> None:
        temp_dir = _paths.fresh_test_dir("real-pst-domain-hard-100-rebuild-fail-closed")
        source_store = ObservationStore(temp_dir)
        source_store.create(
            _observation(
                "obs_old_a",
                occurrence_id="occurrence_a",
                index=1,
                text="unmappable source text",
            )
        )
        source_store.create(
            _observation(
                "obs_old_b",
                occurrence_id="occurrence_b",
                index=2,
                text="Target paragraph beta",
            )
        )
        bundle = _bundle(
            [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_a",
                    index=1,
                    text="different complete body",
                ),
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_b",
                    index=2,
                    text="Target paragraph beta",
                ),
            ]
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "could not be mapped without approximation",
        ):
            rebuild.remap_frozen_manifest(
                _manifest(),
                source_observation_store=source_store,
                bundle=bundle,
            )

    def test_remap_uses_stable_message_identity_when_occurrence_id_drifts(self) -> None:
        temp_dir = _paths.fresh_test_dir("real-pst-domain-hard-100-rebuild-identity-drift")
        source_store = ObservationStore(temp_dir)
        source_store.create(
            _observation(
                "obs_old_a",
                occurrence_id="occurrence_old_a",
                index=1,
                text="Target paragraph alpha",
            )
        )
        source_store.create(
            _message_observation(
                "obs_old_message_a",
                occurrence_id="occurrence_old_a",
                message_id="message_a",
                fingerprint="fingerprint_a",
            )
        )
        source_store.create(
            _observation(
                "obs_old_b",
                occurrence_id="occurrence_b",
                index=2,
                text="Target paragraph beta",
            )
        )
        bundle = _bundle(
            [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_new_a",
                    index=1,
                    text="Target paragraph alpha",
                ),
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_b",
                    index=2,
                    text="Target paragraph beta",
                ),
            ],
            messages=[
                SimpleNamespace(
                    email_message_id="email_message_a",
                    message_fingerprint="fingerprint_a",
                    message_id="message_a",
                    normalized_subject="subject a",
                    sender="sender a",
                    sent_at=NOW,
                    body_hash="body_hash_a",
                )
            ],
            message_occurrences=[
                SimpleNamespace(
                    email_message_id="email_message_a",
                    message_occurrence_id="occurrence_new_a",
                    folder_path_hash="folder_a",
                )
            ],
        )

        mapped = rebuild.remap_frozen_manifest(
            _manifest(),
            source_observation_store=source_store,
            bundle=bundle,
        )

        self.assertEqual(mapped.mapping["obs_old_a"], "obs_new_a")
        self.assertEqual(
            mapped.strategy_counts["stable_message_fingerprint_same_index_content_hash"],
            1,
        )

    def test_resolve_occurrence_uses_body_observation_identity_without_message_row(
        self,
    ) -> None:
        old_observation = _observation(
            "obs_old_a",
            occurrence_id="occurrence_old",
            index=1,
            text="Target paragraph alpha",
            message_id="message_a",
            fingerprint="fingerprint_a",
            folder_path_hash="folder_a",
        )

        occurrence_id, strategy = rebuild._resolve_complete_message_occurrence(
            old_observation,
            source_message=None,
            new_segments_by_occurrence={"occurrence_new": [object()]},
            new_identity_indexes={
                "fingerprint_message_folder": {
                    ("fingerprint_a", "message_a", "folder_a"): {"occurrence_new"}
                },
                "message_folder": {},
                "stable_content": {},
            },
        )

        self.assertEqual(occurrence_id, "occurrence_new")
        self.assertEqual(strategy, "stable_message_fingerprint")
        self.assertTrue(rebuild._observation_has_message_identity(old_observation))

    def test_redacted_historical_segment_maps_by_exact_reconstructed_hash(self) -> None:
        complete_body = "Header paragraph\n\nprivate payload marker\n\nTail paragraph"
        historical_segments = rebuild._historical_body_segment_spans(
            complete_body,
            max_chars=4000,
        )
        redacted_hash = rebuild.sha256_json(historical_segments[1][2])
        old_observation = _observation(
            "obs_old_redacted",
            occurrence_id="occurrence_a",
            index=2,
            text=f"redacted_mail_body_segment {redacted_hash}",
        )
        candidates = [
            _segment(
                "obs_new_a",
                occurrence_id="occurrence_a",
                index=1,
                text=complete_body[:25],
            ),
            _segment(
                "obs_new_b",
                occurrence_id="occurrence_a",
                index=2,
                text=complete_body[25:],
            ),
        ]

        mapped_id, strategy = rebuild._map_observation_to_complete_segment(
            old_observation,
            candidates,
        )

        self.assertEqual(mapped_id, "obs_new_b")
        self.assertEqual(strategy, "historical_redacted_content_hash")

    def test_redacted_historical_segment_fails_closed_on_hash_mismatch(self) -> None:
        old_observation = _observation(
            "obs_old_redacted",
            occurrence_id="occurrence_a",
            index=1,
            text=f"redacted_mail_body_segment sha256:{'a' * 64}",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "could not be mapped without approximation",
        ):
            rebuild._map_observation_to_complete_segment(
                old_observation,
                [
                    _segment(
                        "obs_new_a",
                        occurrence_id="occurrence_a",
                        index=1,
                        text="different complete body",
                    )
                ],
            )

    def test_global_historical_index_maps_only_unique_exact_segment_hash(self) -> None:
        target_text = "unique historical target"
        target_observation = _observation(
            "obs_old_target",
            occurrence_id="occurrence_old",
            index=2,
            text=target_text,
        )
        target_key = rebuild._historical_evidence_key(target_observation)
        self.assertIsNotNone(target_key)
        segments_by_occurrence = {
            "occurrence_new": [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_new",
                    index=1,
                    text="Header\n\nunique historical ",
                ),
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_new",
                    index=2,
                    text="target\n\nTail",
                ),
            ]
        }
        index = rebuild._build_global_historical_evidence_index(
            segments_by_occurrence,
            required_keys={target_key},
        )

        self.assertEqual(
            rebuild._map_from_global_historical_evidence_index(
                target_observation,
                index,
            ),
            "obs_new_a",
        )

        duplicate_index = rebuild._build_global_historical_evidence_index(
            {
                **segments_by_occurrence,
                "occurrence_duplicate": [
                    _segment(
                        "obs_duplicate",
                        occurrence_id="occurrence_duplicate",
                        index=1,
                        text=f"Other header\n\n{target_text}\n\nOther tail",
                    )
                ],
            },
            required_keys={target_key},
        )
        self.assertIsNone(
            rebuild._map_from_global_historical_evidence_index(
                target_observation,
                duplicate_index,
            )
        )

    def test_remap_uses_only_globally_unique_exact_content_when_identity_drifts(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("real-pst-domain-hard-100-rebuild-global-exact")
        source_store = ObservationStore(temp_dir)
        source_store.create(
            _observation(
                "obs_old_a",
                occurrence_id="occurrence_old_a",
                index=3,
                text="Target paragraph alpha",
            )
        )
        source_store.create(
            _observation(
                "obs_old_b",
                occurrence_id="occurrence_b",
                index=2,
                text="Target paragraph beta",
            )
        )
        bundle = _bundle(
            [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_new_a",
                    index=1,
                    text="Prefix Target paragraph alpha suffix",
                ),
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_b",
                    index=2,
                    text="Target paragraph beta",
                ),
            ]
        )

        mapped = rebuild.remap_frozen_manifest(
            _manifest(),
            source_observation_store=source_store,
            bundle=bundle,
        )

        self.assertEqual(mapped.mapping["obs_old_a"], "obs_new_a")
        self.assertEqual(mapped.strategy_counts["global_unique_exact_content"], 1)

    def test_global_exact_content_mapping_fails_closed_when_duplicate(self) -> None:
        old_observation = _observation(
            "obs_old_target",
            occurrence_id="occurrence_old",
            index=3,
            text="duplicate exact target",
        )
        segments_by_occurrence = {
            "occurrence_new_a": [
                _segment(
                    "obs_new_a",
                    occurrence_id="occurrence_new_a",
                    index=1,
                    text="Prefix duplicate exact target suffix",
                )
            ],
            "occurrence_new_b": [
                _segment(
                    "obs_new_b",
                    occurrence_id="occurrence_new_b",
                    index=1,
                    text="Other duplicate exact target tail",
                )
            ],
        }

        self.assertIsNone(
            rebuild._map_from_global_unique_exact_content(
                old_observation,
                segments_by_occurrence,
            )
        )

    def test_direct_verified_store_only_resolves_the_verified_unchanged_file(self) -> None:
        temp_dir = _paths.fresh_test_dir("real-pst-domain-hard-100-direct-store")
        pst_path = temp_dir / "fixture.pst"
        pst_path.write_bytes(b"!BDNcomplete")
        store = rebuild._DirectVerifiedPstObjectStore(
            path=pst_path,
            object_uri="formowl://object/storage/workspace/digest",
            content_hash="sha256:" + "a" * 64,
            file_size=pst_path.stat().st_size,
        )

        self.assertEqual(
            store.resolve_object_path("formowl://object/storage/workspace/digest"),
            pst_path.resolve(),
        )
        self.assertTrue(
            store.verify_object(
                "formowl://object/storage/workspace/digest",
                "sha256:" + "a" * 64,
            )
        )
        self.assertFalse(store.verify_object("formowl://object/storage/workspace/other"))
        pst_path.write_bytes(b"!BDNchanged")
        self.assertIsNone(store.resolve_object_path("formowl://object/storage/workspace/digest"))

    def test_mapping_blocked_report_uses_public_safe_profile_keys(self) -> None:
        report = rebuild._mapping_blocked_report(
            tokenizer_id="jieba_sentencepiece_frozen_profile_candidate_admission_v1",
            archive_sha256="sha256:" + "a" * 64,
            fixture_size=123,
            fixture_elapsed_ms=1,
            fixture_header_ok=True,
            bundle=SimpleNamespace(messages=[], body_segments=[]),
            mapping_diagnostics={
                "required_observation_count": 2,
                "mapped_observation_count": 1,
                "unmapped_observation_count": 1,
                "affected_case_count": 1,
            },
            canaries={"rows": [], "blocking_canary_ids": []},
            import_elapsed_ms=2,
            bundle_read_elapsed_ms=3,
            started=time.monotonic(),
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("lexical_profile_id_hash", report["safe_outputs"])
        self.assertNotIn("tokenizer_id", report["safe_outputs"])

    def test_coo_canary_targets_require_exact_indexed_tokens(self) -> None:
        snippet_index = SimpleNamespace(
            snippets=(
                _indexed_snippet(
                    "obs_exact_coo",
                    {"03.80503g301", "coo"},
                ),
                _indexed_snippet(
                    "obs_exact_origin",
                    {"03.80503g301", "origin"},
                ),
                _indexed_snippet(
                    "obs_false_cooperation",
                    {"03.80503g301", "cooperation."},
                ),
                _indexed_snippet(
                    "obs_wrong_item",
                    {"03.80503g302", "產地"},
                ),
                _indexed_snippet(
                    "obs_attachment",
                    {"03.80503g301", "產地"},
                    segment_source_type="attachment_text",
                ),
            )
        )

        self.assertEqual(
            rebuild._coo_canary_target_ids(snippet_index),
            {"obs_exact_coo", "obs_exact_origin"},
        )

    def test_cross_segment_canary_reads_complete_message_after_search(self) -> None:
        query_result = SimpleNamespace(
            status="ok",
            evidence_snippets=[{"email_message_id": "message_target"}],
            citations=[{"source_observation_id": "obs_segment_a"}],
            evidence_completeness="complete",
            answerability_state="evidence_found_complete",
            to_dict=lambda: {"status": "ok", "phase": "query"},
        )
        read_result = SimpleNamespace(
            status="ok",
            evidence_segments=[
                {"source_observation_id": "obs_segment_a"},
                {"source_observation_id": "obs_segment_b"},
            ],
            evidence_completeness="complete",
            answerability_state="evidence_read_complete",
            to_dict=lambda: {"status": "ok", "phase": "read"},
        )

        class Gateway:
            def query_mail_evidence(self, **_kwargs):
                return query_result

            def read_mail_evidence(self, **_kwargs):
                return read_result

        row = rebuild._execute_query_canary(
            "cross_segment",
            (
                "03.80503G301 COO origin",
                {"obs_segment_a", "obs_segment_b"},
            ),
            gateway=Gateway(),
            bundle=SimpleNamespace(
                mail_evidence_bundle_id="bundle_complete",
                mail_import_session=SimpleNamespace(
                    owner_user_id="user_owner",
                    workspace_id="workspace_formowl",
                ),
            ),
            read_full_messages=True,
        )

        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["matched_target_count"], 2)
        self.assertEqual(row["answerability_state"], "evidence_read_complete")


def _observation(
    observation_id: str,
    *,
    occurrence_id: str,
    index: int,
    text: str,
    message_id: str | None = None,
    fingerprint: str | None = None,
    folder_path_hash: str | None = None,
) -> Observation:
    location = {
        "message_occurrence_id": occurrence_id,
        "body_segment_index": index,
    }
    payload = {"message_occurrence_id": occurrence_id}
    if message_id is not None:
        location["message_id"] = message_id
    if folder_path_hash is not None:
        location["folder_path_hash"] = folder_path_hash
    if fingerprint is not None:
        payload["message_fingerprint"] = fingerprint
    return Observation(
        observation_id=observation_id,
        extractor_run_id="run_source",
        observation_type="email_body_segment",
        modality="mail",
        location=location,
        confidence=1.0,
        permission_scope=PermissionScope.project("project_formowl"),
        created_at=NOW,
        asset_id="asset_source",
        text=text,
        payload=payload,
    )


def _message_observation(
    observation_id: str,
    *,
    occurrence_id: str,
    message_id: str,
    fingerprint: str,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        extractor_run_id="run_source",
        observation_type="email_message",
        modality="mail",
        location={
            "message_occurrence_id": occurrence_id,
            "message_id": message_id,
            "folder_path_hash": "folder_a",
        },
        confidence=1.0,
        permission_scope=PermissionScope.project("project_formowl"),
        created_at=NOW,
        asset_id="asset_source",
        text="subject a",
        payload={
            "message_occurrence_id": occurrence_id,
            "message_id": message_id,
            "message_fingerprint": fingerprint,
            "normalized_subject": "subject a",
            "sender": "sender a",
            "sent_at": NOW,
            "body_hash": "body_hash_a",
        },
    )


def _segment(
    observation_id: str,
    *,
    occurrence_id: str,
    index: int,
    text: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        source_observation_id=observation_id,
        message_occurrence_id=occurrence_id,
        segment_source_type="message_body",
        body_segment_index=index,
        char_start=(index - 1) * 4000,
        email_body_segment_id=f"segment_{observation_id}",
        text=text,
    )


def _indexed_snippet(
    observation_id: str,
    tokens: set[str],
    *,
    segment_source_type: str = "message_body",
) -> SimpleNamespace:
    return SimpleNamespace(
        searchable_tokens=tokens,
        payload={
            "source_observation_id": observation_id,
            "segment_source_type": segment_source_type,
        },
    )


def _bundle(
    segments: list[SimpleNamespace],
    *,
    messages: list[SimpleNamespace] | None = None,
    message_occurrences: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        body_segments=segments,
        messages=messages or [],
        message_occurrences=message_occurrences or [],
        mail_evidence_bundle_id="bundle_complete",
        mail_import_session=SimpleNamespace(
            mail_import_session_id="import_complete",
        ),
        mail_parse_run=SimpleNamespace(parser_version="0.1.0"),
    )


def _manifest() -> dict:
    cases = []
    for index in range(100):
        result_kind = (
            "owner_match" if index < 80 else "no_match" if index < 90 else "permission_denied"
        )
        required = [] if result_kind == "no_match" else ["obs_old_a", "obs_old_b"]
        cases.append(
            {
                "case_id": f"case_{index:03d}",
                "domain": f"domain_{index % 10}",
                "pattern": f"pattern_{index % 4}",
                "intent_kind": "fixture",
                "result_kind": result_kind,
                "query_text": f"private fixed prompt {index}",
                "requester_user_id": (
                    "user_denied" if result_kind == "permission_denied" else "user_owner"
                ),
                "limit": 10,
                "required_match_count": 2,
                "required_source_observation_ids": required,
                "forbidden_source_observation_ids": [],
                "private_fingerprint": f"sha256:{index:064x}",
            }
        )
    return {
        "manifest_type": "mail_full_pst_domain_hard_case_manifest_private",
        "archive_sha256": "sha256:" + "b" * 64,
        "case_count": 100,
        "cases": cases,
        "generated_at": NOW,
        "mail_evidence_bundle_id": "bundle_source",
        "mail_import_session_id": "import_source",
        "parser_version": "0.1.0",
        "policy_version": "formowl_full_pst_domain_hard_case_eval_v1",
    }


if __name__ == "__main__":
    unittest.main()
