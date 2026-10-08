#!/usr/bin/env python3
"""Build/reuse an immutable OFFLINE lexical accelerator for a sealed source start.

Output is a separate directory containing the existing reader's SQLite/manifest
pair. Publication is one atomic no-replace directory rename, not a source or
runtime rewrite. An operator owns any later deployment of the validated pair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "python"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import ContractValidationError, sha256_json  # noqa: E402
from formowl_core import load_issue56_target_mail_tokenizer_profile  # noqa: E402
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
"""
TOKEN_SURFACE_POLICY_ID = "source_matcher_mail_fields_text_caption_v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_lookup(*, directory: Path, expected_revision_sha256: str,
                 output_directory: Path) -> dict:
    revision = load_issue56_ingestion_revision(
        directory, expected_revision_sha256=expected_revision_sha256,
    )
    records = revision.source_records
    if revision.safe_binding.get("source_start") is not True or records is None:
        raise ContractValidationError("source lexical builder requires a source-start preparation")
    profile = load_issue56_target_mail_tokenizer_profile()
    expected = {
        "expected_source_revision_sha256": expected_revision_sha256,
        "expected_snapshot_sha256": revision.safe_binding["snapshot_sha256"],
        "expected_source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
        "expected_tokenizer_id": profile.tokenizer_id,
        "expected_tokenizer_profile_fingerprint": profile.profile_fingerprint,
    }
    try:
        if output_directory.exists() or output_directory.is_symlink():
            lookup = SourceNativeLexicalLookup(directory=output_directory, **expected)
            try:
                if lookup.manifest.get("token_surface_policy_id") != TOKEN_SURFACE_POLICY_ID:
                    raise ContractValidationError("source lexical lookup token surfaces are unverified")
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
        job_ids = [set(authority.observation_ids) for authority in authorities]
        kinds = [_authorized_ingestion_root_source_kinds(authority) for authority in authorities]
        counts = {"references": len(references), "helpers": 0, "postings": 0,
                  "mail_helpers": 0, "document_text_helpers": 0}
        with tempfile.TemporaryDirectory(prefix=".source-lookup-", dir=output_directory.parent) as temp:
            staged = Path(temp) / "artifact"
            staged.mkdir(mode=0o700)
            sqlite_path = staged / "source-lookup.sqlite"
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.executescript(SCHEMA)
                for scanned, (job_index, observation_id, observation_hash) in enumerate(references, 1):
                    authority = authorities[job_index]
                    if observation_id not in job_ids[job_index]:
                        raise ContractValidationError("source lexical Observation is outside its job")
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
                    else:
                        family = None
                    payload = observation.payload or {}
                    fields = ("subject", "normalized_subject", "sender", "from", "to", "cc",
                              "header_name", "header_value", "body_excerpt")
                    # Mirror the source matcher's joined mail surfaces and
                    # the independent-text matcher's text/caption fallback.
                    values = ([observation.text, *(payload.get(key) for key in fields)]
                              if family == "mail" else [observation.text or observation.caption])
                    searchable = " ".join(value for value in values if isinstance(value, str) and value)
                    tokens = (set(profile.analyze(searchable).tokens)
                              if family is not None and searchable else set())
                    if tokens:
                        permission = dict(authority.permission_scope)
                        connection.execute("INSERT INTO helpers VALUES (?, ?, ?, ?, ?, ?, ?)", (
                            observation_hash, observation_id, job_index, authority.job_fingerprint,
                            permission["scope_id"], json.dumps(permission, sort_keys=True), family,
                        ))
                        connection.executemany("INSERT INTO postings VALUES (?, ?, ?)", (
                            (token, family, observation_hash) for token in sorted(tokens)
                        ))
                        counts["helpers"] += 1
                        counts["postings"] += len(tokens)
                        counts[family + "_helpers"] += 1
                    if scanned % 8192 == 0:
                        connection.commit()
                        print(json.dumps({"references_scanned": scanned, **counts}), flush=True)
                connection.commit()
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
                "source_families": ["document_text", "mail"], "counts": counts,
                "sqlite_sha256": _file_sha256(sqlite_path),
            }
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
        if records.runtime_store is not None:
            records.runtime_store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="Sealed source-start preparation")
    parser.add_argument("--expected-revision-sha256", required=True, help="Operator-pinned preparation byte hash")
    parser.add_argument("--output-directory", type=Path, required=True, help="New immutable lookup directory, or matching pair to validate/reuse")
    args = parser.parse_args(argv)
    try:
        result = build_lookup(directory=args.directory, expected_revision_sha256=args.expected_revision_sha256,
                              output_directory=args.output_directory)
    except (ContractValidationError, Issue56SealedSourceLoadError,
            SourceIdentifierCandidateError, OSError, sqlite3.Error):
        print(json.dumps({"status": "rejected"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
