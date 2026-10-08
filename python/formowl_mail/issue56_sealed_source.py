"""Load one sealed Issue #56 mail source into the existing authorized runtime.

This module is intentionally a narrow diagnostic intake adapter.  It validates
the immutable source, materialization, identity-scope, and candidate artifacts
through their existing owner contracts, then constructs the existing
``AuthorizedSemanticMailSession`` and source-backed candidate graph.  It does
not parse a source archive, read a UAT manifest, execute a query, or write
canonical graph state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import stat
import sqlite3
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)
from formowl_core import (
    load_issue56_target_mail_tokenizer_profile,
    load_issue56_target_runtime_components,
)
from formowl_graph import EffectiveGraphView
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    JobStore,
    ObservationStore,
)
from formowl_ingestion.extractors.text import PlainTextObservationExtractor

from .bundle import MailEvidenceBundle
from .candidates import (
    SourceBoundIdentifierMentionBatch,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
)
from .hybrid import (
    AuthorizedHybridMailIndex,
    AuthorizedSemanticMailSession,
    EvidenceIdentityLineageCrosswalk,
    RelationProjectionBasePrecompute,
    SourceBackedGraphBuild,
    build_authorized_semantic_observation_session,
    AuthorizedHybridObservationIndexArtifact,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    precompute_evidence_identity_lineage_crosswalk,
    _sealed_source_neutral_observation,
    precompute_relation_projection_base,
)
from .query import (
    GitHubProjectOccurrenceLineage,
    MailAttachmentChildOccurrenceLineage,
    MailInlineTableOccurrenceLineage,
    MailMessageOccurrenceLineage,
    TextDocumentOccurrenceLineage,
    REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES,
    RevisionOwnedMailSourceScan,
    build_authorized_observation_snippet_index,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from .semantic_plan import validated_authorized_semantic_source
from .semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
)
from .import_workflow import (
    CompletedIngestionJobAuthority,
    open_completed_ingestion_job_reader,
)

from scripts import issue56_identity_scope_attestation as identity_attestation
from scripts import issue56_simulated_uat as simulated_uat
from scripts import issue56_source_identifier_candidates as candidate_builder


ARTIFACT_ID = "formowl_issue56_sealed_source_diagnostic_load_v1"
SCHEMA_VERSION = 1
SOURCE_ARTIFACT_CATEGORY = "sealed_source_complete_retrieval_ready_mail_v1"
IDENTITY_SCOPE_MODE = WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
WORKSPACE_ID = "workspace_formowl"
APPROVER_ACTOR = "user_full_pst_domain_hard_case_eval_owner"
SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v2"
SUPPLEMENTAL_OBSERVATION_ARTIFACT_ID = "formowl_issue56_supplemental_observation_partition_v1"

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_MAX_INGESTION_REVISION_SOURCE_BYTES = 4 * 1024 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
_MAX_SAFE_BYTES = 16 * 1024 * 1024
# Per-message parent maps grow with completed mail jobs, not small metadata.
# Keep their JSON intake finite and separate from every generic manifest cap.
_MAX_INGESTION_PARENT_BINDING_BYTES = 256 * 1024 * 1024
_REVISION_TEXT_RETRIEVAL_OBSERVATION_TYPES = frozenset({"heading", "paragraph"})


def _authorized_ingestion_root_source_kinds(
    authority: CompletedIngestionJobAuthority,
) -> set[str]:
    """Derive native source kinds from the registered root extractor only."""
    source_ref = to_plain(authority.asset.source_ref) or {}
    text_extractor = PlainTextObservationExtractor()
    kinds: set[str] = set()
    root_runs = [
        run
        for run in authority.runs
        if run.asset_id == authority.asset.asset_id and run.status == "succeeded"
    ]
    if not root_runs or any(run.input_hash != authority.asset.content_hash for run in root_runs):
        raise ContractValidationError("ingestion source root authority binding is invalid")
    for run in root_runs:
        if run.extractor_type in {"mail_archive", "mail_attachment_backfill"}:
            kinds.add(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND)
        elif (
            run.extractor_name == text_extractor.name()
            and run.extractor_type == text_extractor.extractor_type()
            and authority.asset.mime_type in text_extractor.supported_mime_types()
            and source_ref.get("source_system") != "formowl_mail_attachment"
            and source_ref.get("source_type") != "email_attachment_occurrence"
        ):
            kinds.add(AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND)
        else:
            raise ContractValidationError("ingestion source root family is unsupported")
    return kinds


class Issue56SealedSourceLoadError(RuntimeError):
    """Fail-closed error carrying one stable, public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class Issue56SealedSourceLoad:
    """Private runtime objects plus a hash/count/status-only public binding."""

    observations: tuple[Observation, ...] = field(repr=False)
    observations_by_bundle_id: Mapping[str, Sequence[Observation]] = field(
        repr=False,
        compare=False,
    )
    source_bundle: MailEvidenceBundle = field(repr=False, compare=False)
    query_bundle: MailEvidenceBundle = field(repr=False, compare=False)
    session: AuthorizedSemanticMailSession = field(repr=False, compare=False)
    index: AuthorizedHybridMailIndex = field(repr=False, compare=False)
    identifier_mention_batch: SourceBoundIdentifierMentionBatch = field(
        repr=False,
        compare=False,
    )
    graph_build: SourceBackedGraphBuild = field(repr=False, compare=False)
    effective_graph_view: EffectiveGraphView = field(repr=False, compare=False)
    safe_binding: Mapping[str, Any]


