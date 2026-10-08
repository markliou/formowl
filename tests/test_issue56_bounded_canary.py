from __future__ import annotations

import hashlib
import json
import ast
from contextlib import redirect_stdout
from dataclasses import replace
import errno
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, PermissionScope, SourceRef, sha256_json
from scripts.issue56_bounded_canary import (
    bounded_reference_prefix,
    bounded_revision_id,
    extract_mcp_citation_response,
    load_bounded_metadata,
    parse_bounded_args,
    validate_bounded_revision_report,
    write_bounded_metadata,
)
from scripts.issue56_uat_web import (
    _authorized_ingestion_root_source_kinds,
    _build_ingestion_revision,
    _finish_indexed_ingestion_revision,
    _finish_prepared_ingestion_revision,
)
from scripts import issue56_uat_web as uat_web
from formowl_mail import hybrid
from formowl_mail import issue56_sealed_source as sealed_source
from formowl_mail.semantic_plan import (
    AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extractors.mail import FixtureMailArchiveExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetStore, ExtractorRunStore, FileObjectStore, JobStore, ObservationStore, StorageBackendRegistry,
)
from formowl_mail.import_workflow import (
    CompletedIngestionJobAuthority, open_completed_ingestion_job_reader,
)
from test_issue56_hybrid_batch_encoding import _MemoryProjectionStore, _PinnedModel, _pinned_runtime
from test_issue56_uat_handler_composition import _completed_registered_text_revision_fixture
from test_mail_evidence_mcp_gateway import _mail_archive, NOW


def _indexed_mixed_fixture(root):
    """Actual completed synthetic jobs; no private payload or live backend."""
    mail_root, text_root = root / "mail", root / "text"
    mail_root.mkdir()
    text_root.mkdir()
    path = mail_root / "synthetic-mail.json"
    path.write_text(json.dumps(_mail_archive()))
    registry = StorageBackendRegistry(mail_root)
    backend = registry.register_local_backend(
        mail_root / "objects", workspace_scope=sealed_source.WORKSPACE_ID,
    )
    objects = FileObjectStore(registry)
    stores = {
        "asset_store": AssetStore(mail_root), "job_store": JobStore(mail_root),
        "extractor_run_store": ExtractorRunStore(mail_root),
        "observation_store": ObservationStore(mail_root),
    }
    asset = register_asset_from_local_file(
        path, object_store=objects, asset_store=stores["asset_store"],
        storage_backend_id=backend.storage_backend_id,
        workspace_id=sealed_source.WORKSPACE_ID, owner_user_id=sealed_source.APPROVER_ACTOR,
        permission_scope=PermissionScope.project("project_mail"),
        source_ref=SourceRef(
            source_system="formowl_upload_session", source_type="mail_archive_upload",
            source_id="synthetic_upload", source_key="synthetic_upload",
        ),
        mime_type="application/vnd.formowl.mail-archive+json",
        created_at=NOW, registered_at=NOW,
    )
    adapters = (FixtureMailArchiveExtractor(),)
    job = create_ingestion_job(
        asset=asset, job_store=stores["job_store"], requested_by=sealed_source.APPROVER_ACTOR,
        extractor_adapters=adapters, created_at=NOW,
    )
    job = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id, **stores, object_store=objects,
        extractor_adapters=adapters, started_at=NOW, completed_at=NOW,
    )
    reader = open_completed_ingestion_job_reader(
        job.ingestion_job_id, **stores, requester_user_id=sealed_source.APPROVER_ACTOR,
        workspace_id=sealed_source.WORKSPACE_ID,
    )
    mail = tuple(item for item in reader.iter_observations() if item.observation_type in {
        "email_message", "email_header", "email_body_segment", "email_attachment_occurrence",
    })
    _, documents, text_authority = _completed_registered_text_revision_fixture(
        text_root, owner_user_id=sealed_source.APPROVER_ACTOR,
    )
    authorities = (reader.authority, text_authority)
    snapshot = {
        "observation_references": [
            [index, item.observation_id, sha256_json(item.to_dict())]
            for index, observations in enumerate((mail, documents)) for item in observations
        ],
        "job_store_bindings": [
            {
                "job_index": index, "store_directory": str(directory),
                "ingestion_job_id": authority.ingestion_job_id,
                "job_fingerprint": authority.job_fingerprint,
                "observation_count": authority.observation_count,
            }
            for index, (directory, authority) in enumerate(
                zip((mail_root, text_root), authorities, strict=True),
            )
        ],
        "source_binding": {
            "source_authority_fingerprint": sha256_json([item.job_fingerprint for item in authorities]),
            "extraction_coverage": {"source_completeness_certified": False},
        },
    }
    return snapshot, (*mail, *documents), authorities


