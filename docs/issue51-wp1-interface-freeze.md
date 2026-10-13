# Issue #51 WP1 Interface Freeze

## Freeze and claim boundary

- Code freeze before this documentation change: `0f2e69b065d082fdb5fb43506f309b1dc2efc1f1`.
- This file is the durable packet committed on top of that code head; its final documentation commit is reported with the commit result.
- Findings 1–6 are closed. At code head `0f2e69b`, Russell and Herschel both returned `RELEASE_DECISION: AGREE` for the final Finding 7 code blocker. That is not the final cumulative code-plus-packet review.
- Issue #51 remains unchecked. WP1 is a reviewed upstream interface candidate until the code-plus-packet review freezes it.

```text
authority_valid=true
methodology_ready=false
status=blocked
pipeline_source_binding_count=64
authority_state_fingerprint=sha256:c8e3fc5ec13d690f33d27797942a3b9b090319d4be8f269c77bccd646d787177
execution_fingerprint=sha256:291c7ea5c5737079cc9ae9d4100fd9ce94f926adfff1a112235ed0aa93cf9665
```

The blocked methodology state is a hard boundary: this packet makes no
methodology-quality UAT, KG-vs-ontology, acceptance, launch-readiness, or
production-readiness claim. The maximum eventual Issue #51 claim is **ready for
Issue #52 independent acceptance**. Issue #53 remains required before WP5.

## Owner paths

```text
python/formowl_contract/evidence_coverage.py
python/formowl_contract/__init__.py
python/formowl_mail/bundle.py
python/formowl_mail/postgres.py
python/formowl_graph/storage/postgres.py
python/formowl_graph/storage/migrations/006_evidence_coverage.sql
```

`006_evidence_coverage.sql` is WP1-owned. `005_oauth_identity.sql` and
`007_task_lifecycle.sql` are reserved optional integrations owned elsewhere;
WP1 adds neither production migration.

## Audited `formowl_contract` public API

These are the WP1-specific names exported by the actual package at the code
freeze. No underscore-prefixed implementation name is public contract.

### Enums and constants

```text
ProcessingState, RawRetentionState, ClaimRequirementKind, AnswerClaimState
IndexFreshness, CoverageFallbackStatus, CoverageNonSearchReason, CoverageProofKind
PROCESSING_STATE_VALUES, RAW_RETENTION_STATE_VALUES, EXCLUSION_REASON_CODE_VALUES
ANSWER_CLAIM_STATE_VALUES, INDEX_FRESHNESS_VALUES
COVERAGE_FALLBACK_STATUS_VALUES, COVERAGE_ITEM_AUTHORIZATION_STATE_VALUES
COVERAGE_ITEM_RELEVANCE_STATE_VALUES, COVERAGE_NON_SEARCH_REASON_VALUES
COVERAGE_PROOF_KIND_VALUES, CELL_STATE_VALUES
COVERAGE_FALLBACK_LIMIT_POLICY_ID, COVERAGE_FALLBACK_LIMIT_POLICY_VERSION
COVERAGE_FALLBACK_LIMIT_POLICY_FINGERPRINT, COVERAGE_FALLBACK_MAX_ITEMS
COVERAGE_FALLBACK_MAX_BYTES, COVERAGE_FALLBACK_MAX_ELAPSED_MS
COVERAGE_FALLBACK_MAX_ATTEMPTS
```

Frozen values are: processing `parsed|preserved_unparsed|unsupported|failed|intentionally_excluded`;
retention `retained|deleted_by_policy|externally_managed`; claim kinds
`single_value|latest_value|current_value|all_matching|aggregation|existential_witness`;
claim states `FOUND|CONFLICT|NOT_FOUND_WITHIN_COMPLETE_SCOPE|INSUFFICIENT_COVERAGE`;
freshness `fresh|stale|mismatch|unavailable`; fallback
`not_required|completed|budget_exhausted|failed|cancelled`; non-search
`not_searched|not_authorized|redacted|failed|unsupported|intentionally_excluded`;
proof kinds `structural|ordinary|combined|intentionally_excluded|fallback`;
item authorization `authorized|ineligible`; item relevance `relevant|irrelevant`;
and cells `populated|blank|absent`.

The bounded fallback policy is `coverage_fallback_limits_v1`, version `1`, with
maxima 1,000 items, 100,000,000 bytes, 600,000 elapsed milliseconds, and 100
attempts. Values are strict finite integers; bools, negatives, overflow, huge or
unversioned values, and mismatched policy metadata fail closed.

### Records and helpers