@dataclass(frozen=True)
class Issue56IngestionRevision:
    """Private operator-built revision of complete authorized ingestion jobs."""

    observations: tuple[Observation, ...] = field(repr=False)
    bundles: tuple[MailEvidenceBundle, ...] = field(repr=False)
    session: Any = field(repr=False)
    snippet_index: Any = field(repr=False)
    graph_build: SourceBackedGraphBuild = field(repr=False)
    safe_binding: Mapping[str, Any]
    exact_lookup_directory: Path | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    exact_lookup_manifest: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    job_authorities: tuple[CompletedIngestionJobAuthority, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    source_records: Any | None = field(default=None, repr=False, compare=False)
    authorized_source: Any | None = field(default=None, repr=False, compare=False)

    @property
    def effective_graph_view(self) -> EffectiveGraphView:
        if self.graph_build is None:
            raise ContractValidationError("retrieval projection is unavailable")
        return self.graph_build.effective_graph_view


def _authorized_mail_selector_for_asset(asset: Any) -> str | None:
    """Derive the canonical mail selector from one validated owner asset."""

    source_ref = to_plain(getattr(asset, "source_ref", None))
    if not isinstance(source_ref, dict):
        return None
    source_id = source_ref.get("source_id")
    if (
        source_ref.get("source_system") != "formowl_upload_session"
        or source_ref.get("source_type") not in {"mail_archive", "mail_archive_upload"}
        or not isinstance(source_id, str)
        or not source_id
        or source_ref.get("source_key") != source_id
    ):
        return None
    return stable_resource_contract_id(
        "mailimport",
        "MailImportSession",
        {
            "upload_session_id": source_id,
            "workspace_id": asset.workspace_id,
            "owner_user_id": asset.owner_user_id,
            "source_asset_id": asset.asset_id,
            "archive_sha256": asset.content_hash,
        },
    )


class SourceNativeLexicalLookup:
    """Read-only lexical accelerator bound to one sealed source preparation.

    The lookup is deliberately not an evidence store.  It returns only
    observation hashes and compact owner references; callers must hydrate each
    result through ``CompletedIngestionJobAuthority`` before exposing source
    evidence.  This lets a source-start revision use a persisted lexical
    accelerator without treating an index miss as source absence or rebuilding
    anything inline.
    """

    ARTIFACT_ID = "formowl_issue56_source_native_lexical_lookup_v1"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        directory: Path,
        expected_source_revision_sha256: str,
        expected_snapshot_sha256: str,
        expected_source_authority_fingerprint: str,
        expected_tokenizer_id: str,
        expected_tokenizer_profile_fingerprint: str,
    ) -> None:
        self.directory = directory
        manifest_path = directory / "source-lookup-manifest.json"
        sqlite_path = directory / "source-lookup.sqlite"
        raw_manifest = manifest_path.read_bytes()
        if len(raw_manifest) > _MAX_SAFE_BYTES:
            raise ContractValidationError("source lexical lookup manifest is too large")
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractValidationError("source lexical lookup manifest is invalid") from exc
        if not isinstance(manifest, dict):
            raise ContractValidationError("source lexical lookup manifest is invalid")
        fingerprint = manifest.pop("manifest_fingerprint", None)
        if fingerprint != sha256_json(manifest):
            raise ContractValidationError("source lexical lookup manifest fingerprint mismatch")
        if (
            manifest.get("artifact_id") != self.ARTIFACT_ID
            or manifest.get("schema_version") != self.SCHEMA_VERSION
            or manifest.get("source_revision_sha256") != expected_source_revision_sha256
            or manifest.get("snapshot_sha256") != expected_snapshot_sha256
            or manifest.get("source_authority_fingerprint") != expected_source_authority_fingerprint
            or manifest.get("tokenizer_id") != expected_tokenizer_id
            or manifest.get("tokenizer_profile_fingerprint")
            != expected_tokenizer_profile_fingerprint
            or manifest.get("source_families") != ["document_text", "mail"]
        ):
            raise ContractValidationError("source lexical lookup authority binding mismatch")
        if not sqlite_path.is_file():
            raise ContractValidationError("source lexical lookup artifact is missing")
        # The accelerator can be larger than the UAT process memory budget.
        # Verify every byte without allocating a second whole-database copy.
        digest = hashlib.sha256()
        with sqlite_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if f"sha256:{digest.hexdigest()}" != manifest.get("sqlite_sha256"):
            raise ContractValidationError("source lexical lookup artifact hash mismatch")
        try:
            connection = sqlite3.connect(
                f"file:{sqlite_path}?mode=ro",
                uri=True,
                timeout=0.5,
                check_same_thread=False,
            )
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 500")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if not {"metadata", "helpers", "postings"}.issubset(tables):
                raise ContractValidationError("source lexical lookup schema is incomplete")
        except sqlite3.Error as exc:
            raise ContractValidationError("source lexical lookup artifact is unreadable") from exc
        self.manifest = MappingProxyType({**manifest, "manifest_fingerprint": fingerprint})
        self._connection = connection
        # The source-start handler is shared by the UAT service.  SQLite's
        # default thread check would reject a later request thread, while a
        # shared connection still needs serialization around its mutable
        # progress/busy handlers.
        self._connection_lock = threading.RLock()

    def _helper_row(
        self, *, observation_hash: str | None = None, observation_id: str | None = None
    ) -> dict[str, Any] | None:
        if (observation_hash is None) == (observation_id is None):
            raise ContractValidationError("source lexical lookup helper key is invalid")
        column, value = (
            ("observation_hash", observation_hash)
            if observation_hash is not None
            else ("observation_id", observation_id)
        )
        with self._connection_lock:
            row = self._connection.execute(
                f"SELECT observation_hash, observation_id, job_index, "
                f"job_fingerprint, source_scope_id, permission_scope_json, source_family "
                f"FROM helpers WHERE {column} = ? LIMIT 2",
                (value,),
            ).fetchall()
        if len(row) > 1:
            raise ContractValidationError("source lexical lookup helper is ambiguous")
        if not row:
            return None
        (
            row_hash,
            row_id,
            job_index,
            job_fingerprint,
            source_scope_id,
            permission_scope_json,
            source_family,
        ) = row[0]
        try:
            permission_scope = json.loads(permission_scope_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContractValidationError(
                "source lexical lookup permission binding is invalid"
            ) from exc
        if (
            not isinstance(row_hash, str)
            or not isinstance(row_id, str)
            or type(job_index) is not int
            or not isinstance(job_fingerprint, str)
            or not isinstance(source_scope_id, str)
            or not isinstance(permission_scope, dict)
            or source_family not in {"mail", "document_text"}
        ):
            raise ContractValidationError("source lexical lookup helper is invalid")
        return {
            "observation_hash": row_hash,
            "observation_id": row_id,
            "source_scope_id": source_scope_id,
            "reference": {
                "job_index": job_index,
                "job_fingerprint": job_fingerprint,
            },
            "permission_scope": permission_scope,
            "source_families": [source_family],
            "retrieval_source_family": source_family,
            "retrieval": True,
        }

    def get_helper(self, observation_id: str) -> dict[str, Any] | None:
        return self._helper_row(observation_id=observation_id)

    def helper_for_hash(self, observation_hash: str) -> dict[str, Any] | None:
        return self._helper_row(observation_hash=observation_hash)

    def helper_for_attachment_asset(self, child_asset_id: str) -> None:
        # The source-native lexical artifact intentionally contains no
        # attachment lineage.  Attachment providers use their owner path.
        del child_asset_id
        return None

    def helpers_for_occurrence(
        self,
        occurrence_id: str,
        *,
        after_id: str | None = None,
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        del occurrence_id, after_id, limit
        return []

    def source_family_lexical_lookup(
        self,
        query_tokens: Iterable[str],
        *,
        source_family: str,
        limit: int = 256,
        timeout_ms: int,
    ) -> list[str]:
        if source_family not in {"mail", "document_text"}:
            raise ContractValidationError("source lexical lookup family is invalid")
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ContractValidationError("source lexical lookup limit is invalid")
        if type(timeout_ms) is not int or timeout_ms < 1:
            raise ContractValidationError("source lexical lookup timeout is invalid")
        tokens = sorted({token for token in query_tokens if isinstance(token, str) and token})
        if not tokens:
            return []
        # Reserve a bounded, materially sized slice for each query token before
        # applying the final coverage ordering.  A small ``limit / token_count``
        # slice is not safe here: a candidate may contain a rare identity token
        # but sort late for another token, so the intersection is silently
        # excluded before hydration.  Keep the accelerator bounded while
        # allowing late candidates from the frozen source corpus to survive;
        # hydration, permission, lineage and source matching remain authoritative
        # after this query.  A timeout is still a miss, never source absence.
        per_token_limit = 8192
        deadline = time.monotonic() + timeout_ms / 1000
        with self._connection_lock:
            self._connection.execute(f"PRAGMA busy_timeout = {min(timeout_ms, 2000)}")
            self._connection.set_progress_handler(
                lambda: 1 if time.monotonic() >= deadline else 0,
                1000,
            )
            try:
                # Query the token-leading primary-key range separately.  A
                # window over the union of all token postings can scan the
                # complete posting table before applying its per-token bound;
                # on a large source artifact that consumes the whole fallback
                # deadline even though each token range is cheap.  The bounded
                # Python merge preserves the same coverage/best-rank ordering
                # without widening the artifact or retaining source text.
                scores: dict[str, list[int]] = {}
                for token in tokens:
                    rows = self._connection.execute(
                        "SELECT p.observation_hash FROM postings p "
                        "JOIN helpers h ON h.observation_hash = p.observation_hash "
                        "WHERE p.source_family = ? AND p.token = ? "
                        "ORDER BY p.observation_hash COLLATE BINARY LIMIT ?",
                        (source_family, token, per_token_limit),
                    ).fetchall()
                    for token_rank, row in enumerate(rows, start=1):
                        observation_hash = row[0]
                        if not isinstance(observation_hash, str) or not observation_hash:
                            raise ContractValidationError("source lexical lookup result is invalid")
                        score = scores.setdefault(observation_hash, [0, token_rank])
                        score[0] += 1
                        score[1] = min(score[1], token_rank)
                ordered = sorted(
                    scores.items(),
                    key=lambda item: (-item[1][0], item[1][1], item[0]),
                )
                result = [observation_hash for observation_hash, _ in ordered[:limit]]
            except sqlite3.OperationalError as exc:
                if "interrupted" not in str(exc).casefold():
                    raise
                # A timed-out accelerator is a miss, never a source-negative.
                # The caller can continue with the bounded sealed-reference
                # scan and report incomplete coverage if its outer deadline is
                # also exhausted.
                result = []
            finally:
                self._connection.set_progress_handler(None, 0)
        if any(not isinstance(item, str) or not item for item in result):
            raise ContractValidationError("source lexical lookup result is invalid")
        return result

    def close(self) -> None:
        with self._connection_lock:
            self._connection.close()


class IngestionRevisionSourceRecords:
    """Bounded source access through sealed references and existing job authority.

    Metadata lives in the existing graph index owner; source bytes/Observations
    stay in their original stores. A matching indexed hash is not an access
    grant. Every requested Observation still crosses the ordinary job reader's
    run, asset, content-hash and permission checks.
    """

    def __init__(
        self,
        *,
        runtime_store: Any,
        job_authorities: Sequence[CompletedIngestionJobAuthority],
        requester_user_id: str,
        workspace_id: str,
        expected_seal: str | None = None,
        observation_references: list[list[Any]] | None = None,
        authorized_source: Any | None = None,
    ) -> None:
        self.runtime_store = runtime_store
        self.job_authorities = tuple(job_authorities)
        # This is the list parsed from the already-verified observations.json
        # seal. Keep the same object; the complete reference sequence is large
        # and must not be duplicated in another source index.
        self.observation_references = observation_references
        self.requester_user_id = requester_user_id
        self.workspace_id = workspace_id
        self.authorized_source = authorized_source
        if not self.job_authorities or any(
            authority.asset.owner_user_id != requester_user_id
            or authority.asset.workspace_id != workspace_id
            or authority.asset.lifecycle_state != "active"
            for authority in self.job_authorities
        ):
            raise ContractValidationError("indexed ingestion source authority is invalid")
        self.manifest = runtime_store.reopen(expected_seal) if expected_seal is not None else None
        if (
            runtime_store is not None
            and hasattr(runtime_store, "workspace_id")
            and runtime_store.workspace_id != workspace_id
        ):
            raise ContractValidationError("indexed ingestion source workspace mismatch")
        if self.manifest is not None:
            metadata = self.manifest["view_metadata"]
            if metadata.get("session", metadata).get("requester_user_id") != requester_user_id:
                raise ContractValidationError("indexed ingestion source requester mismatch")
            expected_jobs = metadata.get("ingestion_job_fingerprints")
            if expected_jobs != [item.job_fingerprint for item in self.job_authorities]:
                raise ContractValidationError("indexed ingestion source job seals changed")

    @property
    def count(self) -> int:
        if self.manifest is None:
            raise ContractValidationError("source count requires a completed revision seal")
        return self.manifest["counts"]["helper"]

    @property
    def authorized_mail_import_session_ids(self) -> tuple[str, ...]:
        """Return persisted owner-bound mail selectors, never guessed selectors.

        The PostgreSQL projection intentionally does not retain a MailEvidenceBundle.
        The completed JobAuthority still retains the registered upload source
        reference, so the stable MailImportSession selector can be re-derived
        from that owner record using the same contract as bundle construction.
        """

        selectors: set[str] = set()
        for authority in self.job_authorities:
            selector = _authorized_mail_selector_for_asset(authority.asset)
            if selector is not None:
                selectors.add(selector)
        return tuple(sorted(selectors))

    def _authority_for_helper(
        self,
        helper: Mapping[str, Any],
    ) -> CompletedIngestionJobAuthority:
        """Validate one sealed helper binding before keyed Observation hydration."""

        if not isinstance(helper, Mapping):
            raise ContractValidationError("indexed ingestion source helper is invalid")
        reference = helper.get("reference")
        job_index = reference.get("job_index") if isinstance(reference, Mapping) else None
        if (
            isinstance(job_index, bool)
            or not isinstance(job_index, int)
            or not 0 <= job_index < len(self.job_authorities)
        ):
            raise ContractValidationError("indexed ingestion source job reference is invalid")
        authority = self.job_authorities[job_index]
        if (
            not isinstance(reference, Mapping)
            or reference.get("job_fingerprint") != authority.job_fingerprint
            or helper.get("permission_scope") != dict(authority.permission_scope)
            or helper.get("source_scope_id") != dict(authority.permission_scope).get("scope_id")
        ):
            raise ContractValidationError("indexed ingestion source permission binding mismatch")
        if not isinstance(helper.get("observation_id"), str) or not isinstance(
            helper.get("observation_hash"), str
        ):
            raise ContractValidationError("indexed ingestion source helper identity is invalid")
        return authority

    def _scan_sealed_authorized_observations(
        self,
        *,
        source_family: str,
        source_scope_ids: Sequence[str],
        max_observations: int,
        deadline_monotonic: float | None,
        mail_import_session_id: str | None,
        observation_callback: Callable[[Observation, str], bool] | None,
    ) -> RevisionOwnedMailSourceScan:
        """Read only sealed references, independent of retrieval helpers."""

        references = getattr(self, "observation_references", None)
        references_available = isinstance(references, list)
        if not references_available and not callable(
            getattr(self.runtime_store, "source_family_lexical_lookup", None)
        ):
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=0,
                complete=False,
                stop_reason="source_reference_unavailable",
            )

        source_scope_by_job_index: dict[int, str] = {}
        for job_index, authority in enumerate(self.job_authorities):
            if source_family == "mail":
                selector = _authorized_mail_selector_for_asset(authority.asset)
                if mail_import_session_id is not None:
                    if selector == mail_import_session_id:
                        source_scope_by_job_index[job_index] = selector
                    continue
                # A captured/native mail source has no upload-session selector.
                # Use only its already validated permission scope as the
                # internal scan scope; it is not a public mail selector.
                scope_id = dict(authority.permission_scope).get("scope_id")
                if isinstance(scope_id, str) and scope_id:
                    source_scope_by_job_index[job_index] = selector or scope_id
            else:
                scope_id = dict(authority.permission_scope).get("scope_id")
                if isinstance(scope_id, str) and scope_id in source_scope_ids:
                    source_scope_by_job_index[job_index] = scope_id
        if not source_scope_by_job_index:
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=0,
                complete=True,
            )

        selected: list[tuple[Observation, str]] = []
        scanned = 0
        seen_mail_parents: set[tuple[str, ...]] = set()
        pending_mail_children: dict[tuple[str, ...], list[tuple[Observation, str]]] = {}

        def observation_matches(
            observation: Observation,
            authority: CompletedIngestionJobAuthority,
        ) -> bool:
            if source_family == "mail":
                return (
                    observation.modality == "mail"
                    and observation.observation_type in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES
                )
            if (
                observation.modality != "text"
                or observation.observation_type not in _REVISION_TEXT_RETRIEVAL_OBSERVATION_TYPES
            ):
                return False
            if to_plain(observation.permission_scope) != dict(authority.permission_scope):
                raise ContractValidationError("indexed ingestion document-text binding is invalid")
            return True

        def emit(
            observation: Observation,
            observed_scope: str,
            authority: CompletedIngestionJobAuthority,
        ) -> bool:
            def deliver(item: Observation, scope: str) -> bool:
                if observation_callback is None:
                    selected.append((item, scope))
                    return True
                return observation_callback(item, scope)

            occurrence_id = (observation.location or {}).get("message_occurrence_id")
            payload = observation.payload or {}
            if source_family != "mail" or not isinstance(occurrence_id, str):
                return deliver(observation, observed_scope)
            # Lexical order need not be extraction order. A child without its
            # own fingerprint needs its genuine, hash-checked parent delivered
            # first; never borrow a parent across jobs/runs/assets/scopes.
            parent_key = (
                authority.job_fingerprint, observation.extractor_run_id,
                observation.asset_id, observed_scope, occurrence_id,
            )
            is_parent = observation.observation_type == "email_message"
            if (
                not is_parent
                and not isinstance(payload.get("message_fingerprint"), str)
                and parent_key not in seen_mail_parents
            ):
                pending_mail_children.setdefault(parent_key, []).append((observation, observed_scope))
                return True
            if not deliver(observation, observed_scope):
                return False
            if is_parent and isinstance(payload.get("message_fingerprint"), str):
                seen_mail_parents.add(parent_key)
                for child, scope in pending_mail_children.pop(parent_key, ()):
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        return True  # The caller reports deadline exhaustion.
                    if not deliver(child, scope):
                        return False
            return True

        # The lexical index is an accelerator only.  It is used when the
        # sealed reference corpus is larger than this bounded pass (or the
        # references are unavailable), and every hash is rehydrated through
        # the existing helper/authority contract before the callback sees it.
        query_terms: tuple[str, ...] = ()
        if callable(getattr(self.runtime_store, "source_family_lexical_lookup", None)):
            from formowl_retrieval.gateway import current_source_evidence_query_terms

            query_terms = current_source_evidence_query_terms()
        # Only successfully hydrated, matching sources may suppress a later
        # authoritative read. Merely seeing an index candidate proves nothing.
        shortlist_hashes: set[str] = set()
        shortlist_seen_hashes: set[str] = set()
        should_shortlist = bool(query_terms) and callable(
            getattr(self.runtime_store, "source_family_lexical_lookup", None)
        )
        if should_shortlist:
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="deadline",
                )
            lookup_timeout_ms = 500
            if deadline_monotonic is not None:
                lookup_timeout_ms = min(
                    lookup_timeout_ms,
                    max(1, int((deadline_monotonic - time.monotonic()) * 1000)),
                )
            shortlisted = self.runtime_store.source_family_lexical_lookup(
                query_terms,
                source_family=source_family,
                limit=min(max_observations, 256),
                timeout_ms=lookup_timeout_ms,
            )
            if not isinstance(shortlisted, list):
                raise ContractValidationError("graph lexical lookup shortlist is invalid")
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="deadline",
                )
            for observation_hash in shortlisted:
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="deadline",
                    )
                if not isinstance(observation_hash, str) or not observation_hash:
                    raise ContractValidationError(
                        "graph lexical lookup observation hash is invalid"
                    )
                if observation_hash in shortlist_seen_hashes:
                    continue
                shortlist_seen_hashes.add(observation_hash)
                helper = self.runtime_store.helper_for_hash(observation_hash)
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="deadline",
                    )
                if helper is None:
                    continue
                authority = self._authority_for_helper(helper)
                if helper["observation_hash"] != observation_hash:
                    raise ContractValidationError("indexed ingestion source helper hash mismatch")
                reference = helper["reference"]
                job_index = reference["job_index"]
                observed_scope = source_scope_by_job_index.get(job_index)
                if observed_scope is None:
                    continue
                if scanned >= max_observations:
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="observation_limit",
                    )
                scanned += 1
                observation = authority.load_indexed_observation(
                    helper["observation_id"],
                    expected_observation_hash=helper["observation_hash"],
                    expected_job_fingerprint=authority.job_fingerprint,
                )
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="deadline",
                    )
                if not observation_matches(observation, authority):
                    continue
                shortlist_hashes.add(observation_hash)
                if not emit(observation, observed_scope, authority):
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="callback",
                    )
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    return RevisionOwnedMailSourceScan(
                        observations=tuple(selected),
                        scanned_observation_count=scanned,
                        complete=False,
                        stop_reason="deadline",
                    )
            if not references_available:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason=(
                        "indexed_shortlist" if shortlist_hashes else "indexed_shortlist_miss"
                    ),
                )

        if not references_available:
            return RevisionOwnedMailSourceScan(
                observations=tuple(selected),
                scanned_observation_count=scanned,
                complete=False,
                stop_reason="source_reference_unavailable",
            )

        for reference in references:
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="deadline",
                )
            if (
                not isinstance(reference, list)
                or len(reference) != 3
                or isinstance(reference[0], bool)
                or not isinstance(reference[0], int)
                or not 0 <= reference[0] < len(self.job_authorities)
                or not isinstance(reference[1], str)
                or not reference[1]
                or not isinstance(reference[2], str)
                or not reference[2]
            ):
                raise ContractValidationError("ingestion revision Observation reference is invalid")
            job_index, observation_id, expected_observation_hash = reference
            observed_scope = source_scope_by_job_index.get(job_index)
            if observed_scope is None:
                continue
            if expected_observation_hash in shortlist_hashes:
                continue
            if scanned >= max_observations:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="observation_limit",
                )
            scanned += 1
            authority = self.job_authorities[job_index]
            observation = authority.load_indexed_observation(
                observation_id,
                expected_observation_hash=expected_observation_hash,
                expected_job_fingerprint=authority.job_fingerprint,
            )
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="deadline",
                )
            if not observation_matches(observation, authority):
                continue
            if not emit(observation, observed_scope, authority):
                return RevisionOwnedMailSourceScan(
                    observations=(),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="callback",
                )
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                return RevisionOwnedMailSourceScan(
                    observations=tuple(selected),
                    scanned_observation_count=scanned,
                    complete=False,
                    stop_reason="deadline",
                )
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            return RevisionOwnedMailSourceScan(
                observations=tuple(selected),
                scanned_observation_count=scanned,
                complete=False,
                stop_reason="deadline",
            )
        return RevisionOwnedMailSourceScan(
            observations=tuple(selected),
            scanned_observation_count=scanned,
            complete=not pending_mail_children,
            stop_reason="source_parent_binding_unresolved" if pending_mail_children else None,
        )

    def scan_authorized_observations(
        self,
        *,
        source_family: str,
        max_observations: int,
        deadline_monotonic: float | None = None,
        source_scope_ids: Sequence[str] = (),
        mail_import_session_id: str | None = None,
        observation_callback: Callable[[Observation, str], bool] | None = None,
    ) -> RevisionOwnedMailSourceScan:
        """Read one authorized source family through sealed job references."""

        if source_family not in {"mail", "document_text"}:
            raise ContractValidationError("source fallback family is invalid")
        if (
            isinstance(max_observations, bool)
            or not isinstance(max_observations, int)
            or max_observations < 1
        ):
            raise ContractValidationError("source fallback observation limit is invalid")
        if deadline_monotonic is not None and (
            isinstance(deadline_monotonic, bool) or not isinstance(deadline_monotonic, (int, float))
        ):
            raise ContractValidationError("source fallback deadline is invalid")
        if source_family == "document_text":
            if (
                not isinstance(source_scope_ids, Sequence)
                or isinstance(source_scope_ids, (str, bytes))
                or not source_scope_ids
                or any(not isinstance(item, str) or not item for item in source_scope_ids)
                or tuple(source_scope_ids) != tuple(sorted(set(source_scope_ids)))
            ):
                raise ContractValidationError("source fallback document scope is invalid")
            authorized_job_scopes = {
                dict(authority.permission_scope).get("scope_id")
                for authority in self.job_authorities
            }
            if not set(source_scope_ids) <= authorized_job_scopes:
                raise ContractValidationError("source fallback document scope is unauthorized")
            if mail_import_session_id is not None:
                raise ContractValidationError("document source fallback cannot use a mail selector")
        elif source_scope_ids:
            raise ContractValidationError("mail source fallback cannot use document scopes")
        if mail_import_session_id is not None and (
            not isinstance(mail_import_session_id, str) or not mail_import_session_id
        ):
            raise ContractValidationError("source fallback selector is invalid")
        if observation_callback is not None and not callable(observation_callback):
            raise ContractValidationError("source fallback callback is invalid")

        return self._scan_sealed_authorized_observations(
            source_family=source_family,
            source_scope_ids=source_scope_ids,
            max_observations=max_observations,
            deadline_monotonic=deadline_monotonic,
            mail_import_session_id=mail_import_session_id,
            observation_callback=observation_callback,
        )

    def scan_authorized_mail_observations(
        self,
        *,
        max_observations: int,
        deadline_monotonic: float | None = None,
        mail_import_session_id: str | None = None,
        observation_callback: Callable[[Observation, str], bool] | None = None,
    ) -> RevisionOwnedMailSourceScan:
        """Read a bounded sealed-reference mail slice through job authority.

        This deliberately bypasses neither permission nor the completed-job
        reader.  It does not populate the projection, rebuild an index, or
        retain the corpus.  An early stop is reported as incomplete, so callers
        cannot turn a bounded miss into a definitive no-data claim.
        """

        return self.scan_authorized_observations(
            source_family="mail",
            max_observations=max_observations,
            deadline_monotonic=deadline_monotonic,
            mail_import_session_id=mail_import_session_id,
            observation_callback=observation_callback,
        )

    def mail_import_session_id_for_observation(
        self,
        observation_id: str,
    ) -> str | None:
        """Resolve one Observation to its persisted owner-bound mail selector."""

        helper, authority = self._helper(observation_id)
        observation = self.get_observation(observation_id)
        if observation.modality != "mail" or observation.asset_id != authority.asset.asset_id:
            return None
        return _authorized_mail_selector_for_asset(authority.asset)

    def _helper(self, observation_id: str) -> tuple[dict[str, Any], CompletedIngestionJobAuthority]:
        helper = (
            self.runtime_store.get_helper(observation_id)
            if self.runtime_store is not None
            and callable(getattr(self.runtime_store, "get_helper", None))
            else None
        )
        if helper is None and self.observation_references is not None:
            for reference in self.observation_references:
                if (
                    isinstance(reference, list)
                    and len(reference) == 3
                    and reference[1] == observation_id
                ):
                    job_index, _, observation_hash = reference
                    authority = self.job_authorities[job_index]
                    helper = {
                        "observation_hash": observation_hash,
                        "observation_id": observation_id,
                        "source_scope_id": dict(authority.permission_scope)["scope_id"],
                        "reference": {
                            "job_index": job_index,
                            "job_fingerprint": authority.job_fingerprint,
                        },
                        "permission_scope": dict(authority.permission_scope),
                    }
                    break
        if helper is None or helper.get("observation_id") != observation_id:
            raise ContractValidationError("indexed ingestion source reference is unavailable")
        authority = self._authority_for_helper(helper)
        return helper, authority

    def get_observation(self, observation_id: str) -> Observation:
        helper, authority = self._helper(observation_id)
        return authority.load_indexed_observation(
            observation_id,
            expected_observation_hash=helper["observation_hash"],
            expected_job_fingerprint=helper["reference"]["job_fingerprint"],
        )

    def observation_hash(self, observation_id: str) -> str:
        helper, _ = self._helper(observation_id)
        return helper["observation_hash"]

    def observation_for_hash(self, observation_hash: str) -> Observation | None:
        helper = (
            self.runtime_store.helper_for_hash(observation_hash)
            if self.runtime_store is not None
            and callable(getattr(self.runtime_store, "helper_for_hash", None))
            else None
        )
        if helper is None and self.observation_references is not None:
            for reference in self.observation_references:
                if (
                    isinstance(reference, list)
                    and len(reference) == 3
                    and reference[2] == observation_hash
                ):
                    helper = {
                        "observation_hash": reference[2],
                        "observation_id": reference[1],
                    }
                    break
        return None if helper is None else self.get_observation(helper["observation_id"])

    def attachment_parent_for_child_asset(self, child_asset_id: str) -> Observation | None:
        helper = (
            self.runtime_store.helper_for_attachment_asset(child_asset_id)
            if self.runtime_store is not None
            and callable(getattr(self.runtime_store, "helper_for_attachment_asset", None))
            else None
        )
        return None if helper is None else self.get_observation(helper["observation_id"])

    def lineage(self, observation_id: str) -> Any:
        helper, authority = self._helper(observation_id)
        data = helper.get("lineage")
        if not isinstance(data, dict) and self.authorized_source is not None:
            observation = self.get_observation(observation_id)
            derived = source_occurrence_lineage_from_observation(
                observation,
                authorized_source=self.authorized_source,
            )
            return derived
        if not isinstance(data, dict) or data.get("source_observation_id") != observation_id:
            raise ContractValidationError("indexed ingestion source lineage is unavailable")
        if "parent_attachment_observation_id" in data:
            factory = MailAttachmentChildOccurrenceLineage
        elif "parent_message_observation_id" in data:
            factory = MailInlineTableOccurrenceLineage
        elif "source_record_fingerprint" in data:
            factory = GitHubProjectOccurrenceLineage
        elif {
            "asset_id",
            "extractor_run_id",
            "line_start",
            "line_end",
        }.issubset(data):
            factory = TextDocumentOccurrenceLineage
        else:
            factory = MailMessageOccurrenceLineage
        try:
            lineage = factory(**data)
        except TypeError as exc:
            raise ContractValidationError("indexed ingestion source lineage is invalid") from exc
        if isinstance(lineage, TextDocumentOccurrenceLineage):
            observation = authority.load_indexed_observation(
                observation_id,
                expected_observation_hash=helper["observation_hash"],
                expected_job_fingerprint=helper["reference"]["job_fingerprint"],
            )
            permission_scope = PermissionScope(**dict(authority.permission_scope))
            text_source = validated_authorized_semantic_source(
                source_kind=AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
                workspace_id=authority.asset.workspace_id,
                source_scope_ids=(permission_scope.scope_id,),
                authorized_permission_scopes=(permission_scope,),
            )
            expected = source_occurrence_lineage_from_observation(
                observation,
                authorized_source=text_source,
            )
            if expected != lineage:
                raise ContractValidationError("indexed ingestion text source lineage mismatch")
        return lineage

    def lineage_by_occurrence(
        self,
        occurrence_id: str,
        *,
        after_id: str | None = None,
        limit: int = 64,
    ) -> tuple[Any, ...]:
        if self.runtime_store is None or not callable(
            getattr(self.runtime_store, "helpers_for_occurrence", None)
        ):
            return ()
        return tuple(
            self.lineage(item["observation_id"])
            for item in self.runtime_store.helpers_for_occurrence(
                occurrence_id,
                after_id=after_id,
                limit=limit,
            )
        )

    def index_prepared_references(
        self,
        references: Sequence[Any],
        *,
        authorized_source: Any,
        progress: Callable[[Mapping[str, Any]], None] | None = None,
        max_candidates: int | None = None,
    ) -> None:
        """Hydrate one bounded batch, persist metadata, then release its bodies.

        The reference-only preparation is already sealed. This does not revisit
        raw ingestion or include source bodies in PostgreSQL helper records.
        Child parent joins are completed from persisted metadata after all
        genuine attachment parents have been indexed, independent of ID order.
        Actual child/parent schema validation still runs before its candidate
        is admitted by the existing bound-record snippet builder.
        """
        from formowl_mail.hybrid import (
            _semantic_observation_retrieval_source_family,
            _semantic_observation_source_families,
        )

        if max_candidates is not None:
            if (
                isinstance(max_candidates, bool)
                or not isinstance(max_candidates, int)
                or max_candidates < 1
            ):
                raise ContractValidationError("prepared reference candidate limit is invalid")
            # Apply the bound before reading any authority/reference or writing
            # helper metadata.  The unbounded production path remains unchanged.
            references = references[:max_candidates]

        store = self.runtime_store
        start = int(store.checkpoint_cursor("prepared_references") or "0")
        if not 0 <= start <= len(references):
            raise ContractValidationError("prepared source cursor is invalid")
        for offset in range(start, len(references), 256):
            batch = []
            for reference in references[offset : offset + 256]:
                if (
                    not isinstance(reference, list)
                    or len(reference) != 3
                    or isinstance(reference[0], bool)
                    or not isinstance(reference[0], int)
                    or not 0 <= reference[0] < len(self.job_authorities)
                    or not all(isinstance(value, str) for value in reference[1:])
                ):
                    raise ContractValidationError("prepared source reference is invalid")
                job_index, observation_id, observation_hash = reference
                authority = self.job_authorities[job_index]
                observation = authority.load_indexed_observation(
                    observation_id,
                    expected_observation_hash=observation_hash,
                    expected_job_fingerprint=authority.job_fingerprint,
                )
                if observation.modality == "mail" and observation.observation_type in {
                    "mail_folder_occurrence",
                    "email_thread",
                }:
                    continue  # Inventory remains in the immutable source checkpoint.
                item = {
                    "observation_id": observation_id,
                    "observation_hash": observation_hash,
                    "source_families": list(_semantic_observation_source_families(observation)),
                    "retrieval_source_family": _semantic_observation_retrieval_source_family(
                        observation,
                    ),
                    "source_scope_id": authority.permission_scope["scope_id"],
                    "reference": {
                        "job_index": job_index,
                        "job_fingerprint": authority.job_fingerprint,
                    },
                    "permission_scope": dict(authority.permission_scope),
                    "retrieval": observation.observation_type
                    in {
                        "email_message",
                        "email_header",
                        "email_body_segment",
                        "email_attachment_occurrence",
                        "table_row",
                    }
                    or (
                        observation.modality == "text"
                        and observation.observation_type
                        in _REVISION_TEXT_RETRIEVAL_OBSERVATION_TYPES
                    ),
                }
                if observation.modality == "mail":
                    lineage = source_occurrence_lineage_from_observation(
                        observation,
                        authorized_source=authorized_source,
                    )
                    item.update(lineage=to_plain(lineage), occurrence_id=lineage.occurrence_id)
                    if observation.observation_type == "email_attachment_occurrence":
                        item["attachment_child_asset_id"] = (observation.payload or {}).get(
                            "child_asset_id",
                            "",
                        )
                else:
                    nested = (observation.payload or {}).get("lineage", {})
                    if nested.get("source_family") == "mail_inline_table":
                        lineage = MailInlineTableOccurrenceLineage(
                            source_observation_id=observation_id,
                            observation_type=observation.observation_type,
                            **{
                                key: nested[key]
                                for key in (
                                    "parent_message_observation_id",
                                    "message_occurrence_id",
                                    "mime_ordinal",
                                    "table_ordinal",
                                )
                            },
                        )
                        item.update(lineage=to_plain(lineage), occurrence_id=lineage.occurrence_id)
                    elif nested.get("child_asset_id") == observation.asset_id:
                        item.update(
                            lineage=None,
                            occurrence_id=observation_id,
                            pending_child_asset_id=observation.asset_id,
                            observation_type=observation.observation_type,
                        )
                    elif observation.modality == "text":
                        lineage = source_occurrence_lineage_from_observation(
                            observation,
                            authorized_source=authorized_source,
                        )
                        item.update(
                            lineage=to_plain(lineage),
                            occurrence_id=lineage.occurrence_id,
                        )
                    else:
                        raise ContractValidationError(
                            "prepared child source lineage is unavailable"
                        )
                batch.append(item)
            store.put_helpers(batch)
            end = min(offset + 256, len(references))
            store.checkpoint("prepared_references", str(end), store.binding)
            if progress is not None and (end % 32768 == 0 or end == len(references)):
                progress({"phase": "prepared_source_references_persisted", "reference_count": end})
        cursor = store.checkpoint_cursor("prepared_lineages")
        while page := store.iter_helpers(after_id=cursor, limit=256):
            updates = []
            for item in page:
                child_asset_id = item.get("pending_child_asset_id")
                if child_asset_id is None:
                    continue
                parent = store.helper_for_attachment_asset(child_asset_id)
                if parent is None or parent["permission_scope"] != item["permission_scope"]:
                    raise ContractValidationError("prepared child parent binding is unavailable")
                lineage = MailAttachmentChildOccurrenceLineage(
                    source_observation_id=item["observation_id"],
                    observation_type=item.pop("observation_type"),
                    child_asset_id=item.pop("pending_child_asset_id"),
                    parent_attachment_observation_id=parent["observation_id"],
                    message_occurrence_id=parent["lineage"]["message_occurrence_id"],
                )
                item["lineage"] = to_plain(lineage)
                updates.append(item)
            if updates:
                store.put_helpers(updates)
            cursor = page[-1]["observation_id"]
            store.checkpoint("prepared_lineages", cursor, store.binding)
        if progress is not None:
            progress(
                {"phase": "prepared_source_metadata_ready", "reference_count": len(references)}
            )

    def iter_retrieval_pages(
        self,
        *,
        after_id: str | None = None,
        limit: int = 256,
    ) -> Iterable[tuple[Observation, ...]]:
        """Build-only bounded pages; normal requests use single-record methods."""
        cursor = after_id
        while page := self.runtime_store.iter_helpers(after_id=cursor, limit=limit):
            observations = tuple(
                self.get_observation(helper["observation_id"])
                for helper in page
                if helper.get("retrieval", True)
            )
            cursor = page[-1]["observation_id"]
            if observations:
                yield observations


