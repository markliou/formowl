from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, SourceRef
from formowl_graph import (
    CanonicalLifecycleEvent,
    CanonicalLifecycleResolution,
    CanonicalLifecycleStore,
    record_canonical_lifecycle_event,
    resolve_canonical_lifecycle_id,
)

_EVENT_TYPES = ("split", "merge", "archive", "deprecate", "supersede", "equivalence")
_RECORD_KINDS = ("atom", "entity", "relation")


class CanonicalLifecycleTests(unittest.TestCase):
    def test_lifecycle_events_keep_previous_ids_resolvable_for_all_kinds_and_types(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-lifecycle-events")
        store = CanonicalLifecycleStore(temp_dir)
        event_payloads = {}

        for index, (kind, event_type) in enumerate(
            (kind, event_type) for kind in _RECORD_KINDS for event_type in _EVENT_TYPES
        ):
            previous_ids, target_ids, status, current_ids = _valid_lifecycle_shape(
                kind,
                event_type,
                index,
            )
            event = record_canonical_lifecycle_event(
                lifecycle_store=store,
                record_kind=kind,
                event_type=event_type,
                scope_type="workspace",
                scope_id="workspace_formowl",
                previous_ids=previous_ids,
                target_ids=target_ids,
                canonical_graph_revision_id=f"graph_revision_lifecycle_{index}",
                ontology_revision_id="ontology_revision_lifecycle_001",
                lifecycle_policy_id="lifecycle_policy_lifecycle_001",
                review_decision_ids=[f"review_decision_lifecycle_{index}"],
                created_by="user_reviewer_lifecycle",
                created_at=f"2026-06-25T10:{index:02d}:00+00:00",
                source_refs=[
                    SourceRef(
                        source_system="review_packet",
                        source_type="canonical_lifecycle_decision",
                        source_id=f"packet_lifecycle_{index}",
                        source_url=f"https://example.invalid/lifecycle/{index}",
                    )
                ],
                evidence_snapshot_ids=[f"ev_lifecycle_{index}"],
                metadata={"reason": f"{event_type}_approved_by_review"},
            )
            event_payloads[event.lifecycle_event_id] = event.to_dict()
            self.assertEqual(event.record_kind, kind)
            self.assertEqual(event.event_type, event_type)
            self.assertEqual(event.previous_ids, previous_ids)
            self.assertEqual(event.target_ids, target_ids)
            self.assertEqual(event.ontology_revision_id, "ontology_revision_lifecycle_001")
            self.assertEqual(event.lifecycle_policy_id, "lifecycle_policy_lifecycle_001")

            for previous_id in previous_ids:
                resolution = resolve_canonical_lifecycle_id(
                    lifecycle_store=store,
                    record_kind=kind,
                    canonical_id=previous_id,
                )
                self.assertEqual(resolution.resolution_status, status)
                self.assertEqual(resolution.current_ids, current_ids)
                self.assertEqual(resolution.lifecycle_event_ids, [event.lifecycle_event_id])
                self.assertEqual(resolution.to_dict()["current_ids"], current_ids)

        restarted = CanonicalLifecycleStore(temp_dir)
        self.assertEqual(
            {event.lifecycle_event_id: event.to_dict() for event in restarted.list_events()},
            event_payloads,
        )
        for event_id, payload in event_payloads.items():
            restarted_event = restarted.get_event(event_id)
            self.assertIsNotNone(restarted_event)
            self.assertEqual(restarted_event.to_dict(), payload)
            self.assertEqual(restarted_event.review_decision_ids, payload["review_decision_ids"])
            self.assertEqual(restarted_event.created_at, payload["created_at"])
            self.assertEqual(restarted_event.created_by, payload["created_by"])
            self.assertEqual(
                restarted_event.canonical_graph_revision_id,
                payload["canonical_graph_revision_id"],
            )
            self.assertEqual(restarted_event.ontology_revision_id, payload["ontology_revision_id"])
            self.assertEqual(restarted_event.lifecycle_policy_id, payload["lifecycle_policy_id"])
            self.assertEqual(restarted_event.previous_ids, payload["previous_ids"])
            self.assertEqual(restarted_event.target_ids, payload["target_ids"])
            for previous_id in payload["previous_ids"]:
                resolution = resolve_canonical_lifecycle_id(
                    lifecycle_store=restarted,
                    record_kind=payload["record_kind"],
                    canonical_id=previous_id,
                )
                self.assertIn(event_id, resolution.lifecycle_event_ids)

        current_resolution = resolve_canonical_lifecycle_id(
            lifecycle_store=restarted,
            record_kind="atom",
            canonical_id="atom_already_current",
        )
        self.assertEqual(current_resolution.resolution_status, "current")
        self.assertEqual(current_resolution.current_ids, ["atom_already_current"])
        self.assertEqual(current_resolution.lifecycle_event_ids, [])
        self.assertEqual(
            current_resolution.to_dict()["requested_id"],
            "atom_already_current",
        )
        _assert_only_lifecycle_state(temp_dir)
        self.assertFalse((temp_dir / "wiki").exists())

    def test_required_governance_fields_fail_without_any_writes(self) -> None:
        cases = [
            ("canonical_graph_revision_id", {"canonical_graph_revision_id": ""}),
            ("ontology_revision_id", {"ontology_revision_id": ""}),
            ("lifecycle_policy_id", {"lifecycle_policy_id": ""}),
            ("review_decision_ids", {"review_decision_ids": []}),
            ("created_by", {"created_by": ""}),
            ("created_at", {"created_at": ""}),
            ("created_at_none", {"created_at": None}),
        ]
        for name, overrides in cases:
            temp_dir = _paths.fresh_test_dir(f"canonical-lifecycle-required-{name}")
            store = CanonicalLifecycleStore(temp_dir)
            kwargs = _event_kwargs(
                previous_ids=["atom_required_old"], target_ids=["atom_required_new"]
            )
            kwargs.update(overrides)
            before_workspace = _workspace_snapshot(temp_dir)

            with self.subTest(name=name):
                with self.assertRaises(ContractValidationError):
                    record_canonical_lifecycle_event(lifecycle_store=store, **kwargs)
                self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)
                self.assertEqual(_lifecycle_relative_paths(temp_dir), [])

    def test_malformed_lifecycle_shapes_fail_without_any_writes(self) -> None:
        cases = [
            ("split_one_target", {"event_type": "split", "target_ids": ["atom_target"]}),
            ("merge_one_previous", {"event_type": "merge", "target_ids": ["atom_target"]}),
            ("archive_with_target", {"event_type": "archive", "target_ids": ["atom_target"]}),
            ("deprecate_with_target", {"event_type": "deprecate", "target_ids": ["atom_target"]}),
            ("supersede_without_target", {"event_type": "supersede", "target_ids": []}),
            (
                "supersede_multiple_targets",
                {"event_type": "supersede", "target_ids": ["atom_target_a", "atom_target_b"]},
            ),
            (
                "equivalence_multiple_previous",
                {
                    "event_type": "equivalence",
                    "previous_ids": ["atom_old_a", "atom_old_b"],
                    "target_ids": ["atom_target"],
                },
            ),
            (
                "overlapping_previous_target",
                {
                    "event_type": "supersede",
                    "previous_ids": ["atom_same"],
                    "target_ids": ["atom_same"],
                },
            ),
            (
                "duplicate_previous_ids",
                {
                    "event_type": "merge",
                    "previous_ids": ["atom_dup", "atom_dup"],
                    "target_ids": ["atom_target"],
                },
            ),
            (
                "duplicate_target_ids",
                {
                    "event_type": "split",
                    "previous_ids": ["atom_old"],
                    "target_ids": ["atom_dup_target", "atom_dup_target"],
                },
            ),
        ]
        for name, overrides in cases:
            temp_dir = _paths.fresh_test_dir(f"canonical-lifecycle-shape-{name}")
            store = CanonicalLifecycleStore(temp_dir)
            overrides = dict(overrides)
            kwargs = _event_kwargs(
                previous_ids=overrides.pop("previous_ids", ["atom_old"]),
                target_ids=overrides.pop("target_ids", ["atom_new"]),
            )
            kwargs.update(overrides)
            before_workspace = _workspace_snapshot(temp_dir)

            with self.subTest(name=name):
                with self.assertRaises(ContractValidationError):
                    record_canonical_lifecycle_event(lifecycle_store=store, **kwargs)
                self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)
                self.assertEqual(_lifecycle_relative_paths(temp_dir), [])

    def test_raw_references_are_rejected_without_echo_or_any_write(self) -> None:
        cases = [
            ("metadata_tmp_path", "/tmp/customer-secret.pdf"),
            ("metadata_etc_path", "/etc/passwd"),
            ("metadata_workspace_path", "/workspace/private.xlsx"),
            ("metadata_users_path", "/Users/alice/file.pdf"),
            ("metadata_home_path", "/home/alice/file.pdf"),
            ("metadata_dot_relative", "../secret.pdf"),
            ("metadata_dot_current", "./secret.pdf"),
            ("metadata_relative", "docs/secrets"),
            ("metadata_extension_relative", "reports/private.pdf"),
            ("metadata_windows_relative", r"..\\secret.pdf"),
            ("metadata_unc_path", r"\\nas\\share\\secret.txt"),
            ("metadata_locator", "formowl://asset/asset_secret"),
            ("metadata_s3", "s3://private-bucket/customer-secret.pdf"),
            ("metadata_assignment_absolute", "path=/workspace/private.xlsx"),
            ("metadata_parenthesized_absolute", "(/tmp/customer-secret.pdf)"),
            ("metadata_colon_relative", "source:../secret.pdf"),
            ("metadata_parenthesized_relative", "(docs/secrets)"),
            ("metadata_sql", "select * from assets"),
        ]
        for name, raw_value in cases:
            temp_dir = _paths.fresh_test_dir(f"canonical-lifecycle-raw-{name}")
            store = CanonicalLifecycleStore(temp_dir)
            kwargs = _event_kwargs(
                previous_ids=["atom_raw_old"],
                target_ids=["atom_raw_new"],
                metadata={"source": raw_value},
            )
            before_workspace = _workspace_snapshot(temp_dir)

            with self.subTest(name=name):
                with self.assertRaises(ContractValidationError) as ctx:
                    record_canonical_lifecycle_event(lifecycle_store=store, **kwargs)
                self.assertNotIn(raw_value, str(ctx.exception))
                self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)
                self.assertEqual(_lifecycle_relative_paths(temp_dir), [])

        temp_dir = _paths.fresh_test_dir("canonical-lifecycle-raw-source-ref-url")
        store = CanonicalLifecycleStore(temp_dir)
        before_workspace = _workspace_snapshot(temp_dir)
        with self.assertRaises(ContractValidationError) as ctx:
            record_canonical_lifecycle_event(
                lifecycle_store=store,
                **_event_kwargs(
                    previous_ids=["atom_raw_source_ref_old"],
                    target_ids=["atom_raw_source_ref_new"],
                    source_refs=[
                        {
                            "source_system": "review_packet",
                            "source_type": "canonical_lifecycle_decision",
                            "source_id": "packet_raw",
                            "source_url": "s3://private-bucket/customer-secret.pdf",
                        }
                    ],
                ),
            )
        self.assertNotIn("s3://private-bucket", str(ctx.exception))
        self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)
        self.assertEqual(_lifecycle_relative_paths(temp_dir), [])

    def test_safe_slash_prose_metadata_is_not_treated_as_raw_path(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-lifecycle-safe-slash-prose")
        store = CanonicalLifecycleStore(temp_dir)

        event = record_canonical_lifecycle_event(
            lifecycle_store=store,
            **_event_kwargs(
                previous_ids=["atom_safe_slash_old"],
                target_ids=["atom_safe_slash_new"],
                metadata={
                    "transition_label": "split/merge review",
                    "availability": "N/A",
                    "standard_hint": "ISO/IEC vocabulary reference",
                },
            ),
        )

        restarted = CanonicalLifecycleStore(temp_dir)
        self.assertEqual(
            restarted.get_event(event.lifecycle_event_id).metadata,
            {
                "transition_label": "split/merge review",
                "availability": "N/A",
                "standard_hint": "ISO/IEC vocabulary reference",
            },
        )
        _assert_only_lifecycle_state(temp_dir)

    def test_previous_id_conflicts_cycles_and_event_id_collisions_do_not_mutate_state(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-lifecycle-conflicts")
        store = CanonicalLifecycleStore(temp_dir)
        first = record_canonical_lifecycle_event(
            lifecycle_store=store,
            **_event_kwargs(
                previous_ids=["atom_conflict_old"],
                target_ids=["atom_conflict_new"],
                metadata={"reason": "first"},
            ),
        )
        before_failures = _workspace_snapshot(temp_dir)

        failure_kwargs = [
            _event_kwargs(
                previous_ids=["atom_conflict_old"],
                target_ids=["atom_conflict_new"],
                metadata={"reason": "same_id_different_payload"},
            ),
            _event_kwargs(
                previous_ids=["atom_conflict_old"],
                target_ids=["atom_conflict_other"],
                created_at="2026-06-25T11:00:00+00:00",
            ),
            _event_kwargs(
                previous_ids=["atom_conflict_new"],
                target_ids=["atom_conflict_old"],
                created_at="2026-06-25T11:05:00+00:00",
            ),
        ]
        for kwargs in failure_kwargs:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ContractValidationError):
                    record_canonical_lifecycle_event(lifecycle_store=store, **kwargs)
                self.assertEqual(_workspace_snapshot(temp_dir), before_failures)

        self.assertEqual(_lifecycle_relative_paths(temp_dir), [f"{first.lifecycle_event_id}.json"])
        self.assertEqual(store.get_event(first.lifecycle_event_id).to_dict(), first.to_dict())
        resolution = resolve_canonical_lifecycle_id(
            lifecycle_store=store,
            record_kind="atom",
            canonical_id="atom_conflict_old",
        )
        self.assertEqual(resolution.current_ids, ["atom_conflict_new"])
        self.assertEqual(resolution.resolution_status, "superseded")
        _assert_only_lifecycle_state(temp_dir)

    def test_resolver_follows_multi_hop_split_then_merge_for_all_record_kinds(self) -> None:
        for index, kind in enumerate(_RECORD_KINDS):
            temp_dir = _paths.fresh_test_dir(f"canonical-lifecycle-multihop-{kind}")
            store = CanonicalLifecycleStore(temp_dir)
            split = record_canonical_lifecycle_event(
                lifecycle_store=store,
                **_event_kwargs(
                    record_kind=kind,
                    event_type="split",
                    previous_ids=[f"{kind}_legacy"],
                    target_ids=[f"{kind}_part_a", f"{kind}_part_b"],
                    created_at=f"2026-06-25T11:{index:02d}:00+00:00",
                ),
            )
            merge = record_canonical_lifecycle_event(
                lifecycle_store=store,
                **_event_kwargs(
                    record_kind=kind,
                    event_type="merge",
                    previous_ids=[f"{kind}_part_a", f"{kind}_part_b"],
                    target_ids=[f"{kind}_summary"],
                    created_at=f"2026-06-25T11:{index + 10:02d}:00+00:00",
                ),
            )
            restarted = CanonicalLifecycleStore(temp_dir)

            for canonical_id in (f"{kind}_legacy", f"{kind}_part_a", f"{kind}_part_b"):
                with self.subTest(kind=kind, canonical_id=canonical_id):
                    resolution = resolve_canonical_lifecycle_id(
                        lifecycle_store=restarted,
                        record_kind=kind,
                        canonical_id=canonical_id,
                    )
                    self.assertEqual(resolution.resolution_status, "merged")
                    self.assertEqual(resolution.current_ids, [f"{kind}_summary"])
                    self.assertIn(merge.lifecycle_event_id, resolution.lifecycle_event_ids)
                    if canonical_id == f"{kind}_legacy":
                        self.assertEqual(
                            resolution.lifecycle_event_ids,
                            [split.lifecycle_event_id, merge.lifecycle_event_id],
                        )
                        self.assertEqual(
                            resolution.to_dict()["lifecycle_event_ids"],
                            [split.lifecycle_event_id, merge.lifecycle_event_id],
                        )
            _assert_only_lifecycle_state(temp_dir)

    def test_public_event_and_resolution_serialization_reject_malformed_payloads_without_write(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-lifecycle-public-serialization")
        before_workspace = _workspace_snapshot(temp_dir)
        payload = _event_payload()

        missing_policy = dict(payload)
        missing_policy.pop("lifecycle_policy_id")
        with self.assertRaises(ContractValidationError):
            CanonicalLifecycleEvent.from_dict(missing_policy)
        self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)

        raw_payload = dict(payload)
        raw_payload["metadata"] = {"source": "/tmp/customer-secret.pdf"}
        with self.assertRaises(ContractValidationError) as ctx:
            CanonicalLifecycleEvent.from_dict(raw_payload)
        self.assertNotIn("/tmp/customer-secret.pdf", str(ctx.exception))
        self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)

        invalid_event = CanonicalLifecycleEvent(
            lifecycle_event_id="life_serialization_invalid",
            record_kind="atom",
            event_type="supersede",
            scope_type="workspace",
            scope_id="workspace_formowl",
            previous_ids=["atom_serialization_old"],
            target_ids=["atom_serialization_new"],
            canonical_graph_revision_id="graph_revision_lifecycle_required",
            ontology_revision_id="ontology_revision_lifecycle_001",
            lifecycle_policy_id="lifecycle_policy_lifecycle_001",
            review_decision_ids=["review_decision_lifecycle_001"],
            created_at="not-a-timestamp",
            created_by="user_reviewer_lifecycle",
        )
        with self.assertRaises(ContractValidationError):
            invalid_event.to_dict()

        invalid_resolution = CanonicalLifecycleResolution(
            record_kind="atom",
            requested_id="atom_old",
            resolution_status="unexpected",
            current_ids=["atom_new"],
        )
        with self.assertRaises(ContractValidationError):
            invalid_resolution.to_dict()

        self.assertEqual(_workspace_snapshot(temp_dir), before_workspace)
        self.assertEqual(_lifecycle_relative_paths(temp_dir), [])


