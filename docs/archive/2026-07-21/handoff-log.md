# Agent Handoff Log

This active log is a bounded recent window. Lossless prior history is preserved
in dated snapshots under `../archive/`; the latest pre-trim snapshot is
`../archive/2026-07-19/handoff-log.md`.

Lifecycle label: `active`.

## Retention Rule

- Keep entries from the latest 14 calendar days, with a hard cap of 300 lines.
- If either limit is exceeded, archive the oldest complete dated entries into a
  new immutable dated snapshot before appending more.
- Never split a dated entry, discard content, or rewrite archive history.
- Append only concise cross-agent facts, blockers, verification, and next action.

## 2026-07-12 — Issue #20 Google-backed OAuth design

- The user selected Google as the sole upstream human identity provider for
  the internal closed beta. GitHub issue #20 now contains the implementation
  specification and the explicit state `Discussion complete; implementation
  may begin` at
  `https://github.com/markliou/formowl/issues/20#issuecomment-4947925113`.
- The accepted boundary does not use Auth0 and does not accept Google access
  tokens as FormOwl MCP bearer tokens. A narrow FormOwl OAuth 2.1 bridge handles
  the predefined ChatGPT client, PKCE, callbacks, invitation mapping,
  resource-bound FormOwl tokens, revocation state, and audit; the MCP Gateway
  continues to resolve current workspace, ownership, and grant authorization.
- No authentication code, migration, deployment, or production-readiness claim
  was made in this planning handoff. Issue #20 remains open for System Backbone
  implementation and verification.
- Issue #20's title and description were updated to the accepted
  implementation-ready Google OAuth / `ActorContext` boundary. The generic
  storage concerns were deliberately split into GitHub issue #41:
  `https://github.com/markliou/formowl/issues/41`.
- Issue #41 applies to every resource format, not only mail. It makes PostgreSQL
  metadata the authorization authority, permits shared object infrastructure
  but forbids flat unscoped ownership, introduces an explicit tenant and owner
  boundary, separates byte-level deduplication from governed Asset identity,
  and specifies occurrence/relationship lineage, upload rollback, lifecycle,
  retention, purge, and cross-scope negative tests. Issue #21 is only a
  downstream mail-adapter consumer of this generic boundary.
- The active work board now tracks #20 and #41 as unchecked System Backbone
  items. The archive-integrity test was generalized to require every archived
  unchecked task to remain present while allowing valid new active tasks; the
  immutable archived checklist counts remain fixed. Focused dev-container
  archive tests pass 4/4 with Ruff check and format check passing.

## 2026-07-12 — Issue #20 first-owner bootstrap slice

- Added operator-authorized, atomic and idempotent first-owner bootstrap for an
  empty workspace. It creates no placeholder user; the first verified Google
  login creates the real user and owner membership and completes bootstrap in
  the same transaction. Conflicting or removed operators, nonempty workspaces,
  incompatible invitations, and partial-write paths fail closed.
- Added service-attributed `AuditLog` identity, `OAuthOwnerBootstrap`, the
  PostgreSQL table and repository/JSONB support, memory-harness equivalents,
  and 18 production-function manifest entries with seven-category evidence.
- Verification: 53 focused dev-container tests passed after a temporary
  `pip install -e .`; the exact onboarding test and bootstrap slice manifest
  audit pass. Two live PostgreSQL race tests passed twice consecutively against
  one fresh database with unique workspace preconditions and `finally` cleanup.
  Targeted Ruff/format, manifest JSON, AST duplicate, migration marker, and
  `git diff --check` checks pass. The read-only reviewer returned
  `RELEASE_DECISION: AGREE` after the live-test pollution blocker was fixed.
- Scope remains bounded. Issue #20 is still unchecked: the canonical dev image
  has not been rebuilt with OAuth dependencies, and global manifest onboarding,
  runtime/operator wiring, full canonical verification, and bounded external
  ChatGPT compatibility smoke remain open.

## 2026-07-13 — Issue #20 Batch 1 function hardening

- Completed bounded hardening for `formowl_auth.config`, `google_oidc`,
  `security`, and `tokens`. Four genuine fixes followed canonical pre-fix
  regressions: token and Google aware-datetime checks now require
  `utcoffset() is not None`, scope parsing rejects non-SP whitespace, and token
  header parsing uses strict validated URL-safe Base64 decoding.
- Each bounded finding received reviewer `RELEASE_DECISION: AGREE`. Read-only
  dev-container runs mounted the repository `:ro`; owner modules pass 45/45 and
  targeted Ruff check/format check passes.