def build_issue56_ingestion_revision(
    *,
    observations: Iterable[Observation],
    bundles: Iterable[MailEvidenceBundle],
    source_binding: Mapping[str, Any],
    requester_user_id: str,
    workspace_id: str,
    precomputed_index_artifact: AuthorizedHybridObservationIndexArtifact | None = None,
    retain_bundles: bool = True,
    retrieval_observation_ids: Sequence[str] | None = None,
    source_authority_fingerprint: str | None = None,
    build_progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> Issue56IngestionRevision:
    """Build outside MCP, with no source/query-specific selection or canonical writes.

    The caller supplies the compact retrieval/helper projection derived by the
    ordinary completed-job reader. Full source records remain in those bound
    JobStores and are not copied into this runtime session.
    """
    normalized_bundles = tuple(bundles)
    if (not normalized_bundles and source_authority_fingerprint is None) or any(
        bundle.mail_import_session.owner_user_id != requester_user_id
        or bundle.mail_import_session.workspace_id != workspace_id
        for bundle in normalized_bundles
    ):
        raise ContractValidationError("ingestion revision owner binding is invalid")
    retained_bundles = normalized_bundles if retain_bundles else ()
    if not retain_bundles:
        del normalized_bundles
    normalized = tuple(_sealed_source_neutral_observation(item) for item in observations)
    if not normalized or len({item.observation_id for item in normalized}) != len(normalized):
        raise ContractValidationError("ingestion revision Observation scope is invalid")
    scopes = {}
    for item in normalized:
        raw_scope = to_plain(item.permission_scope)
        scope = PermissionScope(**raw_scope)
        if scope.scope_id in scopes and scopes[scope.scope_id] != scope:
            raise ContractValidationError("ingestion revision permission scope is ambiguous")
        scopes[scope.scope_id] = scope
    evidence = tuple(
        item
        for item in normalized
        if not (
            item.modality == "mail"
            and item.observation_type in {"mail_folder_occurrence", "email_thread"}
        )
    )
    native_source_kinds: set[str] = set()
    for item in evidence:
        if item.modality == "mail":
            native_source_kinds.add(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND)
        elif item.modality == "text" and item.observation_type in (
            _REVISION_TEXT_RETRIEVAL_OBSERVATION_TYPES
        ):
            native_source_kinds.add(AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND)
        elif item.modality == "document" and item.observation_type in {
            "table_row",
            "table_cell",
        }:
            native_source_kinds.add(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND)
        else:
            raise ContractValidationError(
                "ingestion revision source occurrence family is unsupported"
            )
    if not native_source_kinds:
        raise ContractValidationError("ingestion revision source occurrence is unavailable")
    if AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND in native_source_kinds and (
        not isinstance(source_authority_fingerprint, str)
        or _SHA256_RE.fullmatch(source_authority_fingerprint) is None
        or source_binding.get("source_authority_fingerprint") != source_authority_fingerprint
    ):
        raise ContractValidationError("ingestion revision text source authority binding is invalid")
    if native_source_kinds == {AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND} and retained_bundles:
        raise ContractValidationError(
            "standalone text revision cannot require a mail evidence bundle"
        )
    revision_source_kind = (
        AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
        if native_source_kinds == {AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND}
        else AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND
        if native_source_kinds == {AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND}
        else AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND
        if native_source_kinds
        == {
            AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
        }
        else None
    )
    if revision_source_kind is None:
        raise ContractValidationError("ingestion revision source-kind combination is unsupported")
    source = validated_authorized_semantic_source(
        source_kind=revision_source_kind,
        workspace_id=workspace_id,
        source_scope_ids=tuple(scopes),
        authorized_permission_scopes=tuple(scopes.values()),
    )
    if retrieval_observation_ids is None:
        retrieval_ids = frozenset(
            item.observation_id
            for item in evidence
            if (
                source_authority_fingerprint is None
                or item.observation_type
                in {
                    "email_message",
                    "email_header",
                    "email_body_segment",
                    "email_attachment_occurrence",
                    "table_row",
                }
                or (
                    item.modality == "text"
                    and item.observation_type in _REVISION_TEXT_RETRIEVAL_OBSERVATION_TYPES
                )
            )
        )
    else:
        retrieval_ids = frozenset(retrieval_observation_ids)
        if (
            not retrieval_ids
            or len(retrieval_ids) != len(tuple(retrieval_observation_ids))
            or not retrieval_ids <= {item.observation_id for item in evidence}
        ):
            raise ContractValidationError("ingestion revision retrieval scope is invalid")
    retrieval = tuple(item for item in evidence if item.observation_id in retrieval_ids)
    source_lineages = tuple(
        source_occurrence_lineage_from_observation(item, authorized_source=source)
        for item in evidence
        if item.modality in {"mail", "text"}
    )
    lineages = normalized_authorized_observation_lineages(
        evidence,
        authorized_source=source,
        occurrence_lineages=source_lineages,
    )
    components = load_issue56_target_runtime_components()
    snippet_index, manifest = build_authorized_observation_snippet_index(
        retrieval,
        authorized_source=source,
        occurrence_lineages=tuple(
            lineage for lineage in lineages if lineage.source_observation_id in retrieval_ids
        ),
        authorized_observation_hash_by_id={
            item.observation_id: sha256_json(item.to_dict()) for item in retrieval
        },
        tokenizer_profile=components.tokenizer_profile,
    )
    if build_progress is not None:
        build_progress(
            {
                "phase": "retrieval_units_ready_for_embedding",
                "retrieval_observation_count": len(retrieval),
                "unique_dense_text_count": len(
                    {snippet.dense_evidence_text for snippet in snippet_index.snippets}
                ),
            }
        )
    session = build_authorized_semantic_observation_session(
        authorized_source=source,
        snippet_index=snippet_index,
        authorized_observations=evidence,
        retrieval_observations=retrieval,
        occurrence_lineages=lineages,
        requester_user_id=requester_user_id,
        expected_profile_fingerprint=components.tokenizer_profile.profile_fingerprint,
        precomputed_index_artifact=precomputed_index_artifact,
        expected_precomputed_index_artifact_fingerprint=(
            precomputed_index_artifact.artifact_fingerprint if precomputed_index_artifact else None
        ),
        validated_snippet_index_manifest=manifest,
        authorized_observations_are_sealed=True,
        source_authority_fingerprint=source_authority_fingerprint,
    )
    graph = build_authorized_source_backed_effective_graph_view(
        session=session,
        source_binding_fingerprint=sha256_json(source_binding),
    )
    binding = {
        "source_binding_fingerprint": sha256_json(source_binding),
        "source_session_binding_fingerprint": session.source_session_binding_fingerprint,
        "input_observation_count": len(normalized),
        "retrieval_observation_count": len(retrieval),
        "source_authority_fingerprint": source_authority_fingerprint,
        "inventory_only_observation_counts": {
            kind: sum(item.observation_type == kind for item in normalized)
            for kind in ("mail_folder_occurrence", "email_thread")
        },
        "index": manifest.to_safe_dict(),
        "graph": graph.to_safe_dict(),
        "candidate_graph_only": True,
        "continuous_ingestion_sync": False,
        "extraction_coverage": source_binding.get("extraction_coverage", {}),
    }
    return Issue56IngestionRevision(
        observations=session.authorized_observations,
        bundles=retained_bundles,
        session=session,
        snippet_index=snippet_index,
        graph_build=graph,
        safe_binding=binding,
    )


def open_ingestion_revision_job_authorities(
    bindings: Sequence[Mapping[str, Any]],
    bound_child_failure_exclusions: Mapping[str, Any] | None,
) -> tuple[CompletedIngestionJobAuthority, ...]:
    """Open existing job authority without hydrating its Observation corpus."""
    authorities = []
    for expected_index, binding in enumerate(bindings):
        if (
            not isinstance(binding, dict)
            or set(binding)
            != {
                "job_index",
                "store_directory",
                "ingestion_job_id",
                "job_fingerprint",
                "observation_count",
            }
            or binding.get("job_index") != expected_index
            or not isinstance(binding.get("store_directory"), str)
        ):
            raise ContractValidationError("ingestion revision JobStore binding is invalid")
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
                if binding["ingestion_job_id"]
                == (bound_child_failure_exclusions or {}).get(
                    "ingestion_job_id",
                )
                else None
            ),
        )
        authority = reader.authority
        if (
            authority.job_fingerprint != binding["job_fingerprint"]
            or authority.observation_count != binding["observation_count"]
        ):
            raise ContractValidationError("ingestion revision completed job changed")
        authorities.append(authority)
        del reader
    return tuple(authorities)


