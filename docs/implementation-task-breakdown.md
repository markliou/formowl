# Implementation Task Breakdown

This is the bounded active work board. The lossless board before issue #40
archival is at `docs/archive/2026-07-11/implementation-task-breakdown.md`.

## Retention Rule

- Keep every unchecked checklist item, current phase summaries, and at most five concise recent-completion summaries in this active file.
- Keep this file at or below 400 lines; archive before it exceeds 500 lines.
- Move older completed detail into a dated immutable `docs/archive/` snapshot; never delete or rewrite archived history.
- Preserve existing checklist states mechanically during archival. Historical
  `[x]` and `[ ]` states change only through the normal completion workflow.

## Status Legend

- `[x]` complete in the current repository.
- `[ ]` not started or not verified.
- Goal files hold durable role state; this board holds task completion.
- Archived proof remains authoritative for historical completed details.

## Current Phase Summary

- Phase 0 and the resource-extraction small core are complete.
- Identity, upload/session capture, extractor adapters, semantic candidates,
  graph governance, user graph, wiki projection, infrastructure, mail evidence, and completed-slice test hardening have completed tracked slices.
- One pre-existing broad objective remains unchecked: full KG real-evidence acceptance; its complete historical proof requirements remain archived.
- Issue #38 authority state isolation and clean-clone reproducibility are complete;
  four real-evidence gates remain blocked by missing evidence, not harness drift.
- Issue #39 MCP protocol and shadow-workflow consolidation is complete in this
  working tree.
- Issue #40 archival maintenance is complete in this working tree.
- Pre-feature production cleanup is complete: test-only gateway scenarios no
  longer ship as public production APIs, mail evidence permission helpers are
  shared, and deprecated Python import/query surfaces retain explicit
  compatibility boundaries.
- Pre-feature structural cleanup is complete: repeated evaluator validation,
  HTTP smoke orchestration, PostgreSQL smoke lifecycle, mail payload
  validation, and atomic JSON persistence now use shared implementations.
- Issue #20 local authority is 689/689/689 changed/manifested/onboarded,
  508/508/508/508 requested/resolved/run/pass across 1,388 checked pairs;
  direct trace is 689/689 with missing 0 and blockers `[]`, pending is 0, and
  `test_id_count` is 1,521, with zero execution or
  validator blockers; seven external layers remain `not_supplied`, so #20
  stays open.

## Current Unchecked Work

