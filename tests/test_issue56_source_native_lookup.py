from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from starlette.testclient import TestClient

from formowl_contract import ContractValidationError, sha256_json, stable_resource_contract_id
from formowl_core import load_issue56_target_mail_tokenizer_profile
from formowl_ingestion.extractors.mail import fixture as mail_fixture
from formowl_ingestion.storage import ObservationStore
from formowl_mail.import_workflow import CompletedIngestionJobAuthority
from formowl_mail.issue56_sealed_source import (
    SourceNativeLexicalLookup, load_issue56_ingestion_revision,
    _authorized_mail_selector_for_asset,
)
from formowl_mail.query import (
    _source_mail_observation_match,
    source_occurrence_lineage_from_observation,
)
from formowl_retrieval.gateway import source_evidence_query_terms_scope
from scripts import issue56_source_native_lookup as builder
from scripts.issue56_source_identifier_candidates import SourceIdentifierCandidateError
import test_issue56_uat_handler_composition as composition
from test_issue56_uat_handler_composition import _source_start_preparation_fixture


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_lookup(root: Path, *, sqlite_hash_override: str | None = None) -> dict[str, str]:
    sqlite_path = root / "source-lookup.sqlite"
    connection = sqlite3.connect(sqlite_path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE helpers (
            observation_hash TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            job_index INTEGER NOT NULL,
            job_fingerprint TEXT NOT NULL,
            source_scope_id TEXT NOT NULL,
            permission_scope_json TEXT NOT NULL,
            source_family TEXT NOT NULL
        );
        CREATE TABLE postings (
            token TEXT NOT NULL,
            source_family TEXT NOT NULL,
            observation_hash TEXT NOT NULL,
            PRIMARY KEY (token, source_family, observation_hash)
        );
        """
    )
    permission = json.dumps(
        {"scope_id": "mail_scope", "workspace_id": "workspace_formowl"},
        separators=(",", ":"),
    )
    connection.execute(
        "INSERT INTO helpers VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "sha256:" + "a" * 64,
            "observation-1",
            0,
            "sha256:" + "b" * 64,
            "mail_scope",
            permission,
            "mail",
        ),
    )
    connection.executemany(
        "INSERT INTO postings VALUES (?, ?, ?)",
        [
            ("嘉值", "mail", "sha256:" + "a" * 64),
            ("交期", "mail", "sha256:" + "a" * 64),
        ],
    )
    connection.commit()
    connection.close()
    core = {
        "artifact_id": SourceNativeLexicalLookup.ARTIFACT_ID,
        "schema_version": SourceNativeLexicalLookup.SCHEMA_VERSION,
        "source_revision_sha256": "sha256:" + "c" * 64,
        "snapshot_sha256": "sha256:" + "d" * 64,
        "source_authority_fingerprint": "sha256:" + "e" * 64,
        "tokenizer_id": "tokenizer-v1",
        "tokenizer_profile_fingerprint": "sha256:" + "f" * 64,
        "source_families": ["document_text", "mail"],
        "counts": {"helpers": 1, "postings": 2},
        "sqlite_sha256": sqlite_hash_override or _sha256(sqlite_path),
    }
    manifest = {**core, "manifest_fingerprint": sha256_json(core)}
    (root / "source-lookup-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return {
        "expected_source_revision_sha256": core["source_revision_sha256"],
        "expected_snapshot_sha256": core["snapshot_sha256"],
        "expected_source_authority_fingerprint": core["source_authority_fingerprint"],
    }


def _write_late_hit_lookup(root: Path) -> dict[str, str]:
    sqlite_path = root / "source-lookup.sqlite"
    connection = sqlite3.connect(sqlite_path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE helpers (
            observation_hash TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            job_index INTEGER NOT NULL,
            job_fingerprint TEXT NOT NULL,
            source_scope_id TEXT NOT NULL,
            permission_scope_json TEXT NOT NULL,
            source_family TEXT NOT NULL
        );
        CREATE TABLE postings (
            token TEXT NOT NULL,
            source_family TEXT NOT NULL,
            observation_hash TEXT NOT NULL,
            PRIMARY KEY (token, source_family, observation_hash)
        );
        """
    )
    permission = json.dumps(
        {"scope_id": "mail_scope", "workspace_id": "workspace_formowl"},
        separators=(",", ":"),
    )
    rows = []
    postings = []
    for index in range(300):
        observation_hash = f"sha256:{index:064x}"
        rows.append(
            (
                observation_hash,
                f"observation-{index}",
                0,
                "sha256:" + "b" * 64,
                "mail_scope",
                permission,
                "mail",
            )
        )
        postings.append(("common", "mail", observation_hash))
    late_hash = "sha256:" + "f" * 64
    rows.append(
        (
            late_hash,
            "observation-late",
            0,
            "sha256:" + "b" * 64,
            "mail_scope",
            permission,
            "mail",
        )
    )
    postings.extend(
        [
            ("common", "mail", late_hash),
            ("rare", "mail", late_hash),
        ]
    )
    connection.executemany("INSERT INTO helpers VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    connection.executemany("INSERT INTO postings VALUES (?, ?, ?)", postings)
    connection.commit()
    connection.close()
    core = {
        "artifact_id": SourceNativeLexicalLookup.ARTIFACT_ID,
        "schema_version": SourceNativeLexicalLookup.SCHEMA_VERSION,
        "source_revision_sha256": "sha256:" + "c" * 64,
        "snapshot_sha256": "sha256:" + "d" * 64,
        "source_authority_fingerprint": "sha256:" + "e" * 64,
        "tokenizer_id": "tokenizer-v1",
        "tokenizer_profile_fingerprint": "sha256:" + "f" * 64,
        "source_families": ["document_text", "mail"],
        "counts": {"helpers": len(rows), "postings": len(postings)},
        "sqlite_sha256": _sha256(sqlite_path),
    }
    (root / "source-lookup-manifest.json").write_text(
        json.dumps(
            {**core, "manifest_fingerprint": sha256_json(core)},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return {
        "expected_source_revision_sha256": core["source_revision_sha256"],
        "expected_snapshot_sha256": core["snapshot_sha256"],
        "expected_source_authority_fingerprint": core["source_authority_fingerprint"],
    }


class SourceNativeLexicalLookupTests(unittest.TestCase):
    def test_artifact_hash_is_verified_without_whole_file_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _write_lookup(root)
            read_bytes = Path.read_bytes

            def bounded_read(path):
                if path.name == "source-lookup.sqlite":
                    raise AssertionError("whole SQLite artifact read is forbidden")
                return read_bytes(path)

            with patch.object(Path, "read_bytes", bounded_read):
                lookup = SourceNativeLexicalLookup(
                    directory=root,
                    **expected,
                    expected_tokenizer_id="tokenizer-v1",
                    expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
                )
                lookup.close()
                with (root / "source-lookup.sqlite").open("ab") as stream:
                    stream.write(b"tampered")
                with self.assertRaisesRegex(ContractValidationError, "artifact hash mismatch"):
                    SourceNativeLexicalLookup(
                        directory=root,
                        **expected,
                        expected_tokenizer_id="tokenizer-v1",
                        expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
                    )

    def test_lookup_returns_hash_and_reconstructs_owner_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _write_lookup(root)
            lookup = SourceNativeLexicalLookup(
                directory=root,
                **expected,
                expected_tokenizer_id="tokenizer-v1",
                expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
            )
            self.assertEqual(
                lookup.source_family_lexical_lookup(
                    ("嘉值", "交期"),
                    source_family="mail",
                    limit=8,
                    timeout_ms=50,
                ),
                ["sha256:" + "a" * 64],
            )
            # The UAT handler is shared across request threads; the sealed
            # read-only accelerator must not retain sqlite's default
            # same-thread restriction.
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertEqual(
                    executor.submit(
                        lookup.source_family_lexical_lookup,
                        ("嘉值",),
                        source_family="mail",
                        limit=8,
                        timeout_ms=50,
                    ).result(),
                    ["sha256:" + "a" * 64],
                )
            helper = lookup.helper_for_hash("sha256:" + "a" * 64)
            self.assertIsNotNone(helper)
            assert helper is not None
            self.assertEqual(helper["observation_id"], "observation-1")
            self.assertEqual(helper["reference"]["job_index"], 0)
            self.assertEqual(helper["permission_scope"]["scope_id"], "mail_scope")
            lookup.close()

    def test_tampered_sqlite_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _write_lookup(root, sqlite_hash_override="sha256:" + "0" * 64)
            with self.assertRaisesRegex(ContractValidationError, "artifact hash mismatch"):
                SourceNativeLexicalLookup(
                    directory=root,
                    **expected,
                    expected_tokenizer_id="tokenizer-v1",
                    expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
                )

    def test_late_candidate_survives_bounded_token_slices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _write_late_hit_lookup(root)
            lookup = SourceNativeLexicalLookup(
                directory=root,
                **expected,
                expected_tokenizer_id="tokenizer-v1",
                expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
            )
            result = lookup.source_family_lexical_lookup(
                ("common", "rare"),
                source_family="mail",
                limit=8,
                timeout_ms=100,
            )
            self.assertEqual(result[0], "sha256:" + "f" * 64)
            self.assertIn("sha256:" + "f" * 64, result)
            lookup.close()

    def test_wrong_source_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _write_lookup(root)
            expected["expected_snapshot_sha256"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ContractValidationError, "authority binding mismatch"):
                SourceNativeLexicalLookup(
                    directory=root,
                    **expected,
                    expected_tokenizer_id="tokenizer-v1",
                    expected_tokenizer_profile_fingerprint="sha256:" + "f" * 64,
                )


class SourceNeighborContextTests(unittest.TestCase):
    def test_neighbor_reader_revalidates_identity_permissions_and_locators(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory), mail_text="SYNTH-CONTEXT-057\n\nWindow: 2032-06-09.",
            )
            revision = load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            records = revision.source_records
            authority = records.job_authorities[0]
            anchor, neighbor = [item for item in fixture.observations if item.observation_type == "email_body_segment"]
            parent = next(item for item in fixture.observations if item.observation_type == "email_message")
            fingerprint = parent.payload["message_fingerprint"]
            selector = records.authorized_mail_import_session_ids[0]
            references = records.observation_references
            neighbor_index = next(i for i, ref in enumerate(references) if ref[1] == neighbor.observation_id)
            run = authority._runs_by_id[anchor.extractor_run_id]
            for mode in ("job", "run", "asset", "occurrence", "fingerprint", "permission", "hash"):
                with self.subTest(mode=mode):
                    changed = neighbor
                    runs = dict(authority._runs_by_id)
                    if mode == "run":
                        other_run = replace(run, extractor_run_id="run_context_other")
                        runs[other_run.extractor_run_id] = other_run
                        changed = replace(neighbor, extractor_run_id=other_run.extractor_run_id)
                    elif mode == "asset":
                        other_run = replace(run, extractor_run_id="run_context_other", asset_id="asset_context_other")
                        runs[other_run.extractor_run_id] = other_run
                        changed = replace(neighbor, extractor_run_id=other_run.extractor_run_id, asset_id=other_run.asset_id)
                    elif mode == "occurrence":
                        changed = replace(neighbor, location={**neighbor.location, "message_occurrence_id": "other_occurrence"})
                    elif mode == "fingerprint":
                        changed = replace(neighbor, payload={**neighbor.payload, "message_fingerprint": "different_fingerprint"})
                    elif mode == "permission":
                        changed = replace(neighbor, permission_scope={**dict(authority.permission_scope), "scope_id": "other_scope"})
                    modified_authority = replace(authority, _runs_by_id=runs)
                    modified_references = [list(ref) for ref in references]  # Tiny synthetic fixture only.
                    modified_references[neighbor_index] = [
                        1 if mode == "job" else 0, neighbor.observation_id,
                        "sha256:" + "0" * 64 if mode == "hash" else sha256_json(changed.to_dict()),
                    ]
                    records.job_authorities = (modified_authority, *records.job_authorities[1:])
                    records.observation_references = modified_references
                    delivered = []
                    original_get = authority.observation_store.get
                    with patch.object(authority.observation_store, "get", side_effect=lambda obs_id: changed if obs_id == neighbor.observation_id else original_get(obs_id)):
                        def read():
                            return records.scan_neighbor_context(
                                anchor=anchor, authority=modified_authority, source_scope=selector,
                                max_observations=8, deadline_monotonic=None,
                                message_fingerprint=fingerprint,
                                observation_callback=lambda item, scope: delivered.append(item) or True,
                            )
                        if mode in {"permission", "hash"}:
                            with self.assertRaises(ContractValidationError):
                                read()
                        else:
                            read()
                    self.assertNotIn(neighbor.observation_id, [item.observation_id for item in delivered])
            records.observation_references = references

    def test_neighbor_reader_deadline_and_read_caps_do_not_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory), families=("document_text",),
                document_text="# SYNTH-CONTEXT-071\n\nWindow: next review.\n\nOwner: review team.\n",
            )
            revision = load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            records = revision.source_records
            authority = records.job_authorities[0]
            anchor = fixture.observations[0]
            kwargs = dict(
                anchor=anchor, authority=authority,
                source_scope=dict(authority.permission_scope)["scope_id"],
                max_observations=1, deadline_monotonic=99.0,
                observation_callback=Mock(return_value=True),
            )
            with patch("formowl_mail.issue56_sealed_source.time.monotonic", return_value=100.0), patch.object(authority.observation_store, "get") as read:
                scan = records.scan_neighbor_context(**kwargs)
                read.assert_not_called()
            self.assertEqual(scan.scanned_observation_count, 0)
            self.assertEqual(scan.stop_reason, "deadline")
            with patch.object(authority.observation_store, "get", wraps=authority.observation_store.get) as read:
                scan = records.scan_neighbor_context(**{**kwargs, "deadline_monotonic": None})
            self.assertEqual(read.call_count, 1)
            self.assertEqual(scan.scanned_observation_count, 1)
            self.assertFalse(scan.complete)
            self.assertEqual(kwargs["observation_callback"].call_count, 1)
            neighbor = fixture.observations[1]
            references = records.observation_references
            original_get = authority.observation_store.get
            for mode in ("source", "lines"):
                with self.subTest(mode=mode):
                    changed = (
                        replace(neighbor, payload={**(neighbor.payload or {}), "source_ref": {"source_id": "other_document"}})
                        if mode == "source" else replace(neighbor, location={"line_start": 400, "line_end": 401})
                    )
                    records.observation_references = [
                        [0, anchor.observation_id, sha256_json(anchor.to_dict())],
                        [0, changed.observation_id, sha256_json(changed.to_dict())],
                    ]
                    delivered = Mock(return_value=True)
                    with patch.object(authority.observation_store, "get", side_effect=lambda obs_id: changed if obs_id == neighbor.observation_id else original_get(obs_id)):
                        records.scan_neighbor_context(**{
                            **kwargs, "deadline_monotonic": None, "observation_callback": delivered,
                        })
                    delivered.assert_not_called()
            records.observation_references = references