def load_issue56_ingestion_revision(
    revision_directory: Path,
    *,
    expected_revision_sha256: str,
    projection_connection: Any | None = None,
    projection_connection_factory: Callable[[], Any] | None = None,
) -> Issue56IngestionRevision:
    """Load a pinned revision or a separately pinned immutable source checkpoint.

    A preparation is source authority, not an activated retrieval projection.
    Its byte seal must be supplied by the operator, just like revision.json.
    Never downgrade a failed finalized projection load to a preparation.

    ``projection_connection`` remains the compatibility path for callers that
    already own an opened connection.  A factory may be supplied by startup
    code so an independently sealed source preparation does not open an
    unused projection connection; it is invoked only for a finalized
    PostgreSQL-backed revision.
    """
    if projection_connection is not None and projection_connection_factory is not None:
        raise ContractValidationError("ingestion revision projection connection is ambiguous")
    if not (revision_directory / "revision.json").exists():
        return _load_issue56_source_start_preparation(
            revision_directory,
            expected_sha256=expected_revision_sha256,
        )
    _, manifest = _read_sealed_json(
        revision_directory / "revision.json",
        expected_sha256=expected_revision_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="ingestion_revision",
    )
    if (
        manifest.get("artifact_id") != "formowl_issue56_ingestion_revision_v1"
        or manifest.get("requester_user_id") != APPROVER_ACTOR
        or manifest.get("workspace_id") != WORKSPACE_ID
    ):
        raise ContractValidationError("ingestion revision identity is invalid")
    _, snapshot = _read_sealed_json(
        revision_directory / "observations.json",
        expected_sha256=manifest["snapshot_sha256"],
        maximum_bytes=_MAX_INGESTION_REVISION_SOURCE_BYTES,
        reason_prefix="ingestion_snapshot",
    )
    observation_payloads = snapshot.get("observations")
    observation_references = snapshot.get("observation_references")
    bundle_payloads = snapshot.get("bundles")
    source_binding = snapshot.get("source_binding")
    retrieval_observation_ids = snapshot.get("retrieval_observation_ids")
    job_store_bindings = snapshot.get("job_store_bindings", [])
    if (
        (
            not isinstance(observation_payloads, list)
            and not isinstance(observation_references, list)
        )
        or (observation_payloads is not None and observation_references is not None)
        or not isinstance(bundle_payloads, list)
        or not isinstance(source_binding, dict)
        or (
            retrieval_observation_ids is not None
            and not isinstance(retrieval_observation_ids, list)
        )
        or not isinstance(job_store_bindings, list)
    ):
        raise ContractValidationError("ingestion revision snapshot schema is invalid")
    del snapshot

    exact_lookup_manifest: Mapping[str, Any] = {}
    exact_lookup_directory: Path | None = None
    exact_lookup_manifest_sha256 = manifest.get("exact_lookup_manifest_sha256")
    if exact_lookup_manifest_sha256 is not None:
        _, loaded_exact_lookup_manifest = _read_sealed_json(
            revision_directory / "exact-cells" / "manifest.json",
            expected_sha256=exact_lookup_manifest_sha256,
            maximum_bytes=_MAX_SAFE_BYTES,
            reason_prefix="ingestion_exact_lookup",
        )
        if loaded_exact_lookup_manifest.get(
            "artifact_id"
        ) != "formowl_issue56_ingestion_exact_cell_lookup_v1" or loaded_exact_lookup_manifest.get(
            "source_authority_fingerprint"
        ) != manifest.get("source_authority_fingerprint"):
            raise ContractValidationError("ingestion exact lookup authority binding mismatch")
        exact_lookup_manifest = MappingProxyType(dict(loaded_exact_lookup_manifest))
        exact_lookup_directory = revision_directory / "exact-cells"

    bound_child_failure_exclusions: Mapping[str, Any] | None = None
    bound_child_failure_manifest_sha256 = manifest.get("bound_child_failure_manifest_sha256")
    if bound_child_failure_manifest_sha256 is not None:
        _, loaded_bound_child_failure_exclusions = _read_sealed_json(
            revision_directory / "bound-child-failure-exclusions.json",
            expected_sha256=bound_child_failure_manifest_sha256,
            maximum_bytes=_MAX_SAFE_BYTES,
            reason_prefix="ingestion_child_failure_exclusions",
        )
        if (
            loaded_bound_child_failure_exclusions.get("artifact_id")
            != "formowl_bound_child_content_failure_exclusions_v1"
            or loaded_bound_child_failure_exclusions.get("unknown_parse_failures_must_reject")
            is not True
            or loaded_bound_child_failure_exclusions.get("full_source_coverage_claim") is not False
        ):
            raise ContractValidationError("ingestion child failure exclusion binding is invalid")
        bound_child_failure_exclusions = MappingProxyType(
            dict(loaded_bound_child_failure_exclusions)
        )

    job_authorities = open_ingestion_revision_job_authorities(
        job_store_bindings,
        bound_child_failure_exclusions,
    )
    if manifest.get("storage_mode") == "postgresql_projection_v1":
        from dataclasses import fields
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore
        from .hybrid import (
            reopen_authorized_semantic_observation_session,
            reopen_authorized_effective_graph_view,
        )

        if projection_connection is None:
            if projection_connection_factory is None:
                raise ContractValidationError(
                    "indexed revision requires its operator PostgreSQL connection"
                )
            projection_connection = projection_connection_factory()
        if projection_connection is None:
            raise ContractValidationError(
                "indexed revision requires its operator PostgreSQL connection"
            )
        projection = manifest["projection"]
        binding = projection["binding"]
        if (
            observation_payloads is not None
            or binding["snapshot_sha256"] != manifest["snapshot_sha256"]
            or binding["source_binding_fingerprint"] != sha256_json(source_binding)
            or manifest["source_binding"] != source_binding
            or manifest["job_store_bindings"] != job_store_bindings
            or binding["ingestion_job_fingerprints"]
            != [authority.job_fingerprint for authority in job_authorities]
            or sha256_json(manifest["safe_binding"]) != manifest["revision_binding_fingerprint"]
        ):
            raise ContractValidationError("indexed revision source seal mismatch")
        del bundle_payloads
        store = PostgreSQLGraphProjectionStore(
            projection_connection,
            revision_id=projection["revision_id"],
            workspace_id=manifest["workspace_id"],
            binding=binding,
        )
        records = IngestionRevisionSourceRecords(
            runtime_store=store,
            job_authorities=job_authorities,
            requester_user_id=manifest["requester_user_id"],
            workspace_id=manifest["workspace_id"],
            expected_seal=projection["seal_hash"],
            observation_references=observation_references,
        )
        session = reopen_authorized_semantic_observation_session(
            runtime_store=store,
            expected_seal=projection["seal_hash"],
            requester_user_id=manifest["requester_user_id"],
            runtime_components=load_issue56_target_runtime_components(),
        )
        view = reopen_authorized_effective_graph_view(session=session)
        safe_binding = manifest["safe_binding"]
        if (
            records.manifest["view_metadata"]["source_binding"] != source_binding
            or safe_binding["source_session_binding_fingerprint"]
            != session.source_session_binding_fingerprint
            or safe_binding["graph"]["graph_revision_fingerprint"]
            != records.manifest["view_metadata"]["graph"]["graph_revision_fingerprint"]
        ):
            raise ContractValidationError("indexed revision runtime seal mismatch")
        graph_payload = dict(safe_binding["graph"])
        graph_payload["relation_type_hashes"] = tuple(graph_payload["relation_type_hashes"])
        graph = SourceBackedGraphBuild(
            effective_graph_view=view,
            **{
                field.name: graph_payload[field.name]
                for field in fields(SourceBackedGraphBuild)
                if field.name in graph_payload
            },
        )
        return Issue56IngestionRevision(
            observations=(),
            bundles=(),
            session=session,
            snippet_index=None,
            graph_build=graph,
            safe_binding=MappingProxyType(safe_binding),
            source_records=records,
            exact_lookup_directory=exact_lookup_directory,
            exact_lookup_manifest=exact_lookup_manifest,
            job_authorities=job_authorities,
        )

    _, index_manifest = _read_sealed_json(
        revision_directory / "index.json",
        expected_sha256=manifest["index_manifest_sha256"],
        maximum_bytes=_MAX_INGESTION_REVISION_SOURCE_BYTES,
        reason_prefix="ingestion_index",
    )
    dense_payload = (revision_directory / "dense.bin").read_bytes()
    artifact = AuthorizedHybridObservationIndexArtifact.from_dict(
        index_manifest,
        dense_vector_payload=dense_payload,
        expected_artifact_fingerprint=manifest["index_artifact_fingerprint"],
    )

    def observations_from_snapshot() -> Iterable[Observation]:
        if observation_payloads is not None:
            while observation_payloads:
                yield Observation.from_dict(observation_payloads.pop())
            return
        if observation_references is None:
            raise ContractValidationError(
                "ingestion revision Observation references are unavailable"
            )
        for reference in observation_references:
            if (
                not isinstance(reference, list)
                or len(reference) != 3
                or not isinstance(reference[0], int)
                or isinstance(reference[0], bool)
                or not 0 <= reference[0] < len(job_authorities)
                or not isinstance(reference[1], str)
                or not isinstance(reference[2], str)
            ):
                raise ContractValidationError("ingestion revision Observation reference is invalid")
            authority = job_authorities[reference[0]]
            yield authority.load_indexed_observation(
                reference[1],
                expected_observation_hash=reference[2],
                expected_job_fingerprint=authority.job_fingerprint,
            )

    def bundles_from_snapshot() -> Iterable[MailEvidenceBundle]:
        while bundle_payloads:
            yield MailEvidenceBundle.from_dict(bundle_payloads.pop())

    revision = build_issue56_ingestion_revision(
        observations=observations_from_snapshot(),
        bundles=bundles_from_snapshot(),
        source_binding=source_binding,
        requester_user_id=manifest["requester_user_id"],
        workspace_id=manifest["workspace_id"],
        precomputed_index_artifact=artifact,
        retain_bundles=False,
        retrieval_observation_ids=retrieval_observation_ids,
        source_authority_fingerprint=manifest.get("source_authority_fingerprint"),
    )
    if (
        revision.graph_build.graph_revision_fingerprint != manifest["graph_revision_fingerprint"]
        or revision.session.source_session_binding_fingerprint
        != manifest["source_session_binding_fingerprint"]
        or sha256_json(revision.safe_binding) != manifest["revision_binding_fingerprint"]
    ):
        raise ContractValidationError("ingestion revision activation binding mismatch")
    return Issue56IngestionRevision(
        observations=revision.observations,
        bundles=revision.bundles,
        session=revision.session,
        snippet_index=revision.snippet_index,
        graph_build=revision.graph_build,
        safe_binding=revision.safe_binding,
        exact_lookup_directory=exact_lookup_directory,
        exact_lookup_manifest=exact_lookup_manifest,
        job_authorities=tuple(job_authorities),
    )


