#!/usr/bin/env python3
"""Serve the minimal Issue #56 real-source browser UAT surface."""

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import resource
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for path in (ROOT, PYTHON_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from formowl_gateway.issue56_uat_runtime import (  # noqa: E402
    create_issue56_temporary_lan_query_service,
    create_issue56_uat_query_service,
)
from formowl_mail.human_uat_http import (  # noqa: E402
    create_mail_human_uat_http_server,
)
from formowl_mail.human_uat_orchestrator import (  # noqa: E402
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    CodexResponsesConversationModel,
    build_hardened_codex_app_server_command,
    validate_codex_runtime_state,
)

_MODEL = "gpt-5.5"
_MAX_PROVIDER_API_KEY_BYTES = 16 * 1024
_MAX_REFERENCE_REPAIR_MANIFEST_BYTES = 1024 * 1024


def _copy_file_atomic(source: Path, destination: Path) -> None:
    """Copy bytes through a same-directory temporary, then atomically publish."""
    source = Path(source)
    destination = Path(destination)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".staging",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _link_or_copy_file_atomic(source: Path, destination: Path) -> Path:
    """Prefer a hardlink, but atomically copy when the source is cross-device."""
    source = Path(source)
    destination = Path(destination)
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        _copy_file_atomic(source, destination)
    return destination


def _copytree_atomic(
    source: Path,
    destination: Path,
    *,
    copy_function=shutil.copy2,
    ignore=None,
) -> None:
    """Copy a directory with ordinary copies, then atomically publish the tree."""
    source = Path(source)
    destination = Path(destination)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    staged = temporary / destination.name
    try:
        shutil.copytree(source, staged, copy_function=copy_function, ignore=ignore)
        os.replace(staged, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _finish_prepared_ingestion_revision(
    directory: Path,
    preparation_directory: Path,
    *,
    started: float,
    prepared_observations: list[object] | None = None,
    prepared_bundles: list[object] | None = None,
    pause_before_embedding_file: Path | None = None,
    pause_before_graph_file: Path | None = None,
    projection_connection: object | None = None,
    max_candidates: int | None = None,
) -> dict:
    """Build or resume from the durable source-pass checkpoint."""
    from formowl_contract import (
        Observation,
        assert_no_public_raw_references,
        sha256_json,
    )
    from formowl_ingestion.storage import (
        AssetStore,
        ExtractorRunStore,
        JobStore,
        ObservationStore,
    )
    from formowl_mail.bundle import MailEvidenceBundle
    from formowl_mail.import_workflow import (
        open_completed_ingestion_job_reader,
    )
    from formowl_mail.hybrid import (
        build_authorized_hybrid_observation_index_artifact,
    )
    from formowl_mail.issue56_sealed_source import (
        APPROVER_ACTOR,
        WORKSPACE_ID,
        _MAX_INGESTION_REVISION_SOURCE_BYTES,
        build_issue56_ingestion_revision,
    )

    resumed_from_preparation = prepared_observations is None
    preparation_path = preparation_directory / "preparation.json"
    snapshot_path = preparation_directory / "observations.json"
    exact_directory = preparation_directory / "exact-cells"
    preparation_bytes = preparation_path.read_bytes()
    preparation = json.loads(preparation_bytes)
    preparation_fingerprint = preparation.pop("preparation_fingerprint", None)
    if snapshot_path.stat().st_size > _MAX_INGESTION_REVISION_SOURCE_BYTES:
        raise ValueError("ingestion revision preparation exceeds source size cap")
    snapshot_bytes = snapshot_path.read_bytes()
    if (
        preparation.get("artifact_id") != "formowl_issue56_ingestion_revision_preparation_v1"
        or preparation_fingerprint != sha256_json(preparation)
        or preparation.get("snapshot_size_bytes") != len(snapshot_bytes)
        or preparation.get("snapshot_sha256")
        != "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()
        or len(snapshot_bytes) > _MAX_INGESTION_REVISION_SOURCE_BYTES
        or not exact_directory.is_dir()
    ):
        raise ValueError("ingestion revision preparation checkpoint is invalid")
    exact_manifest_bytes = (exact_directory / "manifest.json").read_bytes()
    if preparation.get("exact_lookup_manifest_sha256") != (
        "sha256:" + hashlib.sha256(exact_manifest_bytes).hexdigest()
    ):
        raise ValueError("ingestion revision exact checkpoint is invalid")
    parent_binding_sha256 = preparation.get("sidecar_parent_binding_sha256")
    if parent_binding_sha256 is not None:
        parent_binding_bytes = (preparation_directory / "sidecar-parent-binding.json").read_bytes()
        if parent_binding_sha256 != ("sha256:" + hashlib.sha256(parent_binding_bytes).hexdigest()):
            raise ValueError("ingestion revision sidecar parent checkpoint is invalid")
    bound_child_failure_binding = preparation.get("bound_child_failure_binding")
    bound_child_failure_exclusions: dict[str, object] | None = None
    if bound_child_failure_binding is not None:
        bound_child_failure_bytes = (
            preparation_directory / "bound-child-failure-exclusions.json"
        ).read_bytes()
        if (
            bound_child_failure_binding.get("manifest_byte_sha256")
            != "sha256:" + hashlib.sha256(bound_child_failure_bytes).hexdigest()
        ):
            raise ValueError("ingestion revision child failure checkpoint is invalid")
        bound_child_failure_exclusions = json.loads(bound_child_failure_bytes)
    snapshot = json.loads(snapshot_bytes)
    source_binding = snapshot.get("source_binding")
    job_store_bindings = snapshot.get("job_store_bindings")
    if not isinstance(source_binding, dict) or not isinstance(job_store_bindings, list):
        raise ValueError("ingestion revision preparation snapshot is invalid")
    if projection_connection is not None:
        if prepared_observations is not None or prepared_bundles is not None:
            raise ValueError("indexed build requires the reference-only checkpoint")
        del snapshot_bytes
        return _finish_indexed_ingestion_revision(
            directory,
            preparation_directory,
            preparation=preparation,
            preparation_fingerprint=preparation_fingerprint,
            snapshot=snapshot,
            bound_child_failure_exclusions=bound_child_failure_exclusions,
            connection=projection_connection,
            started=started,
            pause_before_embedding_file=pause_before_embedding_file,
            pause_before_graph_file=pause_before_graph_file,
            max_candidates=max_candidates,
        )
    if pause_before_graph_file is not None:
        raise ValueError("pre-graph operator wait requires the indexed preparation route")
    if prepared_observations is None:
        observation_payloads = snapshot.get("observations")
        observation_references = snapshot.get("observation_references")
        if observation_payloads is not None:
            if not isinstance(observation_payloads, list):
                raise ValueError("ingestion revision preparation observations are invalid")
            prepared_observations = [Observation.from_dict(item) for item in observation_payloads]
        elif isinstance(observation_references, list):
            authorities = []
            for expected_index, binding in enumerate(job_store_bindings):
                if (
                    not isinstance(binding, dict)
                    or binding.get("job_index") != expected_index
                    or not isinstance(binding.get("store_directory"), str)
                ):
                    raise ValueError("ingestion revision preparation JobStore binding is invalid")
                store_directory = Path(binding["store_directory"])
                reader = open_completed_ingestion_job_reader(
                    binding["ingestion_job_id"],
                    job_store=JobStore(store_directory),
                    asset_store=AssetStore(store_directory),
                    observation_store=ObservationStore(store_directory),
                    extractor_run_store=ExtractorRunStore(store_directory),
                    requester_user_id=APPROVER_ACTOR,
                    workspace_id=WORKSPACE_ID,
                    bound_child_failure_exclusions=(
                        bound_child_failure_exclusions
                        if (
                            bound_child_failure_binding is not None
                            and binding.get("ingestion_job_id")
                            == bound_child_failure_binding.get("ingestion_job_id")
                        )
                        else None
                    ),
                )
                authority = reader.authority
                if (
                    authority.job_fingerprint != binding["job_fingerprint"]
                    or authority.observation_count != binding["observation_count"]
                ):
                    raise ValueError("ingestion revision preparation job changed")
                authorities.append(authority)
                del reader
            prepared_observations = []
            for reference_index, reference in enumerate(
                observation_references,
                start=1,
            ):
                if (
                    not isinstance(reference, list)
                    or len(reference) != 3
                    or not isinstance(reference[0], int)
                    or isinstance(reference[0], bool)
                    or not 0 <= reference[0] < len(authorities)
                    or not isinstance(reference[1], str)
                    or not isinstance(reference[2], str)
                ):
                    raise ValueError("ingestion revision preparation reference is invalid")
                authority = authorities[reference[0]]
                prepared_observations.append(
                    authority.load_indexed_observation(
                        reference[1],
                        expected_observation_hash=reference[2],
                        expected_job_fingerprint=authority.job_fingerprint,
                    )
                )
                if reference_index % 100000 == 0:
                    print(
                        json.dumps(
                            {
                                "phase": ("loading_prepared_retrieval_observations"),
                                "loaded_observation_count": reference_index,
                                "total_observation_count": len(observation_references),
                                "elapsed_seconds": round(
                                    time.monotonic() - started,
                                    3,
                                ),
                            }
                        ),
                        flush=True,
                    )
            del authorities, observation_references
        else:
            raise ValueError("ingestion revision preparation observations are invalid")
    if prepared_bundles is None:
        bundle_payloads = snapshot.get("bundles")
        if not isinstance(bundle_payloads, list):
            raise ValueError("ingestion revision preparation bundles are invalid")
        prepared_bundles = [MailEvidenceBundle.from_dict(item) for item in bundle_payloads]
    del snapshot, snapshot_bytes

    print(
        json.dumps(
            {
                "phase": "building_retrieval_index_candidate_graph",
                "source_observation_count": preparation["source_observation_count"],
                "retrieval_helper_observation_count": len(prepared_observations),
                "root_count": preparation["job_count"],
                "embedding_eta": "unmeasured",
                "resumed_from_preparation": resumed_from_preparation,
            }
        ),
        flush=True,
    )

    def drain(values: list[object]):
        while values:
            yield values.pop()

    if pause_before_embedding_file is not None:
        if not pause_before_embedding_file.is_absolute():
            raise ValueError("pre-embedding pause file must be absolute")
        if pause_before_embedding_file.exists():
            raise ValueError("pre-embedding pause file must not already exist")

    def report_build_progress(payload: object) -> None:
        progress = dict(payload)
        if progress.get("phase") == "retrieval_units_ready_for_embedding":
            statm = Path("/proc/self/statm").read_text().split()
            progress["current_rss_bytes"] = int(statm[1]) * os.sysconf("SC_PAGE_SIZE")
            progress["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        print(
            json.dumps(
                {
                    **progress,
                    "embedding_eta": "unmeasured",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            ),
            flush=True,
        )
        if (
            progress.get("phase") == "retrieval_units_ready_for_embedding"
            and pause_before_embedding_file is not None
        ):
            print(
                json.dumps(
                    {
                        "phase": "waiting_for_operator_before_embedding",
                        "current_rss_bytes": progress["current_rss_bytes"],
                        "peak_rss_bytes": progress["peak_rss_bytes"],
                        "embedding_eta": "unmeasured",
                    }
                ),
                flush=True,
            )
            while not pause_before_embedding_file.exists():
                time.sleep(1)
            if not pause_before_embedding_file.is_file():
                raise ValueError("pre-embedding resume marker is invalid")
            print(
                json.dumps(
                    {"phase": "operator_resumed_embedding"},
                ),
                flush=True,
            )

    revision = build_issue56_ingestion_revision(
        observations=drain(prepared_observations),
        bundles=drain(prepared_bundles),
        source_binding=source_binding,
        requester_user_id=APPROVER_ACTOR,
        workspace_id=WORKSPACE_ID,
        retain_bundles=False,
        source_authority_fingerprint=source_binding["source_authority_fingerprint"],
        build_progress=report_build_progress,
    )
    artifact = build_authorized_hybrid_observation_index_artifact(
        session=revision.session,
        snippet_index=revision.snippet_index,
        graph_build=revision.graph_build,
    )
    directory.mkdir(parents=True, mode=0o700)
    os.link(snapshot_path, directory / "observations.json")
    shutil.copytree(
        exact_directory,
        directory / "exact-cells",
        copy_function=os.link,
    )
    if bound_child_failure_binding is not None:
        os.link(
            preparation_directory / "bound-child-failure-exclusions.json",
            directory / "bound-child-failure-exclusions.json",
        )
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    def encoded_chunks(value: object):
        if isinstance(value, bytes):
            yield value
            return
        for chunk in encoder.iterencode(value):
            yield chunk.encode("utf-8")

    def write(name: str, value: object) -> str:
        maximum_bytes = _MAX_INGESTION_REVISION_SOURCE_BYTES if name == "index.json" else None
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(
            directory / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            for chunk in encoded_chunks(value):
                size += len(chunk)
                if maximum_bytes is not None and size > maximum_bytes:
                    raise ValueError("ingestion revision file exceeds bounded maximum size")
                stream.write(chunk)
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    index_hash = write("index.json", artifact.to_dict())
    write("dense.bin", artifact.dense_vector_payload)
    write("candidate-graph.json", revision.effective_graph_view.to_dict())
    manifest = {
        "artifact_id": "formowl_issue56_ingestion_revision_v1",
        "requester_user_id": APPROVER_ACTOR,
        "workspace_id": WORKSPACE_ID,
        "snapshot_sha256": preparation["snapshot_sha256"],
        "index_manifest_sha256": index_hash,
        "index_artifact_fingerprint": artifact.artifact_fingerprint,
        "source_session_binding_fingerprint": (revision.session.source_session_binding_fingerprint),
        "graph_revision_fingerprint": (revision.graph_build.graph_revision_fingerprint),
        "revision_binding_fingerprint": sha256_json(revision.safe_binding),
        "source_authority_fingerprint": source_binding["source_authority_fingerprint"],
        "exact_lookup_manifest_sha256": preparation["exact_lookup_manifest_sha256"],
        "bound_child_failure_manifest_sha256": (
            bound_child_failure_binding.get("manifest_byte_sha256")
            if bound_child_failure_binding is not None
            else None
        ),
    }
    revision_hash = write("revision.json", manifest)
    summary = {
        "phase": "staged_not_activated",
        "revision_sha256": revision_hash,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source_observation_count": preparation["source_observation_count"],
        "observation_type_counts": preparation["observation_type_counts"],
        "embedding_eta": "unmeasured",
        **dict(revision.safe_binding),
    }
    assert_no_public_raw_references(summary, "ingestion_revision_report")
    write("build-report.json", summary)
    return summary


def _authorized_ingestion_root_source_kinds(authority) -> set[str]:
    """Shared sealed root metadata admission; child runs grant no root authority."""
    from formowl_contract import to_plain
    from formowl_ingestion.extractors.text import PlainTextObservationExtractor
    from formowl_mail.semantic_plan import (
        AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
        AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    )

    asset = authority.asset
    root_runs = [
        run for run in authority.runs
        if run.asset_id == asset.asset_id and run.status == "succeeded"
    ]
    if not root_runs or any(run.input_hash != asset.content_hash for run in root_runs):
        raise ValueError("indexed source root authority binding is invalid")
    text_extractor = PlainTextObservationExtractor()
    source_ref = to_plain(asset.source_ref) or {}
    source_kinds = set()
    for run in root_runs:
        if run.extractor_type in {"mail_archive", "mail_attachment_backfill"}:
            source_kinds.add(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND)
        elif (
            run.extractor_name == text_extractor.name()
            and run.extractor_type == text_extractor.extractor_type()
            and asset.mime_type in text_extractor.supported_mime_types()
            and source_ref.get("source_system") != "formowl_mail_attachment"
            and source_ref.get("source_type") != "email_attachment_occurrence"
        ):
            source_kinds.add(AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND)
        else:
            raise ValueError("indexed source root family is unsupported")
    return source_kinds


def _accepted_governed_mail_root_source_ref(source_ref: Any) -> dict[str, str]:
    """Return only safe, governed mail-root identity fields for source binding."""
    if not isinstance(source_ref, dict):
        raise ValueError("registered mail source reference is invalid")

    system = source_ref.get("source_system")
    source_type = source_ref.get("source_type")
    source_id = source_ref.get("source_id")
    source_key = source_ref.get("source_key")

    def safe_identifier(value: object) -> bool:
        return (
            isinstance(value, str)
            and bool(value)
            and value == value.strip()
            and len(value) <= 512
            and not any(ord(char) < 32 for char in value)
            and "/" not in value
            and "\\" not in value
            and "://" not in value
            and value not in {".", ".."}
        )

    if system == "formowl_upload_session" and source_type in {
        "mail_archive_upload", "mail_archive",
    }:
        if not safe_identifier(source_id):
            raise ValueError("registered mail upload provenance is unavailable")
    elif system == "local" and source_type == "file":
        if not safe_identifier(source_id) or not safe_identifier(source_key):
            raise ValueError("registered local mail provenance is unavailable")
    elif system == "local_folder_inbox" and source_type == "file_content":
        if not isinstance(source_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", source_id) is None:
            raise ValueError("registered inbox mail provenance is unavailable")
    else:
        raise ValueError("registered mail source provenance is unsupported")

    accepted = {
        "source_system": system,
        "source_type": source_type,
        "source_id": source_id,
    }
    if source_key is not None:
        if not safe_identifier(source_key):
            raise ValueError("registered mail source key is unsafe")
        accepted["source_key"] = source_key
    return accepted


def _finish_indexed_ingestion_revision(
    directory: Path,
    preparation_directory: Path,
    *,
    preparation: dict,
    preparation_fingerprint: str,
    snapshot: dict,
    bound_child_failure_exclusions: dict | None,
    connection: object,
    started: float,
    pause_before_embedding_file: Path | None,
    pause_before_graph_file: Path | None = None,
    max_candidates: int | None = None,
) -> dict:
    """Existing checkpoint -> paged owner records -> stored session/graph seal."""
    from formowl_contract import PermissionScope, sha256_json
    from formowl_core.dense_embedding import DenseEvidenceVectorCache
    from formowl_graph.index.records import PostgreSQLGraphProjectionStore
    from formowl_mail import hybrid

    bounded_revision_id = None
    validate_bounded_revision_report = None
    max_bounded_candidates = None
    if max_candidates is not None:
        from scripts.issue56_bounded_canary import (
            MAX_BOUNDED_CANDIDATES,
            bounded_revision_id,
            validate_bounded_revision_report,
        )

        max_bounded_candidates = MAX_BOUNDED_CANDIDATES
    from formowl_mail.issue56_sealed_source import (
        APPROVER_ACTOR,
        WORKSPACE_ID,
        IngestionRevisionSourceRecords,
        open_ingestion_revision_job_authorities,
    )
    from formowl_mail.semantic_plan import (
        AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND,
        validated_authorized_semantic_source,
    )

    if max_candidates is not None and (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= max_bounded_candidates
    ):
        raise ValueError("indexed bounded path requires a positive max-candidates")

    if pause_before_graph_file is not None and (
        not pause_before_graph_file.is_absolute()
        or pause_before_graph_file.exists()
        or pause_before_graph_file == pause_before_embedding_file
    ):
        raise ValueError("indexed pre-graph marker must be new, absolute, and distinct")
    references = snapshot.get("observation_references")
    if not isinstance(references, list) or snapshot.get("observations") is not None:
        raise ValueError("indexed build requires reference-only source preparation")
    authorities = open_ingestion_revision_job_authorities(
        snapshot["job_store_bindings"],
        bound_child_failure_exclusions,
    )
    scopes = {}
    source_kinds = set()
    for authority in authorities:
        scope = PermissionScope(**dict(authority.permission_scope))
        if scope.scope_id in scopes and scopes[scope.scope_id] != scope:
            raise ValueError("indexed source permission scope is ambiguous")
        scopes[scope.scope_id] = scope
        source_kinds.update(_authorized_ingestion_root_source_kinds(authority))
    if not source_kinds:
        raise ValueError("indexed source root authority is unavailable")
    source = validated_authorized_semantic_source(
        source_kind=(
            next(iter(source_kinds)) if len(source_kinds) == 1
            else AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND
        ),
        workspace_id=WORKSPACE_ID,
        source_scope_ids=tuple(scopes),
        authorized_permission_scopes=tuple(scopes.values()),
    )
    source_binding = snapshot["source_binding"]
    binding = {
        "preparation_fingerprint": preparation_fingerprint,
        "snapshot_sha256": preparation["snapshot_sha256"],
        "source_access_fingerprint": source.authorization_fingerprint,
        "source_binding_fingerprint": sha256_json(source_binding),
        "ingestion_job_fingerprints": [authority.job_fingerprint for authority in authorities],
    }
    revision_id = (
        bounded_revision_id(directory.name, max_candidates)
        if max_candidates is not None
        else directory.name
    )
    store = PostgreSQLGraphProjectionStore(
        connection,
        revision_id=revision_id,
        workspace_id=WORKSPACE_ID,
        binding=binding,
    )
    records = IngestionRevisionSourceRecords(
        runtime_store=store,
        job_authorities=authorities,
        requester_user_id=APPROVER_ACTOR,
        workspace_id=WORKSPACE_ID,
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / "revision.json").exists():
        raise ValueError("indexed revision is already published")

    def progress(payload):
        print(
            json.dumps(
                {
                    **payload,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "current_rss_bytes": int(Path("/proc/self/statm").read_text().split()[1])
                    * os.sysconf("SC_PAGE_SIZE"),
                    "embedding_eta": "unmeasured",
                }
            ),
            flush=True,
        )

    progress({"phase": "indexing_prepared_source_references"})
    indexed_references = references[:max_candidates] if max_candidates is not None else references
    records.index_prepared_references(
        indexed_references,
        authorized_source=source,
        progress=progress,
        max_candidates=max_candidates,
    )
    job_store_bindings = snapshot["job_store_bindings"]
    snapshot.clear()
    del references
    del indexed_references
    if pause_before_embedding_file is not None:
        if not pause_before_embedding_file.is_absolute() or pause_before_embedding_file.exists():
            raise ValueError("indexed pre-embedding marker is invalid")
        progress({"phase": "waiting_for_operator_before_embedding"})
        while not pause_before_embedding_file.exists():
            time.sleep(1)
        if not pause_before_embedding_file.is_file():
            raise ValueError("indexed pre-embedding marker is invalid")
    session = hybrid.build_authorized_semantic_observation_session(
        authorized_source=source,
        requester_user_id=APPROVER_ACTOR,
        source_records=records,
        runtime_store=store,
        source_binding=source_binding,
        source_authority_fingerprint=source_binding["source_authority_fingerprint"],
        dense_vector_cache=DenseEvidenceVectorCache(directory / "dense-cache"),
        dense_build_progress=progress,
        streaming_candidate_limit=max_candidates,
    )
    if pause_before_graph_file is not None:
        store.checkpoint(
            "index_ready_before_graph",
            session.index.index_fingerprint,
            binding,
        )
        progress(
            {
                "phase": "durable_index_ready_waiting_before_graph",
                "candidate_count": len(session.index.candidates),
                "index_fingerprint": session.index.index_fingerprint,
                "graph_started": False,
            }
        )
        while not pause_before_graph_file.exists():
            time.sleep(1)
        if not pause_before_graph_file.is_file():
            raise ValueError("indexed pre-graph marker is invalid")
    progress({"phase": "building_stored_candidate_graph"})
    graph = hybrid.build_authorized_source_backed_effective_graph_view(
        session=session,
        source_records=records,
        runtime_store=store,
        source_binding_fingerprint=sha256_json(source_binding),
    )
    safe_binding = {
        "source_binding_fingerprint": sha256_json(source_binding),
        "source_authority_fingerprint": source_binding["source_authority_fingerprint"],
        "source_session_binding_fingerprint": session.source_session_binding_fingerprint,
        "input_observation_count": preparation["source_observation_count"],
        "retrieval_observation_count": len(session.index.candidates),
        "candidate_graph_only": True,
        "continuous_ingestion_sync": False,
        "extraction_coverage": source_binding.get("extraction_coverage", {}),
        "graph": graph.to_safe_dict(),
    }
    if max_candidates is not None:
        safe_binding["bounded_canary_candidate_count"] = max_candidates
    manifest = {
        "artifact_id": "formowl_issue56_ingestion_revision_v1",
        "storage_mode": "postgresql_projection_v1",
        "requester_user_id": APPROVER_ACTOR,
        "workspace_id": WORKSPACE_ID,
        "revision_id": revision_id,
        "snapshot_sha256": preparation["snapshot_sha256"],
        "source_authority_fingerprint": source_binding["source_authority_fingerprint"],
        "source_binding": source_binding,
        "job_store_bindings": job_store_bindings,
        "projection": {
            "revision_id": store.revision_id,
            "binding": binding,
            "seal_hash": store.seal_hash,
        },
        "safe_binding": safe_binding,
        "revision_binding_fingerprint": sha256_json(safe_binding),
        "exact_lookup_manifest_sha256": preparation["exact_lookup_manifest_sha256"],
        "bound_child_failure_manifest_sha256": (
            (preparation.get("bound_child_failure_binding") or {}).get("manifest_byte_sha256")
        ),
    }
    # Same source/exact artifacts; bounded publication must work across devices.
    # The full path above intentionally retains its existing hardlink contract.
    for name in ("observations.json", "bound-child-failure-exclusions.json"):
        source_path = preparation_directory / name
        if source_path.exists() and not (directory / name).exists():
            _copy_file_atomic(source_path, directory / name)
    if not (directory / "exact-cells").exists():
        if max_candidates is not None:
            os.symlink(
                (preparation_directory / "exact-cells").resolve(),
                directory / "exact-cells",
                target_is_directory=True,
            )
        else:
            _copytree_atomic(
                preparation_directory / "exact-cells",
                directory / "exact-cells",
            )
    pending = directory / "revision.pending"
    with pending.open("w", encoding="utf-8") as stream:
        os.chmod(pending, 0o600)
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    revision_hash = "sha256:" + hashlib.sha256(pending.read_bytes()).hexdigest()
    os.replace(pending, directory / "revision.json")
    progress({"phase": "stored_revision_staged_not_activated", "revision_sha256": revision_hash})
    store.reopen(manifest["projection"]["seal_hash"])
    if max_candidates is not None:
        progress(
            {
                "phase": "bounded_projection_seal_reloaded",
                "bounded_canary_candidate_count": max_candidates,
                "seal_hash": manifest["projection"]["seal_hash"],
            }
        )
    report = {
        "phase": "staged_not_activated",
        "revision_sha256": revision_hash,
        "revision_id": revision_id,
        "revision_path": f"{directory.name}/revision.json",
        "source_observation_count": preparation["source_observation_count"],
        **safe_binding,
    }
    if max_candidates is not None:
        validate_bounded_revision_report(
            report,
            revision_id=revision_id,
            candidate_limit=max_candidates,
            workspace_root=directory.parent,
        )
    return report


def _open_ingestion_projection_connection(path: Path):
    """Operator-only private connection file; never put credentials in artifacts."""
    import psycopg
    from psycopg.rows import dict_row
    from formowl_auth.postgres import PsycopgOAuthConnection

    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077 or mode.st_size > 16384:
        raise ValueError("projection connection file must be private and bounded")
    config = json.loads(path.read_bytes())
    if not isinstance(config, dict) or set(config) != {"host", "dbname", "user", "password_file"}:
        raise ValueError("projection connection configuration is invalid")
    password_file = Path(config.pop("password_file"))
    if password_file.stat().st_size > 16384:
        raise ValueError("projection password file exceeds bound")
    connection = psycopg.connect(
        **config,
        password=password_file.read_text().strip(),
        row_factory=dict_row,
        autocommit=True,
    )
    return PsycopgOAuthConnection(connection)


def _compose_independent_root_preparation(
    directory: Path, *, base_preparation_directory: Path,
    document_preparation_directory: Path,
) -> dict:
    """Append one prepared PlainText root; never hydrate the base Observations."""
    from formowl_contract import sha256_json
    from formowl_mail.issue56_sealed_source import (
        APPROVER_ACTOR, WORKSPACE_ID, _MAX_INGESTION_REVISION_SOURCE_BYTES,
        open_ingestion_revision_job_authorities,
    )
    from formowl_mail.semantic_plan import AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND

    output = directory.parent / f".{directory.name}.preembedding"
    if directory.exists() or output.exists():
        raise ValueError("new independent-root preparation directory is required")
    directory.parent.mkdir(parents=True, exist_ok=True)

    def load(path):
        preparation = json.loads((path / "preparation.json").read_bytes())
        fingerprint = preparation.pop("preparation_fingerprint", None)
        snapshot_path = path / "observations.json"
        if snapshot_path.stat().st_size > _MAX_INGESTION_REVISION_SOURCE_BYTES:
            raise ValueError("independent-root preparation exceeds source size cap")
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(snapshot_bytes)
        exact_bytes = (path / "exact-cells" / "manifest.json").read_bytes()
        exact = json.loads(exact_bytes)
        exact_fingerprint = exact.pop("manifest_fingerprint", None)
        source = snapshot["source_binding"]
        if (
            preparation.get("artifact_id") != "formowl_issue56_ingestion_revision_preparation_v1"
            or fingerprint != sha256_json(preparation)
            or preparation.get("snapshot_size_bytes") != len(snapshot_bytes)
            or preparation.get("snapshot_sha256") != "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()
            or preparation.get("exact_lookup_manifest_sha256")
            != "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
            or source.get("exact_lookup_manifest_sha256")
            != preparation["exact_lookup_manifest_sha256"]
            or exact.get("artifact_id") != "formowl_issue56_ingestion_exact_cell_lookup_v1"
            or exact_fingerprint != sha256_json(exact)
            or snapshot.get("bundles") != [] or snapshot.get("observations") is not None
            or not isinstance(snapshot.get("observation_references"), list)
            or source.get("source_authority_fingerprint") != sha256_json({
                "artifact_id": "formowl_completed_ingestion_job_authority_v1",
                "requester_user_id": APPROVER_ACTOR, "workspace_id": WORKSPACE_ID,
                "jobs": source["jobs"],
            })
            or exact.get("source_authority_fingerprint") != source["source_authority_fingerprint"]
        ):
            raise ValueError("independent-root preparation seal is invalid")
        exclusions = None
        for name, expected in (
            ("sidecar-parent-binding.json", preparation.get("sidecar_parent_binding_sha256")),
            ("bound-child-failure-exclusions.json",
             (preparation.get("bound_child_failure_binding") or {}).get("manifest_byte_sha256")),
        ):
            if expected is not None:
                raw = (path / name).read_bytes()
                if "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError("independent-root sidecar/failure binding changed")
                if name == "bound-child-failure-exclusions.json":
                    exclusions = json.loads(raw)
        authorities = open_ingestion_revision_job_authorities(
            snapshot["job_store_bindings"], exclusions,
        )
        # Source jobs keep nested supplements; store bindings remain a flat index.
        pending = list(source["jobs"])
        jobs = {}
        while pending:
            job = pending.pop()
            if job["job_fingerprint"] in jobs:
                raise ValueError("independent-root duplicate job binding")
            jobs[job["job_fingerprint"]] = job
            pending.extend(job.get("supplements", ()))
        if (
            set(jobs) != {a.job_fingerprint for a in authorities}
            or preparation["job_count"] != len(source["jobs"])
            or exact["job_count"] != len(authorities)
            or preparation["source_observation_count"] != sum(a.observation_count for a in authorities)
        ):
            raise ValueError("independent-root job/count binding changed")
        for authority in authorities:
            job = jobs[authority.job_fingerprint]
            if (
                job["root_asset_hash"] != authority.asset.content_hash
                or job["observation_count"] != authority.observation_count
                or job["run_fingerprints"] != [sha256_json(r.to_dict()) for r in authority.runs]
            ):
                raise ValueError("independent-root job authority changed")
        return preparation, snapshot, exact, authorities

    base, snapshot, exact, authorities = load(base_preparation_directory)
    delta, document, delta_exact, added = load(document_preparation_directory)
    if (
        len(added) != 1 or delta["job_count"] != 1
        or document["source_binding"]["jobs"][0].get("supplements")
        or _authorized_ingestion_root_source_kinds(added[0])
        != {AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND}
        or any(a.asset.asset_id == added[0].asset.asset_id for a in authorities)
        or any(a.ingestion_job_id == added[0].ingestion_job_id for a in authorities)
        or delta_exact["shards"] or delta_exact["columns"] or any(delta_exact["counts"].values())
        or delta_exact["tokenizer_profile_fingerprint"] != exact["tokenizer_profile_fingerprint"]
        or delta.get("sidecar_parent_binding_sha256") or delta.get("bound_child_failure_binding")
    ):
        raise ValueError("independent-root document authority is invalid")
    scopes = {}
    for authority in (*authorities, *added):
        scope = dict(authority.permission_scope)
        if scope["scope_id"] in scopes and scopes[scope["scope_id"]] != scope:
            raise ValueError("independent-root permission scope is ambiguous")
        scopes[scope["scope_id"]] = scope
    ids = set()
    for references, job_count in (
        (snapshot["observation_references"], len(authorities)),
        (document["observation_references"], 1),
    ):
        for reference in references:
            if (
                not isinstance(reference, list) or len(reference) != 3
                or type(reference[0]) is not int or not 0 <= reference[0] < job_count
                or not all(isinstance(v, str) and v for v in reference[1:])
                or reference[1] in ids
            ):
                raise ValueError("independent-root Observation reference collision or mismatch")
            ids.add(reference[1])
    for _, observation_id, observation_hash in document["observation_references"]:
        observation = added[0].load_indexed_observation(
            observation_id, expected_observation_hash=observation_hash,
            expected_job_fingerprint=added[0].job_fingerprint,
        )
        if (
            observation.asset_id != added[0].asset.asset_id or observation.modality != "text"
            or observation.observation_type not in {"heading", "paragraph"}
        ):
            raise ValueError("independent-root document reference is invalid")
    source = dict(snapshot["source_binding"])
    source["jobs"] = [*source["jobs"], document["source_binding"]["jobs"][0]]
    source["source_authority_fingerprint"] = sha256_json({
        "artifact_id": "formowl_completed_ingestion_job_authority_v1",
        "requester_user_id": APPROVER_ACTOR, "workspace_id": WORKSPACE_ID, "jobs": source["jobs"],
    })
    coverage = dict(source["extraction_coverage"])
    warnings = dict(coverage["warning_code_counts"])
    for code, count in document["source_binding"]["extraction_coverage"]["warning_code_counts"].items():
        warnings[code] = warnings.get(code, 0) + count
    source["extraction_coverage"] = {
        **coverage, "root_count": len(source["jobs"]), "source_completeness_certified": False,
        "warning_code_counts": warnings, "warning_count": sum(warnings.values()),
    }
    bindings = [*snapshot["job_store_bindings"],
                {**document["job_store_bindings"][0], "job_index": len(authorities)}]
    exact = {**exact, "source_authority_fingerprint": source["source_authority_fingerprint"],
             "job_count": len(bindings)}
    exact_bytes = json.dumps(
        {**exact, "manifest_fingerprint": sha256_json(exact)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    source["exact_lookup_manifest_sha256"] = "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
    snapshot = {
        **snapshot, "source_binding": source, "job_store_bindings": bindings,
        "observation_references": [
            *snapshot["observation_references"],
            *([len(authorities), *ref[1:]] for ref in document["observation_references"]),
        ],
    }
    counts = dict(base["observation_type_counts"])
    for kind, count in delta["observation_type_counts"].items():
        counts[kind] = counts.get(kind, 0) + count
    temporary = Path(tempfile.mkdtemp(prefix=f".{directory.name}.preembedding.", dir=directory.parent))
    try:
        exact_directory = temporary / "exact-cells"
        # The manifest must NOT be hardlinked: its authority/hash changes.
        _copytree_atomic(
            base_preparation_directory / "exact-cells",
            exact_directory,
            copy_function=_link_or_copy_file_atomic,
            ignore=shutil.ignore_patterns("manifest.json"),
        )
        (exact_directory / "manifest.json").write_bytes(exact_bytes)
        for name, present in (
            ("sidecar-parent-binding.json", base.get("sidecar_parent_binding_sha256")),
            ("bound-child-failure-exclusions.json", base.get("bound_child_failure_binding")),
        ):
            if present:
                _link_or_copy_file_atomic(
                    base_preparation_directory / name,
                    temporary / name,
                )
        digest, size = hashlib.sha256(), 0
        with (temporary / "observations.json").open("xb") as stream:
            for chunk in json.JSONEncoder(
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).iterencode(snapshot):
                raw = chunk.encode()
                size += len(raw)
                if size > _MAX_INGESTION_REVISION_SOURCE_BYTES:
                    raise ValueError("independent-root snapshot exceeds source size cap")
                digest.update(raw)
                stream.write(raw)
        preparation = {
            **base, "requested_jobs": [*base["requested_jobs"], *delta["requested_jobs"]],
            "job_count": len(source["jobs"]), "job_authority_count": len(bindings),
            "source_observation_count": base["source_observation_count"] + delta["source_observation_count"],
            "observation_type_counts": counts, "snapshot_size_bytes": size,
            "snapshot_sha256": "sha256:" + digest.hexdigest(),
            "exact_lookup_manifest_sha256": source["exact_lookup_manifest_sha256"],
        }
        (temporary / "preparation.json").write_text(json.dumps(
            {**preparation, "preparation_fingerprint": sha256_json(preparation)},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ))
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"phase": "source_preparation_checkpoint_ready", "preparation_directory": str(output),
            "embedding_status": "not_started", "source_observation_count": preparation["source_observation_count"]}


def _compose_sidecar_supplement_preparation(
    directory: Path,
    *,
    base_preparation_directory: Path,
    supplement_preparation_directory: Path,
    supplement_contract_directory: Path,
    prior_job_id: str,
    bound_child_failure_manifest_path: Path,
) -> dict:
    """Nest one completed sidecar delta under the existing second root."""
    from formowl_contract import sha256_json, to_plain
    from formowl_ingestion.storage import (
        AssetStore,
        ExtractorRunStore,
        JobStore,
        ObservationStore,
    )
    from formowl_mail.import_workflow import (
        open_completed_ingestion_job_reader,
    )
    from formowl_mail.issue56_sealed_source import (
        APPROVER_ACTOR,
        WORKSPACE_ID,
        _MAX_INGESTION_REVISION_SOURCE_BYTES,
    )

    output = directory.parent / f".{directory.name}.preembedding"
    if directory.exists() or output.exists():
        raise ValueError("new supplement revision directory is required")

    def load_preparation(path: Path) -> tuple[dict, dict, dict]:
        preparation = json.loads((path / "preparation.json").read_bytes())
        fingerprint = preparation.pop("preparation_fingerprint", None)
        snapshot_bytes = (path / "observations.json").read_bytes()
        exact_bytes = (path / "exact-cells" / "manifest.json").read_bytes()
        exact = json.loads(exact_bytes)
        exact_fingerprint = exact.pop("manifest_fingerprint", None)
        if (
            preparation.get("artifact_id") != "formowl_issue56_ingestion_revision_preparation_v1"
            or fingerprint != sha256_json(preparation)
            or preparation.get("snapshot_size_bytes") != len(snapshot_bytes)
            or preparation.get("snapshot_sha256")
            != "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()
            or preparation.get("exact_lookup_manifest_sha256")
            != "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
            or exact.get("artifact_id") != "formowl_issue56_ingestion_exact_cell_lookup_v1"
            or exact_fingerprint != sha256_json(exact)
        ):
            raise ValueError("ingestion supplement preparation is invalid")
        return preparation, json.loads(snapshot_bytes), exact

    base_preparation, base_snapshot, base_exact = load_preparation(base_preparation_directory)
    delta_preparation, delta_snapshot, delta_exact = load_preparation(
        supplement_preparation_directory
    )
    base_bindings = base_snapshot.get("job_store_bindings")
    delta_bindings = delta_snapshot.get("job_store_bindings")
    base_source = base_snapshot.get("source_binding")
    delta_source = delta_snapshot.get("source_binding")
    base_references = base_snapshot.get("observation_references")
    delta_references = delta_snapshot.get("observation_references")
    if (
        base_preparation.get("job_count") != 2
        or not isinstance(base_bindings, list)
        or len(base_bindings) != 2
        or not isinstance(delta_bindings, list)
        or len(delta_bindings) != 1
        or not isinstance(base_source, dict)
        or not isinstance(delta_source, dict)
        or not isinstance(base_source.get("jobs"), list)
        or len(base_source["jobs"]) != 2
        or not isinstance(delta_source.get("jobs"), list)
        or len(delta_source["jobs"]) != 1
        or not isinstance(base_references, list)
        or not isinstance(delta_references, list)
        or base_snapshot.get("bundles") != []
        or delta_snapshot.get("bundles") != []
        or delta_exact.get("job_count") != 1
        or delta_exact.get("tokenizer_profile_fingerprint")
        != base_exact.get("tokenizer_profile_fingerprint")
        or delta_exact.get("source_authority_fingerprint")
        != delta_source.get("source_authority_fingerprint")
    ):
        raise ValueError("ingestion supplement scope is invalid")
    prior_indexes = [
        index
        for index, binding in enumerate(base_bindings)
        if binding.get("ingestion_job_id") == prior_job_id
    ]
    if len(prior_indexes) != 1:
        raise ValueError("ingestion supplement prior job is invalid")
    prior_index = prior_indexes[0]
    prior_binding = base_bindings[prior_index]
    delta_binding = delta_bindings[0]
    failure_bytes = bound_child_failure_manifest_path.read_bytes()
    failure_manifest = json.loads(failure_bytes)
    failure_binding = delta_preparation.get("bound_child_failure_binding")
    if (
        failure_binding is None
        or failure_binding.get("manifest_byte_sha256")
        != "sha256:" + hashlib.sha256(failure_bytes).hexdigest()
        or delta_source.get("bound_child_failure_binding") != failure_binding
    ):
        raise ValueError("ingestion supplement child failure binding is invalid")

    def authority(binding: dict, exclusions: dict | None = None):
        store = Path(binding["store_directory"])
        reader = open_completed_ingestion_job_reader(
            binding["ingestion_job_id"],
            job_store=JobStore(store),
            asset_store=AssetStore(store),
            observation_store=ObservationStore(store),
            extractor_run_store=ExtractorRunStore(store),
            requester_user_id=APPROVER_ACTOR,
            workspace_id=WORKSPACE_ID,
            bound_child_failure_exclusions=exclusions,
        )
        authority_value = reader.authority
        if authority_value.job_fingerprint != binding.get(
            "job_fingerprint"
        ) or authority_value.observation_count != binding.get("observation_count"):
            raise ValueError("ingestion supplement completed job changed")
        return authority_value

    prior_authority = authority(prior_binding)
    delta_authority = authority(delta_binding, failure_manifest)
    contract_bytes = {
        name: (supplement_contract_directory / name).read_bytes()
        for name in (
            "config.json",
            "source-scope.json",
            "result.json",
            "repaired-parent-delta.json",
        )
    }
    config = json.loads(contract_bytes["config.json"])
    source_scope = json.loads(contract_bytes["source-scope.json"])
    result = json.loads(contract_bytes["result.json"])
    parent_delta = json.loads(contract_bytes["repaired-parent-delta.json"])
    repair_binding = base_preparation.get("reference_repair_binding")
    parent_map_sha256 = base_preparation.get("sidecar_parent_binding_sha256")
    parent_records = parent_delta.get("records")
    if (
        prior_authority.asset.asset_id != delta_authority.asset.asset_id
        or prior_authority.asset.content_hash != delta_authority.asset.content_hash
        or to_plain(prior_authority.permission_scope) != to_plain(delta_authority.permission_scope)
        or config.get("prior_ingestion_job_id") != prior_job_id
        or config.get("prior_job_fingerprint") != prior_authority.job_fingerprint
        or config.get("parent_binding_byte_sha256") != parent_map_sha256
        or config.get("reference_repair_binding") != repair_binding
        or source_scope.get("source_asset_id") != prior_authority.asset.asset_id
        or source_scope.get("prior_ingestion_job_id") != prior_job_id
        or source_scope.get("reference_repair_binding") != repair_binding
        or source_scope.get("regenerate_parent_messages") is not False
        or source_scope.get("full_source_coverage_claim") is not False
        or result.get("status") != "succeeded"
        or result.get("ingestion_job_id") != delta_authority.ingestion_job_id
        or result.get("prior_ingestion_job_id") != prior_job_id
        or result.get("observation_count") != delta_authority.observation_count
        or result.get("full_source_coverage_claim") is not False
        or parent_delta.get("artifact_id") != "readpst_missing_parent_observation_delta_v1"
        or parent_delta.get("ingestion_job_id") != delta_authority.ingestion_job_id
        or parent_delta.get("prior_ingestion_job_id") != prior_job_id
        or parent_delta.get("original_parent_map_byte_sha256") != parent_map_sha256
        or parent_delta.get("reference_repair_binding") != repair_binding
        or parent_delta.get("full_source_coverage_claim") is not False
        or not isinstance(parent_records, list)
        or parent_delta.get("repaired_parent_count") != len(parent_records)
        or not parent_records
    ):
        raise ValueError("ingestion supplement contract binding is invalid")

    supplement_binding = {
        "artifact_id": "formowl_issue56_ingestion_root_supplement_v1",
        "prior_ingestion_job_id": prior_job_id,
        "prior_job_fingerprint": prior_authority.job_fingerprint,
        "supplement_ingestion_job_id": delta_authority.ingestion_job_id,
        "supplement_job_fingerprint": delta_authority.job_fingerprint,
        "supplement_observation_count": delta_authority.observation_count,
        "source_asset_hash": delta_authority.asset.content_hash,
        "permission_scope_fingerprint": sha256_json(dict(delta_authority.permission_scope)),
        "parent_binding_byte_sha256": parent_map_sha256,
        "reference_repair_binding": repair_binding,
        "bound_child_failure_binding": failure_binding,
        "contract_file_sha256": {
            name: "sha256:" + hashlib.sha256(value).hexdigest()
            for name, value in sorted(contract_bytes.items())
        },
        "source_completeness_certified": False,
    }
    supplement_binding["binding_fingerprint"] = sha256_json(supplement_binding)
    final_job_index = len(base_bindings)
    base_ids = {reference[1] for reference in base_references}
    remapped_references = []
    for reference in delta_references:
        if (
            not isinstance(reference, list)
            or len(reference) != 3
            or reference[0] != 0
            or reference[1] in base_ids
        ):
            raise ValueError("ingestion supplement Observation reference is invalid")
        remapped_references.append([final_job_index, reference[1], reference[2]])
    final_references = [*base_references, *remapped_references]
    final_store_bindings = [
        *base_bindings,
        {**delta_binding, "job_index": final_job_index},
    ]
    final_jobs = [dict(item) for item in base_source["jobs"]]
    prior_job = dict(final_jobs[prior_index])
    prior_job["supplements"] = [
        *prior_job.get("supplements", ()),
        {
            **dict(delta_source["jobs"][0]),
            "supplement_binding": supplement_binding,
        },
    ]
    final_jobs[prior_index] = prior_job
    source_authority_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_completed_ingestion_job_authority_v1",
            "requester_user_id": APPROVER_ACTOR,
            "workspace_id": WORKSPACE_ID,
            "jobs": final_jobs,
        }
    )
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{directory.name}.preembedding.",
            dir=directory.parent,
        )
    )
    os.chmod(temporary, 0o700)
    try:
        exact_directory = temporary / "exact-cells"
        (exact_directory / "rows").mkdir(parents=True, mode=0o700)
        (exact_directory / "values").mkdir(mode=0o700)
        base_shards = {(item["kind"], item["shard"]): item for item in base_exact["shards"]}
        delta_shards = {(item["kind"], item["shard"]): item for item in delta_exact["shards"]}
        final_shards = []
        for key in sorted(base_shards.keys() | delta_shards.keys()):
            kind, shard = key
            subdirectory = "rows" if kind == "row" else "values"
            target = exact_directory / subdirectory / f"{shard}.jsonl"
            base_item = base_shards.get(key)
            delta_item = delta_shards.get(key)
            if delta_item is None:
                os.link(
                    base_preparation_directory / "exact-cells" / subdirectory / f"{shard}.jsonl",
                    target,
                )
                final_shards.append(base_item)
                continue
            digest = hashlib.sha256()
            size = 0
            count = 0
            with target.open("xb") as output_stream:
                if base_item is not None:
                    base_digest = hashlib.sha256()
                    base_size = 0
                    base_count = 0
                    with (
                        base_preparation_directory / "exact-cells" / subdirectory / f"{shard}.jsonl"
                    ).open("rb") as input_stream:
                        for line in input_stream:
                            output_stream.write(line)
                            digest.update(line)
                            base_digest.update(line)
                            size += len(line)
                            base_size += len(line)
                            count += 1
                            base_count += 1
                    if (
                        base_item["record_count"] != base_count
                        or base_item["size_bytes"] != base_size
                        or base_item["sha256"] != "sha256:" + base_digest.hexdigest()
                    ):
                        raise ValueError("base exact lookup shard changed")
                delta_digest = hashlib.sha256()
                delta_size = 0
                delta_count = 0
                with (
                    supplement_preparation_directory
                    / "exact-cells"
                    / subdirectory
                    / f"{shard}.jsonl"
                ).open("rb") as input_stream:
                    for line in input_stream:
                        delta_digest.update(line)
                        delta_size += len(line)
                        delta_count += 1
                        if kind == "row":
                            record = json.loads(line)
                            if (
                                not isinstance(record, list)
                                or len(record) not in {6, 7}
                                or record[0] not in {"row", "cell"}
                                or record[2] != 0
                            ):
                                raise ValueError("supplement exact row reference is invalid")
                            record[2] = final_job_index
                            line = (
                                json.dumps(
                                    record,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode("utf-8")
                                + b"\n"
                            )
                        output_stream.write(line)
                        digest.update(line)
                        size += len(line)
                        count += 1
                if (
                    delta_item["record_count"] != delta_count
                    or delta_item["size_bytes"] != delta_size
                    or delta_item["sha256"] != "sha256:" + delta_digest.hexdigest()
                ):
                    raise ValueError("supplement exact lookup shard changed")
            final_shards.append(
                {
                    "kind": kind,
                    "shard": shard,
                    "record_count": count,
                    "size_bytes": size,
                    "sha256": "sha256:" + digest.hexdigest(),
                }
            )
        counts = dict(base_exact["counts"])
        for key, value in delta_exact["counts"].items():
            counts[key] = counts.get(key, 0) + value
        columns = {
            (
                item["field"],
                item["column_hash"],
                item["inline_table"],
                item["structure_status"],
            ): set(item["candidate_hashes"])
            for item in base_exact["columns"]
        }
        for item in delta_exact["columns"]:
            columns.setdefault(
                (
                    item["field"],
                    item["column_hash"],
                    item["inline_table"],
                    item["structure_status"],
                ),
                set(),
            ).update(item["candidate_hashes"])
        exact_core = {
            **base_exact,
            "source_authority_fingerprint": source_authority_fingerprint,
            "job_count": len(final_store_bindings),
            "capability_status": ("incomplete_base_recovered_supplement_indexed"),
            "exact_query_capability_complete": False,
            "supplement_table_cell_count_indexed": (
                delta_preparation["observation_type_counts"].get(
                    "table_cell",
                    0,
                )
            ),
            "counts": counts,
            "columns": [
                {
                    "field": key[0],
                    "column_hash": key[1],
                    "inline_table": key[2],
                    "structure_status": key[3],
                    "candidate_hashes": sorted(value),
                }
                for key, value in sorted(columns.items())
            ],
            "shards": final_shards,
        }
        exact_manifest = {
            **exact_core,
            "manifest_fingerprint": sha256_json(exact_core),
        }
        exact_bytes = json.dumps(
            exact_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        exact_manifest_path = exact_directory / "manifest.json"
        exact_manifest_path.write_bytes(exact_bytes)
        exact_sha256 = "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
        base_coverage = dict(base_source["extraction_coverage"])
        delta_coverage = delta_source["extraction_coverage"]
        warning_counts = dict(base_coverage["warning_code_counts"])
        for code, count in delta_coverage["warning_code_counts"].items():
            warning_counts[code] = warning_counts.get(code, 0) + count
        source_binding = {
            **base_source,
            "jobs": final_jobs,
            "source_authority_fingerprint": source_authority_fingerprint,
            "exact_lookup_manifest_sha256": exact_sha256,
            "supplement_bindings": [supplement_binding],
            "extraction_coverage": {
                **base_coverage,
                "scope": "declared_completed_jobs_with_root_supplement_v1",
                "root_count": 2,
                "warning_count": base_coverage["warning_count"] + delta_coverage["warning_count"],
                "warning_code_counts": warning_counts,
                "source_completeness_certified": False,
            },
        }
        snapshot = {
            "bundles": [],
            "observation_references": final_references,
            "source_binding": source_binding,
            "job_store_bindings": final_store_bindings,
        }
        snapshot_path = temporary / "observations.json"
        encoder = json.JSONEncoder(
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot_size = 0
        snapshot_digest = hashlib.sha256()
        with snapshot_path.open("xb") as stream:
            for chunk in encoder.iterencode(snapshot):
                encoded = chunk.encode("utf-8")
                snapshot_size += len(encoded)
                if snapshot_size > _MAX_INGESTION_REVISION_SOURCE_BYTES:
                    raise ValueError("ingestion revision snapshot exceeds bounded maximum size")
                stream.write(encoded)
                snapshot_digest.update(encoded)
        os.link(
            base_preparation_directory / "sidecar-parent-binding.json",
            temporary / "sidecar-parent-binding.json",
        )
        (temporary / "bound-child-failure-exclusions.json").write_bytes(failure_bytes)
        type_counts = dict(base_preparation["observation_type_counts"])
        for key, value in delta_preparation["observation_type_counts"].items():
            type_counts[key] = type_counts.get(key, 0) + value
        preparation_core = {
            **base_preparation,
            "supplemental_jobs": delta_preparation["requested_jobs"],
            "supplement_bindings": [supplement_binding],
            "snapshot_sha256": ("sha256:" + snapshot_digest.hexdigest()),
            "snapshot_size_bytes": snapshot_size,
            "exact_lookup_manifest_sha256": exact_sha256,
            "source_observation_count": base_preparation["source_observation_count"]
            + delta_preparation["source_observation_count"],
            "observation_type_counts": type_counts,
            "job_count": 2,
            "job_authority_count": len(final_store_bindings),
            "bound_child_failure_binding": failure_binding,
            "embedding_status": "not_started_operator_boundary",
        }
        preparation_path = temporary / "preparation.json"
        preparation_path.write_text(
            json.dumps(
                {
                    **preparation_core,
                    "preparation_fingerprint": sha256_json(preparation_core),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "phase": "supplement_preparation_checkpoint_ready",
        "preparation_directory": str(output),
        "source_observation_count": preparation_core["source_observation_count"],
        "retrieval_helper_observation_count": len(final_references),
        "root_count": 2,
        "job_authority_count": len(final_store_bindings),
        "supplement_binding_fingerprint": supplement_binding["binding_fingerprint"],
        "embedding_status": "not_started",
        "exact_supplement_status": ("delta_row_value_shards_indexed_base_columns_still_incomplete"),
    }


def _read_codex_provider_api_key(path: Path) -> str:
    if not path.is_absolute():
        raise ValueError("Codex provider API key file must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Codex provider API key file is invalid") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_PROVIDER_API_KEY_BYTES
        ):
            raise ValueError("Codex provider API key file is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            encoded = stream.read(_MAX_PROVIDER_API_KEY_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(encoded) > _MAX_PROVIDER_API_KEY_BYTES:
        raise ValueError("Codex provider API key file is invalid")
    try:
        value = encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Codex provider API key file is invalid") from exc
    if not value or "\x00" in value:
        raise ValueError("Codex provider API key file is invalid")
    return value


def _build_ingestion_revision(
    directory: Path,
    jobs: list[list[str]],
    *,
    sidecar_parent_job_id: str | None = None,
    reference_repair_manifest_path: Path | None = None,
    bound_child_failure_manifest_path: Path | None = None,
    prepare_only: bool = False,
    pause_before_embedding_file: Path | None = None,
) -> dict:
    """Explicit operator batch, never called by an MCP request or a watcher."""
    from formowl_contract import (
        redact_public_raw_references,
        sha256_json,
        to_plain,
    )
    from formowl_ingestion.storage import AssetStore, JobStore, ObservationStore, ExtractorRunStore
    from formowl_mail.exact import (
        source_occurrence_column_capability_hash,
        source_occurrence_exact_cell_value_hash,
    )
    from formowl_mail.import_workflow import open_completed_ingestion_job_reader
    from formowl_mail.issue56_sealed_source import (
        APPROVER_ACTOR,
        WORKSPACE_ID,
        _MAX_INGESTION_REVISION_SOURCE_BYTES,
    )
    from formowl_mail.semantic_plan import (
        AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
        AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    )

    reference_repair_binding: dict[str, object] | None = None
    bound_child_failure_exclusions: dict[str, object] | None = None
    bound_child_failure_binding: dict[str, object] | None = None
    if bound_child_failure_manifest_path is not None:
        if not bound_child_failure_manifest_path.is_absolute():
            raise ValueError("ingestion child failure manifest path must be absolute")
        failure_manifest_bytes = bound_child_failure_manifest_path.read_bytes()
        if (
            not failure_manifest_bytes
            or len(failure_manifest_bytes) > _MAX_REFERENCE_REPAIR_MANIFEST_BYTES
        ):
            raise ValueError("ingestion child failure manifest size is invalid")
        bound_child_failure_exclusions = json.loads(failure_manifest_bytes)
        failure_job_id = bound_child_failure_exclusions.get("ingestion_job_id")
        if (
            bound_child_failure_exclusions.get("artifact_id")
            != "formowl_bound_child_content_failure_exclusions_v1"
            or bound_child_failure_exclusions.get("schema_version") != 1
            or bound_child_failure_exclusions.get("unknown_parse_failures_must_reject") is not True
            or bound_child_failure_exclusions.get("full_source_coverage_claim") is not False
            or [job_id for _, job_id in jobs].count(failure_job_id) != 1
        ):
            raise ValueError("ingestion child failure manifest binding is invalid")
        bound_child_failure_binding = {
            "artifact_id": bound_child_failure_exclusions["artifact_id"],
            "manifest_byte_sha256": (
                "sha256:" + hashlib.sha256(failure_manifest_bytes).hexdigest()
            ),
            "ingestion_job_id": failure_job_id,
            "record_count": len(bound_child_failure_exclusions.get("records", ())),
            "unknown_parse_failures_must_reject": True,
            "full_source_coverage_claim": False,
        }
    if reference_repair_manifest_path is not None:
        if not reference_repair_manifest_path.is_absolute():
            raise ValueError("ingestion reference repair manifest path must be absolute")
        manifest_bytes = reference_repair_manifest_path.read_bytes()
        if not manifest_bytes or len(manifest_bytes) > _MAX_REFERENCE_REPAIR_MANIFEST_BYTES:
            raise ValueError("ingestion reference repair manifest size is invalid")
        repair_manifest = json.loads(manifest_bytes)
        revised_job_id = repair_manifest.get("revised_job_id")
        matching_jobs = [
            Path(store_directory) for store_directory, job_id in jobs if job_id == revised_job_id
        ]
        repairs = repair_manifest.get("repairs")
        if (
            repair_manifest.get("artifact_id")
            != "formowl_ingestion_job_reference_metadata_repair_v1"
            or repair_manifest.get("revision_kind") != "metadata_reference_repair"
            or repair_manifest.get("new_extraction_performed") is not False
            or repair_manifest.get("source_completeness_claim") is not False
            or len(matching_jobs) != 1
            or not isinstance(repairs, list)
            or not repairs
        ):
            raise ValueError("ingestion reference repair manifest binding is invalid")
        revised_job_path = matching_jobs[0] / "ingestion" / "jobs" / f"{revised_job_id}.json"
        revised_job_digest = hashlib.sha256()
        with revised_job_path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                revised_job_digest.update(chunk)
        revised_job_byte_sha256 = "sha256:" + revised_job_digest.hexdigest()
        if (
            repair_manifest.get("revised_job_byte_sha256") != revised_job_byte_sha256
            or not isinstance(
                repair_manifest.get("original_job_byte_sha256"),
                str,
            )
            or not isinstance(
                repair_manifest.get("completed_id_string_audit_sha256"),
                str,
            )
        ):
            raise ValueError("ingestion reference repair job seal is invalid")
        reference_repair_binding = {
            "artifact_id": repair_manifest["artifact_id"],
            "revision_kind": repair_manifest["revision_kind"],
            "manifest_byte_sha256": ("sha256:" + hashlib.sha256(manifest_bytes).hexdigest()),
            "original_job_id": repair_manifest.get("original_job_id"),
            "original_job_byte_sha256": repair_manifest["original_job_byte_sha256"],
            "revised_job_id": revised_job_id,
            "revised_job_byte_sha256": revised_job_byte_sha256,
            "completed_id_string_audit_sha256": repair_manifest["completed_id_string_audit_sha256"],
            "repair_count": len(repairs),
            "new_extraction_performed": False,
            "source_completeness_claim": False,
        }

    if (
        not jobs
        or directory.exists()
        or (
            sidecar_parent_job_id is not None
            and sidecar_parent_job_id not in {job_id for _, job_id in jobs}
        )
    ):
        raise ValueError("new revision directory and completed ingestion jobs are required")
    directory.parent.mkdir(parents=True, exist_ok=True)
    preparation_directory = directory.parent / f".{directory.name}.preembedding"
    if preparation_directory.exists():
        preparation = json.loads((preparation_directory / "preparation.json").read_bytes())
        if (
            preparation.get("requested_jobs") != jobs
            or preparation.get("sidecar_parent_job_id") != sidecar_parent_job_id
            or preparation.get("reference_repair_binding") != reference_repair_binding
            or preparation.get("bound_child_failure_binding") != bound_child_failure_binding
        ):
            raise ValueError("ingestion revision preparation request binding mismatch")
        if prepare_only:
            snapshot = json.loads((preparation_directory / "observations.json").read_bytes())
            return {
                "phase": "source_preparation_checkpoint_ready",
                "preparation_directory": str(preparation_directory),
                "source_observation_count": preparation.get("source_observation_count"),
                "retrieval_helper_observation_count": len(
                    snapshot.get("observation_references", ())
                ),
                "embedding_status": "not_started",
            }
        print(
            json.dumps(
                {
                    "phase": "resuming_preembedding_checkpoint",
                    "source_observation_count": preparation.get("source_observation_count"),
                    "preparation_directory": str(preparation_directory),
                }
            ),
            flush=True,
        )
        return _finish_prepared_ingestion_revision(
            directory,
            preparation_directory,
            started=time.monotonic(),
            pause_before_embedding_file=pause_before_embedding_file,
        )
    observations, bundles, job_bindings, job_store_bindings, warnings = [], [], [], [], []
    sidecar_parent_binding: dict[str, object] | None = None
    roots = set()
    started = time.monotonic()
    components = __import__(
        "formowl_core",
        fromlist=["load_issue56_target_runtime_components"],
    ).load_issue56_target_runtime_components()
    tokenizer_profile = components.tokenizer_profile
    exact_temporary_root = Path(
        tempfile.mkdtemp(
            prefix=f".{directory.name}.exact-cells.",
            dir=directory.parent,
        )
    )
    os.chmod(exact_temporary_root, 0o700)
    value_directory = exact_temporary_root / "values"
    row_directory = exact_temporary_root / "rows"
    value_directory.mkdir(mode=0o700)
    row_directory.mkdir(mode=0o700)
    recovery_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{directory.name}.source-pass-recovery.",
            dir=directory.parent,
        )
    )
    os.chmod(recovery_directory, 0o700)
    recovery_reference_stream = os.fdopen(
        os.open(
            recovery_directory / "observation-references.jsonl",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        ),
        "wb",
    )
    recovery_sidecar_stream = os.fdopen(
        os.open(
            recovery_directory / "sidecar-parent-events.jsonl",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        ),
        "wb",
    )

    shard_streams: dict[tuple[str, str], Any] = {}
    shard_digests: dict[tuple[str, str], Any] = {}
    shard_sizes: dict[tuple[str, str], int] = {}
    shard_counts: dict[tuple[str, str], int] = {}

    def write_shard(kind: str, key_hash: str, value: object) -> None:
        shard = key_hash[7:9]
        key = (kind, shard)
        stream = shard_streams.get(key)
        if stream is None:
            path = (value_directory if kind == "value" else row_directory) / f"{shard}.jsonl"
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            stream = os.fdopen(descriptor, "wb")
            shard_streams[key] = stream
            shard_digests[key] = hashlib.sha256()
            shard_sizes[key] = 0
            shard_counts[key] = 0
        encoded = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        stream.write(encoded)
        shard_digests[key].update(encoded)
        shard_sizes[key] += len(encoded)
        shard_counts[key] += 1

    column_capabilities: dict[
        tuple[str, str, bool, str],
        set[str],
    ] = {}
    exact_counts = {
        "table_row": 0,
        "table_cell": 0,
        "source_provided_row": 0,
        "candidate_only_row": 0,
        "unavailable_row": 0,
        "attachment_authorized_row": 0,
        "attachment_unresolved_row": 0,
        "inline_authorized_row": 0,
        "inline_unresolved_row": 0,
    }
    observation_type_counts: dict[str, int] = {}
    processed_observation_count = 0

    def write_recovery_line(stream, value: object) -> None:
        stream.write(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    def persist_recovery_progress(
        status: str,
        retained_retrieval_helper_count: int,
    ) -> None:
        for stream in (
            recovery_reference_stream,
            recovery_sidecar_stream,
        ):
            stream.flush()
            os.fsync(stream.fileno())
        payload = {
            "artifact_id": ("formowl_issue56_ingestion_source_pass_recovery_v1"),
            "status": status,
            "usable_revision_artifact": False,
            "requested_job_ids": [job_id for _, job_id in jobs],
            "sidecar_parent_job_id": sidecar_parent_job_id,
            "exact_partial_directory": exact_temporary_root.name,
            "processed_observation_count": processed_observation_count,
            "retained_retrieval_helper_count": retained_retrieval_helper_count,
            "table_cell_reference_count": exact_counts["table_cell"],
            "observation_type_counts": observation_type_counts,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".progress.",
            dir=recovery_directory,
        )
        os.fchmod(descriptor, 0o600)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, recovery_directory / "progress.json")
        finally:
            temporary.unlink(missing_ok=True)

    persist_recovery_progress(
        "incomplete_operator_only",
        len(observations),
    )

    def row_key(observation: object) -> str:
        return sha256_json(
            [
                observation.asset_id,
                observation.location.get("parent_message_observation_id"),
                observation.location.get("mime_ordinal"),
                observation.location.get("sheet_name"),
                observation.location.get("table_index"),
                observation.location.get("row_index"),
            ]
        )

    def exact_cell_projection(
        observation: object,
    ) -> tuple[str, str, set[str], set[str], bool]:
        structure = (observation.payload or {}).get("table_structure")
        if not isinstance(structure, dict):
            raise ValueError("table cell structure is unavailable")
        cell_index = observation.location.get("cell_index")
        if not isinstance(cell_index, int) or isinstance(cell_index, bool):
            raise ValueError("table cell location is invalid")
        raw_field = structure.get("column_name")
        if not isinstance(raw_field, str) or not raw_field:
            raw_field = f"column_{cell_index}"
        safe_field = redact_public_raw_references(raw_field)[0][:120]
        normalized_field = tokenizer_profile.normalize_exact_identifier_surface(safe_field)
        if not normalized_field:
            raise ValueError("table cell field is invalid")
        column_hash = source_occurrence_column_capability_hash(normalized_field)
        value = observation.text or ""
        safe_value = redact_public_raw_references(value)[0][:400]
        value_hashes = {
            sha256_json(token) for token in tokenizer_profile.analyze(value).tokens if token
        }
        if safe_value.strip():
            value_hashes.add(
                source_occurrence_exact_cell_value_hash(
                    column_hash,
                    safe_value,
                )
            )
        elif (
            structure.get("structure_status") == "source_provided"
            and (observation.payload or {}).get("cell_state") == "absent"
        ):
            value_hashes.add(sha256_json(["source_provided_structural_blank_value_v1"]))
        header_surfaces: list[str] = []
        header_path = structure.get("header_path", ())
        if not isinstance(header_path, (list, tuple)) or len(header_path) > 4:
            raise ValueError("table cell header path is invalid")
        for component in header_path:
            if not isinstance(component, dict):
                raise ValueError("table cell header path is invalid")
            component_value = component.get("value")
            if not isinstance(component_value, str) or not component_value.strip():
                raise ValueError("table cell header path is invalid")
            safe_component = redact_public_raw_references(component_value)[0][:120]
            normalized_component = tokenizer_profile.normalize_exact_identifier_surface(
                safe_component
            )
            if not normalized_component:
                raise ValueError("table cell header path is invalid")
            header_surfaces.append(normalized_component)
        candidate_surfaces = [safe_field, *header_surfaces]
        candidate_hashes = {
            sha256_json(field_token)
            for surface in candidate_surfaces
            for field_token in tokenizer_profile.analyze(surface).tokens
            if field_token
        }
        phrase_surfaces = list(header_surfaces)
        if not phrase_surfaces or phrase_surfaces[-1] != normalized_field:
            phrase_surfaces.append(normalized_field)
        for start in range(len(phrase_surfaces)):
            for end in range(
                start + 1,
                min(len(phrase_surfaces), start + 4) + 1,
            ):
                candidate_hashes.add(sha256_json("".join(phrase_surfaces[start:end])))
        inline = (observation.payload or {}).get("lineage", {}).get(
            "source_family"
        ) == "mail_inline_table"
        return (
            safe_field,
            column_hash,
            value_hashes,
            candidate_hashes,
            inline,
        )

    for job_index, (store_directory, job_id) in enumerate(jobs, start=1):
        print(
            json.dumps(
                {
                    "phase": "loading_completed_ingestion_job",
                    "job_index": job_index,
                    "job_count": len(jobs),
                }
            ),
            flush=True,
        )
        reader = open_completed_ingestion_job_reader(
            job_id,
            job_store=JobStore(store_directory),
            asset_store=AssetStore(store_directory),
            observation_store=ObservationStore(store_directory),
            extractor_run_store=ExtractorRunStore(store_directory),
            requester_user_id=APPROVER_ACTOR,
            workspace_id=WORKSPACE_ID,
            bound_child_failure_exclusions=(
                bound_child_failure_exclusions
                if job_id == (bound_child_failure_binding or {}).get("ingestion_job_id")
                else None
            ),
        )
        authority = reader.authority
        asset = authority.asset
        runs = authority.runs
        print(
            json.dumps(
                {
                    "phase": "completed_ingestion_job_authority_loaded",
                    "job_index": job_index,
                    "job_count": len(jobs),
                    "observation_count": authority.observation_count,
                    "run_count": len(runs),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            ),
            flush=True,
        )
        if asset.asset_id in roots:
            raise ValueError("revision has multiple active jobs for one root")
        roots.add(asset.asset_id)
        warnings.extend(warning for run in runs for warning in run.warnings)
        source_kinds = _authorized_ingestion_root_source_kinds(authority)
        mail_root = AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND in source_kinds
        source_ref = (
            _accepted_governed_mail_root_source_ref(to_plain(asset.source_ref))
            if mail_root else None
        )
        collect_sidecar_parents = job_id == sidecar_parent_job_id
        if collect_sidecar_parents and not mail_root:
            raise ValueError("sidecar parent requires a registered mail root")
        text_root_run_ids = {
            run.extractor_run_id for run in runs
            if run.asset_id == asset.asset_id and run.status == "succeeded"
        } if AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND in source_kinds else set()
        sidecar_records_by_occurrence: dict[str, dict[str, object]] = {}
        attachment_max_by_occurrence: dict[str, int] = {}
        for observation in reader.iter_observations():
            processed_observation_count += 1
            observation_type_counts[observation.observation_type] = (
                observation_type_counts.get(observation.observation_type, 0) + 1
            )
            observation_hash = sha256_json(observation.to_dict())
            if (mail_root and observation.observation_type in {
                "mail_folder_occurrence",
                "email_thread",
                "email_message",
                "email_header",
                "email_body_segment",
                "email_attachment_occurrence",
                "table_row",
            }) or (
                observation.modality == "text"
                and observation.observation_type in {"heading", "paragraph"}
                and observation.asset_id == asset.asset_id
                and observation.extractor_run_id in text_root_run_ids
            ):
                reference = [
                    job_index - 1,
                    observation.observation_id,
                    observation_hash,
                ]
                observations.append(reference)
                write_recovery_line(
                    recovery_reference_stream,
                    reference,
                )
            if collect_sidecar_parents and observation.observation_type == ("email_message"):
                location = observation.location
                payload = observation.payload or {}
                required = {
                    "source_content_hash": location.get("source_content_hash"),
                    "folder_path_hash": location.get("folder_path_hash"),
                    "message_id": location.get("message_id"),
                    "message_index": location.get("message_index"),
                    "parent_source_inventory_id": location.get("source_inventory_id"),
                    "parent_source_inventory_item_id": location.get("source_inventory_item_id"),
                    "archive_id": location.get("archive_id"),
                    "mailbox_id": location.get("mailbox_id"),
                    "message_occurrence_id": location.get("message_occurrence_id"),
                    "thread_id": location.get("thread_id"),
                    "message_fingerprint": payload.get("message_fingerprint"),
                }
                if (
                    any(
                        not isinstance(value, str) or not value
                        for key, value in required.items()
                        if key != "message_index"
                    )
                    or not isinstance(required["message_index"], int)
                    or isinstance(required["message_index"], bool)
                    or required["message_index"] < 1
                ):
                    raise ValueError("sidecar parent message metadata is incomplete")
                occurrence_id = str(required["message_occurrence_id"])
                record: dict[str, object] = {
                    **required,
                    "parent_observation_id": observation.observation_id,
                    "parent_extractor_run_id": observation.extractor_run_id,
                    "existing_attachment_max_index": 0,
                }
                source_local_key = location.get("source_local_key")
                if isinstance(source_local_key, str) and source_local_key:
                    record["source_local_key"] = source_local_key
                if occurrence_id in sidecar_records_by_occurrence:
                    raise ValueError("sidecar parent message occurrence is ambiguous")
                sidecar_records_by_occurrence[occurrence_id] = record
                write_recovery_line(
                    recovery_sidecar_stream,
                    ["message", job_index - 1, occurrence_id, record],
                )
            elif (
                collect_sidecar_parents
                and observation.observation_type == "email_attachment_occurrence"
            ):
                occurrence_id = observation.location.get("message_occurrence_id")
                attachment_index = observation.location.get("attachment_index")
                if (
                    isinstance(occurrence_id, str)
                    and occurrence_id
                    and isinstance(attachment_index, int)
                    and not isinstance(attachment_index, bool)
                    and attachment_index > 0
                ):
                    attachment_max_by_occurrence[occurrence_id] = max(
                        attachment_max_by_occurrence.get(occurrence_id, 0),
                        attachment_index,
                    )
                    write_recovery_line(
                        recovery_sidecar_stream,
                        [
                            "attachment",
                            job_index - 1,
                            occurrence_id,
                            attachment_index,
                        ],
                    )
            if observation.observation_type == "table_row":
                key = row_key(observation)
                inline = (observation.payload or {}).get("lineage", {}).get(
                    "source_family"
                ) == "mail_inline_table"
                structure = (observation.payload or {}).get("table_structure")
                structure_status = (
                    structure.get("structure_status") if isinstance(structure, dict) else None
                )
                if structure_status not in {
                    "source_provided",
                    "candidate_only",
                    "unavailable",
                }:
                    raise ValueError("table row structure is invalid")
                exact_counts["table_row"] += 1
                exact_counts[f"{structure_status}_row"] += 1
                row_role = structure.get("row_role")
                family = "inline" if inline else "attachment"
                if not (structure_status == "source_provided" and row_role in {"header", "totals"}):
                    exact_counts[f"{family}_authorized_row"] += 1
                    if structure_status == "unavailable" or row_role == "header_candidate":
                        exact_counts[f"{family}_unresolved_row"] += 1
                write_shard(
                    "row",
                    key,
                    [
                        "row",
                        key,
                        job_index - 1,
                        observation.observation_id,
                        observation_hash,
                        inline,
                    ],
                )
            elif observation.observation_type == "table_cell":
                key = row_key(observation)
                (
                    safe_field,
                    column_hash,
                    value_hashes,
                    candidate_hashes,
                    inline,
                ) = exact_cell_projection(observation)
                exact_counts["table_cell"] += 1
                column_capabilities.setdefault(
                    (
                        safe_field,
                        column_hash,
                        inline,
                        str(
                            (observation.payload or {})
                            .get("table_structure", {})
                            .get("structure_status")
                        ),
                    ),
                    set(),
                ).update(candidate_hashes)
                write_shard(
                    "row",
                    key,
                    [
                        "cell",
                        key,
                        job_index - 1,
                        observation.observation_id,
                        observation_hash,
                        column_hash,
                        inline,
                    ],
                )
                for value_hash in sorted(value_hashes):
                    write_shard(
                        "value",
                        value_hash,
                        [value_hash, key, inline],
                    )
            if processed_observation_count % 100000 == 0:
                persist_recovery_progress(
                    "incomplete_operator_only",
                    len(observations),
                )
                print(
                    json.dumps(
                        {
                            "phase": "deriving_compact_ingestion_revision",
                            "processed_observation_count": (processed_observation_count),
                            "retained_retrieval_helper_count": len(observations),
                            "table_cell_reference_count": exact_counts["table_cell"],
                            "elapsed_seconds": round(
                                time.monotonic() - started,
                                3,
                            ),
                        }
                    ),
                    flush=True,
                )
        if (
            processed_observation_count
            < sum(binding["observation_count"] for binding in job_bindings)
            + authority.observation_count
        ):
            raise ValueError("completed ingestion job reader ended early")
        if collect_sidecar_parents:
            for occurrence_id, record in sidecar_records_by_occurrence.items():
                record["existing_attachment_max_index"] = attachment_max_by_occurrence.get(
                    occurrence_id, 0
                )
            records = sorted(
                sidecar_records_by_occurrence.values(),
                key=lambda item: (
                    item["source_content_hash"],
                    item["folder_path_hash"],
                    item["message_id"],
                    item["message_index"],
                ),
            )
            join_keys = {
                (
                    item["source_content_hash"],
                    item["folder_path_hash"],
                    item["message_id"],
                    item["message_index"],
                )
                for item in records
            }
            parent_run_ids = {str(item["parent_extractor_run_id"]) for item in records}
            if not records or len(join_keys) != len(records) or len(parent_run_ids) != 1:
                raise ValueError("sidecar parent binding is incomplete")
            parent_run_id = next(iter(parent_run_ids))
            parent_run = next(
                (
                    run
                    for run in runs
                    if run.extractor_run_id == parent_run_id
                    and run.asset_id == asset.asset_id
                    and run.status == "succeeded"
                ),
                None,
            )
            if parent_run is None:
                raise ValueError("sidecar parent run binding is invalid")
            parent_binding_fingerprint = sha256_json(records)
            sidecar_core = {
                "artifact_id": "issue56_readpst_sidecar_parent_binding_v1",
                "schema_version": 1,
                "source_asset_id": asset.asset_id,
                "source_fingerprint": asset.content_hash,
                "prior_ingestion_job_id": authority.ingestion_job_id,
                "prior_parent_run_id": parent_run_id,
                "prior_job_fingerprint": authority.job_fingerprint,
                "parent_binding_count": len(records),
                "parent_binding_fingerprint": parent_binding_fingerprint,
                "permission_scope_fingerprint": sha256_json(dict(authority.permission_scope)),
                "records": records,
            }
            if reference_repair_binding is not None:
                sidecar_core["reference_repair_binding"] = reference_repair_binding
            sidecar_parent_binding = {
                **sidecar_core,
                "artifact_fingerprint": sha256_json(sidecar_core),
            }
        job_bindings.append(
            {
                "root_asset_hash": asset.content_hash,
                "job_fingerprint": authority.job_fingerprint,
                "run_fingerprints": [sha256_json(run.to_dict()) for run in runs],
                "observation_count": authority.observation_count,
                **({"source_ref": source_ref} if source_ref is not None else {}),
                "excluded_child_runs": [
                    {
                        "run_fingerprint": sha256_json(run.to_dict()),
                        "status": run.status,
                        "reason_codes": list(run.errors),
                    }
                    for run in runs
                    if run.status != "succeeded"
                ],
                **(
                    {"bound_child_failure_binding": (bound_child_failure_binding)}
                    if job_id == (bound_child_failure_binding or {}).get("ingestion_job_id")
                    else {}
                ),
            }
        )
        job_store_bindings.append(
            {
                "job_index": job_index - 1,
                "store_directory": str(Path(store_directory).resolve()),
                "ingestion_job_id": authority.ingestion_job_id,
                "job_fingerprint": authority.job_fingerprint,
                "observation_count": authority.observation_count,
            }
        )
        del reader
    if processed_observation_count != sum(binding["observation_count"] for binding in job_bindings):
        raise ValueError("completed ingestion job scope is incomplete")
    persist_recovery_progress(
        "source_validated_pending_checkpoint",
        len(observations),
    )
    recovery_reference_stream.close()
    recovery_sidecar_stream.close()

    for stream in shard_streams.values():
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
    shard_streams.clear()

    source_authority_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_completed_ingestion_job_authority_v1",
            "requester_user_id": APPROVER_ACTOR,
            "workspace_id": WORKSPACE_ID,
            "jobs": job_bindings,
        }
    )
    exact_manifest_core = {
        "artifact_id": "formowl_issue56_ingestion_exact_cell_lookup_v1",
        "schema_version": 1,
        "source_authority_fingerprint": source_authority_fingerprint,
        "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "job_count": len(job_bindings),
        "counts": exact_counts,
        "columns": [
            {
                "field": field,
                "column_hash": column_hash,
                "inline_table": inline,
                "structure_status": structure_status,
                "candidate_hashes": sorted(candidate_hashes),
            }
            for (
                field,
                column_hash,
                inline,
                structure_status,
            ), candidate_hashes in sorted(
                column_capabilities.items(),
                key=lambda item: item[0],
            )
        ],
        "shards": [
            {
                "kind": kind,
                "shard": shard,
                "record_count": shard_counts[(kind, shard)],
                "size_bytes": shard_sizes[(kind, shard)],
                "sha256": "sha256:" + shard_digests[(kind, shard)].hexdigest(),
            }
            for kind, shard in sorted(shard_counts)
        ],
    }
    exact_manifest = {
        **exact_manifest_core,
        "manifest_fingerprint": sha256_json(exact_manifest_core),
    }
    exact_manifest_bytes = json.dumps(
        exact_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    exact_manifest_path = exact_temporary_root / "manifest.json"
    descriptor = os.open(
        exact_manifest_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(exact_manifest_bytes)
    exact_manifest_sha256 = "sha256:" + hashlib.sha256(exact_manifest_bytes).hexdigest()
    source_binding = {
        "jobs": job_bindings,
        "source_authority_fingerprint": source_authority_fingerprint,
        "exact_lookup_manifest_sha256": exact_manifest_sha256,
        "extraction_coverage": {
            "scope": "declared_completed_jobs_only",
            "root_count": len(roots),
            "warning_count": len(warnings),
            "warning_code_counts": {code: warnings.count(code) for code in sorted(set(warnings))},
            "source_completeness_certified": False,
        },
    }
    if reference_repair_binding is not None:
        source_binding["reference_repair_binding"] = reference_repair_binding
    if bound_child_failure_binding is not None:
        source_binding["bound_child_failure_binding"] = bound_child_failure_binding
    sidecar_parent_binding_path: Path | None = None
    sidecar_parent_binding_sha256: str | None = None
    if sidecar_parent_binding is not None:
        encoded_parent_binding = json.dumps(
            sidecar_parent_binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sidecar_parent_binding_sha256 = (
            "sha256:" + hashlib.sha256(encoded_parent_binding).hexdigest()
        )
        sidecar_parent_binding_path = (
            directory.parent / f".{directory.name}.sidecar-parent-binding.json"
        )
        descriptor, temporary_parent_name = tempfile.mkstemp(
            prefix=f".{directory.name}.sidecar-parent-binding.",
            dir=directory.parent,
        )
        os.fchmod(descriptor, 0o600)
        temporary_parent = Path(temporary_parent_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded_parent_binding)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_parent, sidecar_parent_binding_path)
        finally:
            temporary_parent.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "phase": "sidecar_parent_map_ready",
                    "path": str(sidecar_parent_binding_path),
                    "sha256": sidecar_parent_binding_sha256,
                    "parent_binding_count": sidecar_parent_binding["parent_binding_count"],
                    "elapsed_seconds": round(
                        time.monotonic() - started,
                        3,
                    ),
                }
            ),
            flush=True,
        )

    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    def encoded_chunks(value: object):
        if isinstance(value, bytes):
            yield value
            return
        for chunk in encoder.iterencode(value):
            yield chunk.encode("utf-8")

    directory.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_snapshot_name = tempfile.mkstemp(
        prefix=f".{directory.name}.observations.",
        dir=directory.parent,
    )
    os.fchmod(descriptor, 0o600)
    temporary_snapshot = Path(temporary_snapshot_name)
    snapshot_size = 0
    snapshot_digest = hashlib.sha256()

    def snapshot_write(stream, value: object) -> None:
        nonlocal snapshot_size
        for chunk in encoded_chunks(value):
            snapshot_size += len(chunk)
            if snapshot_size > _MAX_INGESTION_REVISION_SOURCE_BYTES:
                raise ValueError("ingestion revision snapshot exceeds bounded maximum size")
            stream.write(chunk)
            snapshot_digest.update(chunk)

    try:
        with os.fdopen(descriptor, "wb") as stream:
            snapshot_write(stream, b'{"bundles":[')
            for index, bundle in enumerate(bundles):
                if index:
                    snapshot_write(stream, b",")
                snapshot_write(stream, bundle.to_dict())
            snapshot_write(stream, b'],"observation_references":[')
            for index, reference in enumerate(observations):
                if index:
                    snapshot_write(stream, b",")
                snapshot_write(stream, reference)
            snapshot_write(stream, b'],"source_binding":')
            snapshot_write(stream, source_binding)
            snapshot_write(stream, b',"job_store_bindings":')
            snapshot_write(stream, job_store_bindings)
            snapshot_write(stream, b"}")
    except BaseException:
        temporary_snapshot.unlink(missing_ok=True)
        raise
    snapshot_hash = "sha256:" + snapshot_digest.hexdigest()
    print(
        json.dumps(
            {
                "phase": "compact_ingestion_revision_snapshot_sized",
                "snapshot_size_bytes": snapshot_size,
                "maximum_size_bytes": _MAX_INGESTION_REVISION_SOURCE_BYTES,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        ),
        flush=True,
    )
    temporary_preparation = Path(
        tempfile.mkdtemp(
            prefix=f".{directory.name}.preembedding.",
            dir=directory.parent,
        )
    )
    os.chmod(temporary_preparation, 0o700)
    try:
        os.replace(
            temporary_snapshot,
            temporary_preparation / "observations.json",
        )
        os.replace(
            exact_temporary_root,
            temporary_preparation / "exact-cells",
        )
        if sidecar_parent_job_id is not None:
            if sidecar_parent_binding_path is None or sidecar_parent_binding_sha256 is None:
                raise ValueError("sidecar parent binding was not produced")
            os.link(
                sidecar_parent_binding_path,
                temporary_preparation / "sidecar-parent-binding.json",
            )
        if bound_child_failure_binding is not None:
            if bound_child_failure_manifest_path is None:
                raise ValueError("bound child failure manifest path is unavailable")
            os.link(
                bound_child_failure_manifest_path,
                temporary_preparation / "bound-child-failure-exclusions.json",
            )
        preparation_core = {
            "artifact_id": ("formowl_issue56_ingestion_revision_preparation_v1"),
            "schema_version": 1,
            "requested_jobs": jobs,
            "sidecar_parent_job_id": sidecar_parent_job_id,
            "reference_repair_binding": reference_repair_binding,
            "bound_child_failure_binding": bound_child_failure_binding,
            "sidecar_parent_binding_sha256": (sidecar_parent_binding_sha256),
            "snapshot_sha256": snapshot_hash,
            "snapshot_size_bytes": snapshot_size,
            "exact_lookup_manifest_sha256": exact_manifest_sha256,
            "source_observation_count": processed_observation_count,
            "observation_type_counts": observation_type_counts,
            "job_count": len(job_bindings),
        }
        preparation = {
            **preparation_core,
            "preparation_fingerprint": sha256_json(preparation_core),
        }
        descriptor = os.open(
            temporary_preparation / "preparation.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                json.dumps(
                    preparation,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_preparation, preparation_directory)
        print(
            json.dumps(
                {
                    "phase": "source_preparation_checkpoint_ready",
                    "source_observation_count": processed_observation_count,
                    "retrieval_helper_observation_count": len(observations),
                    "preparation_directory": str(preparation_directory),
                    "elapsed_seconds": round(
                        time.monotonic() - started,
                        3,
                    ),
                }
            ),
            flush=True,
        )
        if prepare_only:
            return {
                "phase": "source_preparation_checkpoint_ready",
                "preparation_directory": str(preparation_directory),
                "recovery_directory": str(recovery_directory),
                "source_observation_count": processed_observation_count,
                "retrieval_helper_observation_count": len(observations),
                "embedding_status": "not_started",
            }
        shutil.rmtree(recovery_directory, ignore_errors=True)
        del observations
        return _finish_prepared_ingestion_revision(
            directory,
            preparation_directory,
            started=started,
            prepared_bundles=bundles,
            pause_before_embedding_file=pause_before_embedding_file,
        )
    finally:
        temporary_snapshot.unlink(missing_ok=True)
        if exact_temporary_root.exists():
            shutil.rmtree(exact_temporary_root)
        if temporary_preparation.exists():
            shutil.rmtree(temporary_preparation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"),
    )
    parser.add_argument("--temporary-lan-diagnostic", action="store_true")
    parser.add_argument("--temporary-access-code")
    parser.add_argument("--behavior-log", type=Path)
    parser.add_argument("--record-raw-uat-interactions", action="store_true")
    parser.add_argument(
        "--codex-runtime-state-dir",
        type=Path,
        default=os.environ.get("FORMOWL_ISSUE56_UAT_CODEX_RUNTIME_STATE_DIR"),
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("FORMOWL_UAT_CODEX_COMMAND", "codex"),
    )
    parser.add_argument("--codex-provider-api-key-file", type=Path)
    parser.add_argument("--build-ingestion-revision", type=Path)
    parser.add_argument(
        "--ingestion-job", nargs=2, action="append", metavar=("STORE_DIR", "JOB_ID")
    )
    parser.add_argument("--sidecar-parent-job")
    parser.add_argument(
        "--ingestion-reference-repair-manifest",
        type=Path,
    )
    parser.add_argument(
        "--ingestion-child-failure-manifest",
        type=Path,
    )
    parser.add_argument("--base-ingestion-preparation", type=Path)
    parser.add_argument("--supplement-prior-job")
    parser.add_argument(
        "--prepare-ingestion-revision-only",
        action="store_true",
    )
    parser.add_argument("--pause-before-embedding-file", type=Path)
    parser.add_argument("--pause-before-graph-file", type=Path)
    parser.add_argument("--ingestion-revision", type=Path)
    parser.add_argument("--ingestion-revision-sha256")
    parser.add_argument("--ingestion-projection-postgres-config", type=Path)
    parser.add_argument(
        "--max-candidates",
        type=int,
        help="required for indexed bounded continuation; positive candidate bound",
    )
    args = parser.parse_args()
    if args.host is None:
        args.host = "0.0.0.0" if args.temporary_lan_diagnostic else "127.0.0.1"
    if args.port is None:
        args.port = 8088 if args.temporary_lan_diagnostic else 8766
    if (
        args.ingestion_projection_postgres_config is not None
        and args.build_ingestion_revision is not None
    ):
        if args.max_candidates is not None and args.max_candidates < 1:
            parser.error("--max-candidates must be a positive integer")
        preparation_directory = (
            args.build_ingestion_revision.parent
            / f".{args.build_ingestion_revision.name}.preembedding"
        )
        if (
            not preparation_directory.is_dir()
            or args.ingestion_revision is not None
            or args.prepare_ingestion_revision_only
            or args.ingestion_job
        ):
            parser.error(
                "indexed build requires the existing composed preparation, not new ingestion jobs"
            )
        connection = _open_ingestion_projection_connection(
            args.ingestion_projection_postgres_config
        )
        report = _finish_prepared_ingestion_revision(
            args.build_ingestion_revision,
            preparation_directory,
            started=time.monotonic(),
            projection_connection=connection,
            pause_before_embedding_file=args.pause_before_embedding_file,
            pause_before_graph_file=args.pause_before_graph_file,
            max_candidates=args.max_candidates,
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.pause_before_graph_file is not None:
        parser.error("--pause-before-graph-file requires the indexed preparation build route")
    if args.build_ingestion_revision is not None:
        if not args.ingestion_job or args.ingestion_revision is not None:
            parser.error("build requires completed ingestion jobs, not an active revision")
        if args.base_ingestion_preparation is not None:
            if (
                len(args.ingestion_job) != 1
                or args.supplement_prior_job is None
                or args.ingestion_child_failure_manifest is None
                or args.sidecar_parent_job is not None
                or args.ingestion_reference_repair_manifest is not None
            ):
                parser.error(
                    "supplement build requires one delta job, its bound "
                    "child-failure manifest, and the prior root job"
                )
            preparation_directory = (
                args.build_ingestion_revision.parent
                / f".{args.build_ingestion_revision.name}.preembedding"
            )
            if not preparation_directory.exists():
                supplement_input = (
                    args.build_ingestion_revision.parent
                    / f"{args.build_ingestion_revision.name}.sidecar-input"
                )
                prepared = _build_ingestion_revision(
                    supplement_input,
                    args.ingestion_job,
                    bound_child_failure_manifest_path=(args.ingestion_child_failure_manifest),
                    prepare_only=True,
                )
                composed = _compose_sidecar_supplement_preparation(
                    args.build_ingestion_revision,
                    base_preparation_directory=(args.base_ingestion_preparation),
                    supplement_preparation_directory=Path(prepared["preparation_directory"]),
                    supplement_contract_directory=Path(args.ingestion_job[0][0]),
                    prior_job_id=args.supplement_prior_job,
                    bound_child_failure_manifest_path=(args.ingestion_child_failure_manifest),
                )
                if args.prepare_ingestion_revision_only:
                    print(json.dumps(composed, sort_keys=True))
                    return 0
            elif args.prepare_ingestion_revision_only:
                preparation = json.loads((preparation_directory / "preparation.json").read_bytes())
                print(
                    json.dumps(
                        {
                            "phase": ("supplement_preparation_checkpoint_ready"),
                            "preparation_directory": str(preparation_directory),
                            "source_observation_count": preparation.get("source_observation_count"),
                            "embedding_status": "not_started",
                        },
                        sort_keys=True,
                    )
                )
                return 0
            report = _finish_prepared_ingestion_revision(
                args.build_ingestion_revision,
                preparation_directory,
                started=time.monotonic(),
                pause_before_embedding_file=(args.pause_before_embedding_file),
            )
        else:
            if args.supplement_prior_job is not None:
                parser.error("--supplement-prior-job requires " "--base-ingestion-preparation")
            report = _build_ingestion_revision(
                args.build_ingestion_revision,
                args.ingestion_job,
                sidecar_parent_job_id=args.sidecar_parent_job,
                reference_repair_manifest_path=(args.ingestion_reference_repair_manifest),
                bound_child_failure_manifest_path=(args.ingestion_child_failure_manifest),
                prepare_only=args.prepare_ingestion_revision_only,
                pause_before_embedding_file=(args.pause_before_embedding_file),
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.sidecar_parent_job is not None:
        parser.error("--sidecar-parent-job requires --build-ingestion-revision")
    if args.ingestion_job:
        parser.error("--ingestion-job requires --build-ingestion-revision")
    if args.ingestion_reference_repair_manifest is not None:
        parser.error("--ingestion-reference-repair-manifest requires " "--build-ingestion-revision")
    if args.ingestion_child_failure_manifest is not None:
        parser.error("--ingestion-child-failure-manifest requires " "--build-ingestion-revision")
    if args.base_ingestion_preparation is not None:
        parser.error("--base-ingestion-preparation requires " "--build-ingestion-revision")
    if args.supplement_prior_job is not None:
        parser.error("--supplement-prior-job requires " "--build-ingestion-revision")
    if args.prepare_ingestion_revision_only:
        parser.error("--prepare-ingestion-revision-only requires " "--build-ingestion-revision")
    if args.pause_before_embedding_file is not None:
        parser.error("--pause-before-embedding-file requires " "--build-ingestion-revision")
    if bool(args.ingestion_revision) != bool(args.ingestion_revision_sha256):
        parser.error("ingestion revision path and sha256 must be supplied together")
    if args.ingestion_revision and not args.temporary_lan_diagnostic:
        parser.error("ingestion revision activation is temporary-LAN diagnostic only")
    if args.temporary_access_code is not None and not args.temporary_lan_diagnostic:
        parser.error("--temporary-access-code is temporary-LAN-only")
    if bool(args.behavior_log) != args.record_raw_uat_interactions:
        parser.error("--behavior-log and --record-raw-uat-interactions must be used together")
    if (args.behavior_log or args.record_raw_uat_interactions) and not (
        args.temporary_lan_diagnostic
    ):
        parser.error("raw behavior recording is temporary-LAN-only")
    if not args.temporary_lan_diagnostic and not args.public_base_url:
        parser.error("--public-base-url or FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL is required")
    if args.codex_runtime_state_dir is None:
        parser.error(
            "--codex-runtime-state-dir or "
            "FORMOWL_ISSUE56_UAT_CODEX_RUNTIME_STATE_DIR is required"
        )
    runtime_paths = validate_codex_runtime_state(args.codex_runtime_state_dir)
    provider_env_key = runtime_paths.provider_env_key
    if provider_env_key is None:
        if args.codex_provider_api_key_file is not None:
            parser.error("Codex provider API key file is invalid for ChatGPT runtime state")
        conversation_model = CodexAppServerConversationModel(
            CodexAppServerStdioTransport(
                command=build_hardened_codex_app_server_command(args.codex_command),
                cwd=runtime_paths.workspace,
                codex_home=runtime_paths.codex_home,
                runtime_workspace=runtime_paths.workspace,
            ),
            workspace_dir=runtime_paths.workspace,
            model=_MODEL,
            reasoning_effort="high",
        )
    else:
        if runtime_paths.provider_base_url is None or args.codex_provider_api_key_file is None:
            parser.error("Codex provider API key file is required")
        try:
            provider_api_key = _read_codex_provider_api_key(args.codex_provider_api_key_file)
        except ValueError as exc:
            parser.error(str(exc))
        conversation_model = CodexResponsesConversationModel(
            base_url=runtime_paths.provider_base_url,
            api_key=provider_api_key,
            model=_MODEL,
        )
    if args.temporary_lan_diagnostic:
        ingestion_revision = None
        if args.ingestion_revision is not None:
            from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision

            ingestion_revision = load_issue56_ingestion_revision(
                args.ingestion_revision,
                expected_revision_sha256=args.ingestion_revision_sha256,
                projection_connection_factory=(
                    lambda: _open_ingestion_projection_connection(
                        args.ingestion_projection_postgres_config
                    )
                    if args.ingestion_projection_postgres_config is not None
                    else None
                ),
            )
        print(
            f"Temporary LAN diagnostic: http://{args.host}:{args.port}/",
            flush=True,
        )
        print(
            "WARNING: raw prompts and browser-visible results will be recorded."
            if args.record_raw_uat_interactions
            else "Raw UAT interactions are not being recorded.",
            flush=True,
        )
        query_service = create_issue56_temporary_lan_query_service(
            conversation_model,
            behavior_log_path=args.behavior_log,
            record_raw_uat_interactions=args.record_raw_uat_interactions,
            ingestion_revision=ingestion_revision,
        )
    else:
        try:
            query_service = asyncio.run(
                create_issue56_uat_query_service(
                    conversation_model,
                    public_base_url=args.public_base_url,
                )
            )
        except Exception:
            conversation_model.close()
            raise
    with query_service:
        server = create_mail_human_uat_http_server(
            args.host,
            args.port,
            query_service,
            temporary_access_code=(
                args.temporary_access_code if args.temporary_lan_diagnostic else None
            ),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