```text
DisplayPagination, StructuralCell, StructuralColumn, StructuralRow
IntentionalExclusionProof, SourceInventoryItem, SourceInventory, StructuralObservation
ClaimRequirement, VersionManifest, FingerprintManifest, EvidenceVersionManifest
SourceInventoryRecord, CoverageAuthorizationBinding, StructuralPublicScopeDecision
CoverageVersionBinding, CoverageObservationPartition, CoverageScopePolicyBinding
CoverageItemAuthorizationDecision, CoverageItemRelevanceDecision
CoverageScopeAuthorityVerifier, CoverageScopeAuthority, CoverageScopePartition
CoverageFallbackUsage, CoverageProofRecord, CoverageLedger, AnswerClaim
fingerprint_manifest, validate_fingerprint_binding
```

`FingerprintManifest` and `EvidenceVersionManifest` alias `VersionManifest`;
`SourceInventoryRecord` aliases `SourceInventoryItem`. They are not extra models.
The shared exported `ContractValidationError` is the fail-closed exception and
`sha256_json` is the canonical JSON fingerprint helper.

### Consumer-facing constructors and serializers

- Pagination: `to_dict()` / `from_dict()`.
- Structural cell/column/row: `to_public_dict(scope_decision=...)`,
  `to_dict(scope_decision=...)`, `to_persistence_dict()`,
  `from_dict(...)`, `from_persistence_dict(...)`.
- Inventory item/observation: `create(**values)`, public/private serializers,
  and both deserializers. `SourceInventory.create(*, source_asset_id,
  source_fingerprint, parser_fingerprint, items, created_at=None)` plus the same
  serializers/deserializers.
- Exclusion proof: `create(...)`, `bind_to_inventory(...)`,
  `validate_for_claim(...)`, redacted `to_dict()`, private serializer, and both
  deserializers.
- Requirement: `create(*, query_id, kind, target, predicate=None,
  parameters=None, required_scope=(), created_at=None)`, `to_dict()`,
  `to_persistence_dict()`, and both deserializers.
- Manifest: `create(*, source_fingerprint, parser_fingerprint,
  tokenizer_fingerprint, index_fingerprint, implementation_fingerprint,
  index_freshness="fresh", source_version="1", parser_version="1",
  tokenizer_version="1", index_version="1", implementation_version="1",
  created_at=None)`, `matches(...)`, `usable_for_claim(...)`,
  `assert_usable_for_claim(...)`, serializers, and both deserializers.
- Scope: `CoverageAuthorizationBinding.to_dict/from_dict`,
  `StructuralPublicScopeDecision.authorize/deny/assert_matches_permission_scope`,
  `CoverageVersionBinding.from_manifest/matches_manifest`,
  `CoverageObservationPartition` serializers plus `all_observation_ids`, and
  `CoverageScopePolicyBinding.create/to_dict/from_dict`.
- Typed decisions: `CoverageItemAuthorizationDecision.create`,
  `validate_for_item`, serializers, and both deserializers; likewise
  `CoverageItemRelevanceDecision.create`, `validate_for_claim`, serializers,
  and both deserializers.
- Authority: `CoverageScopeAuthorityVerifier.generate()`,
  `from_external_root(root)`, `verifier_fingerprint`, `revalidate(...)`;
  `CoverageScopeAuthority.create`, its three derived item-ID views,
  `validate_for_claim`, serializers, and both deserializers.
- Partition/coverage: `CoverageScopePartition.create`,
  `observation_partition_for`, `validate_for_claim`, serializers, and both
  deserializers; `CoverageFallbackUsage.to_dict/from_dict`;
  `CoverageProofRecord.create(**values)`, serializers, and both deserializers;
  `CoverageLedger.create`, `binding_valid_for_claim`,
  `has_direct_authorized_witness`, `has_direct_incompatible_values`,
  `usable_for_claim`, `searched_observation_ids`, `claim_scope_complete`,
  serializers, and both deserializers.
- Claim: `AnswerClaim.create`, `to_dict`, `to_persistence_dict`,
  `from_dict`, and `from_persistence_dict`.

An independently retained verifier/root is required for definitive authority.
Replayed serialized fields cannot create trust; verifier/capability material is
not serializable or transferable through pickle/copy. Incomplete claims may
retain embedded authority as untrusted round-trip data only.

## Semantic invariants

### Inventory and structural evidence

- `SourceInventory` is a persisted aggregate with canonical
  `source_inventory_id`, recomputed on construction and persistence read. It is
  never inferred solely from child rows; forged aggregate IDs fail closed.
- Every item belongs to exactly one aggregate. Item IDs are validated for every
  item. Child aggregate, asset, source fingerprint, parser fingerprint, and
  exclusion-proof membership must agree.
- `source_observation_ids` are set-like and canonicalized before item identity;
  source ordinals, locations, version lineage, chronology, and other ordered
  fields remain ordered.