def _load_issue56_source_start_preparation(
    directory: Path,
    *,
    expected_sha256: str,
) -> Issue56IngestionRevision:
    """Validate existing preembedding source authority without opening an index."""
    _, preparation = _read_sealed_json(
        directory / "preparation.json",
        expected_sha256=expected_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="ingestion_preparation",
    )
    core = dict(preparation)
    fingerprint = core.pop("preparation_fingerprint", None)
    if (
        core.get("artifact_id") != "formowl_issue56_ingestion_revision_preparation_v1"
        or core.get("schema_version") != 1
        or fingerprint != sha256_json(core)
    ):
        raise ContractValidationError("ingestion source preparation binding is invalid")
    raw, snapshot = _read_sealed_json(
        directory / "observations.json",
        expected_sha256=core.get("snapshot_sha256"),
        maximum_bytes=_MAX_INGESTION_REVISION_SOURCE_BYTES,
        reason_prefix="ingestion_snapshot",
    )
    references = snapshot.get("observation_references")
    bindings = snapshot.get("job_store_bindings")
    source_binding = snapshot.get("source_binding")
    if (
        core.get("snapshot_size_bytes") != len(raw)
        or snapshot.get("observations") is not None
        or not isinstance(references, list)
        or not references
        or not isinstance(bindings, list)
        or not bindings
        or not isinstance(source_binding, dict)
        or core.get("requested_jobs")
        != [
            [item.get("store_directory"), item.get("ingestion_job_id")]
            for item in bindings
            if isinstance(item, dict)
        ]
    ):
        raise ContractValidationError("ingestion source snapshot binding is invalid")
    del raw
    exclusions = None
    failure_binding = core.get("bound_child_failure_binding")
    if failure_binding is not None:
        if not isinstance(failure_binding, dict):
            raise ContractValidationError("ingestion source exclusion binding is invalid")
        _, exclusions = _read_sealed_json(
            directory / "bound-child-failure-exclusions.json",
            expected_sha256=failure_binding.get("manifest_byte_sha256"),
            maximum_bytes=_MAX_SAFE_BYTES,
            reason_prefix="ingestion_child_failure_exclusions",
        )
        if (
            exclusions.get("unknown_parse_failures_must_reject") is not True
            or exclusions.get("full_source_coverage_claim") is not False
        ):
            raise ContractValidationError("ingestion source exclusion binding is invalid")
    parent_hash = core.get("sidecar_parent_binding_sha256")
    if parent_hash is not None:
        _read_sealed_json(
            directory / "sidecar-parent-binding.json",
            expected_sha256=parent_hash,
            maximum_bytes=_MAX_INGESTION_PARENT_BINDING_BYTES,
            reason_prefix="ingestion_parent_binding",
        )
    authorities = open_ingestion_revision_job_authorities(bindings, exclusions)
    jobs = source_binding.get("jobs")
    authority_hash = source_binding.get("source_authority_fingerprint")
    if (
        not isinstance(jobs, list)
        or core.get("job_count") != len(jobs)
        or authority_hash
        != sha256_json(
            {
                "artifact_id": "formowl_completed_ingestion_job_authority_v1",
                "requester_user_id": APPROVER_ACTOR,
                "workspace_id": WORKSPACE_ID,
                "jobs": jobs,
            }
        )
    ):
        raise ContractValidationError("ingestion source authority binding is invalid")
    sealed_jobs = [
        item
        for job in jobs
        for item in (job, *(job.get("supplements", ()) if isinstance(job, dict) else ()))
    ]
    if len(sealed_jobs) != len(authorities):
        raise ContractValidationError("ingestion source job scope is invalid")
    scopes, kinds = {}, set()
    for authority, job in zip(authorities, sealed_jobs):
        if (
            not isinstance(job, dict)
            or job.get("job_fingerprint") != authority.job_fingerprint
            or job.get("root_asset_hash") != authority.asset.content_hash
            or job.get("observation_count") != authority.observation_count
            or job.get("run_fingerprints") != [sha256_json(run.to_dict()) for run in authority.runs]
        ):
            raise ContractValidationError("ingestion source completed job changed")
        scope = PermissionScope(**dict(authority.permission_scope))
        if scope.scope_id in scopes and scopes[scope.scope_id] != scope:
            raise ContractValidationError("ingestion source permission scope is ambiguous")
        scopes[scope.scope_id] = scope
        kinds.update(_authorized_ingestion_root_source_kinds(authority))
    for reference in references:
        if (
            not isinstance(reference, list)
            or len(reference) != 3
            or type(reference[0]) is not int
            or not 0 <= reference[0] < len(authorities)
            or not isinstance(reference[1], str)
            or not reference[1]
            or not isinstance(reference[2], str)
            or _SHA256_RE.fullmatch(reference[2]) is None
        ):
            raise ContractValidationError("ingestion source Observation reference is invalid")
    source = validated_authorized_semantic_source(
        source_kind=(
            next(iter(kinds)) if len(kinds) == 1 else AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND
        ),
        workspace_id=WORKSPACE_ID,
        source_scope_ids=tuple(scopes),
        authorized_permission_scopes=tuple(scopes.values()),
    )
    _, exact = _read_sealed_json(
        directory / "exact-cells" / "manifest.json",
        expected_sha256=core.get("exact_lookup_manifest_sha256"),
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="ingestion_exact_lookup",
    )
    if (
        exact.get("artifact_id") != "formowl_issue56_ingestion_exact_cell_lookup_v1"
        or exact.get("source_authority_fingerprint") != authority_hash
        or source_binding.get("exact_lookup_manifest_sha256")
        != core.get("exact_lookup_manifest_sha256")
    ):
        raise ContractValidationError("ingestion source exact binding is invalid")
    binding = {
        "source_start": True,
        "retrieval_projection_status": "unavailable",
        "source_revision_sha256": expected_sha256,
        "snapshot_sha256": core["snapshot_sha256"],
        "source_authority_fingerprint": authority_hash,
        "source_session_binding_fingerprint": sha256_json(
            {
                "source_revision_sha256": expected_sha256,
                "snapshot_sha256": core["snapshot_sha256"],
                "source_authorization_fingerprint": source.authorization_fingerprint,
                "requester_user_id": APPROVER_ACTOR,
            }
        ),
        "extraction_coverage": source_binding.get("extraction_coverage", {}),
    }
    assert_no_public_raw_references(binding, "ingestion_source_start")
    source_lookup: SourceNativeLexicalLookup | None = None
    source_lookup_manifest_path = directory / "source-lookup-manifest.json"
    source_lookup_sqlite_path = directory / "source-lookup.sqlite"
    if source_lookup_manifest_path.exists() or source_lookup_sqlite_path.exists():
        profile = load_issue56_target_mail_tokenizer_profile()
        source_lookup = SourceNativeLexicalLookup(
            directory=directory,
            expected_source_revision_sha256=expected_sha256,
            expected_snapshot_sha256=core["snapshot_sha256"],
            expected_source_authority_fingerprint=authority_hash,
            expected_tokenizer_id=profile.tokenizer_id,
            expected_tokenizer_profile_fingerprint=profile.profile_fingerprint,
        )
        binding = {
            **binding,
            "source_lexical_lookup": {
                "artifact_id": source_lookup.ARTIFACT_ID,
                "manifest_fingerprint": source_lookup.manifest["manifest_fingerprint"],
                "sqlite_sha256": source_lookup.manifest["sqlite_sha256"],
                "source_families": list(source_lookup.manifest["source_families"]),
                "counts": dict(source_lookup.manifest["counts"]),
            },
        }
        assert_no_public_raw_references(binding, "ingestion_source_start")
    records = IngestionRevisionSourceRecords(
        runtime_store=source_lookup,
        job_authorities=authorities,
        requester_user_id=APPROVER_ACTOR,
        workspace_id=WORKSPACE_ID,
        observation_references=references,
        authorized_source=source,
    )
    return Issue56IngestionRevision(
        observations=(),
        bundles=(),
        session=None,
        snippet_index=None,
        graph_build=None,
        safe_binding=MappingProxyType(binding),
        source_records=records,
        job_authorities=authorities,
        authorized_source=source,
    )