- Batch 1 is 53/53 status-onboarded with zero scoped manifest-validator
  blockers. The global manifest is only 139/598 onboarded with 459 pending, so
  the full exact-onboarding test remains failing by design while whole-issue
  onboarding, full canonical verification, and external gates remain
  incomplete. Issue #20 stays unchecked with no production-readiness claim.

## 2026-07-13 — Issue #20 audit metadata sanitizer hardening

- Status-onboarded `formowl_auth.audit.sanitize_oauth_audit_metadata` with two
  direct executable tests and zero scoped manifest-validator blockers.
- Canonical pre-fix runs proved two production gaps: mixed-type unsupported
  keys escaped as `TypeError`, and seven allowlisted fields accepted invalid
  semantic types. The sanitizer now uses generic non-leaking errors and a
  closed per-key type table for code strings, scopes, HTTP status, and replay.
- Read-only `:ro` dev-container verification passes 2/2 focused tests, 9/9
  related-module tests, targeted Ruff check/format check, and the scoped
  validator. The reviewer gate passed 3/3 `RELEASE_DECISION: AGREE`.
- Global state is still incomplete: 140/598 onboarded, 458 pending, and 853
  blockers comprising 458 pending functions, 394 N/A hygiene findings, and one
  stale source binding. Issue #20 remains unchecked with no production-readiness
  claim.

## 2026-07-13 — Issue #20 function-harness self-integrity

- The harness now resolves a supplied repository root with temporary root,
  `root/tests`, and `root/python` imports; evicts and exactly restores
  `tests`, `tests.*`, and direct `tests/*.py` bare aliases; cleans up only
  modules physically loaded from the active `root/tests`; and restores the
  exact original `sys.path` on success and failure.
- Read-only `:ro` verification passes 3/3 alias regressions, the 32/32 harness
  module, the 98/98 focused combination, targeted Ruff check/format-check, and
  scoped diff-check. The final read-only reviewer gate passed 3/3
  `RELEASE_DECISION: AGREE`.
- This is a harness/test-only slice. Issue #20 remains unchecked at 140/598
  onboarded, 458 pending, and 853 global blockers; no whole-issue or
  production-readiness claim is supported.

## 2026-07-13 — Issue #20 stale source binding resolved

- Evidence-backed rebound the sole stale binding for
  `formowl_gateway.remote.build_remote_tool_descriptors`; existing direct tests
  pass 2/2, the gateway module passes 20/20, and tracing covers 1 with 0 missing.
- The mismatch count moved 1 to 0; Ruff/format, manifest JSON, and diff checks
  pass, and the reviewer gate agreed 3/3.
- Issue #20 stays unchecked at 140/598 onboarded, 458 pending, 394 N/A hygiene
  blockers, zero stale bindings, and 852 total blockers.
- 2026-07-14: Production-shaped `open_upload_session` now uses a valid Google-OAuth `SessionIdentity`; canonical `:ro` exact/runtime/gateway/onboarding checks pass 1/1, 34/34, 45/45, and 1/1, Ruff passes, and the scoped reviewer gate is 3/3 AGREE.
- `docs/issue20-account-system-verification-status.md` now records 601 functions, 206 onboarded, 395 pending, 194/194 requested tests, zero resolution/execution blockers, seven external blockers, and a full suite of 1,187 tests with four failures and six skips; Issue #20 stays open.

## 2026-07-15 — Methodology-first SPEC rewrite

- Replaced `SPEC.md` in full instead of appending an override. The canonical
  order now starts with source-neutral evidence, observations, business
  objects and universal candidate assertions, governance, scoped canonical
  knowledge, effective views, and projections/action proposals. Mail and
  procurement are examples only; cross-domain acceptance requires a materially
  different second domain.
- Realigned README, extraction, architecture, provenance, workflow,
  infrastructure, and wiki-schema entry sections so obsolete wiki/mail-first
  framing and the stale manual connected-identity description no longer
  contradict the SPEC.
- Read-only dev-container methodology audit passed. The canonical full suite ran
  1,204 tests with three failures and six skips; all three failures are in the
  concurrent Issue #20 operator/onboarding work, not the rewritten documents.
  No work-board completion or reviewer-gate claim is made for this authority
  rewrite.

## 2026-07-15 — Issue #20 connected startup/secret batch

- Status-onboarded 13 `formowl_gateway.secret_init` plus 12
  `formowl_gateway.container_entrypoint` functions. Production close,
  final-ownership, and quarantine rollback fixes plus signing and staged-secret
  cleanup regressions passed the scoped read-only gate; reviewers agreed 3/3
  `RELEASE_DECISION: AGREE`.