- [ ] Implement issue #20 Google-backed ChatGPT MCP OAuth identity mapping and
  gateway-controlled `ActorContext`.
  - Owner paths: `python/formowl_auth/`, `python/formowl_gateway/`, identity and
    audit contracts/migrations, focused tests, and relevant durable docs.
  - Current state: the Google-backed OAuth design remains the authority. The
    first-owner bootstrap slice is implemented: an injected operator authority
    may atomically create the first pending owner invitation for an empty
    workspace without creating a fake user; identical retries are idempotent,
    conflicts fail closed, the verified Google login creates the real user and
    owner membership, and service-attributed audit plus PostgreSQL persistence
    preserve the bootstrap lifecycle. Batch 1 for `formowl_auth.config`,
    `google_oidc`, `security`, and `tokens` is 53/53 status-onboarded with zero
    scoped manifest-validator blockers. The next bounded function,
    `formowl_auth.audit.sanitize_oauth_audit_metadata`, is also status-onboarded
    with zero scoped blockers. The function-harness self-integrity slice is
    complete: a supplied repository root now provides temporary root,
    `root/tests`, and `root/python` imports; `tests`, `tests.*`, and direct
    `tests/*.py` bare aliases are evicted and restored by exact object identity;
    cleanup is physically scoped to `root/tests`; and `sys.path` is restored
    exactly after success or failure. The production-shaped
    `open_upload_session` slice now uses a real Google-OAuth-shaped
    `SessionIdentity` bound to the principal user and token session; governed
    upload-session persistence, a single audit, cross-workspace denial, and
    leak-safety assertions pass without weakening `_validate_actor_context`.
    The NaN audit-truthfulness finding is also closed: production
    `_safe_handler_envelope` rejects NaN and positive/negative infinity before
    a semantic success log can be recorded, while finite `1.25` remains a
    canonical success through the bearer-authenticated exact `/mcp` path.
  - Slice proof: read-only dev-container runs with the repository mounted `:ro`
    pass all 45 owner-module tests plus targeted Ruff check and format check.
    The sanitizer's focused tests pass 2/2, its related module passes 9/9, and
    targeted Ruff check/format check passes. Canonical pre-fix regressions
    proved that mixed-type unsupported keys escaped as `TypeError` and seven
    allowlisted fields accepted the wrong semantic types; the fixes now use
    generic non-leaking errors and a closed per-key type table. The sanitizer
    reviewer gate passed 3/3 `RELEASE_DECISION: AGREE`. Earlier bootstrap proof
    also includes two live PostgreSQL concurrency tests run twice against one
    fresh database. Harness self-integrity proof passes 3/3 alias-lifecycle
    regressions, the 32/32 harness module, and the 98/98 focused combination
    under a read-only repository mount, plus targeted Ruff check/format-check
    and scoped diff-check; its final read-only reviewer gate passed 3/3
    `RELEASE_DECISION: AGREE`. The sole stale source binding,
    `formowl_gateway.remote.build_remote_tool_descriptors`, was rebound only
    after its existing two tests passed and the direct runtime tracer covered
    the function with zero missing traces. Read-only proof passes 2/2 bound
    tests, the 20/20 gateway module, targeted Ruff/format, manifest JSON, and
    diff checks; the binding reviewer gate passed 3/3 `RELEASE_DECISION: AGREE`.
    The production-shaped upload slice passes the exact regression 1/1,
    `test_connected_runtime.py` 34/34, `test_mcp_oauth_gateway.py` 45/45,
    scoped remote-helper onboarding 1/1, and targeted Ruff checks under a
    read-only repository mount. Its scoped reviewer gate passed 3/3
    `RELEASE_DECISION: AGREE`. NaN/non-finite proof uses real `TestClient`
    bearer-authenticated exact `POST /mcp` E2E and passes scoped 15/15, direct
    trace 1/1 with zero missing traces, Ruff check/format, manifest JSON, and
    scoped diff checks. Its engineering, manifest/onboarding, and
    governance/safety reviewer gate passed 3/3 `RELEASE_DECISION: AGREE`;
    this is scoped finding completion, not Issue #20-wide reviewer evidence.
    The read-only wheel-build test harness now stages only `pyproject.toml`,
    `README.md`, and `python/` into a writable `/tmp` source tree while
    excluding `build`, `*.egg-info`, `__pycache__`, and `*.pyc`; the repository
    remains mounted `:ro`, and the existing migration and connected-entrypoint
    wheel assertions are unchanged. The exact regression passes 1/1, the
    connected-runtime container module passes 15/15, and targeted Ruff
    check/format-check passes. The wheel-harness engineering,
    governance/safety, and packaging/test-methodology reviewer gate passed 3/3
    `RELEASE_DECISION: AGREE`; production packaging was not changed.
    At that historical validator checkpoint, the self-test switched to one
    bounded synthetic pending-function context instead of layering malformed
    rows over the then-current 601-function manifest. Its exact regression passes
    1/1, and the related 22-test module
    has only the expected global exact-onboarding failure. Its engineering,
    governance/fail-closed, and test-methodology reviewer gate passed 3/3
    `RELEASE_DECISION: AGREE` with no blocking findings.
    The local-folder persistence regression now reloads the completed
    `IngestionJob`, follows its source-ordered `observation_ids`, fails
    explicitly if a persisted observation is missing, and verifies the
    heading/paragraph order plus complete `source_ref` lineage. The exact test
    passes 1/1, the local-folder module passes 10/10, the related text-extraction
    and ingestion-workflow modules pass 14/14, and targeted Ruff check/format
    plus `git diff --check` pass. Generic store ordering and stable observation
    IDs were not changed. Its engineering, governance/safety, and
    test-methodology reviewer gate passed 3/3 `RELEASE_DECISION: AGREE`.
    `formowl_evidence.issue20.issue20_implementation_contract_hash` is now the
    next bounded status-onboarded function: repeated input returns one valid
    SHA-256, included source drift changes the digest, and a missing required
    glob fails closed with one generic error while leaving the fixture tree
    unchanged. Read-only proof passes the 3/3 focused checks, the 14/14 related
    module, scoped direct tracing with both bound tests passing and 1/1 function
    covered with zero missing traces, zero function-scoped validator blockers,
    targeted Ruff check/format-check, manifest JSON parsing, and
    `git diff --check`. Its engineering, governance/safety, and
    test-methodology reviewer gate passed 3/3 `RELEASE_DECISION: AGREE` with
    zero blockers.
    `formowl_auth.provider.ManualTrustedInternalAuthProvider.select_actor` is
    also status-onboarded after a real audit-failure regression proved that the
    prior ordering could replace `whoami()` before the actor-selection audit
    was durable. The provider now commits `_selected_context` only after audit
    persistence succeeds, so failure preserves the previous actor context and
    audit bytes. Read-only focused evidence passes 4/4 across the exact
    audit-failure regression, success/current-workspace path, expired/revoked
    grant filtering, and scoped onboarding assertion; provider-module 2/2,
    function-scoped execution 3/3, direct trace 1/1 with zero missing traces,
    targeted Ruff/format, manifest JSON, and `git diff --check` also pass. Its
    engineering, governance/safety, and test-methodology reviewer gate passed
    3/3 `RELEASE_DECISION: AGREE` after reviewers required explicit current
    workspace ID/role and audit session/target lineage assertions.
    `formowl_auth.models.ExternalIdentity.to_dict` is also status-onboarded
    with a fixed exact ten-field payload. All nine string fields require exact
    `str` runtime types and reject subclasses, `email_verified` requires exact
    `bool`, and malicious `__copy__` / `__deepcopy__` probes are never invoked.
    A verified email must pass `normalize_verified_email` and already equal its
    canonical normalized form; the serializer fails closed and never silently
    normalizes output. Malformed or whitespace/case-noncanonical email raises
    exactly `ContractValidationError("ExternalIdentity is invalid")` without
    leaking input or mutating object state. The first reviewer identified
    missing exact-runtime-type proof, and the canonical pre-fix email regression
    failed twice because malformed and noncanonical email were serialized.
    Final read-only proof passes the exact regression 1/1, contract module
    19/19, scoped onboarding 1/1, validator with zero binding mismatches and
    zero target blockers, one-function harness 1/1, direct trace 1/1 with zero
    missing traces/blockers, targeted Ruff check/format-check, manifest JSON,
    and `git diff --check`. The engineering, governance, and manifest reviewer
    gate passed 3/3 `RELEASE_DECISION: AGREE`; two blockers were closed by
    re-review from their original reviewers. This remains bounded function
    completion, not Issue #20 completion or production readiness.
    The current 17-target OAuth models batch is status-onboarded. Its malicious
    non-string key colliding with an allowed string key now fails closed before
    dictionary materialization, while generic `Mapping` compatibility remains
    supported. Engineering, governance/safety, and manifest/onboarding
    reviewers agreed 3/3 `RELEASE_DECISION: AGREE`. This is bounded batch
    completion, not Issue #20 completion or production readiness.
    The current 22-target exact `/mcp` to `open_upload_session` boundary batch
    is also status-onboarded without a production change: 13
    `formowl_gateway.remote`, seven `formowl_gateway.runtime`, and two
    `formowl_mail.upload_session` functions. Its scoped validator has zero
    target blockers and zero source-binding mismatches; exact regressions pass
    4/4, the related gateway/runtime/mail modules pass 92/92, the onboarding
    module excluding the intentional global gate passes 26/26, the target
    harness passes 21/21, and direct tracing covers 22/22 functions across 52
    evidence pairs. Engineering, governance/safety, and manifest/onboarding
    reviewers agreed 3/3 `RELEASE_DECISION: AGREE`. The original reviewers
    closed three blockers on re-review: temporal N/A middleware ordering,
    audit-lineage ownership wording for the outer middleware, and fixed global
    manifest-total coupling in the scoped test. This bounded batch reviewer
    gate is not the Issue #20-wide reviewer external layer, which remains
    `not_supplied`.
    The current 22-target `formowl_gateway.operator` batch is also
    status-onboarded without a production change. Its public
    `lookup_token_session` timestamp path now has executable evidence for
    non-UTC normalization to UTC plus malicious `utcoffset()` and
    `astimezone()` failures that map to generic errors without repository,
    transaction, audit, or mutation side effects. Exact onboarding passes 1/1,
    the three timestamp regressions pass 3/3, the operator module passes 13/13,
    the target harness passes 12/12 across 69 evidence pairs, and direct
    tracing covers 22/22 functions with zero missing traces. Engineering,
    governance/safety, and manifest/onboarding reviewers agreed 3/3
    `RELEASE_DECISION: AGREE`. This is bounded batch completion, not Issue #20
    completion or production readiness.
    The current connected startup/secret batch is also status-onboarded: 13
    `formowl_gateway.secret_init` functions plus 12
    `formowl_gateway.container_entrypoint` functions, 25 total. Production
    fixes close `_read_secret` descriptor-close leakage, prevent `main` from
    leaving false-success evidence after final ownership failure, and preserve
    fail-closed state when secret-set quarantine rollback itself fails.
    Strengthened regressions pin the exact current/previous signing manifest and
    previous-key `verify_until`, and table-drive staged-secret `write`,
    `fchown`, `fsync`, and descriptor `close` failures through generic error,
    empty-stage, leak-safety, descriptor-handling, and retry assertions.
    Read-only proof passes the exact regression 1/1, entrypoint module 12/12,
    scoped onboarding 1/1, zero target validator blockers or binding
    mismatches, target harness 21/21 across 53 evidence pairs, and direct
    tracing for 25/25 functions with zero missing. Engineering,
    governance/safety, and manifest/onboarding reviewers agreed 3/3
    `RELEASE_DECISION: AGREE`. This remains bounded batch completion, not
    Issue #20 completion, external-evidence completion, or production readiness.
    The PostgreSQL migration/transaction boundary is now a status-onboarded
    25-function batch: six `PostgreSQLOAuthRepository`
    lifecycle functions, seven `PsycopgOAuthConnection` transaction/query
    functions, `oauth_migration_path`, and all 11
    `formowl_graph.storage.postgres` migration functions. The batch also
    repairs 34 existing N/A-reason hygiene mappings. Read-only proof passes
    32/32 owner-module tests, scoped onboarding 1/1, the target harness 9/9,
    and direct tracing for 25/25 functions across 31 evidence pairs. The only
    test hardening adds the repository-wrapper `apply_migrations` partial-state
    rollback regression and pins the fixed safe
    `PostgreSQLMigrationResult.to_safe_dict` result boundary; production code
    is unchanged. Engineering, governance/safety, and manifest/onboarding
    reviewers agreed 3/3 `RELEASE_DECISION: AGREE`. This is repository-side
    bounded evidence, not live PostgreSQL, Issue #20 completion, external
    evidence, or production readiness.
    The remaining 33-function `formowl_auth.postgres` CRUD/row-mapping batch is
    now status-onboarded: six transaction/code functions, three invitation
    functions, eight identity/profile functions, seven membership/grant
    functions, seven client/token functions, and two row-mapping helpers. All
    35 batch N/A-reason hygiene mappings were cleaned individually. Production
    code is unchanged. Final read-only proof passes the keyed/not-found,
    zero-side-effect identity-read regression, the revoked/expired token-session
    preservation regression, the 22/22 owner module, scoped onboarding 2/2,
    target harness 12/12, and direct trace 33/33 across 46 evidence pairs, with
    zero target validator blockers or source-binding mismatches. Engineering,
    governance/safety, and manifest/onboarding reviewers agreed 3/3
    `RELEASE_DECISION: AGREE`; the original reviewers closed their blockers on
    re-review. This remains bounded repository evidence, not live PostgreSQL,
    external evidence, Issue #20 completion, or production readiness.
    The runner boundary batch is now status-onboarded: 10 newly onboarded
    `scripts.issue20_runner_boundary` functions plus a refreshed
    `verify_inner_boundary`. Production safety fixes pin the validated canonical
    runner inode across a path swap, restore pre-existing fd 9 and close
    temporary descriptors after post-`dup2` `execve()` failure, and require all
    five capability sets (`CapInh`, `CapPrm`, `CapEff`, `CapBnd`, `CapAmb`) to
    be present, valid hexadecimal, and zero. Final read-only proof passes the
    exact regression 1/1, runner module 33/33 with `ResourceWarning` promoted
    to error, scoped onboarding 1/1, target harness 16/16 across 23 evidence
    pairs, and direct trace 11/11 with zero target blockers or binding
    mismatches. Engineering, governance/safety, and manifest/onboarding
    reviewers agreed 3/3 `RELEASE_DECISION: AGREE` after the final exact
    `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` blocker was fixed.
    The evidence-packet batch is status-onboarded with its recorded 3/3 reviewer
    agreement. The 56-function connected-runtime live-E2E batch passes owner
    84/84, onboarding/isolation 2/2, harness 59/59, trace 56/56 across 106
    pairs, five negative regressions, and reviewers 3/3 AGREE; it remains
    bounded repository evidence, not accepted external evidence or readiness.
    `_invalid_token_challenge` independently passes owner 85/85,
    onboarding/isolation 2/2, harness 60/60, trace 57/57 across 108 pairs, and
    reviewers 3/3 agree. The earlier `_validate_external_layer_counts` binding
    is test-only status-onboarded: focused 3/3, harness 2/2, trace 1/1 with zero
    missing, related 41/41, zero target blockers, and reviewers 3/3 agree.
    The 31-function `scripts.oauth_mcp_harness` batch is status-onboarded;
    atomic output failure preserves prior bytes and emits only generic failure,
    while hostile constructor fallbacks have test-only proof. Harness 15/15,
    trace 31/31 across 52 pairs, related 44/44, onboarding 1/1, checks, and
    reviewers 3/3 agree.
    The 29-function connected operator PostgreSQL journey is also
    status-onboarded. Production now requires all five capability sets to be
    present, valid hexadecimal, and zero, and binds the exact audit workspace
    and target lineage to dynamic bootstrap/member invitation IDs while public
    output remains count/hash-only. Read-only proof passes owner 19/19,
    onboarding 1/1, harness 16/16, trace 29/29 across 36 pairs, zero target
    blockers/mismatches, Ruff/format/JSON/diff checks, and reviewers 3/3 agree.
  - Remaining state: issue #20 stays unchecked and open. Repository authority is
    689/689/689 changed/manifested/onboarded; pending, missing, extra, duplicate,
    source-binding mismatch, N/A hygiene, and validator blockers are all zero.
    Whole-manifest requested/resolved/run/pass is 508/508/508/508 across 1,388
    evidence pairs; direct trace is 689/689 with zero missing,
    `test_id_count` is 1,521, and skips, failures, errors, resolution blockers,
    execution blockers, and validator blockers are all zero.
  - Final fixes: the implementation contract binds tracked deploy templates and
    examples, not ignored operator-local Caddy/env copies; real BuildKit proves
    current-source/frozen-snapshot equality. Finalization computation faults
    become generic failed validation; its strengthened regression and
    onboarding manifest update are included in the 508-test harness authority.
  - Canonical full suite: `Ran 1521 tests in 964.613s`, `OK (skipped=7)`; Ruff check passed, 306 files are formatted, and shell/JSON/diff checks passed.
  - Latest harness `/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json` has SHA-256 `1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`.
  - External state: `live_postgresql`, `operator_cli_postgresql`,
    `production_container_lifecycle`, `mcp_inspector`, `live_chatgpt_google`,
    `reviewer_gate`, and `completion_audit` remain `not_supplied`.
  - Next: freeze docs/local harness, run all seven external layers, and keep #20 unchecked.
  - Completion proof: deterministic fake-Google and simulated-ChatGPT harness,
    negative OAuth/forgery/revocation coverage, canonical dev-container checks,
    bounded live ChatGPT compatibility smoke, and the required reviewer gate.

