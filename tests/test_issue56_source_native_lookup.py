from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from starlette.testclient import TestClient

from formowl_contract import ContractValidationError, sha256_json, stable_resource_contract_id
from formowl_core import load_issue56_target_mail_tokenizer_profile
from formowl_ingestion.extractors.mail import fixture as mail_fixture
from formowl_mail.import_workflow import CompletedIngestionJobAuthority
from formowl_mail.issue56_sealed_source import SourceNativeLexicalLookup
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


class SourceNativeLexicalBuilderTests(unittest.TestCase):
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
            path = store / "ingestion" / "observations" / f"{reference[1]}.json"
            raw = json.loads(path.read_bytes())
            raw["text"] = "GENERIC-TAMPERED-002"
            path.write_text(json.dumps(raw))
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