- Global state is 294/601 onboarded, 307 pending, and 629 blockers comprising
  307 pending functions plus 322 N/A-reason hygiene findings, with zero
  source-binding mismatches. Whole-manifest execution passes 249/249 tests and
  direct tracing covers 294/294 functions across 731 evidence pairs.
- The next coherent 25-function batch is the PostgreSQL
  migration/transaction boundary: six repository lifecycle functions, seven
  Psycopg transaction/query functions, `oauth_migration_path`, and all 11
  pending `formowl_graph.storage.postgres` functions. It advances live
  PostgreSQL/E2E authority rather than isolated helpers.
- All 7/7 required external evidence layers, the Issue #20-wide reviewer
  external layer, and independent completion audit remain `not_supplied`;
  Issue #20 stays open with no production-readiness claim.

## 2026-07-16 — Issue #20 PostgreSQL migration/transaction batch

- Status-onboarded 25 repository/connection/migration functions and repaired
  34 existing N/A-reason hygiene mappings without changing production code.
  The only test hardening covers repository-wrapper migration rollback with no
  partial state and the fixed safe migration-result dictionary boundary.
- Read-only proof passes 32/32 owner-module tests, scoped onboarding 1/1,
  target harness 9/9, direct trace 25/25 across 31 evidence pairs, and the
  engineering, governance/safety, and manifest/onboarding reviewer gate 3/3.
- At this migration-batch checkpoint, global state was 319/601 onboarded,
  282 pending, and 510 blockers with zero source-binding mismatches. All 7/7
  external layers remained `not_supplied`; Issue #20 stayed unchecked with no
  live PostgreSQL or production claim.
- The next batch at that checkpoint was the remaining coherent 33-function
  `formowl_auth.postgres` CRUD/row-mapping batch.

## 2026-07-16 — Issue #20 PostgreSQL CRUD/row-mapping batch

- Status-onboarded 33 functions: six transaction/code, three invitation, eight
  identity/profile, seven membership/grant, seven client/token, and two
  row-mapping functions. All 35 batch N/A-reason hygiene mappings were cleaned
  individually; production code is unchanged.
- Read-only proof passes identity keyed/not-found/zero-side-effect and token
  revoked/expired-preservation regressions, owner 22/22, scoped onboarding 2/2,
  harness 12/12, and direct trace 33/33 across 46 evidence pairs. Target
  blockers and source-binding mismatches are zero. Engineering,
  governance/safety, and manifest/onboarding reviewers agreed 3/3 after the
  original reviewers closed their blockers.
- Current validation is 352/601 onboarded, 249 pending, and 477 blockers
  comprising 249 pending-function plus 228 N/A-reason hygiene blockers. The
  whole-manifest execution snapshot still predates this batch; all 7/7 external
  layers remain `not_supplied`, and Issue #20 stays unchecked.
- Next: onboard the 10 `scripts.issue20_runner_boundary` functions to lock
  invocation identity, trusted executable/private-directory requirements,
  mounts, and process safety before external-packet and live-journey modules.

## 2026-07-16 — Issue #20 runner boundary batch

- Onboarded 10 runner functions and refreshed `verify_inner_boundary`; fixes
  pin the canonical runner inode, restore/clean fd 9, and require all five
  capability sets zero.
- Read-only proof: exact 1/1, module 33/33, onboarding 1/1, harness 16/16
  across 23 pairs, direct trace 11/11, target blockers/mismatches zero.
- Reviewers agreed 3/3 after exact open flags were pinned to
  `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`.
- Global state is 362/601 onboarded, 239 pending, 467 blockers
  (239 pending + 228 hygiene), mismatches zero.
- Fresh whole-manifest proof is 285/285 tests, 362/362 traces, 831 pairs, zero
  execution blockers; 7/7 external layers remain `not_supplied`.
- Next is exactly 56 `formowl_evidence.issue20_packet` functions; Issue #20
  stays open with no production-readiness claim.

## 2026-07-16 — Issue #20 evidence-packet batch

- Status-onboarded all 56 `formowl_evidence.issue20_packet` functions.
  Read-only proof passes the final packet module 37/37, exact onboarding 1/1,
  target harness 14/14, and direct trace 56/56 across 69 evidence pairs.
- Scoped validator target blockers and source-binding mismatches are both zero;
  engineering, governance/safety, and manifest/onboarding reviewers agreed 3/3.