- [ ] Implement issue #41 generic Core Asset Storage identity binding, tenant
  isolation, lifecycle, retention, and authorization.
  - Owner paths: `python/formowl_contract/`, `python/formowl_ingestion/`, storage
    and ingestion migrations/tests, `SPEC.md`, `docs/infra-spec.md`,
    `RESOURCE_EXTRACTION_SPEC.md`, workflows, and MCP boundary docs.
  - Current state: existing workspace-scoped content-addressed storage and
    `Asset` / `UploadSession` contracts remain the base. Issue #41 requires an
    explicit tenant and owner-scope boundary, `AssetOccurrence` and relationship
    lineage, byte-level deduplication separated from Asset authorization,
    recoverable upload commit/rollback, and generic lifecycle/retention policy.
  - Completion proof: all resource families use the generic Asset boundary;
    cross-user/workspace/tenant probes fail closed; duplicate bytes cannot merge
    permissions; upload, rollback, orphan cleanup, transfer, redaction, purge,
    and retention tests pass in the canonical dev container; required docs and
    reviewer gate agree.

- [ ] Complete the full KG real-evidence objective across sessions.
  - Owner paths: `docs/agent-goals/`, `.formowl/kg-eval/`, KG-owned graph,
    ontology, evaluation, and test files.
  - Current state: blocked on four real-evidence gates. The state-independent
    authority harness now reports that blocked state consistently; do not
    reinterpret harness completion as KG objective completion.
  - Completion proof: canonical authority reports must agree on 12 passed gates,
    zero failed gates, zero remaining gates, and a complete objective audit;
    canonical dev-container checks and the required reviewer gate must pass.
  - Full historical requirements and checkpoint evidence:
    `docs/archive/2026-07-11/implementation-task-breakdown.md`.