class SourceNativeLexicalBuilderTests(unittest.TestCase):
    def test_parent_extension_clones_existing_postings_without_retokenization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root, families=("mail",), attachment_csv="Code,State\n7812046639,open\n",
            )
            base = root / "base"
            self._build(fixture, base)
            parent = next(item for item in fixture.observations if item.observation_type == "email_attachment_occurrence")
            parent_hash = sha256_json(parent.to_dict())
            with sqlite3.connect(base / "source-lookup.sqlite") as db:
                postings = db.execute("SELECT * FROM postings ORDER BY token,source_family,observation_hash").fetchall()
                db.execute("DROP TABLE attachment_parents")
                db.execute("DELETE FROM helpers WHERE observation_hash = ?", (parent_hash,))
            manifest_path = base / "source-lookup-manifest.json"
            core = json.loads(manifest_path.read_text())
            for key in ("attachment_parent_policy_id", "attachment_parent_count", "manifest_fingerprint"):
                core.pop(key)
            core["counts"]["helpers"] -= 1
            core["counts"]["mail_helpers"] -= 1
            core["sqlite_sha256"] = _sha256(base / "source-lookup.sqlite")
            manifest_path.write_text(json.dumps({**core, "manifest_fingerprint": sha256_json(core)}))
            before = {_file.name: _sha256(_file) for _file in base.iterdir()}
            profile = load_issue56_target_mail_tokenizer_profile()
            frozen = SimpleNamespace(tokenizer_id=profile.tokenizer_id, profile_fingerprint=profile.profile_fingerprint,
                                     analyze=Mock(side_effect=AssertionError("clone must not retokenize")))
            output = root / "extended"
            with patch.object(builder, "load_issue56_target_mail_tokenizer_profile", return_value=frozen):
                result = builder.build_lookup(directory=fixture.directory,
                    expected_revision_sha256=fixture.preparation_sha256, output_directory=output,
                    base_lookup_directory=base)
            self.assertEqual(result["status"], "created")
            frozen.analyze.assert_not_called()
            self.assertEqual(before, {_file.name: _sha256(_file) for _file in base.iterdir()})
            with sqlite3.connect(output / "source-lookup.sqlite") as db:
                self.assertEqual(postings, db.execute("SELECT * FROM postings ORDER BY token,source_family,observation_hash").fetchall())
            for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
                shutil.copyfile(output / name, fixture.directory / name)
            revision = load_issue56_ingestion_revision(fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
            lookup = revision.source_records.runtime_store
            try:
                helper = lookup.helper_for_attachment_asset(parent.payload["child_asset_id"])
                self.assertEqual(helper["observation_hash"], parent_hash)
                self.assertEqual(helper["reference"]["job_fingerprint"], fixture.authorities[0].job_fingerprint)
                self.assertEqual(revision.source_records.attachment_parent_for_child_asset(parent.payload["child_asset_id"]), parent)
                self.assertIsNone(lookup.helper_for_attachment_asset("synthetic-missing-child"))
            finally:
                lookup.close()

    def _fixture(self, root):
        return _source_start_preparation_fixture(
            root, mail_text="GENERIC-MAIL-001 alpha material",
        )

    def _build(self, fixture, output):
        return builder.build_lookup(
            directory=fixture.directory,
            expected_revision_sha256=fixture.preparation_sha256,
            output_directory=output,
        )

    def test_two_completed_jobs_mail_and_independent_text_build_and_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            output = root / "lookup"
            input_hashes = {
                path.name: _sha256(path) for path in fixture.directory.glob("*.json")
            }
            calls = []
            original = CompletedIngestionJobAuthority.load_indexed_observation

            def keyed_load(authority, observation_id, **kwargs):
                calls.append((authority.job_fingerprint, observation_id, kwargs))
                return original(authority, observation_id, **kwargs)

            with patch.object(CompletedIngestionJobAuthority, "load_indexed_observation", keyed_load):
                result = self._build(fixture, output)
            references = fixture.snapshot["observation_references"]
            self.assertEqual(result["status"], "created")
            self.assertEqual(result["counts"]["references"], len(references))
            self.assertEqual(len(calls), len(references))
            self.assertEqual({fingerprint for fingerprint, *_ in calls}, {
                authority.job_fingerprint for authority in fixture.authorities
            })
            for call, reference in zip(calls, references):
                job_index, observation_id, observation_hash = reference
                self.assertEqual(call, (
                    fixture.authorities[job_index].job_fingerprint, observation_id,
                    {"expected_observation_hash": observation_hash,
                     "expected_job_fingerprint": fixture.authorities[job_index].job_fingerprint},
                ))
            profile = load_issue56_target_mail_tokenizer_profile()
            lookup = SourceNativeLexicalLookup(
                directory=output,
                expected_source_revision_sha256=fixture.preparation_sha256,
                expected_snapshot_sha256=fixture.preparation_core["snapshot_sha256"],
                expected_source_authority_fingerprint=(
                    fixture.snapshot["source_binding"]["source_authority_fingerprint"]
                ),
                expected_tokenizer_id=profile.tokenizer_id,
                expected_tokenizer_profile_fingerprint=profile.profile_fingerprint,
            )
            try:
                for job_index, authority in enumerate(fixture.authorities):
                    family = "mail" if job_index == 0 else "document_text"
                    observation = next(item for item in fixture.observations
                                       if item.asset_id == authority.asset.asset_id and item.text
                                       and profile.analyze(item.text).tokens
                                       and lookup.get_helper(item.observation_id) is not None)
                    observation_hash = sha256_json(observation.to_dict())
                    helper = lookup.helper_for_hash(observation_hash)
                    self.assertEqual(helper["reference"], {
                        "job_index": job_index, "job_fingerprint": authority.job_fingerprint,
                    })
                    self.assertEqual(helper["permission_scope"], dict(authority.permission_scope))
                    self.assertEqual(helper["source_scope_id"], authority.permission_scope["scope_id"])
                    token = next(iter(profile.analyze(observation.text).tokens))
                    self.assertIn(observation_hash, lookup.source_family_lexical_lookup(
                        (token,), source_family=family, limit=256, timeout_ms=100,
                    ))
                self.assertGreater(result["counts"]["mail_helpers"], 0)
                self.assertGreater(result["counts"]["document_text_helpers"], 0)
            finally:
                lookup.close()
            output_hashes = {path.name: _sha256(path) for path in output.iterdir()}
            with patch.object(builder, "_rename_directory_no_replace", side_effect=AssertionError("rebuilt")):
                reused = self._build(fixture, output)
            self.assertEqual(reused, {**result, "status": "reused"})
            self.assertEqual(output_hashes, {path.name: _sha256(path) for path in output.iterdir()})
            self.assertEqual(input_hashes, {
                path.name: _sha256(path) for path in fixture.directory.glob("*.json")
            })

    def test_tampered_source_hash_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            reference = fixture.snapshot["observation_references"][-1]
            store = Path(fixture.snapshot["job_store_bindings"][reference[0]]["store_directory"])
            observations = ObservationStore(store, create_directory=False)
            path = observations._store._record_path(reference[1])
            self.assertTrue(path.is_file())
            record_paths = set(observations._store.base_dir.rglob("*.json"))
            self.assertEqual(len(record_paths), len({item.stem for item in record_paths}))
            self.assertEqual(list(observations._store.base_dir.rglob(f"{reference[1]}.json")), [path])
            raw = json.loads(path.read_bytes())
            raw["text"] = "GENERIC-TAMPERED-002"
            path.write_text(json.dumps(raw))
            self.assertEqual(set(observations._store.base_dir.rglob("*.json")), record_paths)
            self.assertEqual(observations.get(reference[1]).text, raw["text"])
            with self.assertRaisesRegex(ContractValidationError, "indexed Observation binding is invalid"):
                self._build(fixture, root / "lookup")
            self.assertFalse((root / "lookup").exists())
            self.assertEqual(list(root.glob(".source-lookup-*")), [])

    def test_generic_identity_and_header_only_surfaces_match_source_lookup(self):
        fields = ("subject", "normalized_subject", "sender", "from", "to", "cc",
                  "header_name", "header_value", "body_excerpt")
        surfaces = {field: f"GENERIC-SURFACE-{index:03d}"
                    for index, field in enumerate(fields, 1)}
        original = mail_fixture._iter_mail_observations

        def payload_only(*args, **kwargs):
            for parsed in original(*args, **kwargs):
                if parsed.observation_type in {"email_message", "email_header"}:
                    yield replace(parsed, text=None, payload={
                        **parsed.payload, **surfaces,
                        "body": "GENERIC-UNSEARCHED-001",
                        "snippet": "GENERIC-UNSEARCHED-002",
                        "text": "GENERIC-UNSEARCHED-003",
                    })
                else:
                    yield parsed

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(mail_fixture, "_iter_mail_observations", payload_only):
                fixture = self._fixture(root)
            self.assertEqual(len(fixture.authorities), 2)
            output = root / "lookup"
            self._build(fixture, output)
            profile = load_issue56_target_mail_tokenizer_profile()
            lookup = SourceNativeLexicalLookup(
                directory=output,
                expected_source_revision_sha256=fixture.preparation_sha256,
                expected_snapshot_sha256=fixture.preparation_core["snapshot_sha256"],
                expected_source_authority_fingerprint=(
                    fixture.snapshot["source_binding"]["source_authority_fingerprint"]
                ),
                expected_tokenizer_id=profile.tokenizer_id,
                expected_tokenizer_profile_fingerprint=profile.profile_fingerprint,
            )
            try:
                for kind in ("email_message", "email_header"):
                    observation = next(item for item in fixture.observations
                                       if item.observation_type == kind)
                    self.assertIsNone(observation.text)
                    self.assertIsNone(observation.extracted_value)
                    observation_hash = sha256_json(observation.to_dict())
                    for field, surface in surfaces.items():
                        with self.subTest(kind=kind, field=field):
                            analysis = profile.analyze(surface)
                            protected = {span.exact_token for span in analysis.protected_identifiers}
                            self.assertTrue(protected)
                            self.assertIsNotNone(_source_mail_observation_match(
                                observation, query_terms=set(analysis.tokens), required_terms=None,
                                protected_query_tokens=protected, tokenizer_profile=profile,
                            ))
                            self.assertIn(observation_hash, lookup.source_family_lexical_lookup(
                                analysis.tokens, source_family="mail", limit=256, timeout_ms=100,
                            ))
                    searchable = " ".join(observation.payload[field] for field in fields)
                    with sqlite3.connect(output / "source-lookup.sqlite") as connection:
                        tokens = {row[0] for row in connection.execute(
                            "SELECT token FROM postings WHERE observation_hash = ?",
                            (observation_hash,),
                        )}
                    self.assertEqual(tokens, set(profile.analyze(searchable).tokens))
            finally:
                lookup.close()

    def test_existing_mismatched_or_partial_pair_is_preserved(self):
        for invalid in ("hash", "binding", "surfaces", "partial"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = self._fixture(root)
                output = root / "lookup"
                self._build(fixture, output)
                manifest_path = output / "source-lookup-manifest.json"
                if invalid == "hash":
                    with (output / "source-lookup.sqlite").open("ab") as stream:
                        stream.write(b"tamper")
                elif invalid in {"binding", "surfaces"}:
                    manifest = json.loads(manifest_path.read_bytes())
                    manifest.pop("manifest_fingerprint")
                    if invalid == "binding":
                        manifest["source_revision_sha256"] = "sha256:" + "0" * 64
                    else:
                        manifest.pop("token_surface_policy_id")
                    manifest_path.write_text(json.dumps({
                        **manifest, "manifest_fingerprint": sha256_json(manifest),
                    }))
                else:
                    manifest_path.unlink()
                before = {path.name: path.read_bytes() for path in output.iterdir()}
                with self.assertRaises((ContractValidationError, OSError)):
                    self._build(fixture, output)
                self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})

    def test_old_token_surface_policy_reuse_and_clone_are_rejected_immutably(self):
        old_policy = "source_matcher_mail_fields_text_caption_v1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            old_artifact = root / "old-policy"
            self._build(fixture, old_artifact)
            manifest_path = old_artifact / "source-lookup-manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest.pop("manifest_fingerprint")
            manifest["token_surface_policy_id"] = old_policy
            manifest_path.write_text(json.dumps({
                **manifest, "manifest_fingerprint": sha256_json(manifest),
            }))
            before_old_artifact = {
                path.name: path.read_bytes() for path in old_artifact.iterdir()
            }
            with self.assertRaisesRegex(ContractValidationError, "token surfaces"):
                self._build(fixture, old_artifact)
            self.assertEqual(
                before_old_artifact,
                {path.name: path.read_bytes() for path in old_artifact.iterdir()},
            )

            clone_target = root / "clone-target"
            with self.assertRaisesRegex(ContractValidationError, "token surfaces"):
                builder.build_lookup(
                    directory=fixture.directory,
                    expected_revision_sha256=fixture.preparation_sha256,
                    output_directory=clone_target,
                    base_lookup_directory=old_artifact,
                )
            self.assertFalse(clone_target.exists())
            self.assertEqual(
                before_old_artifact,
                {path.name: path.read_bytes() for path in old_artifact.iterdir()},
            )

    def test_competing_publication_never_overwrites_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            output = root / "lookup"
            original = builder._rename_directory_no_replace

            def race(staged, destination):
                self.assertEqual({item.name for item in staged.iterdir()}, {
                    "source-lookup.sqlite", "source-lookup-manifest.json",
                })
                destination.mkdir()
                (destination / "existing").write_bytes(b"preserve")
                original(staged, destination)

            with patch.object(builder, "_rename_directory_no_replace", side_effect=race):
                with self.assertRaisesRegex(SourceIdentifierCandidateError, "immutable_output_already_exists"):
                    self._build(fixture, output)
            self.assertEqual(list(output.iterdir()), [output / "existing"])
            self.assertEqual((output / "existing").read_bytes(), b"preserve")
            self.assertEqual(list(root.glob(".source-lookup-*")), [])