def _valid_lifecycle_shape(
    kind: str,
    event_type: str,
    index: int,
) -> tuple[list[str], list[str], str, list[str]]:
    prefix = f"{kind}_{event_type}_{index}"
    if event_type == "split":
        return (
            [f"{prefix}_old"],
            [f"{prefix}_child_a", f"{prefix}_child_b"],
            "split",
            [
                f"{prefix}_child_a",
                f"{prefix}_child_b",
            ],
        )
    if event_type == "merge":
        return (
            [f"{prefix}_old_a", f"{prefix}_old_b"],
            [f"{prefix}_merged"],
            "merged",
            [f"{prefix}_merged"],
        )
    if event_type == "archive":
        return [f"{prefix}_old"], [], "archived", [f"{prefix}_old"]
    if event_type == "deprecate":
        return [f"{prefix}_old"], [], "deprecated", [f"{prefix}_old"]
    if event_type == "supersede":
        return [f"{prefix}_old"], [f"{prefix}_current"], "superseded", [f"{prefix}_current"]
    if event_type == "equivalence":
        return [f"{prefix}_old"], [f"{prefix}_equivalent"], "equivalent", [f"{prefix}_equivalent"]
    raise AssertionError(f"unsupported event type fixture: {event_type}")


def _event_kwargs(
    *,
    previous_ids: list[str],
    target_ids: list[str],
    event_type: str = "supersede",
    record_kind: str = "atom",
    created_at: str = "2026-06-25T10:00:00+00:00",
    source_refs: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "record_kind": record_kind,
        "event_type": event_type,
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "previous_ids": previous_ids,
        "target_ids": target_ids,
        "canonical_graph_revision_id": "graph_revision_lifecycle_required",
        "ontology_revision_id": "ontology_revision_lifecycle_001",
        "lifecycle_policy_id": "lifecycle_policy_lifecycle_001",
        "review_decision_ids": ["review_decision_lifecycle_001"],
        "created_by": "user_reviewer_lifecycle",
        "created_at": created_at,
        "source_refs": source_refs or [],
        "metadata": metadata or {},
    }