## Recent Completions

- [x] Issue #36 evidence-grounded ChatGPT × FormOwl MCP evaluation completed
  with its documented deterministic offline claim boundary and reviewer gate.
- [x] Issue #21 governed mail evidence reading milestones completed through the
  tracked local deterministic checkpoints; no production-readiness claim.
- [x] Candidate KG, ontology-guided comparison, and governed effective graph
  query slices completed without canonical graph/type writes.
- [x] Remaining backbone storage, worker, folder-ingestion, and readiness-smoke
  slices completed with their historical verification evidence archived.
- [x] Completed-slice test hardening and required reviewer gates completed.

## Issues #38-#40 Maintenance Completion

- [x] Complete issues #38, #39, and #40 without weakening authority, MCP, or
  durable-history boundaries.
  - Proof: state-independent KG authority fixtures pass in operator and clean
    layouts, including a read-only repository mount for enterprise/preflight.
  - Proof: one shared MCP protocol engine and JSONL runner preserve entrypoints,
    fail closed on missing identity, reject identity forgery, and require
    injected semantic handlers.
  - Proof: byte-identical snapshots and SHA-256 manifest under
    `docs/archive/2026-07-11/`.
  - Proof: active-file retention rules, archive-integrity tests, canonical
    dev-container suites, and a 3/3 read-only reviewer gate pass.