class SourceNativePrefixSeedTests(unittest.TestCase):
    def _compose(self, root, prefix, delta, name):
        """Synthetic sealed composition over genuine completed native jobs."""
        directory = root / name
        shutil.copytree(prefix.directory, directory)
        snapshot = json.loads(json.dumps(prefix.snapshot))
        jobs = snapshot["source_binding"]["jobs"]
        jobs[-1]["supplements"] = delta.snapshot["source_binding"]["jobs"]
        authority_hash = sha256_json({
            "artifact_id": "formowl_completed_ingestion_job_authority_v1",
            "requester_user_id": composition.loader.APPROVER_ACTOR,
            "workspace_id": composition.loader.WORKSPACE_ID, "jobs": jobs,
        })
        snapshot["source_binding"]["source_authority_fingerprint"] = authority_hash
        offset = len(prefix.authorities)
        snapshot["job_store_bindings"].extend(
            {**item, "job_index": item["job_index"] + offset}
            for item in delta.snapshot["job_store_bindings"]
        )
        snapshot["observation_references"].extend(
            [index + offset, observation_id, observation_hash]
            for index, observation_id, observation_hash in delta.snapshot["observation_references"]
        )
        exact_path = directory / "exact-cells" / "manifest.json"
        exact = json.loads(exact_path.read_text())
        exact.pop("manifest_fingerprint")
        exact["source_authority_fingerprint"] = authority_hash
        exact_path.write_text(json.dumps({**exact, "manifest_fingerprint": sha256_json(exact)}))
        snapshot["source_binding"]["exact_lookup_manifest_sha256"] = _sha256(exact_path)
        core = {**prefix.preparation_core,
                "requested_jobs": [[item["store_directory"], item["ingestion_job_id"]]
                                   for item in snapshot["job_store_bindings"]],
                "exact_lookup_manifest_sha256": _sha256(exact_path)}
        result = SimpleNamespace(directory=directory, preparation_core=core, snapshot=snapshot,
                                 authorities=(*prefix.authorities, *delta.authorities),
                                 observations=(*prefix.observations, *delta.observations))
        self._reseal(result)
        return result

    def _reseal(self, fixture):
        path = fixture.directory / "observations.json"
        path.write_text(json.dumps(fixture.snapshot, sort_keys=True))
        core = {**fixture.preparation_core, "snapshot_sha256": _sha256(path),
                "snapshot_size_bytes": path.stat().st_size}
        preparation_path = fixture.directory / "preparation.json"
        preparation_path.write_text(json.dumps({**core, "preparation_fingerprint": sha256_json(core)}))
        fixture.preparation_sha256 = _sha256(preparation_path)

    def _fixtures(self, root):
        prefix_root, old_root, new_root = [root / name for name in ("prefix", "old-delta", "new-delta")]
        for path in (prefix_root, old_root, new_root):
            path.mkdir()
        prefix = _source_start_preparation_fixture(
            prefix_root, mail_text="cerulean immutable root", document_text="immutable handbook\n",
        )
        old_delta = _source_start_preparation_fixture(
            old_root, families=("mail",), mail_text="obsolete saffron",
            attachment_csv="Code,State\nold,retired\n",
        )
        new_delta = _source_start_preparation_fixture(
            new_root, mail_text="vermillion shipment", document_text="tangerine procedure\n",
            attachment_csv="Code,State\nnew,confirmed\n",
        )
        old = self._compose(root, prefix, old_delta, "old-prepared")
        new = self._compose(root, prefix, new_delta, "new-prepared")
        base = root / "base-lookup"
        builder.build_lookup(directory=old.directory, expected_revision_sha256=old.preparation_sha256,
                             output_directory=base)
        return prefix, old, new, base

    def _seed(self, old, new, base, output, **kwargs):
        return builder.build_lookup(**{
            "directory": new.directory, "expected_revision_sha256": new.preparation_sha256,
            "output_directory": output, "base_lookup_directory": base,
            "seed_preparation_directory": old.directory,
            "seed_expected_revision_sha256": old.preparation_sha256,
            "seed_job_prefix_count": 2, **kwargs,
        })

    def _hashes(self, root):
        return {path.relative_to(root): _sha256(path) for path in root.rglob("*") if path.is_file()}

    def test_replacement_suffix_matches_fresh_build_without_reading_or_tokenizing_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix, old, new, base = self._fixtures(root)
            before = self._hashes(root)
            retained_ids = {item[1] for item in prefix.snapshot["observation_references"]}
            reads = []
            original_load = CompletedIngestionJobAuthority.load_indexed_observation
            profile = load_issue56_target_mail_tokenizer_profile()
            analyze = Mock(wraps=profile.analyze)
            frozen = SimpleNamespace(tokenizer_id=profile.tokenizer_id,
                                     profile_fingerprint=profile.profile_fingerprint, analyze=analyze)

            def load(authority, observation_id, **kwargs):
                self.assertNotIn(observation_id, retained_ids)
                reads.append(observation_id)
                return original_load(authority, observation_id, **kwargs)

            output = root / "seeded"
            with patch.object(CompletedIngestionJobAuthority, "load_indexed_observation", load), patch.object(
                builder, "load_issue56_target_mail_tokenizer_profile", return_value=frozen,
            ):
                result = self._seed(old, new, base, output)
            new_ids = {ref[1] for ref in new.snapshot["observation_references"]} - retained_ids
            self.assertEqual(set(reads), new_ids)
            self.assertEqual(len(reads), len(new_ids))
            self.assertTrue(analyze.called)
            self.assertTrue(all("immutable" not in call.args[0] for call in analyze.call_args_list))
            self.assertEqual(before, {path: digest for path, digest in self._hashes(root).items()
                                      if path.parts[0] != "seeded"})
            fresh = root / "fresh"
            fresh_result = builder.build_lookup(directory=new.directory,
                expected_revision_sha256=new.preparation_sha256, output_directory=fresh)
            self.assertEqual(result, fresh_result)
            with sqlite3.connect(output / "source-lookup.sqlite") as seeded, sqlite3.connect(fresh / "source-lookup.sqlite") as rebuilt:
                for table in ("helpers", "postings", "reference_locators", "occurrence_helpers", "attachment_parents"):
                    self.assertEqual(seeded.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall(),
                                     rebuilt.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall(), table)
            expected = builder._lookup_expected(load_issue56_ingestion_revision(
                new.directory, expected_revision_sha256=new.preparation_sha256,
            ), profile)
            lookup = SourceNativeLexicalLookup(directory=output, **expected)
            try:
                self.assertEqual(lookup.manifest["seed_binding"]["reference_prefix_count"], len(retained_ids))
                self.assertEqual(lookup.manifest["lexical_build_mode"], "offline_seeded_job_prefix")
                for family, query in (("mail", "vermillion"), ("document_text", "tangerine")):
                    self.assertTrue(lookup.source_family_lexical_lookup(
                        profile.analyze(query).tokens, source_family=family, timeout_ms=100,
                    ))
                    self.assertEqual(lookup.source_family_lexical_lookup(
                        profile.analyze("obsolete").tokens, source_family=family, timeout_ms=100,
                    ), [])
            finally:
                lookup.close()
            # Ordinary reopen/reuse works; seed always requires a NEW output.
            with self.assertRaisesRegex(ContractValidationError, "new output"):
                self._seed(old, new, base, output)
            reused = builder.build_lookup(directory=new.directory,
                expected_revision_sha256=new.preparation_sha256, output_directory=output)
            self.assertEqual(reused, {**result, "status": "reused"})

    def test_append_from_validated_two_root_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix, _, new, _ = self._fixtures(root)
            base = root / "two-root-lookup"
            builder.build_lookup(directory=prefix.directory, expected_revision_sha256=prefix.preparation_sha256,
                                 output_directory=base)
            output = root / "appended"
            with patch("builtins.print") as printed:
                status = builder.main([
                    "--directory", str(new.directory), "--expected-revision-sha256", new.preparation_sha256,
                    "--output-directory", str(output), "--base-lookup-directory", str(base),
                    "--seed-preparation-directory", str(prefix.directory),
                    "--seed-expected-revision-sha256", prefix.preparation_sha256,
                    "--seed-job-prefix-count", "2",
                ])
            self.assertEqual(status, 0)
            result = json.loads(printed.call_args.args[0])
            self.assertEqual(result["counts"]["references"], len(new.snapshot["observation_references"]))
            self.assertNotIn(str(root), printed.call_args.args[0])

    def test_new_native_attachment_text_parent_and_hash_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix, _, _, base = self._fixtures(root)
            delta_root = root / "attachment-text"
            delta_root.mkdir()
            delta = _source_start_preparation_fixture(
                delta_root, families=("mail",), mail_text="indigo dispatch",
                attachment_content=(b"violet native paragraph\n", "text/plain"),
            )
            parent = next(item for item in delta.observations if item.observation_type == "email_attachment_occurrence")
            child = next(item for item in delta.observations if item.modality == "document" and item.observation_type == "paragraph")
            # The fixture materializer supplies a genuine source ref; add its
            # inventory identity to the synthetic parent, as real mail does.
            parent = replace(parent, payload={**parent.payload, "source_inventory_item_id": "synthetic-native-table"})
            store = Path(delta.snapshot["job_store_bindings"][0]["store_directory"])
            observations = ObservationStore(store, create_directory=False)
            parent_path = observations._store._record_path(parent.observation_id)
            self.assertTrue(parent_path.is_file())
            record_paths = set(observations._store.base_dir.rglob("*.json"))
            self.assertEqual(len(record_paths), len({item.stem for item in record_paths}))
            self.assertEqual(list(observations._store.base_dir.rglob(f"{parent.observation_id}.json")), [parent_path])
            parent_path.write_text(json.dumps(parent.to_dict()))
            self.assertEqual(set(observations._store.base_dir.rglob("*.json")), record_paths)
            self.assertEqual(observations.get(parent.observation_id).to_dict(), parent.to_dict())
            for ref in delta.snapshot["observation_references"]:
                if ref[1] == parent.observation_id:
                    ref[2] = sha256_json(parent.to_dict())
            old = self._compose(root, prefix, delta, "text-old-prepared")
            # Use the base built over the earlier old preparation only for its
            # separately validated root prefix, with its own original pin.
            original_old = SimpleNamespace(directory=root / "old-prepared",
                                            preparation_sha256=_sha256(root / "old-prepared" / "preparation.json"))
            output = root / "text-seeded"
            self._seed(original_old, old, base, output)
            profile = load_issue56_target_mail_tokenizer_profile()
            revision = load_issue56_ingestion_revision(old.directory, expected_revision_sha256=old.preparation_sha256)
            lookup = SourceNativeLexicalLookup(directory=output, **builder._lookup_expected(revision, profile))
            try:
                self.assertIn(sha256_json(child.to_dict()), lookup.source_family_lexical_lookup(
                    profile.analyze("violet").tokens, source_family="mail", timeout_ms=100,
                ))
                self.assertEqual(lookup.helper_for_attachment_asset(child.asset_id)["observation_hash"], sha256_json(parent.to_dict()))
            finally:
                lookup.close()
            # A self-consistent new Observation hash cannot bless false native
            # child/parent lineage. The indexed job checks alone are insufficient.
            changed = replace(child, payload={**child.payload, "lineage": {
                **child.payload["lineage"], "child_content_hash": "sha256:" + "0" * 64,
            }})
            child_path = observations._store._record_path(child.observation_id)
            self.assertTrue(child_path.is_file())
            self.assertEqual(list(observations._store.base_dir.rglob(f"{child.observation_id}.json")), [child_path])
            child_path.write_text(json.dumps(changed.to_dict()))
            self.assertEqual(set(observations._store.base_dir.rglob("*.json")), record_paths)
            self.assertEqual(observations.get(child.observation_id).to_dict(), changed.to_dict())
            for ref in old.snapshot["observation_references"]:
                if ref[1] == child.observation_id:
                    ref[2] = sha256_json(changed.to_dict())
            self._reseal(old)
            before = self._hashes(root)
            with self.assertRaisesRegex(ContractValidationError, "attachment run binding"):
                self._seed(original_old, old, base, root / "text-rejected")
            self.assertEqual(before, self._hashes(root))

    def test_seed_rejects_prefix_conflicts_pins_policy_hash_and_active_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix, old, new, base = self._fixtures(root)
            valid_snapshot = json.loads(json.dumps(new.snapshot))
            manifest_path = base / "source-lookup-manifest.json"
            valid_manifest = manifest_path.read_bytes()
            retained_count = len(prefix.snapshot["observation_references"])
            modes = ("reorder", "hash", "mixed", "missing", "job", "permission", "source", "old-pin", "new-pin",
                     "policy", "profile", "sqlite", "helper", "locator", "wal", "journal", "arguments", "prefix-count")
            for mode in modes:
                with self.subTest(mode=mode):
                    new.snapshot = json.loads(json.dumps(valid_snapshot))
                    self._reseal(new)
                    kwargs = {}
                    sqlite_path = base / "source-lookup.sqlite"
                    saved_sqlite = sqlite_path.read_bytes()  # Tiny synthetic fixture only.
                    if mode == "reorder":
                        refs = new.snapshot["observation_references"]
                        refs[0], refs[1] = refs[1], refs[0]
                    elif mode == "hash":
                        new.snapshot["observation_references"][0][2] = "sha256:" + "0" * 64
                    elif mode == "mixed":
                        refs = new.snapshot["observation_references"]
                        refs[0], refs[retained_count] = refs[retained_count], refs[0]
                    elif mode == "missing":
                        new.snapshot["observation_references"].pop(0)
                    elif mode == "job":
                        new.snapshot["job_store_bindings"][0]["job_fingerprint"] = "sha256:" + "0" * 64
                    elif mode in {"permission", "source"}:
                        revision = load_issue56_ingestion_revision(new.directory, expected_revision_sha256=new.preparation_sha256)
                        jobs = revision.source_records.job_authorities
                        changed = (replace(jobs[0], permission_scope={**dict(jobs[0].permission_scope), "scope_id": "different"})
                                   if mode == "permission" else replace(jobs[0], asset=replace(jobs[0].asset, source_ref={"source_system": "changed"})))
                        revision.source_records.job_authorities = (changed, *jobs[1:])
                        original = builder.load_issue56_ingestion_revision
                        kwargs["_revision"] = (revision, original)
                    elif mode in {"old-pin", "new-pin", "arguments"}:
                        kwargs[{"old-pin": "seed_expected_revision_sha256", "new-pin": "expected_revision_sha256",
                                "arguments": "seed_job_prefix_count"}[mode]] = None if mode == "arguments" else "sha256:" + "0" * 64
                    elif mode == "prefix-count":
                        kwargs["seed_job_prefix_count"] = 3
                    elif mode in {"policy", "profile"}:
                        manifest = json.loads(valid_manifest)
                        manifest.pop("manifest_fingerprint")
                        manifest["token_surface_policy_id" if mode == "policy" else "tokenizer_profile_fingerprint"] = "incompatible"
                        manifest_path.write_text(json.dumps({**manifest, "manifest_fingerprint": sha256_json(manifest)}))
                    elif mode == "sqlite":
                        with sqlite_path.open("ab") as stream:
                            stream.write(b"tampered")
                    elif mode in {"helper", "locator"}:
                        with sqlite3.connect(sqlite_path) as db:
                            db.execute("UPDATE helpers SET permission_scope_json = '{}'" if mode == "helper"
                                       else "UPDATE reference_locators SET job_fingerprint = 'changed'")
                        manifest = json.loads(valid_manifest)
                        manifest.pop("manifest_fingerprint")
                        manifest["sqlite_sha256"] = _sha256(sqlite_path)
                        manifest_path.write_text(json.dumps({**manifest, "manifest_fingerprint": sha256_json(manifest)}))
                    elif mode in {"wal", "journal"}:
                        (base / ("source-lookup.sqlite-" + mode)).write_bytes(b"active")
                    self._reseal(new)
                    output = root / "rejected"
                    before = self._hashes(root)
                    try:
                        if "_revision" in kwargs:
                            revision, original = kwargs.pop("_revision")
                            with patch.object(builder, "load_issue56_ingestion_revision",
                                side_effect=lambda path, **kw: revision if path == new.directory else original(path, **kw)):
                                with self.assertRaises(ContractValidationError):
                                    self._seed(old, new, base, output, **kwargs)
                        else:
                            with self.assertRaises((ContractValidationError, builder.Issue56SealedSourceLoadError)):
                                self._seed(old, new, base, output, **kwargs)
                        self.assertFalse(output.exists())
                        self.assertEqual(before, self._hashes(root))
                        self.assertEqual(list(root.glob(".source-lookup-*")), [])
                    finally:
                        for suffix in ("-wal", "-journal"):
                            (base / ("source-lookup.sqlite" + suffix)).unlink(missing_ok=True)
                        sqlite_path.write_bytes(saved_sqlite)
                        manifest_path.write_bytes(valid_manifest)