def load_issue56_sealed_source(
    *,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    bundle_artifact_path: Path,
    expected_bundle_artifact_sha256: str,
    retrieval_report_path: Path,
    expected_retrieval_report_sha256: str,
    materialized_work_dir: Path,
    expected_materialization_artifact_sha256: str,
    expected_materialization_safe_report_sha256: str,
    identity_scope_attestation_path: Path,
    expected_identity_scope_attestation_sha256: str,
    identity_scope_safe_report_path: Path,
    expected_identity_scope_safe_report_sha256: str,
    source_identifier_candidate_artifact_path: Path,
    expected_source_identifier_candidate_artifact_sha256: str,
    source_identifier_candidate_safe_report_path: Path,
    expected_source_identifier_candidate_safe_report_sha256: str,
    expected_identity_scope_fingerprint: str,
    identity_scope_mode: str,
    workspace_id: str,
    approver_actor: str,
    requester_user_id: str,
    include_participant_authorization_observations: bool = False,
    supplemental_observation_artifact_path: Path | None = None,
    expected_supplemental_observation_artifact_sha256: str | None = None,
    supplemental_parent_snapshot_path: Path | None = None,
    expected_supplemental_parent_snapshot_sha256: str | None = None,
) -> Issue56SealedSourceLoad:
    """Validate one immutable source package and build existing runtime objects.

    The caller supplies every byte seal and identity binding explicitly.  The
    function accepts only the approved workspace-only diagnostic identity and
    rejects an exact ``tenant_id`` key anywhere in the decoded package.
    """

    _validate_fixed_identity_inputs(
        identity_scope_mode=identity_scope_mode,
        workspace_id=workspace_id,
        approver_actor=approver_actor,
        requester_user_id=requester_user_id,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
    )
    supplemental_inputs = (
        supplemental_observation_artifact_path,
        expected_supplemental_observation_artifact_sha256,
        supplemental_parent_snapshot_path,
        expected_supplemental_parent_snapshot_sha256,
    )
    if any(value is not None for value in supplemental_inputs) and not all(
        value is not None for value in supplemental_inputs
    ):
        raise Issue56SealedSourceLoadError("supplemental_observation_artifact_binding_incomplete")

    snapshot_bytes, snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_sha256=expected_retrieval_snapshot_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="retrieval_snapshot",
    )
    report_bytes, retrieval_report = _read_sealed_json(
        retrieval_report_path,
        expected_sha256=expected_retrieval_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="retrieval_report",
    )
    _reject_tenant_id(snapshot, "retrieval_snapshot")
    _reject_tenant_id(retrieval_report, "retrieval_report")
    try:
        source_observations, source_inventory = candidate_builder._validate_retrieval_inputs(
            snapshot,
            retrieval_report,
        )
        selected_observations, observation_selection_binding = (
            candidate_builder._select_source_observations(
                observations=source_observations,
                snapshot=snapshot,
                snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
                report=retrieval_report,
                report_byte_sha256=_sha256_bytes(report_bytes),
                materialized_work_dir=materialized_work_dir,
                expected_materialization_artifact_sha256=(expected_materialization_artifact_sha256),
                expected_materialization_safe_report_sha256=(
                    expected_materialization_safe_report_sha256
                ),
            )
        )
    except candidate_builder.SourceIdentifierCandidateError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    _reject_tenant_id(observation_selection_binding, "materialization_binding")
    for observation in selected_observations:
        _reject_tenant_id(observation.to_dict(), "materialized_observation")

    bundle_bytes, bundle_artifact = _read_sealed_json(
        bundle_artifact_path,
        expected_sha256=expected_bundle_artifact_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="bundle_artifact",
    )
    _reject_tenant_id(bundle_artifact, "bundle_artifact")
    try:
        retrieval_intake = simulated_uat._load_native_retrieval_ready_bundle_intake(
            bundle_artifact_path=bundle_artifact_path,
            expected_bundle_artifact_sha256=expected_bundle_artifact_sha256,
            report_path=retrieval_report_path,
            expected_report_sha256=expected_retrieval_report_sha256,
        )
        source_bundle = MailEvidenceBundle.from_dict(retrieval_intake.bundle_payload)
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("retrieval_ready_bundle_owner_contract_invalid") from exc
    _validate_source_bundle_identity(
        source_bundle,
        workspace_id=workspace_id,
        requester_user_id=requester_user_id,
        snapshot=snapshot,
        source_inventory_asset_id=source_inventory.source_asset_id,
    )

    attestation_bytes, private_attestation = _read_sealed_json(
        identity_scope_attestation_path,
        expected_sha256=expected_identity_scope_attestation_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="identity_scope_attestation",
    )
    attestation_safe_bytes, safe_attestation = _read_sealed_json(
        identity_scope_safe_report_path,
        expected_sha256=expected_identity_scope_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="identity_scope_safe_report",
    )
    _reject_tenant_id(private_attestation, "identity_scope_attestation")
    _reject_tenant_id(safe_attestation, "identity_scope_safe_report")
    try:
        loaded_attestation = identity_attestation.load_identity_scope_attestation(
            identity_scope_attestation_path,
            expected_sha256=expected_identity_scope_attestation_sha256,
        )
        identity_attestation.validate_safe_identity_scope_report(
            safe_attestation,
            private_artifact_bytes=attestation_bytes,
        )
    except identity_attestation.IdentityScopeAttestationError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    if loaded_attestation != private_attestation:
        raise Issue56SealedSourceLoadError("identity_scope_attestation_round_trip_mismatch")
    _validate_identity_attestation_binding(
        private_attestation,
        safe_attestation=safe_attestation,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
        workspace_id=workspace_id,
        approver_actor=approver_actor,
        snapshot=snapshot,
        source_inventory_asset_id=source_inventory.source_asset_id,
    )

    candidate_bytes, candidate_artifact = _read_sealed_json(
        source_identifier_candidate_artifact_path,
        expected_sha256=expected_source_identifier_candidate_artifact_sha256,
        maximum_bytes=_MAX_ARTIFACT_BYTES,
        reason_prefix="source_identifier_candidate_artifact",
    )
    candidate_safe_bytes, candidate_safe_report = _read_sealed_json(
        source_identifier_candidate_safe_report_path,
        expected_sha256=expected_source_identifier_candidate_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="source_identifier_candidate_safe_report",
    )
    _reject_tenant_id(candidate_artifact, "source_identifier_candidate_artifact")
    _reject_tenant_id(
        candidate_safe_report,
        "source_identifier_candidate_safe_report",
    )
    try:
        candidate_builder.validate_private_identifier_candidate_artifact(candidate_artifact)
        candidate_builder.validate_safe_identifier_candidate_report(
            candidate_safe_report,
            private_artifact_bytes=candidate_bytes,
        )
    except candidate_builder.SourceIdentifierCandidateError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    _validate_candidate_attestation_binding(
        candidate_artifact,
        candidate_safe_report=candidate_safe_report,
        private_attestation=private_attestation,
        expected_attestation_sha256=expected_identity_scope_attestation_sha256,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
        workspace_id=workspace_id,
    )

    selected_by_id = {
        observation.observation_id: observation for observation in selected_observations
    }
    selected_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in selected_by_id.items()
    }
    try:
        candidate_intake = simulated_uat._load_source_identifier_candidate_intake(
            artifact_path=source_identifier_candidate_artifact_path,
            expected_artifact_sha256=(expected_source_identifier_candidate_artifact_sha256),
            expected_identity_scope_fingerprint=(expected_identity_scope_fingerprint),
            expected_workspace_id=workspace_id,
            selected_observations_by_id=selected_by_id,
            selected_observation_hash_by_id=selected_hash_by_id,
            retrieval_ready_binding=retrieval_intake.safe_binding,
        )
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError(
            "source_identifier_candidate_owner_contract_invalid"
        ) from exc
    if candidate_intake.projected_batch.tenant_id is not None:
        raise Issue56SealedSourceLoadError("workspace_only_tenant_fabrication")

    query_bundle = _project_query_bundle(
        source_bundle,
        selected_observations=selected_observations,
    )
    supplemental_bytes: bytes | None = None
    supplemental_parent_bytes: bytes | None = None
    supplemental_observations: tuple[Observation, ...] = ()
    supplemental_binding: Mapping[str, Any] | None = None
    if supplemental_observation_artifact_path is not None:
        assert expected_supplemental_observation_artifact_sha256 is not None
        assert supplemental_parent_snapshot_path is not None
        assert expected_supplemental_parent_snapshot_sha256 is not None
        supplemental_parent_bytes, supplemental_parent = _read_sealed_json(
            supplemental_parent_snapshot_path,
            expected_sha256=expected_supplemental_parent_snapshot_sha256,
            maximum_bytes=_MAX_ARTIFACT_BYTES,
            reason_prefix="supplemental_parent_snapshot",
        )
        supplemental_bytes, supplemental_artifact = _read_sealed_json(
            supplemental_observation_artifact_path,
            expected_sha256=expected_supplemental_observation_artifact_sha256,
            maximum_bytes=_MAX_ARTIFACT_BYTES,
            reason_prefix="supplemental_observation_artifact",
        )
        _reject_tenant_id(supplemental_parent, "supplemental_parent_snapshot")
        _reject_tenant_id(supplemental_artifact, "supplemental_observation_artifact")
        supplemental_observations, supplemental_binding = (
            _validate_supplemental_observation_partition(
                supplemental_artifact,
                parent_snapshot=supplemental_parent,
                parent_snapshot_byte_sha256=_sha256_bytes(supplemental_parent_bytes),
                base_snapshot=snapshot,
            )
        )
    authorization_observations = tuple(selected_observations)
    if include_participant_authorization_observations:
        full_source_occurrence_ids = {
            occurrence.message_occurrence_id for occurrence in source_bundle.message_occurrences
        }
        participant_observations = tuple(
            observation
            for observation in source_observations
            if _observation_message_occurrence_id(observation) in full_source_occurrence_ids
            and (
                observation.observation_type == "email_message"
                or (
                    observation.observation_type == "email_header"
                    and str((observation.payload or {}).get("header_name", "")).casefold()
                    in {"from", "sender", "to", "cc"}
                )
            )
        )
        selected_asset_ids = {observation.asset_id for observation in selected_observations}
        selected_permission_fingerprints = {
            sha256_json(observation.permission_scope) for observation in selected_observations
        }
        if any(
            observation.asset_id not in selected_asset_ids
            or sha256_json(observation.permission_scope) not in selected_permission_fingerprints
            for observation in participant_observations
        ):
            raise Issue56SealedSourceLoadError("participant_authorization_scope_mismatch")
        if {
            occurrence_id
            for observation in participant_observations
            if (occurrence_id := _observation_message_occurrence_id(observation)) is not None
        } != full_source_occurrence_ids:
            raise Issue56SealedSourceLoadError(
                "participant_authorization_occurrence_scope_incomplete"
            )
        authorization_by_id = dict(selected_by_id)
        for observation in participant_observations:
            existing = authorization_by_id.get(observation.observation_id)
            if existing is not None and sha256_json(existing.to_dict()) != sha256_json(
                observation.to_dict()
            ):
                raise Issue56SealedSourceLoadError("participant_authorization_hash_mismatch")
            authorization_by_id[observation.observation_id] = observation
        authorization_observations = tuple(
            authorization_by_id[key] for key in sorted(authorization_by_id)
        )
    mail_authorization_observations = authorization_observations
    if supplemental_observations:
        authorization_by_id = {
            observation.observation_id: observation for observation in authorization_observations
        }
        for observation in supplemental_observations:
            existing = authorization_by_id.get(observation.observation_id)
            if existing is not None and existing != observation:
                raise Issue56SealedSourceLoadError("supplemental_observation_id_collision")
            authorization_by_id[observation.observation_id] = observation
        authorization_observations = tuple(
            authorization_by_id[key] for key in sorted(authorization_by_id)
        )
    retrieval_observations = tuple(
        sorted(
            (
                *selected_observations,
                *(
                    observation
                    for observation in supplemental_observations
                    if observation.observation_type in {"email_attachment_occurrence", "table_row"}
                ),
            ),
            key=lambda observation: observation.observation_id,
        )
    )
    observations_by_bundle_id = MappingProxyType(
        {query_bundle.mail_evidence_bundle_id: retrieval_observations}
    )
    mail_observations_by_bundle_id = MappingProxyType(
        {
            query_bundle.mail_evidence_bundle_id: tuple(
                sorted(
                    selected_observations,
                    key=lambda observation: observation.observation_id,
                )
            )
        }
    )
    mail_authorization_by_bundle_id = MappingProxyType(
        {query_bundle.mail_evidence_bundle_id: mail_authorization_observations}
    )
    source_binding = {
        "artifact_id": ARTIFACT_ID,
        "source_artifact_category": SOURCE_ARTIFACT_CATEGORY,
        "retrieval_ready_binding_fingerprint": retrieval_intake.safe_binding[
            "input_binding_fingerprint"
        ],
        "observation_selection_binding_fingerprint": sha256_json(observation_selection_binding),
        "candidate_binding_fingerprint": candidate_intake.safe_binding["binding_fingerprint"],
        "identity_scope_fingerprint": expected_identity_scope_fingerprint,
    }
    if supplemental_binding is not None:
        source_binding["supplemental_observation_partition_fingerprint"] = supplemental_binding[
            "partition_fingerprint"
        ]
    source_binding_fingerprint = sha256_json(source_binding)
    try:
        mail_session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=mail_observations_by_bundle_id,
            authorization_observations_by_bundle_id=mail_authorization_by_bundle_id,
            bundles=(query_bundle,),
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            expected_profile_fingerprint=str(snapshot["tokenizer_profile_fingerprint"]),
            mail_evidence_bundle_id=query_bundle.mail_evidence_bundle_id,
        )
        session = mail_session
        runtime_scope_id = query_bundle.mail_evidence_bundle_id
        if supplemental_observations:
            runtime_scope_id = "project_formowl"
            permission_scope = PermissionScope.project(runtime_scope_id)
            authorized_source = validated_authorized_semantic_source(
                source_kind=mail_session.authorized_source.source_kind,
                workspace_id=workspace_id,
                source_scope_ids=(runtime_scope_id,),
                authorized_permission_scopes=(permission_scope,),
            )
            mail_lineages = tuple(
                source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=authorized_source,
                )
                for observation in authorization_observations
                if observation.modality == "mail"
            )
            lineages = normalized_authorized_observation_lineages(
                authorization_observations,
                authorized_source=authorized_source,
                occurrence_lineages=mail_lineages,
            )
            retrieval_ids = {observation.observation_id for observation in retrieval_observations}
            snippet_index, _ = build_authorized_observation_snippet_index(
                retrieval_observations,
                authorized_source=authorized_source,
                occurrence_lineages=tuple(
                    item for item in lineages if item.source_observation_id in retrieval_ids
                ),
                authorized_observation_hash_by_id={
                    observation.observation_id: sha256_json(observation.to_dict())
                    for observation in retrieval_observations
                },
                tokenizer_profile=mail_session.index._runtime_components.tokenizer_profile,
            )
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=authorization_observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=lineages,
                requester_user_id=requester_user_id,
                expected_profile_fingerprint=str(snapshot["tokenizer_profile_fingerprint"]),
            )
        if len(session.authorized_observations) != len(
            authorization_observations
        ) or session.authorized_source_scope_ids != (runtime_scope_id,):
            raise ContractValidationError("sealed source authorization projection is incomplete")
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            observations_by_bundle_id=MappingProxyType({runtime_scope_id: retrieval_observations}),
            source_binding_fingerprint=source_binding_fingerprint,
            identifier_mention_batch=(
                None if supplemental_observations else candidate_intake.projected_batch
            ),
            source_graph_policy_id=(None if supplemental_observations else SOURCE_GRAPH_POLICY_ID),
        )
        precompute_started_ns = time.perf_counter_ns()
        lineage_crosswalk = precompute_evidence_identity_lineage_crosswalk(
            session=session,
            effective_graph_view=graph_build.effective_graph_view,
        )
        lineage_crosswalk_precompute_elapsed_ms = round(
            (time.perf_counter_ns() - precompute_started_ns) / 1_000_000.0,
            6,
        )
        relation_projection_base_precompute = None
        relation_projection_base_precompute_elapsed_ms = None
        if not supplemental_observations:
            relation_precompute_started_ns = time.perf_counter_ns()
            relation_projection_base_precompute = precompute_relation_projection_base(
                session=session,
                effective_graph_view=graph_build.effective_graph_view,
            )
            relation_projection_base_precompute_elapsed_ms = round(
                (time.perf_counter_ns() - relation_precompute_started_ns) / 1_000_000.0,
                6,
            )
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("authorized_runtime_source_binding_invalid") from exc

    safe_binding = _safe_binding(
        snapshot=snapshot,
        retrieval_report=retrieval_report,
        retrieval_ready_binding=retrieval_intake.safe_binding,
        retrieval_snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
        bundle_artifact_byte_sha256=_sha256_bytes(bundle_bytes),
        materialization_artifact_byte_sha256=(expected_materialization_artifact_sha256),
        materialization_safe_report_byte_sha256=(expected_materialization_safe_report_sha256),
        attestation_artifact_byte_sha256=_sha256_bytes(attestation_bytes),
        attestation_safe_report_byte_sha256=_sha256_bytes(attestation_safe_bytes),
        candidate_artifact_byte_sha256=_sha256_bytes(candidate_bytes),
        candidate_safe_report_byte_sha256=_sha256_bytes(candidate_safe_bytes),
        identity_scope_fingerprint=expected_identity_scope_fingerprint,
        attestation=private_attestation,
        candidate_binding=candidate_intake.safe_binding,
        observation_selection_binding=observation_selection_binding,
        source_observation_count=len(source_observations),
        selected_observation_count=len(selected_observations),
        source_bundle=source_bundle,
        query_bundle=query_bundle,
        session=session,
        graph_build=graph_build,
        source_binding_fingerprint=source_binding_fingerprint,
        lineage_crosswalk=lineage_crosswalk,
        lineage_crosswalk_precompute_elapsed_ms=(lineage_crosswalk_precompute_elapsed_ms),
        relation_projection_base_precompute=(relation_projection_base_precompute),
        relation_projection_base_precompute_elapsed_ms=(
            relation_projection_base_precompute_elapsed_ms
        ),
        supplemental_artifact_byte_sha256=(
            _sha256_bytes(supplemental_bytes) if supplemental_bytes is not None else None
        ),
        supplemental_parent_snapshot_byte_sha256=(
            _sha256_bytes(supplemental_parent_bytes)
            if supplemental_parent_bytes is not None
            else None
        ),
        supplemental_binding=supplemental_binding,
    )
    return Issue56SealedSourceLoad(
        observations=retrieval_observations,
        observations_by_bundle_id=observations_by_bundle_id,
        source_bundle=source_bundle,
        query_bundle=query_bundle,
        session=session,
        index=session.index,
        identifier_mention_batch=candidate_intake.projected_batch,
        graph_build=graph_build,
        effective_graph_view=graph_build.effective_graph_view,
        safe_binding=MappingProxyType(safe_binding),
    )