- Current validation is 418/601 onboarded, 183 pending, and 411 blockers
  (183 pending + 228 hygiene), with zero source-binding mismatches. The latest
  fresh whole-manifest execution remains the earlier runner checkpoint.
- Next is exactly 56 `scripts.connected_runtime_postgres_live_e2e` functions;
  this repository-side journey batch is not external completion, and all 7/7
  required external layers remain `not_supplied`.

## 2026-07-18 — Issue #20 connected-runtime live-E2E batch
- Status-onboarded the fixed 56-function batch; owner 84/84, onboarding/isolation 2/2, harness 59/59, trace 56/56 across 106 pairs, and Ruff/JSON/diff checks pass under `:ro`.
- Five direct negative regressions cover protocol mismatch, bearer denial, malformed tool/structured results, and delegated tool-call error validation.
- Engineering, governance/safety, and manifest/onboarding reviewers agreed 3/3; this is bounded repository evidence, not accepted external evidence or production readiness.
- Authority is 474/601 onboarded, 127 pending, and 358 blockers; `_invalid_token_challenge` is missing and `_validate_external_layer_counts` has a source-binding mismatch.
- Issue #20 stays open/unchecked; independently onboard the missing function, repair the unrelated binding, then continue pending functions and N/A hygiene.

## 2026-07-19 — Issue #20 repository authority closeout

- Repository authority is 603 changed / 603 manifested / 603 onboarded, with
  zero pending, missing, extra, duplicate, source-binding mismatch, or validator
  blockers.
- Whole-manifest requested/resolved/run/pass is 454/454/454/454, with 1,214
  checked evidence pairs and zero skips, failures, errors, resolution blockers,
  or execution blockers. Direct trace is 603/603 with zero missing.
- Runtime readiness now fails closed on descriptor-close or cleanup faults while
  still attempting probe cleanup; engineering, governance/safety, and
  manifest/onboarding reviewers agreed 3/3 with zero blockers.
- This is local repository evidence only. All seven required external layers
  remain `not_supplied`, so Issue #20 remains open and unchecked.

## 2026-07-20 — Issue #20 cross-UID diagnostic custody

- Replaced the unreadable inner-owned mode-`0400` diagnostic path with an
  ephemeral inner UID `10001` handoff written as `0200`, fsynced, then finalized
  as `0444`; outer validates its closed metadata/content contract before creating
  the runner-owned mode-`0400` final diagnostic.
- Read-only offline dev-container proof passes operator 28/28, runner 38/38,
  target harness 25/25 across 51 pairs, target trace 33/33, global authority
  605/605/605, whole manifest 456/456/456/456 across 1,217 pairs, and global
  trace 605/605 with zero missing or blockers.
- Full Ruff check/format, manifest JSON parse, runner shell syntax, container
  diff-check, and untracked text-style checks pass. The original governance
  reviewer closed the custody finding with a finding-specific 1/1
  `RELEASE_DECISION: AGREE`; author and verification-only agents do not count,
  while the existing connected-operator batch gate remains 3/3. All seven
  external layers remain `not_supplied`, so Issue #20 remains open and
  unchecked.

## 2026-07-20 — Issue #20 predefined-client bootstrap correction

- Removed the circular paired client-ID/redirect sentinel flow. A containerized
  helper now derives or validates one safe non-secret predefined client ID
  before discovery; the redirect sentinel alone selects `discovery_only`.
- Discovery and final OAuth enforce the same exact client ID, while finalization
  replaces only the ChatGPT-displayed callback. If app management cannot use
  that predefined ID, the live campaign stops as an external blocker.
- Canonical focused OAuth/runtime tests pass 106/106 and operator/docs contracts
  pass 10/10. No shared manifest or onboarding file was changed.
- Issue #20 remains open and unchecked; all seven governed external layers still
  require accepted evidence before closure.

## 2026-07-21 — Issue #20 final local authority cleanup

- Final local authority is 689/689/689 functions, whole harness
  507/507/507/507 across 1,387 pairs, trace 689/689, and `test_id_count` 1,520;
  the canonical full suite is 1,520 OK with seven environment-gated skips.
- Runtime readiness no longer returns from `finally`; focused runtime is 36/36.
  Exact Git/Docker exclusions cover operator-local Caddy/env files while
  tracked templates remain included; real BuildKit and safe-start 71/71 pass.
- Prior source reviewers predate this cleanup and do not satisfy the Issue-wide
  gate. Freeze the post-cleanup source, preserve stale scratch, then run all
  eight local stages and prepare a fresh final reviewer packet.
- Seven external layers remain `not_supplied`; Issue #20 remains open and
  unchecked.