class PersistedSourceLocatorTests(unittest.TestCase):
    class NoEnumeration(list):
        def __iter__(self):
            raise AssertionError("query must not enumerate sealed references")

        def __getitem__(self, key):
            raise AssertionError("query must not traverse sealed references")

        def index(self, *args):
            raise AssertionError("query must not seek a source locator linearly")

    def _admit(self, fixture, output):
        for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
            shutil.copyfile(output / name, fixture.directory / name)
        revision = load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        records = revision.source_records
        records.observation_references = self.NoEnumeration(records.observation_references)
        return records

    def _build(self, fixture, output, **kwargs):
        return builder.build_lookup(
            directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            output_directory=output, **kwargs,
        )

    def test_multiple_mail_and_independent_text_queries_reopen_without_scans_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root, families=("mail", "mail_other", "document_text"),
                mail_text="cerulean\n\nState: pending.\n\nvermillion\n\nOwner: review team.",
                document_text="# cerulean\n\nState: pending.\n\n# vermillion\n\nOwner: review team.\n",
            )
            output = root / "lookup"
            self._build(fixture, output)
            before = {path.name: _sha256(path) for path in output.iterdir()}
            profile = load_issue56_target_mail_tokenizer_profile()
            for reopen in range(2):
                records = self._admit(fixture, output)
                lookup = records.runtime_store
                sql = []
                lookup._connection.set_trace_callback(sql.append)
                try:
                    for job_index, authority in enumerate(records.job_authorities):
                        family = "document_text" if job_index == 2 else "mail"
                        selector = _authorized_mail_selector_for_asset(authority.asset)
                        for term, context in (("cerulean", "State: pending."), ("vermillion", "Owner: review team.")):
                            with self.subTest(reopen=reopen, family=family, job=job_index, term=term):
                                delivered, neighbors = [], []
                                def matched(item, scope):
                                    if family == "mail":
                                        return _source_mail_observation_match(
                                            item, query_terms=set(profile.analyze(term).tokens),
                                            required_terms=(term,), protected_query_tokens=set(),
                                            tokenizer_profile=profile,
                                        ) is not None
                                    return term in (item.text or "")
                                with (
                                    source_evidence_query_terms_scope(profile.analyze(term).tokens),
                                    patch.object(CompletedIngestionJobAuthority, "open_reader", side_effect=AssertionError("full job reader")),
                                    patch.object(Path, "write_bytes", side_effect=AssertionError("query writes")),
                                    patch.object(Path, "write_text", side_effect=AssertionError("query writes")),
                                ):
                                    scan = records.scan_authorized_observations(
                                        source_family=family,
                                        source_scope_ids=(authority.permission_scope["scope_id"],) if family == "document_text" else (),
                                        mail_import_session_id=selector, max_observations=32,
                                        deadline_monotonic=time.monotonic() + .5,
                                        observation_callback=lambda item, scope: delivered.append((item, scope)) or True,
                                        context_anchor_callback=matched,
                                        context_callback=lambda anchor, item, scope: neighbors.append((anchor, item, scope)) or True,
                                    )
                                self.assertFalse(scan.complete)
                                self.assertEqual(scan.stop_reason, "indexed_shortlist")
                                self.assertLessEqual(scan.scanned_observation_count, 32)
                                anchors = [item for item, scope in delivered if matched(item, scope)]
                                self.assertTrue(anchors)
                                self.assertTrue(any(context in (item.text or "") for _, item, _ in neighbors))
                                self.assertTrue(all(item.asset_id == authority.asset.asset_id for item, _ in delivered))
                                self.assertTrue(all(item.asset_id == authority.asset.asset_id for _, item, _ in neighbors))
                                if family == "mail":
                                    parent = next(item for item, _ in delivered if item.observation_type == "email_message")
                                    self.assertEqual(parent.location["message_occurrence_id"], anchors[0].location["message_occurrence_id"])
                                    self.assertLess(delivered.index((parent, selector)), delivered.index((anchors[0], selector)))
                                    occurrence = parent.location["message_occurrence_id"]
                                    first = lookup.helpers_for_occurrence(occurrence, limit=1)
                                    second = lookup.helpers_for_occurrence(occurrence, after_id=first[0]["observation_id"], limit=1)
                                    self.assertTrue(first and second)
                                    self.assertGreater(second[0]["observation_id"], first[0]["observation_id"])
                    self.assertFalse(any(statement.lstrip().split()[0].upper() in {
                        "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP",
                    } for statement in sql))
                finally:
                    lookup.close()
            self.assertEqual(before, {path.name: _sha256(path) for path in output.iterdir()})
            with patch.object(CompletedIngestionJobAuthority, "load_indexed_observation", side_effect=AssertionError("reuse must not hydrate")):
                self.assertEqual(self._build(fixture, output)["status"], "reused")

    def test_caps_misses_legacy_and_keyed_locator_hydration_are_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root, mail_text="cerulean\n\nState: pending.",
                attachment_csv="Label,State\nsynthetic-row,pending\n",
            )
            output = root / "lookup"
            self._build(fixture, output)
            records = self._admit(fixture, output)
            lookup = records.runtime_store
            authority = records.job_authorities[0]
            kwargs = {"source_family": "mail", "mail_import_session_id": _authorized_mail_selector_for_asset(authority.asset),
                      "max_observations": 32, "observation_callback": Mock(return_value=True)}
            try:
                for term, cap, deadline, reason in (
                    ("cerulean", 1, None, "observation_limit"),
                    ("cerulean", 32, 0, "deadline"),
                    ("unrelatedmissing", 32, None, "indexed_shortlist_miss"),
                ):
                    with self.subTest(reason=reason), source_evidence_query_terms_scope((term,)):
                        kwargs["observation_callback"].reset_mock()
                        scan = records.scan_authorized_observations(**{**kwargs, "max_observations": cap, "deadline_monotonic": deadline})
                        self.assertFalse(scan.complete)
                        self.assertEqual(scan.stop_reason, reason)
                        self.assertLessEqual(scan.scanned_observation_count, cap)
                        kwargs["observation_callback"].assert_not_called()
                scan = records.scan_authorized_observations(**kwargs)
                self.assertFalse(scan.complete)
                self.assertEqual(scan.stop_reason, "indexed_query_terms_unavailable")
                # Native rows are not lexical helpers, but their sealed locators
                # must hydrate by hash/ID without enumerating any source list.
                row = next(item for item in fixture.observations if item.observation_type == "table_row")
                self.assertIsNone(lookup.get_helper(row.observation_id))
                self.assertEqual(records.get_observation(row.observation_id), row)
                self.assertEqual(records.observation_for_hash(sha256_json(row.to_dict())), row)
                self.assertIsNone(records.observation_for_hash("sha256:" + "0" * 64))
            finally:
                lookup.close()
            # Simulate a valid legacy artifact: no inline metadata migration,
            # no full-source scan to make a miss/parent lookup look complete.
            manifest_path = output / "source-lookup-manifest.json"
            core = json.loads(manifest_path.read_text())
            for key in ("manifest_fingerprint", "locator_policy_id", "locator_count"):
                core.pop(key)
            with sqlite3.connect(output / "source-lookup.sqlite") as db:
                db.execute("DROP TABLE reference_locators")
                db.execute("DROP TABLE occurrence_helpers")
            core["sqlite_sha256"] = _sha256(output / "source-lookup.sqlite")
            manifest_path.write_text(json.dumps({**core, "manifest_fingerprint": sha256_json(core)}))
            records = self._admit(fixture, output)
            try:
                self.assertFalse(records.runtime_store.has_keyed_source_metadata)
                existing = next(item for item in fixture.observations if item.observation_type == "email_message")
                self.assertEqual(records.get_observation(existing.observation_id), existing)
                self.assertEqual(records.observation_for_hash(sha256_json(existing.to_dict())), existing)
                self.assertIsNone(records.runtime_store.get_helper(row.observation_id))
                for missing_id in ("synthetic-missing-observation", row.observation_id):
                    with self.subTest(legacy_missing_id=missing_id):
                        with self.assertRaisesRegex(ContractValidationError, "source reference is unavailable"):
                            records.get_observation(missing_id)
                for missing_hash in ("sha256:" + "0" * 64, sha256_json(row.to_dict())):
                    with self.subTest(legacy_missing_hash=missing_hash):
                        self.assertIsNone(records.observation_for_hash(missing_hash))
                with source_evidence_query_terms_scope(("cerulean",)):
                    scan = records.scan_authorized_observations(**kwargs)
                self.assertFalse(scan.complete)
                self.assertEqual(scan.stop_reason, "source_parent_binding_unresolved")
                self.assertEqual(records.runtime_store.helpers_for_occurrence("missing"), [])
                with self.assertRaisesRegex(ContractValidationError, "offline extension"):
                    self._build(fixture, output)
            finally:
                records.runtime_store.close()

    def test_clone_adds_locators_without_retokenizing_or_rebuilding_missing_postings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root, mail_text="cerulean", document_text="# vermillion\n")
            base = root / "base"
            self._build(fixture, base)
            with sqlite3.connect(base / "source-lookup.sqlite") as db:
                db.execute("DROP TABLE reference_locators")
                db.execute("DROP TABLE occurrence_helpers")
                db.execute("DELETE FROM postings WHERE token = 'cerulean'")
                postings = db.execute("SELECT * FROM postings ORDER BY token,source_family,observation_hash").fetchall()
            path = base / "source-lookup-manifest.json"
            core = json.loads(path.read_text())
            for key in ("manifest_fingerprint", "locator_policy_id", "locator_count"):
                core.pop(key)
            core["counts"]["postings"] = len(postings)
            core["sqlite_sha256"] = _sha256(base / "source-lookup.sqlite")
            path.write_text(json.dumps({**core, "manifest_fingerprint": sha256_json(core)}))
            before = {item.name: _sha256(item) for item in base.iterdir()}
            profile = load_issue56_target_mail_tokenizer_profile()
            frozen = SimpleNamespace(tokenizer_id=profile.tokenizer_id, profile_fingerprint=profile.profile_fingerprint,
                                     analyze=Mock(side_effect=AssertionError("clone retokenized")))
            output = root / "extended"
            with patch.object(builder, "load_issue56_target_mail_tokenizer_profile", return_value=frozen):
                self._build(fixture, output, base_lookup_directory=base)
            frozen.analyze.assert_not_called()
            self.assertEqual(before, {item.name: _sha256(item) for item in base.iterdir()})
            with sqlite3.connect(output / "source-lookup.sqlite") as db:
                self.assertEqual(postings, db.execute("SELECT * FROM postings ORDER BY token,source_family,observation_hash").fetchall())
                self.assertEqual(db.execute("SELECT COUNT(*) FROM reference_locators").fetchone()[0], len(fixture.snapshot["observation_references"]))
            records = self._admit(fixture, output)
            try:
                self.assertEqual(records.runtime_store.manifest["lexical_build_mode"], "retained_verified_postings")
                self.assertEqual(records.runtime_store.source_family_lexical_lookup(("cerulean",), source_family="mail", timeout_ms=100), [])
            finally:
                records.runtime_store.close()

    def test_keyed_neighbors_reject_tamper_permissions_and_stop_under_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root, families=("document_text",), document_text="# cerulean\n\nState: pending.\n",
            )
            output = root / "lookup"
            self._build(fixture, output)
            records = self._admit(fixture, output)
            lookup = records.runtime_store
            authority = records.job_authorities[0]
            anchor, neighbor = fixture.observations
            callback = Mock(return_value=True)
            kwargs = {"anchor": anchor, "authority": authority,
                      "source_scope": authority.permission_scope["scope_id"],
                      "max_observations": 1, "deadline_monotonic": None,
                      "observation_callback": callback}
            try:
                with patch.object(authority.observation_store, "get", wraps=authority.observation_store.get) as read:
                    scan = records.scan_neighbor_context(**kwargs)
                self.assertEqual(scan.scanned_observation_count, 1)
                self.assertEqual(read.call_count, 1)
                self.assertFalse(scan.complete)
                for changed in (
                    replace(neighbor, text="tampered"),
                    replace(neighbor, permission_scope={**dict(authority.permission_scope), "scope_id": "other_scope"}),
                ):
                    with self.subTest(tamper=changed.text), patch.object(authority.observation_store, "get", return_value=changed):
                        with self.assertRaisesRegex(ContractValidationError, "Observation binding is invalid"):
                            records.scan_neighbor_context(**kwargs)
                callback.reset_mock()
                for exhausted in ({"max_observations": 0}, {"deadline_monotonic": 0}):
                    with patch.object(authority.observation_store, "get", side_effect=AssertionError("read after cap")):
                        scan = records.scan_neighbor_context(**{**kwargs, **exhausted})
                    self.assertFalse(scan.complete)
                    self.assertEqual(scan.scanned_observation_count, 0)
                callback.assert_not_called()
                with self.assertRaisesRegex(ContractValidationError, "anchor permission mismatch"):
                    records.scan_neighbor_context(**{**kwargs, "source_scope": "denied_scope"})
            finally:
                lookup.close()
            # A hash-valid SQLite pair may not claim the keyed capability after
            # its lookup index disappears. Reject at reopen, not during queries.
            with sqlite3.connect(output / "source-lookup.sqlite") as db:
                db.execute("DROP INDEX occurrence_helpers_binding")
            path = output / "source-lookup-manifest.json"
            core = json.loads(path.read_text())
            core.pop("manifest_fingerprint")
            core["sqlite_sha256"] = _sha256(output / "source-lookup.sqlite")
            path.write_text(json.dumps({**core, "manifest_fingerprint": sha256_json(core)}))
            with self.assertRaisesRegex(ContractValidationError, "locator indexes are invalid"):
                self._admit(fixture, output)

    def test_parent_callback_expiry_prevents_child_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root, families=("mail",), mail_text="cerulean")
            output = root / "lookup"
            self._build(fixture, output)
            records = self._admit(fixture, output)
            lookup = records.runtime_store
            body = next(item for item in fixture.observations if item.observation_type == "email_body_segment")
            parent = next(item for item in fixture.observations if item.observation_type == "email_message")
            clock, delivered = [10.0], []

            def callback(item, scope):
                delivered.append(item.observation_id)
                self.assertEqual(item.observation_id, parent.observation_id)
                clock[0] = 12.0
                return True

            try:
                with (
                    source_evidence_query_terms_scope(("cerulean",)),
                    patch("formowl_mail.issue56_sealed_source.time.monotonic", side_effect=lambda: clock[0]),
                    patch.object(lookup, "source_family_lexical_lookup", return_value=[sha256_json(body.to_dict())]),
                ):
                    scan = records.scan_authorized_observations(
                        source_family="mail", max_observations=8, deadline_monotonic=11.0,
                        mail_import_session_id=records.authorized_mail_import_session_ids[0],
                        observation_callback=callback,
                    )
                self.assertEqual(delivered, [parent.observation_id])
                self.assertFalse(scan.complete)
                self.assertEqual(scan.stop_reason, "deadline")
                self.assertEqual(scan.scanned_observation_count, 2)
            finally:
                lookup.close()


class SourceNativeLexicalAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_builder_pair_admitted_on_cloned_source_start_serves_both_families(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            source_root.mkdir()
            fixture = _source_start_preparation_fixture(source_root)
            original_hashes = {
                path.relative_to(source_root): _sha256(path)
                for path in source_root.rglob("*") if path.is_file()
            }
            output = root / "lookup"
            built = builder.build_lookup(
                directory=fixture.directory,
                expected_revision_sha256=fixture.preparation_sha256,
                output_directory=output,
            )
            self.assertEqual(built["status"], "created")
            output_hashes = {path.name: _sha256(path) for path in output.iterdir()}
            clone = shutil.copytree(fixture.directory, root / "admitted")
            for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
                shutil.copy2(output / name, clone / name)
            cloned_fixture = SimpleNamespace(**{**vars(fixture), "directory": clone})
            helper = composition.ProjectionIndependentSourceMcpTests(methodName="runTest")
            # _compose reloads through load_issue56_ingestion_revision with the
            # original expected byte hash; no manifest or snapshot is resealed.
            revision, runtime, principal, actor = await helper._compose(root, cloned_fixture)
            lookup = revision.source_records.runtime_store
            try:
                self.assertIsInstance(lookup, SourceNativeLexicalLookup)
                manifest = json.loads((output / "source-lookup-manifest.json").read_bytes())
                self.assertEqual(revision.safe_binding["source_lexical_lookup"], {
                    "artifact_id": manifest["artifact_id"],
                    "manifest_fingerprint": manifest["manifest_fingerprint"],
                    "sqlite_sha256": manifest["sqlite_sha256"],
                    "source_families": manifest["source_families"],
                    "counts": manifest["counts"],
                })
                self.assertEqual(len(revision.source_records.job_authorities), 2)
                parent = next(item for item in fixture.observations
                              if item.observation_type == "email_message")
                body = next(item for item in fixture.observations
                            if item.observation_type == "email_body_segment")
                query_tokens = fixture.runtime.tokenizer_profile.analyze("written owner approval").tokens
                hits = lookup.source_family_lexical_lookup(
                    query_tokens, source_family="mail", limit=256, timeout_ms=100,
                )
                self.assertIn(sha256_json(body.to_dict()), hits)
                self.assertNotIn(sha256_json(parent.to_dict()), hits)
                selector = revision.source_records.authorized_mail_import_session_ids[0]
                bounded_ids = []
                with source_evidence_query_terms_scope(query_tokens):
                    bounded = revision.source_records.scan_authorized_observations(
                        source_family="mail", mail_import_session_id=selector, max_observations=1,
                        observation_callback=lambda observation, scope: (
                            bounded_ids.append(observation.observation_id) or True
                        ),
                    )
                self.assertFalse(bounded.complete)
                self.assertEqual(bounded.stop_reason, "observation_limit")
                self.assertEqual(bounded.scanned_observation_count, 1)
                self.assertNotIn(body.observation_id, bounded_ids)
                hydration_calls = []
                emitted_ids = []
                original_load = CompletedIngestionJobAuthority.load_indexed_observation
                original_scan = revision.source_records.scan_authorized_observations

                def keyed_load(authority, observation_id, **kwargs):
                    observation = original_load(authority, observation_id, **kwargs)
                    hydration_calls.append((authority.job_fingerprint, observation_id, kwargs))
                    self.assertEqual(dict(observation.permission_scope), dict(authority.permission_scope))
                    return observation

                def traced_scan(**kwargs):
                    callback = kwargs["observation_callback"]

                    def traced_callback(observation, scope):
                        emitted_ids.append(observation.observation_id)
                        return callback(observation, scope)

                    return original_scan(**{**kwargs, "observation_callback": traced_callback})

                with (
                    patch.object(CompletedIngestionJobAuthority, "load_indexed_observation", keyed_load),
                    patch.object(revision.source_records, "scan_authorized_observations", traced_scan),
                    patch.object(lookup, "source_family_lexical_lookup",
                                 wraps=lookup.source_family_lexical_lookup) as lexical,
                    patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                    TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                ):
                    for family, kind in (("mail", "email_body_segment"), ("document_text", "paragraph")):
                        with self.subTest(source_family=family):
                            hydration_calls.clear()
                            emitted_ids.clear()
                            lexical.reset_mock()
                            result = helper._post(client, family=(family,))
                            self.assertFalse(result["isError"], result)
                            self.assertNotIn(str(root), json.dumps(result))
                            payload = result["structuredContent"]["data"]
                            self.assertEqual(payload["status"], "ok", payload)
                            self.assertEqual(payload["coverage"]["status"], "incomplete")
                            self.assertTrue(lexical.called)
                            self.assertEqual({call.kwargs["source_family"]
                                              for call in lexical.call_args_list}, {family})
                            observation = next(item for item in fixture.observations
                                               if item.observation_type == kind)
                            observation_hash = sha256_json(observation.to_dict())
                            authority = next(item for item in revision.source_records.job_authorities
                                             if item.asset.asset_id == observation.asset_id)
                            self.assertIn((authority.job_fingerprint, observation.observation_id, {
                                "expected_observation_hash": observation_hash,
                                "expected_job_fingerprint": authority.job_fingerprint,
                            }), hydration_calls)
                            evidence = next(item for item in payload["evidence"]
                                            if item["citation_hash"] == observation_hash)
                            self.assertIn("written owner approval", evidence["snippet"])
                            self.assertEqual(evidence["occurrence_lineage_fingerprint"],
                                source_occurrence_lineage_from_observation(
                                    observation, authorized_source=revision.authorized_source,
                                ).lineage_fingerprint)
                            self.assertEqual(evidence["revision_binding"], {
                                key: revision.safe_binding[key] for key in (
                                    "source_authority_fingerprint", "source_session_binding_fingerprint",
                                )
                            })
                            if family == "mail":
                                parent = next(item for item in fixture.observations
                                              if item.observation_type == "email_message")
                                self.assertLess(emitted_ids.index(parent.observation_id),
                                                emitted_ids.index(observation.observation_id))
                                self.assertIn((authority.job_fingerprint, parent.observation_id, {
                                    "expected_observation_hash": sha256_json(parent.to_dict()),
                                    "expected_job_fingerprint": authority.job_fingerprint,
                                }), hydration_calls)
                                self.assertEqual(evidence["email_message_id"], stable_resource_contract_id(
                                    "emailmsg", "EmailMessage",
                                    {"message_fingerprint": parent.payload["message_fingerprint"]},
                                ))
            finally:
                await runtime.aclose()
                if lookup is not None:
                    lookup.close()
            self.assertEqual(original_hashes, {
                path.relative_to(source_root): _sha256(path)
                for path in source_root.rglob("*") if path.is_file()
            })
            self.assertEqual(output_hashes, {path.name: _sha256(path) for path in output.iterdir()})
            self.assertEqual({**{
                path.relative_to(fixture.directory): _sha256(path)
                for path in fixture.directory.rglob("*") if path.is_file()
            }, **{Path(name): digest for name, digest in output_hashes.items()}}, {
                path.relative_to(clone): _sha256(path)
                for path in clone.rglob("*") if path.is_file()
            })


if __name__ == "__main__":
    unittest.main()
