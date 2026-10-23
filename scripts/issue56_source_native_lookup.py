#!/usr/bin/env python3
"""Build/reuse an immutable OFFLINE lexical accelerator for a sealed source start.

Output is a separate directory containing the existing reader's SQLite/manifest
pair. Publication is one atomic no-replace directory rename, not a source or
runtime rewrite. An operator owns any later deployment of the validated pair.
"""
from __future__ import annotations

import argparse
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "python"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import ContractValidationError, sha256_json  # noqa: E402
from formowl_core import load_issue56_target_mail_tokenizer_profile  # noqa: E402
from formowl_mail.hybrid import _is_attachment_text_observation  # noqa: E402
from formowl_mail.query import _attachment_child_lineages  # noqa: E402
from formowl_mail.issue56_sealed_source import (  # noqa: E402
    Issue56SealedSourceLoadError,
    SourceNativeLexicalLookup,
    _authorized_ingestion_root_source_kinds,
    load_issue56_ingestion_revision,
)
from formowl_mail.semantic_plan import (  # noqa: E402
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND, AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
)
from scripts.issue56_source_identifier_candidates import (  # noqa: E402
    SourceIdentifierCandidateError,
    _fsync_directory,
    _rename_directory_no_replace,
    _write_file_exclusive,
)

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE helpers (
 observation_hash TEXT PRIMARY KEY, observation_id TEXT NOT NULL,
 job_index INTEGER NOT NULL, job_fingerprint TEXT NOT NULL,
 source_scope_id TEXT NOT NULL, permission_scope_json TEXT NOT NULL,
 source_family TEXT NOT NULL
);
CREATE TABLE postings (
 token TEXT NOT NULL, source_family TEXT NOT NULL, observation_hash TEXT NOT NULL,
 PRIMARY KEY (token, source_family, observation_hash)
);
CREATE INDEX postings_family_token ON postings(source_family, token);
CREATE INDEX postings_hash ON postings(observation_hash);
CREATE UNIQUE INDEX helpers_observation_id ON helpers(observation_id);
CREATE TABLE attachment_parents (
 child_asset_id TEXT PRIMARY KEY, observation_hash TEXT NOT NULL UNIQUE
);
"""
LOCATOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_locators (
 observation_hash TEXT PRIMARY KEY, observation_id TEXT NOT NULL UNIQUE,
 job_index INTEGER NOT NULL, job_fingerprint TEXT NOT NULL,
 position INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS occurrence_helpers (
 observation_hash TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL,
 job_index INTEGER NOT NULL, asset_id TEXT NOT NULL, extractor_run_id TEXT NOT NULL,
 observation_type TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS occurrence_helpers_binding ON occurrence_helpers(
 occurrence_id, job_index, asset_id, extractor_run_id, observation_type
);
"""
TOKEN_SURFACE_POLICY_ID = "source_matcher_mail_fields_text_caption_attachment_text_v2"
ATTACHMENT_PARENT_POLICY_ID = "sealed_attachment_parent_helpers_v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _lookup_expected(revision, profile) -> dict:
    if revision.safe_binding.get("source_start") is not True or revision.source_records is None:
        raise ContractValidationError("source lexical builder requires a source-start preparation")
    if revision.exact_lookup_manifest.get("tokenizer_profile_fingerprint") != profile.profile_fingerprint:
        raise ContractValidationError("source lexical preparation tokenizer profile mismatch")
    return {
        "expected_source_revision_sha256": revision.safe_binding["source_revision_sha256"],
        "expected_snapshot_sha256": revision.safe_binding["snapshot_sha256"],
        "expected_source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
        "expected_tokenizer_id": profile.tokenizer_id,
        "expected_tokenizer_profile_fingerprint": profile.profile_fingerprint,
    }


