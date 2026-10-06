# Dual-Track UAT and KG Research Coordinator Goal

## Lifecycle

- Label: `complete`
- Status: document-first POC complete; GitHub issue #55 closed with successful
  completion comment ID `5315010812`.
- Checkpoint: `2026-08-17`
- Retention: keep only the current objective, proof, boundaries, and next action;
  archive before 250 lines.

## Current Objective

The internal UAT POC now uses the document-first route:

```text
UAT webpage
  -> deployed Codex sidecar and persistent thread
  -> exactly one read-only document MCP call
  -> authorized existing-export document content
  -> Codex synthesis
  -> newly rendered DOM answer
```

This route supersedes the stale exact-77 private-reconciliation and
KG/ontology path. Do not resume that reconciliation as the completion route
for this POC.

## Completed Acceptance

### Local real-Chromium UAT

- One real Chromium click produced one same-origin `POST /api/chat`, HTTP
  status `200`; there was no retry, fallback, or second click.
- The turn made exactly one dynamic document-tool invocation. MCP
  attempted/successful delta was `1/1`, with no delayed second call.
- The newly rendered DOM exactly equaled the nonempty `assistant_text`.
- MCP response and model-reinjection commitments were equal, and the summary
  commitments also matched.
- Recursive checks of the public response/network JSON and DOM found zero
  leaked document `content` or `snippet`, sentinel values, or raw references.
- Safe acceptance JSON SHA-256:
  `sha256:6e3f25bdc4329129ecb5571a33d66815d04e4ea646904b16497d9254a13941cc`.

### Independent private-oracle UAT

- Agy used its independently established private question and oracle for one
  real click and one `POST /api/chat`, which returned HTTP `200`.
- The answer was present and matched the private oracle. No error, retry,
  second submit, or second MCP call occurred.
- Server chat/MCP-attempted/MCP-successful accounting changed from `1/1/1` to
  `2/2/2`: delta `+1/+1/+1`, stable for an additional eight seconds.
- Safe post-Agy accounting JSON SHA-256:
  `sha256:26689a84986462100268971d75ed71cdffd41c3d1edcce258980112439de7c06`.
- Both independent reviewer checkpoints returned `AGREE`.

### Safety boundary

- The repair did not broaden the global `_guards` authorized-evidence scalar
  allowlist.
- Full document content is admitted only through the dedicated document-UAT
  internal validation and same-tool model-reinjection path.
- Public `/api/chat` projection and browser rendering exclude document
  `content` and `snippet`; path, backend, credential, sentinel, and raw-reference
  checks remain fail closed.

## Live State

Verified after local and independent acceptance:

```text
UAT web: running on 192.168.71.211:8089
read-only document MCP: running on 127.0.0.1:8093
Codex sidecar: running
CDP endpoints: loopback-only
ordinary-bridge Chromium and FormOwl page: running
```

LAN connections to ports `8093`, `9222`, and `9233` remained refused. All three
UAT services and the bridge browser remain running. Do not restart or stop them
merely to update durable state.

## Authority and Claim Boundary

- Methodology authority remains valid but blocked:
  `authority_valid=true`, `methodology_ready=false`, `status=blocked`.
- No `--require-ready` claim is authorized.
- The POC reused an authorized existing export; PST parsing, extraction, and
  re-materialization were not rerun.
- The route is read-only and performed no canonical graph write.
- KG and ontology were not invoked.
- No expected answer, oracle answer, private document content, token, or
  private runtime path is recorded here.
- This is not KG/ontology methodology-quality UAT, a comparative-method result,
  production readiness, or production hardening.

## Track 2 Boundary

PostgreSQL remains canonical and Neo4j remains rejected. Existing Track 2
diagnostics remain separate historical research evidence. They do not gate,
explain, or upgrade this document-first POC.

## Next Action

1. Preserve the currently running UAT services and browser until the owner no
   longer needs the live surface.
2. Preserve the completed GitHub issue #55 closure record and successful
   comment ID `5315010812`.
3. Keep methodology and production-readiness claims blocked unless their
   independent authority gates later pass.

## Completion

The document-first UAT POC and its local plus independent private-oracle
acceptance are complete. GitHub issue #55 is closed with successful completion
comment ID `5315010812`; this goal is `complete` and does not retain an exact-77
reconciliation blocker.