- Processing and authorization are orthogonal. Exclusion proof is required iff
  state is `intentionally_excluded` and forbidden for every other state. It is a
  closed typed proof bound to exact aggregate/item, raw-unit fingerprint,
  requirement, manifest, authorization revision, policy, actor, reason, and
  proof identity. Hidden, relevant, unsupported, failed, or undecidable units
  cannot prove a definitive negative.
- `StructuralObservation` is bound to its inventory item and asset/source/parser
  fingerprints. Rows, columns, cells, headers, occurrence/version lineage,
  chronology, and table topology are ordered private data and round-trip
  exactly. Public structural output requires a typed scope decision; denial is
  uniform and cardinality-neutral.

### Requirement, manifest, scope, ledger

- `ClaimRequirement` is closed and ID-bound to query ID, kind, target, predicate,
  parameters, and required scope. Unknown fields and forged IDs fail closed.
- `VersionManifest` has one exact shape/identity over required source, parser,
  tokenizer, index, implementation fingerprints, versions, freshness, and
  metadata. Missing, extra, forged, stale, mismatched, or unavailable manifests
  cannot authorize definitive coverage.
- `CoverageAuthorizationBinding` exactly binds actor context, permission
  revision, and grant revision.
- `CoverageScopeAuthority` binds exact inventory, requirement, authorization,
  manifest, and versioned policy. Independently produced per-item authorization
  and relevance decisions derive the partition; processing state and caller
  category lists are not authorization truth. The partition is total with no
  missing, duplicate, overlapping, unknown, stale, cross-scope, or relabeled
  decisions; relevant items have exact observation accounting.
- Complete scope requires the exact relevant set, exact structural/ordinary
  searched sets and proof coverage, fresh version binding, valid authorization,
  and acceptable fallback. Omitted, unresolved, failed, unsupported, redacted,
  or unsearched relevant observations fail closed.
- Set-like ledger inputs/proofs are canonicalized before identity and
  serialization. Topology, chronology, lineage, source ordinals, and display
  order remain ordered. Pagination is presentation-only and excluded from
  `coverage_ledger_id` and claim identity. Duplicate proof IDs, duplicate
  semantic proofs, and reused observation provenance fail closed. Partial
  conflict requires two direct incompatible populated values with distinct
  fingerprints and disjoint observations. Fallback budget exhaustion/failure/
  cancellation cannot authorize completeness.

### AnswerClaim wire and state rules

All four states are supported:

```text
FOUND
CONFLICT
NOT_FOUND_WITHIN_COMPLETE_SCOPE
INSUFFICIENT_COVERAGE
```

Every claim binds typed ledger, requirement, inventory, and matching manifest.
Definitive states additionally require independent scope authority and
claim-kind-specific proof/completeness. `FOUND` requires complete proof for
single/latest/current, all-matching, and aggregation; existential support-only
may use incomplete overall scope only with an explicit boolean requirement and a
direct typed authorized witness. Partial `CONFLICT` is only for
single/latest/current. Complete negative requires complete usable scope, fresh
proof, completed/unneeded fallback, and no unresolved relevant units.
`INSUFFICIENT_COVERAGE` remains representable for typed but incomplete coverage.

`AnswerClaim.to_dict()` emits exactly these nine keys:

```text
state, reason_codes, claim_requirement_id, coverage_ledger_id,
evidence_snapshot_ids, source_fingerprint, parser_fingerprint,
tokenizer_fingerprint, index_fingerprint
```

Private persistence uses `to_persistence_dict/from_persistence_dict`; public
`from_dict` cannot manufacture authoritative success.

## Persistence adapters

### File-private `MailEvidenceBundle`

`MailEvidenceBundle` is not a `formowl_contract` export. Its adapter surface is
`to_dict()`, `to_public_dict(*, scope_decision=None,
include_answer_claims=False)`, `to_persistence_dict()`, rejecting
`from_dict(...)`, and `from_persistence_dict(..., *,
expected_scope_authorities=None)`. Private payloads carry marker
`wp1_persistence`, schema `formowl_mail_evidence_wp1_v1`, and exact counts for
`source_inventory`, `source_inventory_items`, `structural_observations`,
`claim_requirements`, `coverage_ledgers`, `answer_claims`, and
`version_manifests`.

The bundle persists mail session, archive/folder occurrences, messages/message
occurrences, body segments, attachments/attachment occurrences, quoted and
embedded relations, parse run/warnings, then the seven WP1 families above.
Missing/legacy/partial marker state, malformed rows, forged IDs, stale hashes,
or self-certified definitive authority fail closed. Public output is an
allowlist of safe envelope metadata and typed actor-scoped structural summaries;
claims are included only with a matching typed decision and remain the exact
nine-field wire.