def _sealed_lookup_state(directory: Path) -> tuple:
    paths = [directory / name for name in ("source-lookup.sqlite", "source-lookup-manifest.json")]
    if directory.is_symlink() or any(path.is_symlink() or not path.is_file() for path in paths):
        raise ContractValidationError("source seed requires immutable regular lookup files")
    if any((directory / ("source-lookup.sqlite" + suffix)).exists()
           for suffix in ("-wal", "-shm", "-journal")):
        raise ContractValidationError("source seed lookup has active SQLite sidecars")
    return tuple((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                 for s in (path.stat() for path in paths))


def _seed_prefix(base, old_records, records, job_prefix_count: int) -> int:
    """Prove a complete unchanged job/reference prefix without reading source text."""
    old_jobs, jobs = old_records.job_authorities, records.job_authorities
    if type(job_prefix_count) is not int or not 0 < job_prefix_count <= min(len(old_jobs), len(jobs)):
        raise ContractValidationError("source seed job prefix count is invalid")
    for old, new in zip(old_jobs[:job_prefix_count], jobs[:job_prefix_count]):
        if (old != new or old.observation_ids != new.observation_ids
                or old.required_failed_child_bindings != new.required_failed_child_bindings
                or dict(old.permission_scope) != dict(new.permission_scope)):
            raise ContractValidationError("source seed immutable job prefix mismatch")
    old_refs, refs = old_records.observation_references, records.observation_references

    def prefix_length(references):
        end = next((i for i, ref in enumerate(references) if ref[0] >= job_prefix_count), len(references))
        if not end or any(ref[0] < job_prefix_count for ref in islice(references, end, None)):
            raise ContractValidationError("source seed references are not a strict job prefix")
        return end

    retained = prefix_length(old_refs)
    if retained != prefix_length(refs) or any(a != b for a, b in zip(islice(old_refs, retained), islice(refs, retained))):
        raise ContractValidationError("source seed immutable reference prefix mismatch")
    manifest = base.manifest
    if (manifest.get("token_surface_policy_id") != TOKEN_SURFACE_POLICY_ID
            or manifest.get("attachment_parent_policy_id") != ATTACHMENT_PARENT_POLICY_ID
            or not base.has_keyed_source_metadata):
        raise ContractValidationError("source seed lookup policies are incompatible")
    db = base._connection
    counts = manifest.get("counts")
    actual = _lookup_counts(db, len(old_refs))
    if counts != actual or manifest.get("attachment_parent_count") != db.execute(
        "SELECT COUNT(*) FROM attachment_parents"
    ).fetchone()[0]:
        raise ContractValidationError("source seed lookup counts mismatch")
    rows = db.execute("SELECT job_index, observation_id, observation_hash, job_fingerprint, position "
                      "FROM reference_locators ORDER BY position")
    for position, ref in enumerate(old_refs):
        row = next(rows, None)
        if row != (*ref, old_jobs[ref[0]].job_fingerprint, position):
            raise ContractValidationError("source seed locator binding mismatch")
    if next(rows, None) is not None:
        raise ContractValidationError("source seed locator binding mismatch")
    permissions = [(job.job_fingerprint, job.permission_scope["scope_id"],
                    json.dumps(dict(job.permission_scope), sort_keys=True)) for job in old_jobs]
    for row in db.execute(
        "SELECT h.job_index, h.job_fingerprint, h.source_scope_id, h.permission_scope_json, "
        "h.observation_id, h.source_family, r.job_index, r.job_fingerprint, r.observation_id "
        "FROM helpers h LEFT JOIN reference_locators r USING(observation_hash)"
    ):
        index, fingerprint, scope, permission, observation_id, family, ref_job, ref_fingerprint, ref_id = row
        if (type(index) is not int or not 0 <= index < len(old_jobs)
                or (fingerprint, scope, permission) != permissions[index]
                or (index, fingerprint, observation_id) != (ref_job, ref_fingerprint, ref_id)
                or family not in {"mail", "document_text"}):
            raise ContractValidationError("source seed helper binding mismatch")
    for query in (
        "SELECT 1 FROM postings p LEFT JOIN helpers h USING(observation_hash) "
        "WHERE h.observation_hash IS NULL OR p.source_family != h.source_family LIMIT 1",
        "SELECT 1 FROM occurrence_helpers o LEFT JOIN helpers h USING(observation_hash) "
        "WHERE h.observation_hash IS NULL OR o.job_index != h.job_index LIMIT 1",
        "SELECT 1 FROM attachment_parents p LEFT JOIN helpers h USING(observation_hash) "
        "WHERE h.observation_hash IS NULL OR h.source_family != 'mail' LIMIT 1",
    ):
        if db.execute(query).fetchone() is not None:
            raise ContractValidationError("source seed helper relations are invalid")
    return retained


def _lookup_counts(db, references: int) -> dict:
    families = dict(db.execute("SELECT source_family, COUNT(*) FROM helpers GROUP BY source_family"))
    return {"references": references, "helpers": sum(families.values()),
            "postings": db.execute("SELECT COUNT(*) FROM postings").fetchone()[0],
            "mail_helpers": families.get("mail", 0), "document_text_helpers": families.get("document_text", 0)}


def build_lookup(*, directory: Path, expected_revision_sha256: str,
                 output_directory: Path, base_lookup_directory: Path | None = None,
                 seed_preparation_directory: Path | None = None,
                 seed_expected_revision_sha256: str | None = None,
                 seed_job_prefix_count: int | None = None) -> dict:
    """Seed only an explicit unchanged job prefix; replace old suffix offline.

    Without seed arguments, base_lookup_directory retains its same-revision
    metadata-extension contract. Seeding requires a separately pinned old
    preparation, a current-policy base lookup and a NEW output directory.
    """
    seeding = any(value is not None for value in (
        seed_preparation_directory, seed_expected_revision_sha256, seed_job_prefix_count,
    ))
    if seeding and (base_lookup_directory is None or seed_preparation_directory is None
                    or seed_expected_revision_sha256 is None or seed_job_prefix_count is None):
        raise ContractValidationError("source seed requires preparation, pin, lookup and job prefix count")
    if seeding:
        if output_directory.exists() or output_directory.is_symlink():
            raise ContractValidationError("source seed requires a new output directory")
        for source_directory in (directory, seed_preparation_directory, base_lookup_directory):
            if output_directory.resolve().is_relative_to(source_directory.resolve()):
                raise ContractValidationError("source seed output must be separate from its inputs")
            if (source_directory / "source-lookup.sqlite").exists():
                _sealed_lookup_state(source_directory)
    revision = load_issue56_ingestion_revision(
        directory, expected_revision_sha256=expected_revision_sha256,
    )
    records = revision.source_records
    seed_revision = None
    try:
        profile = load_issue56_target_mail_tokenizer_profile()
        expected = _lookup_expected(revision, profile)
        if output_directory.exists() or output_directory.is_symlink():
            lookup = SourceNativeLexicalLookup(directory=output_directory, **expected)
            try:
                if lookup.manifest.get("token_surface_policy_id") != TOKEN_SURFACE_POLICY_ID:
                    raise ContractValidationError("source lexical lookup token surfaces are unverified")
                if lookup.manifest.get("attachment_parent_policy_id") != ATTACHMENT_PARENT_POLICY_ID:
                    raise ContractValidationError("source attachment parent helpers require an offline extension")
                if not lookup.has_keyed_source_metadata:
                    raise ContractValidationError("source keyed locators require an offline extension")
                counts = lookup.manifest.get("counts")
                if (not isinstance(counts, dict) or set(counts) != {
                    "references", "helpers", "postings", "mail_helpers", "document_text_helpers",
                } or any(type(value) is not int or value < 0 for value in counts.values())):
                    raise ContractValidationError("source lexical lookup counts are invalid")
                return {"status": "reused", "counts": dict(counts)}
            finally:
                lookup.close()
        authorities = records.job_authorities
        references = records.observation_references
        job_ids = {}
        kinds = [_authorized_ingestion_root_source_kinds(authority) for authority in authorities]
        counts = {"references": len(references), "helpers": 0, "postings": 0,
                  "mail_helpers": 0, "document_text_helpers": 0}
        with tempfile.TemporaryDirectory(prefix=".source-lookup-", dir=output_directory.parent) as temp:
            staged = Path(temp) / "artifact"
            staged.mkdir(mode=0o700)
            sqlite_path = staged / "source-lookup.sqlite"
            connection = sqlite3.connect(sqlite_path)
            base_fingerprint = None
            retained = 0
            try:
                if base_lookup_directory is None:
                    connection.executescript(SCHEMA)
                else:
                    base_expected = expected
                    if seeding:
                        base_state = _sealed_lookup_state(base_lookup_directory)
                        seed_revision = load_issue56_ingestion_revision(
                            seed_preparation_directory, expected_revision_sha256=seed_expected_revision_sha256,
                        )
                        base_expected = _lookup_expected(seed_revision, profile)
                    base = SourceNativeLexicalLookup(directory=base_lookup_directory, **base_expected)
                    try:
                        if base.manifest.get("token_surface_policy_id") != TOKEN_SURFACE_POLICY_ID:
                            raise ContractValidationError("source lexical lookup token surfaces are unverified")
                        with base._connection_lock:
                            if seeding:
                                retained = _seed_prefix(base, seed_revision.source_records, records, seed_job_prefix_count)
                            base_counts = dict(base.manifest["counts"])
                            append_only_seed = seeding and retained == base_counts["references"]
                            if append_only_seed:
                                # Prefix validation and the immutable source/hash proof
                                # complete before copying; avoid SQLite backup's full
                                # page read/write path when there is no old suffix.
                                if (base_state != _sealed_lookup_state(base_lookup_directory)
                                        or _file_sha256(base_lookup_directory / "source-lookup.sqlite")
                                        != base.manifest["sqlite_sha256"]):
                                    raise ContractValidationError("source seed lookup changed during copy")
                                connection.close()
                                sqlite_path.unlink()
                                shutil.copyfile(base_lookup_directory / "source-lookup.sqlite", sqlite_path)
                                shutil.copymode(base_lookup_directory / "source-lookup.sqlite", sqlite_path)
                                connection = sqlite3.connect(sqlite_path)
                            else:
                                base._connection.backup(connection)
                        counts = dict(base.manifest["counts"])
                        if not seeding and counts.get("references") != len(references):
                            raise ContractValidationError("source lexical clone reference count mismatch")
                        base_fingerprint = base.manifest["manifest_fingerprint"]
                        if seeding and (base_state != _sealed_lookup_state(base_lookup_directory)
                                or _file_sha256(base_lookup_directory / "source-lookup.sqlite") != base.manifest["sqlite_sha256"]
                                or append_only_seed and _file_sha256(sqlite_path) != base.manifest["sqlite_sha256"]):
                            raise ContractValidationError("source seed lookup changed during copy")
                    finally:
                        base.close()
                    if seed_revision is not None:
                        if seed_revision.source_records.runtime_store is not None:
                            seed_revision.source_records.runtime_store.close()
                        # The old snapshot can be large. Its proved prefix is
                        # now in staging; release it before suffix hydration.
                        seed_revision = None
                    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS helpers_observation_id ON helpers(observation_id)")
                    connection.execute("CREATE TABLE IF NOT EXISTS attachment_parents (child_asset_id TEXT PRIMARY KEY, observation_hash TEXT NOT NULL UNIQUE)")
                    if seeding and retained == counts["references"]:
                        # _seed_prefix validated every old row/count before the
                        # unchanged-base backup: there is no old suffix to drop.
                        counts["references"] = len(references)
                    elif seeding:
                        # Delete on the private copy only. Never retain postings
                        # or native locators belonging to the replaced delta.
                        for table in ("postings", "attachment_parents", "occurrence_helpers"):
                            connection.execute(f"DELETE FROM {table} WHERE observation_hash IN "
                                               "(SELECT observation_hash FROM reference_locators WHERE position >= ?)", (retained,))
                        connection.execute("DELETE FROM helpers WHERE job_index >= ?", (seed_job_prefix_count,))
                        connection.execute("DELETE FROM reference_locators WHERE position >= ?", (retained,))
                        counts = _lookup_counts(connection, len(references))
                connection.executescript(LOCATOR_SCHEMA)
                parent_count = connection.execute("SELECT COUNT(*) FROM attachment_parents").fetchone()[0]
                attachment_text_refs = []
                for scanned, (job_index, observation_id, observation_hash) in enumerate(islice(references, retained, None), retained + 1):
                    authority = authorities[job_index]
                    if job_index not in job_ids:
                        job_ids[job_index] = set(authority.observation_ids)
                    if observation_id not in job_ids[job_index]:
                        raise ContractValidationError("source lexical Observation is outside its job")
                    locator = (observation_hash, observation_id, job_index, authority.job_fingerprint, scanned - 1)
                    existing_locator = connection.execute(
                        "SELECT observation_hash, observation_id, job_index, job_fingerprint, position "
                        "FROM reference_locators WHERE observation_id = ?", (observation_id,),
                    ).fetchone()
                    if existing_locator is not None and existing_locator != locator:
                        raise ContractValidationError("source keyed clone reference binding mismatch")
                    connection.execute("INSERT OR IGNORE INTO reference_locators VALUES (?, ?, ?, ?, ?)", locator)
                    observation = authority.load_indexed_observation(
                        observation_id, expected_observation_hash=observation_hash,
                        expected_job_fingerprint=authority.job_fingerprint,
                    )
                    if (observation.modality == "mail" and observation.observation_type in {
                        "email_message", "email_header", "email_body_segment",
                    } and AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND in kinds[job_index]):
                        family = "mail"
                    elif (observation.modality == "text"
                          and observation.observation_type in {"heading", "paragraph"}
                          and observation.asset_id == authority.asset.asset_id
                          and AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND in kinds[job_index]):
                        family = "document_text"
                    elif (
                        _is_attachment_text_observation(observation)
                        and AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND in kinds[job_index]
                    ):
                        # Admission still needs genuine parent/hash/job binding
                        # at hydration. Classification itself grants no access.
                        family = "mail"
                    else:
                        family = None
                    payload = observation.payload or {}
                    if seeding and _is_attachment_text_observation(observation):
                        attachment_text_refs.append((job_index, observation_id, observation_hash, observation.asset_id))
                    child_asset_id = payload.get("child_asset_id")
                    parent = (observation.modality == "mail"
                              and observation.observation_type == "email_attachment_occurrence"
                              and observation.asset_id == authority.asset.asset_id
                              and isinstance(child_asset_id, str) and bool(child_asset_id)
                              and AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND in kinds[job_index])
                    fields = ("subject", "normalized_subject", "sender", "from", "to", "cc",
                              "header_name", "header_value", "body_excerpt")
                    # Mirror the source matcher's joined mail surfaces and
                    # the independent-text matcher's text/caption fallback.
                    values = ([observation.text, *(payload.get(key) for key in fields)]
                              if family == "mail" else [observation.text or observation.caption])
                    searchable = " ".join(value for value in values if isinstance(value, str) and value)
                    tokens = (set(profile.analyze(searchable).tokens)
                              if (seeding or base_lookup_directory is None) and family is not None and searchable else set())
                    if family is not None or parent:
                        if parent:
                            family = "mail"
                        permission = dict(authority.permission_scope)
                        helper = (
                            observation_hash, observation_id, job_index, authority.job_fingerprint,
                            permission["scope_id"], json.dumps(permission, sort_keys=True), family,
                        )
                        existing = connection.execute(
                            "SELECT * FROM helpers WHERE observation_id = ?", (observation_id,),
                        ).fetchone()
                        if existing is not None and existing != helper:
                            raise ContractValidationError("source lexical clone helper binding mismatch")
                        if existing is None:
                            connection.execute("INSERT INTO helpers VALUES (?, ?, ?, ?, ?, ?, ?)", helper)
                            connection.executemany("INSERT INTO postings VALUES (?, ?, ?)", (
                                (token, family, observation_hash) for token in sorted(tokens)
                            ))
                            counts["helpers"] += 1
                            counts["postings"] += len(tokens)
                            counts[family + "_helpers"] += 1
                        occurrence_id = (observation.location or {}).get("message_occurrence_id")
                        if family == "mail" and isinstance(occurrence_id, str) and occurrence_id:
                            context = (observation_hash, occurrence_id, job_index, observation.asset_id,
                                       observation.extractor_run_id, observation.observation_type)
                            existing_context = connection.execute(
                                "SELECT * FROM occurrence_helpers WHERE observation_hash = ?", (observation_hash,),
                            ).fetchone()
                            if existing_context is not None and existing_context != context:
                                raise ContractValidationError("source keyed clone occurrence binding mismatch")
                            connection.execute("INSERT OR IGNORE INTO occurrence_helpers VALUES (?, ?, ?, ?, ?, ?)", context)
                        if parent:
                            existing_parent = connection.execute(
                                "SELECT observation_hash FROM attachment_parents WHERE child_asset_id = ?", (child_asset_id,),
                            ).fetchone()
                            if existing_parent is not None and existing_parent != (observation_hash,):
                                raise ContractValidationError("source keyed clone attachment binding mismatch")
                            if existing_parent is None:
                                connection.execute("INSERT INTO attachment_parents VALUES (?, ?)", (child_asset_id, observation_hash))
                                parent_count += 1
                    if scanned % 8192 == 0:
                        connection.commit()
                        print(json.dumps({"references_scanned": scanned, **counts}), flush=True)
                connection.commit()
                for job_index, observation_id, observation_hash, child_asset_id in attachment_text_refs:
                    parent_ref = connection.execute(
                        "SELECT h.observation_id, h.observation_hash, h.job_index FROM attachment_parents p "
                        "JOIN helpers h USING(observation_hash) WHERE p.child_asset_id = ?", (child_asset_id,),
                    ).fetchone()
                    if parent_ref is None or parent_ref[2] != job_index:
                        raise ContractValidationError("source seed attachment parent job binding mismatch")
                    authority = authorities[job_index]
                    child = authority.load_indexed_observation(
                        observation_id, expected_observation_hash=observation_hash,
                        expected_job_fingerprint=authority.job_fingerprint,
                    )
                    parent = authority.load_indexed_observation(
                        parent_ref[0], expected_observation_hash=parent_ref[1],
                        expected_job_fingerprint=authority.job_fingerprint,
                    )
                    if (parent.asset_id != authority.asset.asset_id or parent.modality != "mail"
                            or authority._runs_by_id[child.extractor_run_id].input_hash != child.payload["lineage"].get("child_content_hash")):
                        raise ContractValidationError("source seed attachment run binding mismatch")
                    _attachment_child_lineages({child.observation_id: child, parent.observation_id: parent})
                locator_count = connection.execute("SELECT COUNT(*) FROM reference_locators").fetchone()[0]
                if locator_count != len(references):
                    raise ContractValidationError("source keyed locator count mismatch")
            finally:
                connection.close()
            core = {
                "artifact_id": SourceNativeLexicalLookup.ARTIFACT_ID,
                "schema_version": SourceNativeLexicalLookup.SCHEMA_VERSION,
                "source_revision_sha256": expected_revision_sha256,
                "snapshot_sha256": expected["expected_snapshot_sha256"],
                "source_authority_fingerprint": expected["expected_source_authority_fingerprint"],
                "tokenizer_id": profile.tokenizer_id,
                "tokenizer_profile_fingerprint": profile.profile_fingerprint,
                "token_surface_policy_id": TOKEN_SURFACE_POLICY_ID,
                "attachment_parent_policy_id": ATTACHMENT_PARENT_POLICY_ID,
                "attachment_parent_count": parent_count,
                "locator_policy_id": SourceNativeLexicalLookup.LOCATOR_POLICY_ID,
                "locator_count": locator_count,
                "lexical_build_mode": ("offline_seeded_job_prefix" if seeding else
                                       "retained_verified_postings" if base_fingerprint else "offline_tokenized"),
                "base_lexical_manifest_fingerprint": base_fingerprint,
                "source_families": ["document_text", "mail"], "counts": counts,
                "sqlite_sha256": _file_sha256(sqlite_path),
            }
            if seeding:
                core["seed_binding"] = {"source_revision_sha256": seed_expected_revision_sha256,
                                        "job_prefix_count": seed_job_prefix_count, "reference_prefix_count": retained}
            with sqlite_path.open("rb") as stream:
                os.fsync(stream.fileno())
            _write_file_exclusive(staged / "source-lookup-manifest.json", json.dumps({
                **core, "manifest_fingerprint": sha256_json(core),
            }, sort_keys=True, separators=(",", ":")).encode())
            lookup = SourceNativeLexicalLookup(directory=staged, **expected)
            lookup.close()
            _fsync_directory(staged)
            _rename_directory_no_replace(staged, output_directory)
            _fsync_directory(output_directory.parent)
        return {"status": "created", "counts": counts}
    finally:
        if records is not None and records.runtime_store is not None:
            records.runtime_store.close()
        if seed_revision is not None and seed_revision.source_records.runtime_store is not None:
            seed_revision.source_records.runtime_store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="Sealed source-start preparation")
    parser.add_argument("--expected-revision-sha256", required=True, help="Operator-pinned preparation byte hash")
    parser.add_argument("--output-directory", type=Path, required=True, help="New immutable lookup directory, or matching pair to validate/reuse")
    parser.add_argument("--base-lookup-directory", type=Path, help="Clone verified postings and add sealed locator/occurrence/parent metadata offline; no retokenization or missing lexical surface rebuild")
    parser.add_argument("--seed-preparation-directory", type=Path, help="Separately validated OLD source preparation for offline prefix seeding")
    parser.add_argument("--seed-expected-revision-sha256", help="Operator-pinned OLD preparation byte hash")
    parser.add_argument("--seed-job-prefix-count", type=int, help="Exact unchanged leading job count to retain; discard old suffix and tokenize new suffix offline")
    args = parser.parse_args(argv)
    try:
        result = build_lookup(directory=args.directory, expected_revision_sha256=args.expected_revision_sha256,
                              output_directory=args.output_directory, base_lookup_directory=args.base_lookup_directory,
                              seed_preparation_directory=args.seed_preparation_directory,
                              seed_expected_revision_sha256=args.seed_expected_revision_sha256,
                              seed_job_prefix_count=args.seed_job_prefix_count)
    except (ContractValidationError, Issue56SealedSourceLoadError,
            SourceIdentifierCandidateError, OSError, sqlite3.Error):
        print(json.dumps({"status": "rejected"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