## Pre-Feature Production Cleanup

- [x] Remove high-confidence dead and duplicate production code without
  changing KG, MCP, permission, or compatibility behavior.
  - Production Python changed by 103 additions and 256 deletions: net `-153`
    lines. Test scenarios moved out of `formowl_gateway`; mail bundle selection,
    grant normalization, and grant expiry now have one shared implementation.
  - Empty readiness markers and an unused JSON-RPC response helper were
    removed. Retrieval uses one private implementation while preserving the
    deprecated alias signature and canonical effective-view requirement.
  - Project and Wiki servers use shared observability directly; legacy import
    paths remain as documented deprecated re-exports.
  - Proof: canonical dev-container suite 726 tests OK, full Ruff check passed,
    325 files passed format check, and the 3/3 reviewer gate agreed.

## Pre-Feature Structural Cleanup

- [x] Consolidate high-cost duplicated validation and smoke harness behavior
  before the next feature slice.
  - Eleven evaluator and smoke entrypoints now delegate common exact-key,
    SHA-256, privacy, HTTP, multipart, gateway-command, and report validation to
    shared evaluator modules while preserving their CLI and output contracts.
  - PostgreSQL live-smoke entrypoints share one startup, readiness, migration,
    and cleanup harness. Mail workflow payload checks and atomic JSON file
    persistence also have one implementation per architectural layer.
  - Real adapters, interfaces, and migrations are the primary tested surfaces.
    Previously exported name-list helpers remain thin compatibility wrappers so
    this maintenance pass does not introduce an unannounced package API break.
  - Total change: 1,334 additions and 1,514 deletions, net `-180` lines. Script
    and experiment entrypoints are net `-893` lines; the added production code
    is shared infrastructure replacing those repeated implementations.
  - Proof: canonical dev-container suite 730 tests OK, full Ruff check passed,
    331 files passed format check, `git diff --check`, and 3/3 reviewer gate passed.

## Agent Dispatch Notes

Choose the current unchecked task only when it belongs to the active role unless
the user assigns cross-role work. Read archives only for historical detail.