def _validate_fixed_identity_inputs(
    *,
    identity_scope_mode: str,
    workspace_id: str,
    approver_actor: str,
    requester_user_id: str,
    expected_identity_scope_fingerprint: str,
) -> None:
    if identity_scope_mode != IDENTITY_SCOPE_MODE:
        raise Issue56SealedSourceLoadError("identity_scope_mode_mismatch")
    if workspace_id != WORKSPACE_ID:
        raise Issue56SealedSourceLoadError("workspace_binding_mismatch")
    if approver_actor != APPROVER_ACTOR:
        raise Issue56SealedSourceLoadError("approver_binding_mismatch")
    if requester_user_id != approver_actor:
        raise Issue56SealedSourceLoadError("requester_approver_binding_mismatch")
    _require_sha256(
        expected_identity_scope_fingerprint,
        "identity_scope_fingerprint_invalid",
    )


def _validate_source_bundle_identity(
    bundle: MailEvidenceBundle,
    *,
    workspace_id: str,
    requester_user_id: str,
    snapshot: Mapping[str, Any],
    source_inventory_asset_id: str,
) -> None:
    session = bundle.mail_import_session
    if (
        session.workspace_id != workspace_id
        or session.owner_user_id != requester_user_id
        or session.source_asset_id != source_inventory_asset_id
        or session.archive_sha256 != snapshot.get("source_asset_sha256")
    ):
        raise Issue56SealedSourceLoadError("source_bundle_identity_binding_mismatch")


def _validate_identity_attestation_binding(
    attestation: Mapping[str, Any],
    *,
    safe_attestation: Mapping[str, Any],
    expected_identity_scope_fingerprint: str,
    workspace_id: str,
    approver_actor: str,
    snapshot: Mapping[str, Any],
    source_inventory_asset_id: str,
) -> None:
    scope = attestation.get("identity_scope")
    approval = attestation.get("approval")
    asset_binding = attestation.get("asset_binding")
    if not all(isinstance(value, Mapping) for value in (scope, approval, asset_binding)):
        raise Issue56SealedSourceLoadError("identity_scope_attestation_binding_invalid")
    assert isinstance(scope, Mapping)
    assert isinstance(approval, Mapping)
    assert isinstance(asset_binding, Mapping)
    if (
        scope.get("mode") != IDENTITY_SCOPE_MODE
        or scope.get("workspace_id") != workspace_id
        or "tenant_id" in scope
        or approval.get("approver_actor") != approver_actor
        or safe_attestation.get("identity_scope_fingerprint") != expected_identity_scope_fingerprint
        or sha256_json(dict(scope)) != expected_identity_scope_fingerprint
        or asset_binding.get("asset_id") != source_inventory_asset_id
        or asset_binding.get("asset_content_hash") != snapshot.get("source_asset_sha256")
        or attestation.get("source_fingerprint") != snapshot.get("source_snapshot_fingerprint")
        or attestation.get("permission_fingerprint") != snapshot.get("permission_fingerprint")
    ):
        raise Issue56SealedSourceLoadError("identity_scope_attestation_binding_mismatch")


def _validate_candidate_attestation_binding(
    artifact: Mapping[str, Any],
    *,
    candidate_safe_report: Mapping[str, Any],
    private_attestation: Mapping[str, Any],
    expected_attestation_sha256: str,
    expected_identity_scope_fingerprint: str,
    workspace_id: str,
) -> None:
    identity_binding = artifact.get("identity_scope_binding")
    if not isinstance(identity_binding, Mapping):
        raise Issue56SealedSourceLoadError("candidate_identity_scope_binding_invalid")
    if (
        artifact.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or identity_binding.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or identity_binding.get("workspace_id") != workspace_id
        or identity_binding.get("identity_scope_fingerprint") != expected_identity_scope_fingerprint
        or identity_binding.get("identity_scope_attestation_fingerprint")
        != private_attestation.get("attestation_fingerprint")
        or artifact.get("identity_scope_attestation_byte_sha256") != expected_attestation_sha256
        or artifact.get("identity_scope_attestation_fingerprint")
        != private_attestation.get("attestation_fingerprint")
        or candidate_safe_report.get("identity_scope_fingerprint")
        != expected_identity_scope_fingerprint
        or artifact.get("candidate_only") is not True
        or artifact.get("canonical_write_allowed") is not False
        or artifact.get("overflow_count") != 0
    ):
        raise Issue56SealedSourceLoadError("candidate_identity_scope_binding_mismatch")


