# Issue #56 PM Checkpoint — 2026-09-29

**Status: WIP diagnostic checkpoint; not release-ready.**

## Scope

This is a docs-only weekly progress checkpoint. It records already available
UAT and methodology evidence; it is not a new provider acceptance run and does
not claim completion, readiness, KG/ontology superiority, or production
acceptance. No private source, prompt, credential, raw provider response, or
private log is included.

## UAT progress

- The retained UAT deployment is `formowl-uat-8088`, exposed on host port
  `8088` and backed by the internal service port `8766`.
- The latest recorded provider-free basic path passed `5/5`: homepage HTTP
  `200`, `/api/health` reported `status=ok` and
  `query_service_connected=true`, new session creation worked, reset rotated
  the conversation cookie, and logout cleared the cookie.
- The recorded Sep 24 browser diagnostics also passed the benign ordinary
  MCP-zero/reload/reset path and synthetic provider-free shared-core checks.
  These are useful transport and state-management diagnostics only; they are
  not real-provider or private-source acceptance.
- No fresh live UAT request was made for this checkpoint. The current sandbox
  cannot access the Docker socket, so the deployment was not revalidated here.

## Provider failure isolation

- A recorded business-prompt attempt received provider HTTP `408` with
  `invalid_request_error`, before MCP execution, with safe `call_count=0` and
  no accepted citations.
- This classifies the event as a pre-MCP provider failure. It does **not** mean
  that the KG, source data, or MCP query returned no result.
- Existing provider bridge tests use a localhost Responses stub. They validate
  error classification, safe projection, and citation handling, but do not
  establish why the external provider rejected the real request.
- Real business-prompt provider acceptance, cited answer acceptance, and
  private-source acceptance remain open.

## Methodology and release boundary

- The current local authority probe reports `methodology_ready=false` and is
  blocked because the host runtime lacks the required tokenizer/CJK dependency
  probe. The canonical dev-container records remain the authoritative runtime
  evidence when available, but they also retain the four blocked methodology
  gates.
- The four open gates are source completeness against a raw oracle, accepted
  execution-fingerprint binding, same-pipeline real-source ablation, and
  independent real-user final-answer acceptance.
- Issue #56 step 4 remains `in-progress`. The implementation is therefore a
  bounded diagnostic/demo path, not a release-ready KG research result.

## PM decision point

Track two decisions separately:

1. **Product/demo transport:** the 8088 page, health endpoint, session state,
   reset, logout, and provider-free browser diagnostics are useful evidence.
2. **KG research readiness:** remains blocked until the authority gates and
   real provider/source acceptance are satisfied.

Passing the first track must not be reported as completion of the second.

## Next bounded actions

1. Align the running UAT image, source revision, startup command, and port
   mapping so deployment evidence is traceable.
2. Use a benign, non-private provider request to capture only allowlisted
   request-shape/error fields and distinguish provider rejection from MCP/KG
   no-data.
3. Re-run canonical checks in the dev container and preserve the blocked
   authority state until all required gates have evidence.
4. Do not send private mail/document content to an unconfirmed provider.

## Explicit exclusions

This checkpoint excludes implementation changes, credentials, raw business or
source data, private snapshots, private logs, build output, `node_modules`,
package files, archived documentation, and all other broad modified or
untracked paths in the worktree.