def _event_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "lifecycle_event_id": "life_serialization_001",
        "record_kind": "atom",
        "event_type": "supersede",
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "previous_ids": ["atom_serialization_old"],
        "target_ids": ["atom_serialization_new"],
        "canonical_graph_revision_id": "graph_revision_lifecycle_required",
        "ontology_revision_id": "ontology_revision_lifecycle_001",
        "lifecycle_policy_id": "lifecycle_policy_lifecycle_001",
        "review_decision_ids": ["review_decision_lifecycle_001"],
        "created_at": "2026-06-25T10:00:00+00:00",
        "created_by": "user_reviewer_lifecycle",
        "source_refs": [],
        "evidence_snapshot_ids": [],
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _lifecycle_relative_paths(temp_dir) -> list[str]:
    root = temp_dir / "graph" / "canonical-lifecycle-events"
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _assert_only_lifecycle_state(temp_dir) -> None:
    allowed_prefix = "graph/canonical-lifecycle-events/"
    allowed_dir = "graph/canonical-lifecycle-events/"
    for path in _workspace_relative_paths(temp_dir):
        if path in ("graph/", allowed_dir):
            continue
        if path.startswith(allowed_prefix) and path.endswith(".json"):
            continue
        raise AssertionError(f"unexpected lifecycle side effect: {path}")


def _workspace_relative_paths(temp_dir) -> list[str]:
    return sorted(
        f"{path.relative_to(temp_dir).as_posix()}/"
        if path.is_dir()
        else path.relative_to(temp_dir).as_posix()
        for path in temp_dir.rglob("*")
    )


def _workspace_snapshot(temp_dir) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(temp_dir.rglob("*")):
        relative = path.relative_to(temp_dir).as_posix()
        if path.is_file():
            snapshot[relative] = path.read_bytes()
        else:
            snapshot[f"{relative}/"] = b""
    return snapshot


if __name__ == "__main__":
    unittest.main()