### PostgreSQL `PostgreSQLMailEvidenceStore`

This adapter is not a `formowl_contract` export. Its public adapter methods are:

```text
upsert_bundle(bundle, *, transaction=None, expected_scope_authorities=None)
get_bundle(*, mail_import_session_id=None, mail_evidence_bundle_id=None,
           expected_scope_authorities=None)
```

Direct upsert owns one transaction, commits once after all statements succeed,
and rolls back on validation, execution, or collision failure. A supplied active
same-connection `PostgreSQLUnitOfWork` retains outer transaction ownership.
Exact immutable retries are idempotent; same ID with a different payload/hash is
rejected without mutation. Reads/writes validate payload hashes, semantic IDs,
aggregate/item membership, asset/fingerprint relationships,
requirement/ledger/claim/manifest relationships, and session/workspace/owner
scope. Composite constraints prevent cross-scope rebinding. Reads validate
selected persisted row IDs, scope/relationship columns, payloads, and hashes
before reconstruction. Reconstructed families use one canonical ordering;
body-segment order and structural ordered semantics are preserved. Definitive
persistence requires an external expected-authority mapping.

`PostgreSQLUnitOfWork` exposes `__enter__`, `__exit__`, `commit()`, and
`active`; `PostgresMigration` exposes `from_file(path)` and
`from_text(filename=..., text=...)`; `PostgreSQLMigrationRunner` exposes
`migration_replay(migrations=None)`. These are adapter/migration APIs, not
`formowl_contract` record types.

## Migration chain and replay

The discovery/replay boundary is `python/formowl_graph/storage/postgres.py`:

```text
001_metadata_store.sql
002_vector_index.sql
003_ingestion_records.sql
004_mail_evidence.sql
006_evidence_coverage.sql
```

Optional exact reserved additions are `005_oauth_identity.sql` and
`007_task_lifecycle.sql`, in numeric order. Cumulative guarantees from
`24e66f1`, `2e37c0c`, `df1a424`, and `0f2e69b` are:

- unique three-digit slots, deterministic numeric order, exact reserved names,
  required base 001–004 and 006, and invalid manifests rejected before execute;
- migration ID/filename, SHA-256, and statement count bound to resolved file
  text; all files captured, validated, lexically split, and preflighted before
  the first execute; replay uses those captured statements;
- top-level semicolon splitting handles single quotes with doubled quotes,
  double quotes with doubled quotes, `$$`/`$tag$` dollar blocks, line comments,
  and block comments; unterminated quoted, block-comment, and dollar states fail
  closed;
- the real issue-20 OAuth fixture's two `DO $formowl_migration$ ... END IF; ...
  $formowl_migration$;` blocks remain single statements, not `END IF` fragments;
- `tests/fixtures/postgres/005_oauth_identity.sql` is test-only, byte-identical
  to issue-20 `ad75f1e`, with SHA-256
  `5af3eff6d1cf774483c3ac30c6db5da4a1baf28f814066a92bc1d1b28826d2e7`; no fake
  production 005/007 was added.

## WP2/WP3/WP4 boundaries and interface-change rule

- **WP2** produces source-neutral inventory aggregates/items and structural
  observations using frozen IDs, membership, fingerprints, ordered topology,
  and private serializers. It does not create alternate inventory, manifest,
  coverage, authority, or claim truth.
- **WP3** consumes inventory, observations, requirements, manifests, and typed
  authorization; it may produce typed proofs, fallback usage, and ledger inputs
  for retrieval/index/fallback, but not a parallel coverage, scope, proof,
  manifest, or claim system.
- **WP4** consumes typed inventory, requirement, manifest, independently
  verified authority, and validated ledger to construct `AnswerClaim`; it cannot
  bypass proof, completeness, authority, fingerprint, fallback, persistence, or
  the nine-field wire.

No downstream component may authorize definitive claims from caller booleans,
processing status, raw IDs, persisted self-certified authority, or public bundle
projections. Downstream work may consume this interface but must not silently
mutate it. Any required API, identity, serialization, persistence, migration,
or semantic change returns to WP1 as a separately reviewed change with a
refreshed packet.

## Verification at code head `0f2e69b`

- Exact canonical eight-module suite: **118 tests, OK**.
- Targeted dev-container Ruff check and format check: **passed** for exactly
  `python/formowl_graph/storage/postgres.py`,
  `tests/test_postgres_adapter_contracts.py`, and
  `tests/test_issue51_wp1_contracts.py`.
- The pinned SQL fixture was hash-verified and exercised by the composition/
  replay test separately; it was not passed to `ruff format --check`.
- `git diff --check`: **passed**; post-commit `git diff HEAD^ --check`: **passed**.
- Code worktree at the freeze head was clean before this documentation commit.