class Issue56BoundedCanaryTests(unittest.TestCase):
    def test_independent_root_composition_rejects_mutated_authority_and_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, _observations, authorities = _indexed_mixed_fixture(root)
            jobs = [[b["store_directory"], b["ingestion_job_id"]]
                    for b in snapshot["job_store_bindings"]]
            with (
                patch("formowl_core.load_issue56_target_runtime_components",
                      return_value=_pinned_runtime(_PinnedModel())),
                redirect_stdout(io.StringIO()),
            ):
                base = Path(_build_ingestion_revision(
                    root / "mail_prepared", jobs[:1], prepare_only=True,
                )["preparation_directory"])
                document = Path(_build_ingestion_revision(
                    root / "text_prepared", jobs[1:], prepare_only=True,
                )["preparation_directory"])
            original_job_get, original_asset_get = JobStore.get, AssetStore.get

            def changed_job(store, job_id):
                job = original_job_get(store, job_id)
                return (replace(job, completed_at="2026-10-01T00:00:00+00:00")
                        if job_id == authorities[1].ingestion_job_id else job)

            def changed_scope(store, asset_id):
                asset = original_asset_get(store, asset_id)
                return (replace(asset, permission_scope=PermissionScope.project("changed_scope"))
                        if asset_id == authorities[1].asset.asset_id else asset)

            for name, owner, method, changed in (
                ("job", JobStore, "get", changed_job),
                ("scope", AssetStore, "get", changed_scope),
            ):
                with (
                    self.subTest(name=name), patch.object(owner, method, changed),
                    self.assertRaises((ValueError, ContractValidationError)),
                ):
                    uat_web._compose_independent_root_preparation(
                        root / name, base_preparation_directory=base,
                        document_preparation_directory=document,
                    )
                self.assertFalse((root / f".{name}.preembedding").exists())
            with self.assertRaisesRegex(ValueError, "document authority"):
                uat_web._compose_independent_root_preparation(
                    root / "root_collision", base_preparation_directory=document,
                    document_preparation_directory=document,
                )
            # Valid outer hashes cannot disguise an Observation-ID collision.
            payload = json.loads((document / "observations.json").read_bytes())
            payload["observation_references"][0][1] = json.loads(
                (base / "observations.json").read_bytes(),
            )["observation_references"][0][1]
            raw = json.dumps(payload, sort_keys=True).encode()
            (document / "observations.json").write_bytes(raw)
            preparation = json.loads((document / "preparation.json").read_bytes())
            preparation.pop("preparation_fingerprint")
            preparation.update(snapshot_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
                               snapshot_size_bytes=len(raw))
            (document / "preparation.json").write_text(json.dumps({
                **preparation, "preparation_fingerprint": sha256_json(preparation),
            }))
            with self.assertRaisesRegex(ValueError, "reference collision"):
                uat_web._compose_independent_root_preparation(
                    root / "reference_collision", base_preparation_directory=base,
                    document_preparation_directory=document,
                )
            self.assertFalse((root / ".reference_collision.preembedding").exists())

    def test_registered_plaintext_root_rejects_attachment_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _snapshot, _observations, authorities = _indexed_mixed_fixture(Path(directory))
            authority = authorities[1]
            self.assertEqual(_authorized_ingestion_root_source_kinds(authority),
                             {AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND})
            for system, kind in (
                ("formowl_mail_attachment", "document"),
                ("registered_document", "email_attachment_occurrence"),
            ):
                with self.subTest(system=system, kind=kind):
                    attachment = replace(authority.asset, source_ref=SourceRef(
                        source_system=system, source_type=kind, source_id="synthetic_attachment",
                    ))
                    with self.assertRaisesRegex(ValueError, "source root family is unsupported"):
                        _authorized_ingestion_root_source_kinds(replace(authority, asset=attachment))

    def test_indexed_mixed_mail_plaintext_build_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, observations, authorities = _indexed_mixed_fixture(root)
            runtime = _pinned_runtime(_PinnedModel())
            jobs = [[item["store_directory"], item["ingestion_job_id"]]
                    for item in snapshot["job_store_bindings"]]
            with (
                patch("formowl_core.load_issue56_target_runtime_components", return_value=runtime),
                patch.object(runtime.dense_encoder._model, "encode",
                             side_effect=AssertionError("prepare_only must not embed")),
                redirect_stdout(io.StringIO()),
            ):
                base = _build_ingestion_revision(
                    root / "mail_revision", jobs[:1], prepare_only=True,
                )
                document = _build_ingestion_revision(
                    root / "document_revision", jobs[1:], prepare_only=True,
                )
            base_dir = Path(base["preparation_directory"])
            before = {p.relative_to(base_dir): p.read_bytes()
                      for p in base_dir.rglob("*") if p.is_file()}
            load_record = CompletedIngestionJobAuthority.load_indexed_observation

            def document_only(authority, *args, **kwargs):
                self.assertEqual(authority.asset.asset_id, authorities[1].asset.asset_id,
                                 "composition must not hydrate old mail Observations")
                return load_record(authority, *args, **kwargs)

            with patch.object(CompletedIngestionJobAuthority, "load_indexed_observation",
                              document_only):
                prepared = uat_web._compose_independent_root_preparation(
                    root / "mixed_revision", base_preparation_directory=base_dir,
                    document_preparation_directory=Path(document["preparation_directory"]),
                )
            self.assertEqual(before, {p.relative_to(base_dir): p.read_bytes()
                                      for p in base_dir.rglob("*") if p.is_file()})
            self.assertEqual(prepared["embedding_status"], "not_started")
            preparation_dir = Path(prepared["preparation_directory"])
            snapshot_bytes = (preparation_dir / "observations.json").read_bytes()
            snapshot = json.loads(snapshot_bytes)
            preparation = json.loads((preparation_dir / "preparation.json").read_bytes())
            self.assertEqual(preparation["requested_jobs"], jobs)
            self.assertEqual(preparation["snapshot_sha256"],
                             "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest())
            self.assertEqual(preparation["source_observation_count"],
                             sum(item.observation_count for item in authorities))
            references = {item[1]: (item[0], item[2])
                          for item in snapshot["observation_references"]}
            for observation in observations:
                self.assertEqual(references[observation.observation_id], (
                    1 if observation.modality == "text" else 0,
                    sha256_json(observation.to_dict()),
                ))
            self.assertEqual(
                [item["job_fingerprint"] for item in snapshot["job_store_bindings"]],
                [item.job_fingerprint for item in authorities],
            )
            exact_bytes = (preparation_dir / "exact-cells" / "manifest.json").read_bytes()
            self.assertEqual(preparation["exact_lookup_manifest_sha256"],
                             "sha256:" + hashlib.sha256(exact_bytes).hexdigest())
            self.assertEqual(json.loads(exact_bytes)["job_count"], 2)
            stores = []

            def new_store(connection, **kwargs):
                store = _MemoryProjectionStore(connection, **kwargs)
                stores.append(store)
                return store

            with (
                patch("formowl_graph.index.records.PostgreSQLGraphProjectionStore", new_store),
                patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=runtime),
                patch.object(CompletedIngestionJobAuthority, "open_reader",
                             side_effect=AssertionError("full-source discovery forbidden")),
                redirect_stdout(io.StringIO()),
            ):
                report = _finish_prepared_ingestion_revision(
                    root / "mixed_revision", preparation_dir, started=0,
                    projection_connection=Mock(), max_candidates=128,
                )
            store = stores[0]
            manifest = store.reopen(store.seal_hash)
            self.assertEqual(manifest["view_metadata"]["source_families"], ["document_text", "mail"])
            self.assertEqual(manifest["counts"]["candidate"], len(observations))
            self.assertEqual(report["retrieval_observation_count"], len(observations))
            self.assertEqual(manifest["counts"]["helper"], len(observations))
            # Fresh lazy owner reopens the sealed projection, not source scans or embeddings.
            reopened_store = _MemoryProjectionStore(
                Mock(), revision_id=store.revision_id, workspace_id=store.workspace_id,
                binding=store.binding,
            )
            reopened_store.rows = store.rows
            reopened_store.vectors = store.vectors
            with (
                patch.object(runtime.dense_encoder._model, "encode",
                             side_effect=AssertionError("reopen must not re-embed")),
                patch.object(CompletedIngestionJobAuthority, "open_reader",
                             side_effect=AssertionError("reopen must not rescan")),
            ):
                records = sealed_source.IngestionRevisionSourceRecords(
                    runtime_store=reopened_store, job_authorities=authorities,
                    requester_user_id=sealed_source.APPROVER_ACTOR,
                    workspace_id=sealed_source.WORKSPACE_ID, expected_seal=store.seal_hash,
                )
                session = hybrid.reopen_authorized_semantic_observation_session(
                    runtime_store=reopened_store, expected_seal=store.seal_hash,
                    requester_user_id=sealed_source.APPROVER_ACTOR, runtime_components=runtime,
                )
                view = hybrid.reopen_authorized_effective_graph_view(session=session)
                self.assertEqual(
                    session.authorized_source.source_kind,
                    AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND,
                )
                for observation in observations:
                    observation_hash = sha256_json(observation.to_dict())
                    self.assertEqual(records.get_observation(observation.observation_id), observation)
                    helper = reopened_store.get_helper(observation.observation_id)
                    self.assertEqual(helper["observation_hash"], observation_hash)
                    self.assertEqual(
                        helper["retrieval_source_family"],
                        "document_text" if observation.modality == "text" else "mail",
                    )
                    self.assertIsNotNone(reopened_store.candidate_for_observation(observation_hash))
                    self.assertTrue(reopened_store.nodes_for_observation(observation.observation_id))
                self.assertTrue(view.visible_nodes)
            with self.assertRaisesRegex(ContractValidationError, "job seals changed"):
                sealed_source.IngestionRevisionSourceRecords(
                    runtime_store=reopened_store,
                    job_authorities=(authorities[0], replace(
                        authorities[1], job_fingerprint=sha256_json("different authority"),
                    )),
                    requester_user_id=sealed_source.APPROVER_ACTOR,
                    workspace_id=sealed_source.WORKSPACE_ID, expected_seal=store.seal_hash,
                )

    def test_independent_root_composition_falls_back_across_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, _observations, _authorities = _indexed_mixed_fixture(root)
            jobs = [[item["store_directory"], item["ingestion_job_id"]]
                    for item in snapshot["job_store_bindings"]]
            with (
                patch("formowl_core.load_issue56_target_runtime_components",
                      return_value=_pinned_runtime(_PinnedModel())),
                redirect_stdout(io.StringIO()),
            ):
                base = Path(_build_ingestion_revision(
                    root / "mail_revision", jobs[:1], prepare_only=True,
                )["preparation_directory"])
                document = Path(_build_ingestion_revision(
                    root / "document_revision", jobs[1:], prepare_only=True,
                )["preparation_directory"])
            base_before = {
                path.relative_to(base): path.read_bytes()
                for path in base.rglob("*")
                if path.is_file()
            }
            callback_paths = []
            original_link_or_copy = uat_web._link_or_copy_file_atomic

            def record_callback_paths(source, destination):
                callback_paths.append((source, destination))
                return original_link_or_copy(source, destination)

            with patch.object(
                uat_web.os,
                "link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ):
                uat_web._copytree_atomic(
                    str(base / "exact-cells"),
                    str(root / "string_callback_copy"),
                    copy_function=record_callback_paths,
                )
            self.assertTrue(
                any(isinstance(source, str) and isinstance(destination, str)
                    for source, destination in callback_paths),
                "copytree must pass string paths to its copy callback",
            )
            with patch.object(
                uat_web.os,
                "link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ):
                result = uat_web._compose_independent_root_preparation(
                    root / "mixed_revision",
                    base_preparation_directory=base,
                    document_preparation_directory=document,
                )
            output = Path(result["preparation_directory"])
            self.assertEqual(
                base_before,
                {
                    path.relative_to(base): path.read_bytes()
                    for path in base.rglob("*")
                    if path.is_file()
                },
            )
            snapshot_bytes = (output / "observations.json").read_bytes()
            exact_bytes = (output / "exact-cells" / "manifest.json").read_bytes()
            preparation = json.loads((output / "preparation.json").read_bytes())
            preparation_fingerprint = preparation.pop("preparation_fingerprint")
            self.assertEqual(
                preparation["snapshot_sha256"],
                "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest(),
            )
            self.assertEqual(
                preparation["exact_lookup_manifest_sha256"],
                "sha256:" + hashlib.sha256(exact_bytes).hexdigest(),
            )
            self.assertEqual(preparation_fingerprint, sha256_json(preparation))
            self.assertFalse((output / "exact-cells").is_symlink())

    def test_indexed_function_preserves_full_and_bounded_paths(self) -> None:
        import formowl_graph.index.records as records_module
        import formowl_mail.hybrid as hybrid_module
        import formowl_mail.issue56_sealed_source as sealed_source_module
        import formowl_core.dense_embedding as dense_module

        class Authority:
            permission_scope = {
                "scope_type": "project", "scope_id": "scope-1",
                "visibility": "restricted",
            }
            job_fingerprint = "job-fingerprint"
            asset = SimpleNamespace(
                asset_id="synthetic_mail_asset", content_hash="synthetic_hash",
                source_ref=None,
            )
            runs = (SimpleNamespace(
                asset_id="synthetic_mail_asset", input_hash="synthetic_hash",
                status="succeeded", extractor_type="mail_archive",
            ),)

        class Store:
            seal_hash = "seal-hash"

            def __init__(self, connection, *, revision_id, workspace_id, binding):
                self.revision_id = revision_id
                self.binding = binding
                self.checkpoints = []
                self.reopened = None

            def checkpoint(self, *args):
                self.checkpoints.append(args)

            def reopen(self, seal_hash):
                self.reopened = seal_hash

        class Records:
            calls = []

            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def index_prepared_references(self, references, **kwargs):
                type(self).calls.append((list(references), kwargs))

        class Index:
            candidates = ("candidate-1",)
            index_fingerprint = "index-fingerprint"

        class Session:
            index = Index()
            source_session_binding_fingerprint = "session-binding"

        class Graph:
            def to_safe_dict(self):
                return {"graph": "safe"}

        authority = Authority()
        source = Mock(authorization_fingerprint="source-fingerprint")
        preparation = {
            "snapshot_sha256": "snapshot-fingerprint",
            "source_observation_count": 3,
            "exact_lookup_manifest_sha256": "exact-fingerprint",
        }
        source_binding = {
            "source_authority_fingerprint": "authority-fingerprint",
            "extraction_coverage": {},
        }
        references = [["0", "observation-1", "hash-1"], ["0", "observation-2", "hash-2"],
                      ["0", "observation-3", "hash-3"]]
        snapshot = {
            "observation_references": references,
            "source_binding": source_binding,
            "job_store_bindings": [{"job_index": 0}],
        }
        bounded_module = __import__(
            "scripts.issue56_bounded_canary", fromlist=["validate_bounded_revision_report"]
        )
        for max_candidates, expected_id, expected_count in (
            (None, "full-revision", 3),
            (2, "full-revision.bounded-2", 2),
        ):
            with self.subTest(max_candidates=max_candidates), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory = root / "full-revision"
                preparation_directory = root / "preparation"
                (preparation_directory / "exact-cells").mkdir(parents=True)
                (preparation_directory / "exact-cells" / "manifest.json").write_text("{}")
                Records.calls.clear()
                with patch.object(
                    sealed_source_module,
                    "open_ingestion_revision_job_authorities",
                    return_value=[authority],
                ), patch.object(
                    sealed_source_module,
                    "IngestionRevisionSourceRecords", Records,
                ), patch.object(
                    records_module, "PostgreSQLGraphProjectionStore", Store,
                ), patch.object(
                    hybrid_module, "validated_authorized_semantic_source",
                    return_value=source,
                ), patch.object(
                    hybrid_module, "build_authorized_semantic_observation_session",
                    return_value=Session(),
                ), patch.object(
                    hybrid_module, "build_authorized_source_backed_effective_graph_view",
                    return_value=Graph(),
                ), patch.object(
                    dense_module, "DenseEvidenceVectorCache", Mock(),
                ), patch.object(
                    bounded_module, "validate_bounded_revision_report", Mock(),
                ) as validator:
                    report = _finish_indexed_ingestion_revision(
                        directory, preparation_directory,
                        preparation=preparation.copy(),
                        preparation_fingerprint="preparation-fingerprint",
                        snapshot={
                            **snapshot,
                            "observation_references": list(references),
                            "source_binding": dict(source_binding),
                        },
                        bound_child_failure_exclusions=None,
                        connection=object(), started=0.0,
                        pause_before_embedding_file=None,
                        max_candidates=max_candidates,
                    )
                self.assertEqual(Records.calls[0][0], references[:expected_count])
                self.assertEqual(Records.calls[0][1]["max_candidates"], max_candidates)
                self.assertEqual(report["revision_id"], expected_id)
                if max_candidates is None:
                    self.assertFalse((directory / "exact-cells").is_symlink())
                    self.assertNotIn("bounded_canary_candidate_count", report)
                    validator.assert_not_called()
                else:
                    self.assertTrue((directory / "exact-cells").is_symlink())
                    validator.assert_called_once()

    def test_indexed_root_authority_rejects_unknown_family_or_hash_mismatch(self) -> None:
        for run_fields in (
            {"extractor_type": "unknown_family", "input_hash": "synthetic_hash",
             "extractor_name": "unknown"},
            {"extractor_type": "mail_archive", "input_hash": "different_hash"},
        ):
            with self.subTest(run_fields=run_fields), tempfile.TemporaryDirectory() as directory:
                authority = SimpleNamespace(
                    asset=SimpleNamespace(
                        asset_id="synthetic_asset", content_hash="synthetic_hash", source_ref=None,
                    ),
                    permission_scope=PermissionScope.project("synthetic_scope").to_dict(),
                    runs=(SimpleNamespace(asset_id="synthetic_asset", status="succeeded",
                                          **run_fields),),
                )
                with (
                    patch.object(sealed_source, "open_ingestion_revision_job_authorities",
                                 return_value=(authority,)),
                    patch("formowl_graph.index.records.PostgreSQLGraphProjectionStore") as store,
                    self.assertRaisesRegex(ValueError, "indexed source root"),
                ):
                    _finish_indexed_ingestion_revision(
                        Path(directory) / "revision", Path(directory) / "preparation",
                        preparation={}, preparation_fingerprint="synthetic",
                        snapshot={"observation_references": [], "job_store_bindings": []},
                        bound_child_failure_exclusions=None, connection=Mock(),
                        started=0, pause_before_embedding_file=None,
                    )
                store.assert_not_called()

    def test_max_candidates_is_required_and_applied_before_persistence(self) -> None:
        with self.assertRaises(SystemExit):
            parse_bounded_args([])
        self.assertEqual(parse_bounded_args(["--max-candidates", "128"]).max_candidates, 128)
        with self.assertRaises(ContractValidationError):
            parse_bounded_args(["--max-candidates", "0"])
        with self.assertRaises(ContractValidationError):
            parse_bounded_args(["--max-candidates", "129"])
        references = [["job", index] for index in range(4)]
        self.assertEqual(bounded_reference_prefix(references, 2), references[:2])

    def test_uat_indexed_bounded_branch_rejects_over_maximum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                _finish_indexed_ingestion_revision(
                    Path(directory) / "revision",
                    Path(directory) / "preparation",
                    preparation={},
                    preparation_fingerprint="preparation",
                    snapshot={},
                    bound_child_failure_exclusions=None,
                    connection=object(),
                    started=0.0,
                    pause_before_embedding_file=None,
                    max_candidates=129,
                )

    def test_metadata_path_hash_and_independent_revision_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("bounded=True\n")
            metadata = root / "continuation-bounded.json"
            metadata.write_text(
                json.dumps(
                    {
                        "bounded_canary_candidate_count": 128,
                        "binding": {"source": "existing-checkpoint"},
                        "candidate_checkpoint": {
                            "revision_id": "revision_full",
                        },
                        "code_hashes": {
                            "source.py": hashlib.sha256(source.read_bytes()).hexdigest()
                        },
                    }
                )
            )
            loaded = load_bounded_metadata(
                metadata,
                expected_path=metadata,
                workspace_root=root,
                candidate_limit=128,
            )
            self.assertEqual(loaded["bounded_canary_candidate_count"], 128)
            self.assertEqual(
                bounded_revision_id("revision_full", 128),
                "revision_full.bounded-128",
            )
            with self.assertRaises(ContractValidationError):
                load_bounded_metadata(
                    metadata,
                    expected_path=root / "other.json",
                    workspace_root=root,
                    candidate_limit=128,
                )

    def test_report_requires_matching_revision_and_safe_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = root / "revision.json"
            revision.write_text(json.dumps({"revision_id": "revision_full.bounded-2"}))
            report = {
                "phase": "staged_not_activated",
                "bounded_canary_candidate_count": 2,
                "revision_id": "revision_full.bounded-2",
                "revision_path": "revision.json",
                "source_observation_count": 1,
            }
            validate_bounded_revision_report(
                report,
                revision_id="revision_full.bounded-2",
                candidate_limit=2,
                workspace_root=root,
            )
            with self.assertRaises(ContractValidationError):
                validate_bounded_revision_report(
                    {**report, "revision_path": "../revision.json"},
                    revision_id="revision_full.bounded-2",
                    candidate_limit=2,
                    workspace_root=root,
                )

    def test_metadata_writer_has_no_literal_backslash_newline_or_extra_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuation-bounded.json"
            metadata = {"revision_id": "bounded-128", "candidate_count": 128}
            self.assertEqual(write_bounded_metadata(path, metadata), metadata)
            raw = path.read_bytes()
            self.assertNotEqual(raw[-2:], b"\\n")
            self.assertEqual(json.loads(raw), metadata)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(raw + b"\\n")

    def test_mcp_result_uses_actual_status_error_and_citations(self) -> None:
        query = Mock(status_code=200)
        query.json.return_value = {
            "result": {
                "isError": False,
                "structuredContent": {
                    "data": {"answer": {"citation_count": 3}}
                },
            }
        }
        self.assertEqual(
            extract_mcp_citation_response(query),
            {"http_status": 200, "tool_is_error": False, "citation_count": 3},
        )
        for response in (
            Mock(status_code=201),
            Mock(status_code=200, json=Mock(return_value={
                "result": {
                    "isError": True,
                    "structuredContent": {"data": {"answer": {"citation_count": 3}}},
                }
            })),
        ):
            with self.assertRaises(ContractValidationError):
                extract_mcp_citation_response(response)

    def test_bounded_artifacts_use_copy_and_atomic_rename_across_devices(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "scripts/issue56_uat_web.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        helpers = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_copy_file_atomic", "_copytree_atomic"}
        ]
        namespace = {
            "Path": Path,
            "os": os,
            "shutil": shutil,
            "stat": stat,
            "tempfile": tempfile,
        }
        exec(compile(ast.Module(body=helpers, type_ignores=[]), str(source_path), "exec"), namespace)
        copy_file_atomic = namespace["_copy_file_atomic"]
        copytree_atomic = namespace["_copytree_atomic"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.write_bytes(b"bounded-observation")
            with patch.object(
                os,
                "link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ):
                copy_file_atomic(source, destination)
            self.assertEqual(destination.read_bytes(), source.read_bytes())

            source_tree = root / "source-tree"
            source_tree.mkdir()
            (source_tree / "manifest.json").write_text(
                '{"bounded":true}', encoding="utf-8"
            )
            destination_tree = root / "destination-tree"
            with patch.object(
                os,
                "link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ):
                copytree_atomic(source_tree, destination_tree)
            self.assertEqual(
                (destination_tree / "manifest.json").read_text(encoding="utf-8"),
                '{"bounded":true}',
            )


if __name__ == "__main__":
    unittest.main()