def _validate_supplemental_observation_partition(
    artifact: Mapping[str, Any],
    *,
    parent_snapshot: Mapping[str, Any],
    parent_snapshot_byte_sha256: str,
    base_snapshot: Mapping[str, Any],
) -> tuple[tuple[Observation, ...], Mapping[str, Any]]:
    source = parent_snapshot.get("source")
    binding = {
        "artifact_type": parent_snapshot.get("artifact_type"),
        "schema_version": parent_snapshot.get("schema_version"),
        "artifact_byte_sha256": parent_snapshot_byte_sha256,
        "artifact_commitment": parent_snapshot.get("artifact_commitment"),
        "record_stream_fingerprint": parent_snapshot.get("record_stream_fingerprint"),
        "record_count": parent_snapshot.get("record_count"),
        "source_asset_id": source.get("source_asset_id") if isinstance(source, Mapping) else None,
        "source_fingerprint": source.get("source_fingerprint")
        if isinstance(source, Mapping)
        else None,
        "permission_scope_fingerprint": source.get("permission_scope_fingerprint")
        if isinstance(source, Mapping)
        else None,
        "selection_checkpoint_fingerprint": source.get("selection_checkpoint_fingerprint")
        if isinstance(source, Mapping)
        else None,
    }
    if (
        binding["artifact_type"] != "formowl_diagnostic_current_export_table_snapshot_v2"
        or binding["schema_version"] != 2
        or not isinstance(source, Mapping)
        or not isinstance(parent_snapshot.get("records"), list)
        or binding["record_count"] != len(parent_snapshot["records"])
        or (parent_snapshot.get("capture") or {}).get("candidate_only") is not True
        or (parent_snapshot.get("capture") or {}).get("canonical_kg") is not False
        or source.get("workspace_id") != WORKSPACE_ID
        or source.get("owner_user_id") != APPROVER_ACTOR
        or binding["permission_scope_fingerprint"] != base_snapshot.get("permission_fingerprint")
        or not isinstance(binding["source_asset_id"], str)
        or not binding["source_asset_id"]
    ):
        raise Issue56SealedSourceLoadError("supplemental_parent_snapshot_contract_invalid")
    for key in (
        "artifact_byte_sha256",
        "artifact_commitment",
        "record_stream_fingerprint",
        "source_fingerprint",
        "permission_scope_fingerprint",
        "selection_checkpoint_fingerprint",
    ):
        _require_sha256(binding[key], "supplemental_parent_snapshot_contract_invalid")
    raw = artifact.get("observations")
    counts = artifact.get("counts")
    expected_base = {
        key: base_snapshot.get(key)
        for key in (
            "source_snapshot_fingerprint",
            "source_asset_sha256",
            "source_inventory_fingerprint",
            "permission_fingerprint",
        )
    }
    if (
        set(artifact)
        != {
            "artifact_id",
            "schema_version",
            "identity_scope_mode",
            "workspace_id",
            "approver_actor",
            "base_source_binding",
            "v25_parent_snapshot_binding",
            "counts",
            "observations",
        }
        or artifact.get("artifact_id") != SUPPLEMENTAL_OBSERVATION_ARTIFACT_ID
        or artifact.get("schema_version") != 1
        or artifact.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or artifact.get("workspace_id") != WORKSPACE_ID
        or artifact.get("approver_actor") != APPROVER_ACTOR
        or artifact.get("base_source_binding") != expected_base
        or artifact.get("v25_parent_snapshot_binding") != binding
        or not isinstance(counts, Mapping)
        or not isinstance(raw, list)
        or not raw
    ):
        raise Issue56SealedSourceLoadError("supplemental_observation_artifact_contract_invalid")
    try:
        observations = tuple(
            Observation.from_dict(dict(item)) for item in raw if isinstance(item, Mapping)
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError("supplemental_observation_contract_invalid") from exc
    if len(observations) != len(raw) or len({item.observation_id for item in observations}) != len(
        observations
    ):
        raise Issue56SealedSourceLoadError("supplemental_observation_contract_invalid")
    permission = PermissionScope.project("project_formowl").to_dict()
    parents = {
        str((item.payload or {}).get("child_asset_id")): item
        for item in observations
        if item.observation_type == "email_attachment_occurrence"
    }
    if len(parents) != sum(
        item.observation_type == "email_attachment_occurrence" for item in observations
    ) or any(
        item.permission_scope != permission
        or item.modality != "mail"
        or item.asset_id != binding["source_asset_id"]
        or _observation_message_occurrence_id(item)
        != (item.payload or {}).get("message_occurrence_id")
        or _SHA256_RE.fullmatch(str((item.payload or {}).get("raw_message_fingerprint"))) is None
        or _SHA256_RE.fullmatch(str((item.payload or {}).get("attachment_content_fingerprint")))
        is None
        for item in parents.values()
    ):
        raise Issue56SealedSourceLoadError("supplemental_attachment_parent_lineage_invalid")
    children = tuple(
        item for item in observations if item.observation_type != "email_attachment_occurrence"
    )
    referenced_structural_ids = {
        str((item.payload or {}).get("lineage", {}).get("source_structural_observation_id"))
        for item in children
    }
    parent_records = {}
    try:
        for record in parent_snapshot["records"]:
            structural = record["structural_observation"]
            structural_id = structural["structural_observation_id"]
            if structural_id not in referenced_structural_ids:
                continue
            rows_by_ordinal = {}
            for source_row in structural["rows"]:
                cells = source_row["cells"]
                cells_by_ordinal = {
                    source_cell["column_ordinal"]: source_cell for source_cell in cells
                }
                row_ordinal = source_row["row_ordinal"]
                if (
                    len(cells_by_ordinal) != len(cells)
                    or any(
                        not isinstance(index, int) or isinstance(index, bool)
                        for index in cells_by_ordinal
                    )
                    or not isinstance(row_ordinal, int)
                    or isinstance(row_ordinal, bool)
                    or row_ordinal in rows_by_ordinal
                ):
                    raise ValueError
                rows_by_ordinal[row_ordinal] = (
                    "\t".join(
                        cells_by_ordinal[index].get("value", "")
                        for index in sorted(cells_by_ordinal)
                    ),
                    cells_by_ordinal,
                )
            if structural_id in parent_records:
                raise ValueError
            parent_records[structural_id] = (
                record,
                sha256_json(record),
                rows_by_ordinal,
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError("supplemental_parent_record_binding_invalid") from exc
    if set(parent_records) != referenced_structural_ids:
        raise Issue56SealedSourceLoadError("supplemental_parent_record_binding_invalid")
    statuses: list[str] = []
    structural_ids: set[str] = set()
    for item in children:
        payload = item.payload or {}
        lineage = payload.get("lineage")
        structure = payload.get("table_structure")
        parent = parents.get(item.asset_id or "")
        status = structure.get("structure_status") if isinstance(structure, Mapping) else None
        structural_id = (
            lineage.get("source_structural_observation_id")
            if isinstance(lineage, Mapping)
            else None
        )
        parent_record = parent_records.get(str(structural_id))
        source_row = (
            parent_record[2].get(lineage.get("source_row_ordinal"))
            if parent_record is not None and isinstance(lineage, Mapping)
            else None
        )
        source_cell = None
        expected_value = source_row[0] if source_row is not None else None
        if item.observation_type == "table_cell" and source_row is not None:
            source_cell = source_row[1].get(lineage.get("source_column_ordinal"))
            expected_value = source_cell.get("value", "") if source_cell is not None else None
        if (
            item.permission_scope != permission
            or item.modality != "document"
            or item.observation_type not in {"table_row", "table_cell"}
            or parent is None
            or not isinstance(lineage, Mapping)
            or lineage.get("parent_attachment_observation_id") != parent.observation_id
            or lineage.get("source_structural_observation_id") in {None, ""}
            or status not in {"source_provided", "candidate_only"}
            or payload.get("canonical_fact_status") != "not_asserted"
            or parent_record is None
            or lineage.get("snapshot_record_fingerprint") != parent_record[1]
            or (status == "source_provided" and parent_record[0].get("record_type") != "xlsx_sheet")
            or parent_record[0]["structural_observation"].get("source_asset_id") != parent.asset_id
            or parent_record[0].get("raw_message_fingerprint")
            != (parent.payload or {}).get("raw_message_fingerprint")
            or parent_record[0].get("attachment_content_fingerprint")
            != (parent.payload or {}).get("attachment_content_fingerprint")
            or source_row is None
            or payload.get("value") != expected_value
            or item.text != expected_value
            or (
                item.observation_type == "table_cell"
                and (
                    source_cell is None
                    or payload.get("cell_state") != source_cell.get("cell_state")
                )
            )
        ):
            raise Issue56SealedSourceLoadError("supplemental_attachment_child_lineage_invalid")
        structural_ids.add(str(lineage["source_structural_observation_id"]))
        statuses.append(str(status))
    rows = sum(item.observation_type == "table_row" for item in children)
    computed = {
        "reviewed_xlsx_binding_count": len(structural_ids),
        "parent_message_occurrence_count": len(
            {_observation_message_occurrence_id(item) for item in parents.values()}
        ),
        "attachment_parent_count": len(parents),
        "table_row_count": rows,
        "table_cell_count": len(children) - rows,
        "source_provided_table_observation_count": statuses.count("source_provided"),
        "candidate_only_table_observation_count": statuses.count("candidate_only"),
        "authorized_supplemental_observation_count": len(observations),
        "retrieval_supplemental_observation_count": len(parents) + rows,
    }
    if not parents or not rows or not computed["table_cell_count"] or dict(counts) != computed:
        raise Issue56SealedSourceLoadError("supplemental_observation_count_mismatch")
    return observations, MappingProxyType(
        {
            "status": "loaded",
            "partition_fingerprint": sha256_json(artifact),
            "parent_snapshot_artifact_commitment": binding["artifact_commitment"],
            "parent_snapshot_record_stream_fingerprint": binding["record_stream_fingerprint"],
            "counts": computed,
        }
    )


def _project_query_bundle(
    source_bundle: MailEvidenceBundle,
    *,
    selected_observations: Sequence[Observation],
) -> MailEvidenceBundle:
    selected_ids = {observation.observation_id for observation in selected_observations}
    if len(selected_ids) != len(selected_observations):
        raise Issue56SealedSourceLoadError("selected_observation_id_duplicate")
    if any(
        observation.modality != "mail"
        or observation.observation_type != "email_body_segment"
        or not isinstance(observation.text, str)
        or not observation.text
        for observation in selected_observations
    ):
        raise Issue56SealedSourceLoadError("materialized_query_observation_type_unsupported")

    body_by_observation_id = {
        segment.source_observation_id: segment for segment in source_bundle.body_segments
    }
    selected_segments = [
        body_by_observation_id[observation_id]
        for observation_id in sorted(selected_ids)
        if observation_id in body_by_observation_id
    ]
    if len(selected_segments) != len(selected_ids):
        raise Issue56SealedSourceLoadError("bundle_body_observation_lineage_incomplete")
    observation_by_id = {
        observation.observation_id: observation for observation in selected_observations
    }
    if any(
        segment.text != observation_by_id[segment.source_observation_id].text
        or segment.message_occurrence_id
        != _observation_message_occurrence_id(observation_by_id[segment.source_observation_id])
        for segment in selected_segments
    ):
        raise Issue56SealedSourceLoadError("bundle_body_observation_lineage_mismatch")

    selected_message_ids = {segment.email_message_id for segment in selected_segments}
    selected_messages = [
        message
        for message in source_bundle.messages
        if message.email_message_id in selected_message_ids
    ]
    if {message.email_message_id for message in selected_messages} != selected_message_ids:
        raise Issue56SealedSourceLoadError("bundle_message_lineage_incomplete")
    selected_occurrence_ids = {segment.message_occurrence_id for segment in selected_segments}
    selected_message_occurrences = [
        occurrence
        for occurrence in source_bundle.message_occurrences
        if occurrence.message_occurrence_id in selected_occurrence_ids
    ]
    if {
        occurrence.message_occurrence_id for occurrence in selected_message_occurrences
    } != selected_occurrence_ids:
        raise Issue56SealedSourceLoadError("bundle_message_occurrence_lineage_incomplete")

    query_bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=source_bundle.mail_evidence_bundle_id,
        producer_type=source_bundle.producer_type,
        mail_import_session=source_bundle.mail_import_session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=sorted(
            selected_messages,
            key=lambda message: message.email_message_id,
        ),
        message_occurrences=sorted(
            selected_message_occurrences,
            key=lambda occurrence: occurrence.email_message_occurrence_id,
        ),
        body_segments=sorted(
            selected_segments,
            key=lambda segment: segment.email_body_segment_id,
        ),
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=source_bundle.mail_parse_run,
        parse_warnings=[],
        created_at=source_bundle.created_at,
    )
    MailEvidenceBundle.from_dict(query_bundle.to_dict())
    return query_bundle


def _safe_binding(
    *,
    snapshot: Mapping[str, Any],
    retrieval_report: Mapping[str, Any],
    retrieval_ready_binding: Mapping[str, Any],
    retrieval_snapshot_byte_sha256: str,
    bundle_artifact_byte_sha256: str,
    materialization_artifact_byte_sha256: str,
    materialization_safe_report_byte_sha256: str,
    attestation_artifact_byte_sha256: str,
    attestation_safe_report_byte_sha256: str,
    candidate_artifact_byte_sha256: str,
    candidate_safe_report_byte_sha256: str,
    identity_scope_fingerprint: str,
    attestation: Mapping[str, Any],
    candidate_binding: Mapping[str, Any],
    observation_selection_binding: Mapping[str, Any],
    source_observation_count: int,
    selected_observation_count: int,
    source_bundle: MailEvidenceBundle,
    query_bundle: MailEvidenceBundle,
    session: AuthorizedSemanticMailSession,
    graph_build: SourceBackedGraphBuild,
    source_binding_fingerprint: str,
    lineage_crosswalk: EvidenceIdentityLineageCrosswalk,
    lineage_crosswalk_precompute_elapsed_ms: float,
    relation_projection_base_precompute: RelationProjectionBasePrecompute | None,
    relation_projection_base_precompute_elapsed_ms: float | None,
    supplemental_artifact_byte_sha256: str | None,
    supplemental_parent_snapshot_byte_sha256: str | None,
    supplemental_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    counts = {
        "source_observation_count": source_observation_count,
        "selected_observation_count": selected_observation_count,
        "authorized_observation_count": len(session.authorized_observations),
        "full_bundle_message_count": len(source_bundle.messages),
        "full_bundle_message_occurrence_count": len(source_bundle.message_occurrences),
        "full_bundle_body_segment_count": len(source_bundle.body_segments),
        "full_bundle_attachment_count": len(source_bundle.attachments),
        "full_bundle_attachment_occurrence_count": len(source_bundle.attachment_occurrences),
        "query_bundle_message_count": len(query_bundle.messages),
        "query_bundle_message_occurrence_count": len(query_bundle.message_occurrences),
        "query_bundle_body_segment_count": len(query_bundle.body_segments),
        "identifier_occurrence_count": int(candidate_binding["selected_mention_count"]),
        "resolved_candidate_count": int(candidate_binding["selected_resolved_candidate_count"]),
        "overflow_count": int(candidate_binding["overflow_count"]),
        "graph_source_observation_count": graph_build.source_observation_count,
        "graph_observation_node_count": graph_build.observation_node_count,
        "graph_entity_node_count": graph_build.entity_node_count,
        "graph_edge_count": graph_build.edge_count,
    }
    binding: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "diagnostic_source_load_only_no_quality_claim",
        "methodology_readiness_status": "blocked",
        "source_artifact_category": SOURCE_ARTIFACT_CATEGORY,
        "identity_scope_mode_status": IDENTITY_SCOPE_MODE,
        "tenant_dimension_status": "not_modeled_not_fabricated",
        "candidate_only": True,
        "canonical_write_allowed": False,
        "source_graph_policy_id": graph_build.graph_policy_id,
        "retrieval_snapshot_byte_sha256": retrieval_snapshot_byte_sha256,
        "bundle_artifact_byte_sha256": bundle_artifact_byte_sha256,
        "retrieval_report_byte_sha256": retrieval_ready_binding["retrieval_report_byte_hash"],
        "materialization_artifact_byte_sha256": (materialization_artifact_byte_sha256),
        "materialization_safe_report_byte_sha256": (materialization_safe_report_byte_sha256),
        "identity_scope_attestation_byte_sha256": (attestation_artifact_byte_sha256),
        "identity_scope_safe_report_byte_sha256": (attestation_safe_report_byte_sha256),
        "source_identifier_candidate_artifact_byte_sha256": (candidate_artifact_byte_sha256),
        "source_identifier_candidate_safe_report_byte_sha256": (candidate_safe_report_byte_sha256),
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_asset_fingerprint": snapshot["source_asset_sha256"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": retrieval_report["report_fingerprint"],
        "mail_evidence_bundle_fingerprint": retrieval_ready_binding[
            "mail_evidence_bundle_fingerprint"
        ],
        "candidate_admission_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "identity_scope_fingerprint": identity_scope_fingerprint,
        "identity_scope_attestation_fingerprint": attestation["attestation_fingerprint"],
        "identity_scope_policy_fingerprint": attestation["policy_fingerprint"],
        "operator_approval_fingerprint": candidate_binding["operator_approval_fingerprint"],
        "spec_approval_fingerprint": candidate_binding["spec_approval_fingerprint"],
        "observation_selection_binding_fingerprint": sha256_json(observation_selection_binding),
        "source_identifier_mention_batch_fingerprint": (
            candidate_binding["selected_mention_batch_fingerprint"]
        ),
        "source_identifier_resolution_fingerprint": (
            candidate_binding["selected_resolution_fingerprint"]
        ),
        "source_binding_fingerprint": source_binding_fingerprint,
        "index_fingerprint": session.index.index_fingerprint,
        "graph_revision_fingerprint": graph_build.graph_revision_fingerprint,
        "graph_build_fingerprint": graph_build.build_fingerprint,
        "lineage_crosswalk_precompute": _lineage_crosswalk_precompute_safe_binding(
            lineage_crosswalk=lineage_crosswalk,
            elapsed_ms=lineage_crosswalk_precompute_elapsed_ms,
        ),
        "relation_projection_base_precompute": (
            _relation_projection_base_precompute_safe_binding(
                precompute=relation_projection_base_precompute,
                elapsed_ms=relation_projection_base_precompute_elapsed_ms,
            )
            if relation_projection_base_precompute is not None
            else {
                "status": "skipped",
                "reason": "supplemental_observation_partition_not_applicable",
                "helper_invocation_count": 0,
            }
        ),
        "counts": counts,
    }
    if supplemental_binding is not None:
        if (
            supplemental_artifact_byte_sha256 is None
            or supplemental_parent_snapshot_byte_sha256 is None
        ):
            raise Issue56SealedSourceLoadError("supplemental_observation_safe_binding_invalid")
        binding.update(
            supplemental_observation_artifact_byte_sha256=(supplemental_artifact_byte_sha256),
            supplemental_parent_snapshot_byte_sha256=(supplemental_parent_snapshot_byte_sha256),
            supplemental_parent_snapshot_artifact_commitment=(
                supplemental_binding["parent_snapshot_artifact_commitment"]
            ),
            supplemental_parent_snapshot_record_stream_fingerprint=(
                supplemental_binding["parent_snapshot_record_stream_fingerprint"]
            ),
            supplemental_observation_partition_fingerprint=(
                supplemental_binding["partition_fingerprint"]
            ),
            supplemental_observation_partition_status=supplemental_binding["status"],
        )
        counts.update(supplemental_binding["counts"])
    for field_name, value in binding.items():
        if field_name.endswith("_fingerprint") or field_name.endswith("_sha256"):
            _require_sha256(value, f"{field_name}_invalid")
    if (
        counts["authorized_observation_count"] < counts["selected_observation_count"]
        or counts["selected_observation_count"] != counts["query_bundle_body_segment_count"]
        or counts["overflow_count"] != 0
    ):
        raise Issue56SealedSourceLoadError("safe_binding_count_mismatch")
    precompute_binding = binding["lineage_crosswalk_precompute"]
    if (
        precompute_binding["index_fingerprint"] != binding["index_fingerprint"]
        or precompute_binding["graph_revision_fingerprint"] != binding["graph_revision_fingerprint"]
        or precompute_binding["source_session_binding_fingerprint"]
        != session.source_session_binding_fingerprint
        or precompute_binding["counts"]["authorized_evidence_count"]
        != counts["authorized_observation_count"]
    ):
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_binding_mismatch")
    relation_precompute_binding = binding["relation_projection_base_precompute"]
    if relation_projection_base_precompute is not None and (
        relation_precompute_binding["index_fingerprint"] != binding["index_fingerprint"]
        or relation_precompute_binding["graph_revision_fingerprint"]
        != binding["graph_revision_fingerprint"]
        or relation_precompute_binding["candidate_admission_profile_fingerprint"]
        != binding["candidate_admission_profile_fingerprint"]
        or relation_precompute_binding["counts"]["authorized_observation_count"]
        != counts["authorized_observation_count"]
        or relation_precompute_binding["counts"]["candidate_count"] != len(session.index.candidates)
        or relation_precompute_binding["counts"]["projected_node_count"]
        != graph_build.observation_node_count + graph_build.entity_node_count
    ):
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_binding_mismatch")
    binding["binding_fingerprint"] = sha256_json(binding)
    try:
        assert_no_public_raw_references(binding, "issue56_sealed_source_load")
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("safe_binding_private_reference_exposed") from exc
    _reject_tenant_id(binding, "safe_binding")
    return binding


def _lineage_crosswalk_precompute_safe_binding(
    *,
    lineage_crosswalk: EvidenceIdentityLineageCrosswalk,
    elapsed_ms: float,
) -> dict[str, Any]:
    if not isinstance(elapsed_ms, float) or elapsed_ms < 0:
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_elapsed_invalid")
    counts = {
        "authorized_evidence_count": lineage_crosswalk.authorized_evidence_count,
        "indexed_evidence_count": lineage_crosswalk.indexed_evidence_count,
        "occurrence_bound_evidence_count": (lineage_crosswalk.occurrence_bound_evidence_count),
        "graph_node_bound_evidence_count": (lineage_crosswalk.graph_node_bound_evidence_count),
        "graph_edge_bound_evidence_count": (lineage_crosswalk.graph_edge_bound_evidence_count),
    }
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_count_invalid")
    cache_key_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_issue56_evidence_identity_lineage_cache_key_v1",
            "index_fingerprint": lineage_crosswalk.index_fingerprint,
            "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
            "source_session_binding_fingerprint": (
                lineage_crosswalk.source_session_binding_fingerprint
            ),
        }
    )
    binding = {
        "artifact_id": "formowl_issue56_lineage_crosswalk_precompute_safe_v1",
        "schema_version": 1,
        "status": "passed",
        "cache_status": "primed",
        "helper_invocation_count": 1,
        "elapsed_ms": elapsed_ms,
        "crosswalk_fingerprint": lineage_crosswalk.crosswalk_fingerprint,
        "index_fingerprint": lineage_crosswalk.index_fingerprint,
        "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
        "source_session_binding_fingerprint": (
            lineage_crosswalk.source_session_binding_fingerprint
        ),
        "cache_key_fingerprint": cache_key_fingerprint,
        "counts": counts,
    }
    for field_name in (
        "crosswalk_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "source_session_binding_fingerprint",
        "cache_key_fingerprint",
    ):
        _require_sha256(
            binding[field_name],
            f"lineage_crosswalk_precompute_{field_name}_invalid",
        )
    return binding


def _relation_projection_base_precompute_safe_binding(
    *,
    precompute: RelationProjectionBasePrecompute,
    elapsed_ms: float,
) -> dict[str, Any]:
    if not isinstance(elapsed_ms, float) or elapsed_ms < 0:
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_elapsed_invalid")
    binding = precompute.to_safe_dict()
    binding["helper_invocation_count"] = 1
    binding["elapsed_ms"] = elapsed_ms
    for field_name in (
        "cache_binding_fingerprint",
        "graph_revision_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "precompute_fingerprint",
    ):
        _require_sha256(
            binding[field_name],
            f"relation_projection_base_precompute_{field_name}_invalid",
        )
    counts = binding["counts"]
    if not isinstance(counts, dict) or any(
        type(value) is not int or value < 0 for value in counts.values()
    ):
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_count_invalid")
    return binding


def _observation_message_occurrence_id(observation: Observation) -> str | None:
    for source in (observation.location, observation.payload or {}):
        value = source.get("message_occurrence_id")
        if isinstance(value, str) and value:
            return value
    return None


def _read_sealed_json(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    _require_sha256(expected_sha256, f"{reason_prefix}_expected_sha256_invalid")
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise OSError("not a regular file")
        if file_stat.st_size > maximum_bytes:
            raise OSError("file exceeds maximum size")
        raw = path.read_bytes()
    except OSError as exc:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_unavailable") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_byte_seal_mismatch")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_json_invalid") from exc
    if type(payload) is not dict:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_json_invalid")
    return raw, payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _reject_tenant_id(value: Any, reason_prefix: str) -> None:
    if isinstance(value, Mapping):
        if "tenant_id" in value:
            raise Issue56SealedSourceLoadError(f"{reason_prefix}_tenant_id_forbidden")
        for item in value.values():
            _reject_tenant_id(item, reason_prefix)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_tenant_id(item, reason_prefix)


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Issue56SealedSourceLoadError(reason_code)
    return value


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
