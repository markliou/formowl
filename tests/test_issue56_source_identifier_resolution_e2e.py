from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    Observation,
    PermissionScope,
    sha256_json,
)
from formowl_core import (
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    build_ascii_identifier_regex_tokenizer_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_graph.resolution import (
    resolve_exact_protected_identifier_candidates,
)
from formowl_graph.storage import CandidateMentionStore
from formowl_mail.candidates import (
    IdentifierOccurrenceOverflowError,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SourceIdentifierIdentityScope,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    extract_and_store_source_bound_identifier_mentions,
    extract_source_bound_identifier_mentions,
)

CREATED_AT = "2026-08-19T10:00:00+00:00"
TENANT_ID = "tenant_issue56"
WORKSPACE_ID = "workspace_issue56"
EXTRACTOR_RUN_ID = "run_issue56_identifier_candidates_v1"


class Issue56SourceIdentifierResolutionE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_issue56_target_mail_tokenizer_profile()

    def test_shared_identifier_cross_thread_round_trips_and_resolves_candidate_only(
        self,
    ) -> None:
        protected_identifier = "PO-9001"
        observations = [
            _observation(
                "obs_thread_alpha",
                message_occurrence_id="message_occurrence_alpha",
                thread_fingerprint=sha256_json("thread-alpha"),
                text=f"採購單 {protected_identifier} 已由第一個討論串提出。",
                permission_scope=PermissionScope.project("project_shared"),
                private_locator="/private/export/thread-alpha/message.eml",
            ),
            _observation(
                "obs_thread_beta",
                message_occurrence_id="message_occurrence_beta",
                thread_fingerprint=sha256_json("thread-beta"),
                text=f"第二個討論串再次引用 {protected_identifier} 並要求覆核。",
                permission_scope=PermissionScope.project("project_shared"),
                private_locator="/private/export/thread-beta/message.eml",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            stored = extract_and_store_source_bound_identifier_mentions(
                observations,
                candidate_mention_store=CandidateMentionStore(temp_dir),
                identity_scope=_identity_scope(),
                extractor_run_id=EXTRACTOR_RUN_ID,
                created_at=CREATED_AT,
            )
            round_tripped = CandidateMentionStore(temp_dir).list()

        self.assertEqual(stored.occurrence_count, 2)
        self.assertEqual(
            [item.to_dict() for item in round_tripped],
            [item.to_dict() for item in stored.candidate_mentions],
        )
        self.assertEqual(
            {item.metadata["source_observation_fingerprint"] for item in stored.candidate_mentions},
            {sha256_json(observation.to_dict()) for observation in observations},
        )
        self.assertEqual(
            len(
                {
                    item.metadata["message_occurrence_fingerprint"]
                    for item in stored.candidate_mentions
                }
            ),
            2,
        )
        for mention in stored.candidate_mentions:
            self.assertEqual(
                mention.metadata["tokenizer_profile_fingerprint"],
                ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
            )
            self.assertEqual(
                mention.metadata["extraction_policy_fingerprint"],
                SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
            )
            self.assertFalse(mention.metadata["canonical_write_allowed"])
            self.assertTrue(mention.metadata["candidate_only"])

        resolution = resolve_exact_protected_identifier_candidates(stored.candidate_mentions)
        self.assertEqual(resolution.source_mention_count, 2)
        self.assertEqual(resolution.candidate_count, 1)
        candidate = resolution.candidates[0]
        self.assertEqual(
            candidate.exact_protected_token_hash,
            sha256_json(protected_identifier.casefold()),
        )
        self.assertEqual(
            {scope.source_observation_id for scope in candidate.occurrence_scopes},
            {"obs_thread_alpha", "obs_thread_beta"},
        )
        self.assertEqual(candidate.status, "pending_review")
        self.assertTrue(candidate.requires_review)
        self.assertFalse(candidate.canonical_merge_performed)
        self.assertFalse(candidate.canonical_write_allowed)
        rendered = json.dumps(
            {
                "batch": stored.to_dict(),
                "resolution": resolution.to_dict(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(protected_identifier, rendered)
        self.assertNotIn("/private/export", rendered)

    def test_more_than_twenty_four_identifiers_and_repeated_occurrences_are_preserved(
        self,
    ) -> None:
        identifiers = [f"CASE-{index:04d}" for index in range(1, 31)]
        repeated = identifiers[0]
        observation = _observation(
            "obs_many_identifiers",
            message_occurrence_id="message_occurrence_many",
            thread_fingerprint=sha256_json("thread-many"),
            text="識別碼清單：" + " ".join([*identifiers, repeated]),
            permission_scope=PermissionScope.project("project_many"),
        )

        batch = extract_source_bound_identifier_mentions(
            [observation],
            identity_scope=_identity_scope(),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )

        self.assertEqual(batch.occurrence_count, 31)
        self.assertEqual(len(batch.candidate_mentions), 31)
        self.assertEqual(
            len({mention.candidate_mention_id for mention in batch.candidate_mentions}),
            31,
        )
        repeated_hash = sha256_json(repeated.casefold())
        self.assertEqual(
            sum(mention.text_hash == repeated_hash for mention in batch.candidate_mentions),
            2,
        )
        resolution = resolve_exact_protected_identifier_candidates(batch.candidate_mentions)
        self.assertEqual(resolution.source_mention_count, 31)
        self.assertEqual(resolution.candidate_count, 30)
        repeated_candidate = next(
            candidate
            for candidate in resolution.candidates
            if candidate.exact_protected_token_hash == repeated_hash
        )
        self.assertEqual(len(repeated_candidate.occurrence_scopes), 2)

    def test_explicit_cap_blocks_before_any_candidate_store_write(self) -> None:
        observation = _observation(
            "obs_overflow",
            message_occurrence_id="message_occurrence_overflow",
            thread_fingerprint=sha256_json("thread-overflow"),
            text=" ".join(f"ITEM-{index:04d}" for index in range(25)),
            permission_scope=PermissionScope.project("project_overflow"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            store = CandidateMentionStore(temp_dir)
            with self.assertRaisesRegex(
                IdentifierOccurrenceOverflowError,
                "source_bound_identifier_occurrence_overflow",
            ) as context:
                extract_and_store_source_bound_identifier_mentions(
                    [observation],
                    candidate_mention_store=store,
                    identity_scope=_identity_scope(),
                    extractor_run_id=EXTRACTOR_RUN_ID,
                    tokenizer_profile=self.profile,
                    created_at=CREATED_AT,
                    max_identifier_occurrences=24,
                )
            self.assertEqual(context.exception.occurrence_count, 25)
            self.assertEqual(context.exception.occurrence_limit, 24)
            self.assertEqual(store.list(), [])

    def test_permission_boundaries_isolate_same_exact_identifier(self) -> None:
        observations = [
            _observation(
                "obs_permission_alpha",
                message_occurrence_id="message_occurrence_permission_alpha",
                thread_fingerprint=sha256_json("thread-permission-alpha"),
                text="受限專案引用 SHARE-771。",
                permission_scope=PermissionScope.project("project_alpha"),
            ),
            _observation(
                "obs_permission_beta",
                message_occurrence_id="message_occurrence_permission_beta",
                thread_fingerprint=sha256_json("thread-permission-beta"),
                text="另一權限邊界也引用 SHARE-771。",
                permission_scope=PermissionScope.project("project_beta"),
            ),
        ]

        batch = extract_source_bound_identifier_mentions(
            observations,
            identity_scope=_identity_scope(),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        resolution = resolve_exact_protected_identifier_candidates(batch.candidate_mentions)

        self.assertEqual(resolution.source_mention_count, 2)
        self.assertEqual(resolution.candidate_count, 2)
        self.assertEqual(
            len({candidate.permission_boundary_fingerprint for candidate in resolution.candidates}),
            2,
        )
        self.assertEqual(
            len({candidate.candidate_resolution_id for candidate in resolution.candidates}),
            2,
        )
        other_workspace = extract_source_bound_identifier_mentions(
            [observations[0]],
            identity_scope=_identity_scope(workspace_id="workspace_issue56_other"),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        self.assertNotEqual(
            batch.candidate_mentions[0].candidate_mention_id,
            other_workspace.candidate_mentions[0].candidate_mention_id,
        )
        other_resolution = resolve_exact_protected_identifier_candidates(
            other_workspace.candidate_mentions
        )
        self.assertNotIn(
            other_resolution.candidates[0].candidate_resolution_id,
            {candidate.candidate_resolution_id for candidate in resolution.candidates},
        )

    def test_reordered_inputs_are_deterministic_and_tamper_fails_closed(self) -> None:
        observations = [
            _observation(
                "obs_deterministic_alpha",
                message_occurrence_id="message_occurrence_deterministic_alpha",
                thread_fingerprint=sha256_json("thread-deterministic-alpha"),
                text="追蹤 DET-101 與 DET-202。",
                permission_scope=PermissionScope.project("project_deterministic"),
            ),
            _observation(
                "obs_deterministic_beta",
                message_occurrence_id="message_occurrence_deterministic_beta",
                thread_fingerprint=sha256_json("thread-deterministic-beta"),
                text="另一封郵件再次引用 DET-101。",
                permission_scope=PermissionScope.project("project_deterministic"),
            ),
        ]

        forward = extract_source_bound_identifier_mentions(
            observations,
            identity_scope=_identity_scope(),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        reverse = extract_source_bound_identifier_mentions(
            list(reversed(observations)),
            identity_scope=_identity_scope(),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        forward_resolution = resolve_exact_protected_identifier_candidates(
            forward.candidate_mentions
        )
        reverse_resolution = resolve_exact_protected_identifier_candidates(
            tuple(reversed(reverse.candidate_mentions))
        )

        self.assertEqual(forward.batch_fingerprint, reverse.batch_fingerprint)
        self.assertEqual(forward.to_dict(), reverse.to_dict())
        self.assertEqual(
            forward_resolution.to_dict(),
            reverse_resolution.to_dict(),
        )

        tampered_payload = deepcopy(forward.candidate_mentions[0].to_dict())
        tampered_payload["metadata"]["permission_boundary_fingerprint"] = "sha256:" + "0" * 64
        tampered = CandidateMention.from_dict(tampered_payload)
        with self.assertRaisesRegex(
            ContractValidationError,
            "permission boundary binding mismatch",
        ):
            resolve_exact_protected_identifier_candidates([tampered])

    def test_workspace_only_is_deterministic_omits_tenant_and_never_cross_merges(
        self,
    ) -> None:
        observation = _observation(
            "obs_workspace_only",
            message_occurrence_id="message_occurrence_workspace_only",
            thread_fingerprint=sha256_json("thread-workspace-only"),
            text="工作區核准的識別碼 SCOPE-101。",
            permission_scope=PermissionScope.project("project_scope"),
        )
        workspace_scope = _identity_scope(
            mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
            tenant_id=None,
        )
        first = extract_source_bound_identifier_mentions(
            [observation],
            identity_scope=workspace_scope,
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        second = extract_source_bound_identifier_mentions(
            [observation],
            identity_scope=workspace_scope,
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertNotIn('"tenant_id"', json.dumps(first.to_dict(), sort_keys=True))

        tenant_batch = extract_source_bound_identifier_mentions(
            [observation],
            identity_scope=_identity_scope(),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        cross_mode = resolve_exact_protected_identifier_candidates(
            [*first.candidate_mentions, *tenant_batch.candidate_mentions]
        )
        self.assertEqual(cross_mode.candidate_count, 2)
        self.assertEqual(
            {candidate.identity_scope_mode for candidate in cross_mode.candidates},
            {
                TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
                WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
            },
        )
        workspace_candidate = next(
            candidate
            for candidate in cross_mode.candidates
            if candidate.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        )
        self.assertNotIn("tenant_id", workspace_candidate.to_dict())

        other_workspace = extract_source_bound_identifier_mentions(
            [observation],
            identity_scope=_identity_scope(
                mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
                tenant_id=None,
                workspace_id="workspace_issue56_other",
            ),
            extractor_run_id=EXTRACTOR_RUN_ID,
            tokenizer_profile=self.profile,
            created_at=CREATED_AT,
        )
        cross_workspace = resolve_exact_protected_identifier_candidates(
            [*first.candidate_mentions, *other_workspace.candidate_mentions]
        )
        self.assertEqual(cross_workspace.candidate_count, 2)

    def test_legacy_raw_tenant_api_and_workspace_only_tenant_fabrication_are_rejected(
        self,
    ) -> None:
        observation = _observation(
            "obs_legacy_api",
            message_occurrence_id="message_occurrence_legacy_api",
            thread_fingerprint=sha256_json("thread-legacy-api"),
            text="舊 API 的 LEGACY-101 不得降級。",
            permission_scope=PermissionScope.project("project_legacy"),
        )
        with self.assertRaisesRegex(TypeError, "tenant_id"):
            extract_source_bound_identifier_mentions(
                [observation],
                tenant_id=TENANT_ID,  # type: ignore[call-arg]
                workspace_id=WORKSPACE_ID,  # type: ignore[call-arg]
                extractor_run_id=EXTRACTOR_RUN_ID,
                tokenizer_profile=self.profile,
                created_at=CREATED_AT,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "forbids tenant_id fabrication",
        ):
            _identity_scope(
                mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
                tenant_id=TENANT_ID,
            )

    def test_missing_occurrence_lineage_and_ascii_profile_fail_closed(self) -> None:
        missing_lineage = _observation(
            "obs_missing_lineage",
            message_occurrence_id=None,
            thread_fingerprint=sha256_json("thread-missing"),
            text="缺少 occurrence 的 MISSING-101 不可建立 mention。",
            permission_scope=PermissionScope.project("project_missing"),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requires one message occurrence lineage",
        ):
            extract_source_bound_identifier_mentions(
                [missing_lineage],
                identity_scope=_identity_scope(),
                extractor_run_id=EXTRACTOR_RUN_ID,
                tokenizer_profile=self.profile,
                created_at=CREATED_AT,
            )

        valid = _observation(
            "obs_ascii_rejected",
            message_occurrence_id="message_occurrence_ascii",
            thread_fingerprint=sha256_json("thread-ascii"),
            text="ASCII-101 仍不得走 legacy profile。",
            permission_scope=PermissionScope.project("project_ascii"),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requires the frozen target profile",
        ):
            extract_source_bound_identifier_mentions(
                [valid],
                identity_scope=_identity_scope(),
                extractor_run_id=EXTRACTOR_RUN_ID,
                tokenizer_profile=build_ascii_identifier_regex_tokenizer_profile(),
                created_at=CREATED_AT,
            )


def _identity_scope(
    *,
    mode: str = TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    tenant_id: str | None = TENANT_ID,
    workspace_id: str = WORKSPACE_ID,
) -> SourceIdentifierIdentityScope:
    scope_payload = {
        "mode": mode,
        "workspace_id": workspace_id,
    }
    if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        scope_payload["tenant_id"] = tenant_id
    return SourceIdentifierIdentityScope(
        identity_scope_mode=mode,
        identity_scope_fingerprint=sha256_json(scope_payload),
        workspace_id=workspace_id,
        identity_scope_attestation_fingerprint=sha256_json(
            {"scope": scope_payload, "attestation": "fixture"}
        ),
        identity_scope_policy_fingerprint=sha256_json("identity-scope-policy"),
        operator_approval_fingerprint=sha256_json("operator-approval"),
        tenant_id=tenant_id,
        spec_approval_fingerprint=(
            sha256_json("workspace-only-spec-approval")
            if mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else None
        ),
    )


def _observation(
    observation_id: str,
    *,
    message_occurrence_id: str | None,
    thread_fingerprint: str,
    text: str,
    permission_scope: PermissionScope,
    private_locator: str | None = None,
) -> Observation:
    location = {
        "archive_fingerprint": sha256_json("archive-issue56"),
        "mailbox_fingerprint": sha256_json("mailbox-issue56"),
        "thread_fingerprint": thread_fingerprint,
        "segment_ordinal": 1,
    }
    payload = {
        "thread_fingerprint": thread_fingerprint,
    }
    if message_occurrence_id is not None:
        location["message_occurrence_id"] = message_occurrence_id
        payload["message_occurrence_id"] = message_occurrence_id
    if private_locator is not None:
        location["private_parser_locator"] = private_locator
    return Observation.from_dict(
        {
            "observation_id": observation_id,
            "asset_id": "asset_issue56_identifier_source",
            "extractor_run_id": "run_issue56_source_mail_v1",
            "observation_type": "email_body_segment",
            "modality": "mail",
            "location": location,
            "text": text,
            "payload": payload,
            "confidence": 1.0,
            "permission_scope": permission_scope.to_dict(),
            "created_at": CREATED_AT,
        }
    )


if __name__ == "__main__":
    unittest.main()
