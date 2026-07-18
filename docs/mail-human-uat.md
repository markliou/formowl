# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a shared browser surface for May, Maggie, and other
related colleagues to test FormOwl mail retrieval without connecting ChatGPT.
The first screen is a chat interface, and mail upload opens only when needed in
a same-origin custom iframe.

## Behavior

- Uses one server-loaded `MailEvidenceBundle` plus private UAT-upload bundles.
- Opens directly into a FormOwl-style conversation without login or an access
  code.
- Opens `/upload` inside a same-origin iframe from the chat composer.
- Returns uploaded-file completion to the parent chat with `postMessage`, then
  allows immediate questions about the new mail.
- Uses one shared server-bound UAT identity and workspace; the browser still
  cannot provide identity, grant, storage, parser, worker, or path controls.
- Accepts up to 20 `.eml` files per request, with a 25 MB per-file limit. The
  browser preflight also keeps the combined selection at or below 60 MB so the
  multipart request remains below the server's 64 MB request limit.
- Parses searchable subject, sender, sent time, plain-text/HTML body, and
  source observations immediately after upload.
- Stores uploaded EML bytes by content hash in the private UAT state volume so
  they remain queryable after a service restart.
- Accepts a question, PO, material number, supplier, or Pull-in keyword.
- Automatically prefers recent ordering for questions containing terms such as
  `最近`, `最新`, `近期`, `latest`, or `recent`; other questions use relevance
  ordering.
- Shows bounded evidence context and stable observation citations.
- Records upload, query, and tester feedback events in a private runtime
  directory.
- Does not call ChatGPT, write Project/Wiki systems, or mutate
  candidate/canonical graph state.

## Upload format boundary

The shared UAT upload path supports `.eml` only. It intentionally rejects
`.msg`, `.pst`, `.ost`, and `.mbox` rather than pretending that an unsupported
format was parsed. The current container has `readpst` for governed PST batch
work but no MSG parser. If the testers' real workflow cannot produce EML, add a
separately tested server-side MSG conversion adapter instead of accepting MSG
as opaque EML.

Attachments remain part of the stored EML carrier, but attachment file content
is not indexed by this UAT surface. The response reports a warning when an EML
contains attachments.

## Shared UAT boundary

This temporary shared UAT intentionally has no login or access-code gate.
Query, upload, summary, and feedback APIs are directly available to colleagues
who can reach the internal server. Uploaded mail is shared in the same UAT
index. Upload responses expose counts and warnings only; original filenames and
mail content are not echoed.

This is a temporary HTTP surface for an internal LAN or VPN. It is not a
replacement for the connected FormOwl OAuth and HTTPS boundary, and it must not
be exposed through a public tunnel.

## Container run

The canonical runtime is the repository dev container:

```sh
docker run --rm \
  -p 8088:8088 \
  -v "$PWD:/workspace:ro" \
  -v "<private-corpus>:/private-corpus:ro" \
  -v "<private-cache>:/private-cache:ro" \
  -v "<private-uat-state>:/uat-state" \
  -w /workspace \
  formowl-dev:local \
  python scripts/mail_human_uat.py \
    --host 0.0.0.0 \
    --port 8088 \
    --corpus-root /private-corpus \
    --private-manifest /private-corpus/artifacts/domain_hard_case_manifest.private.json \
    --bundle-cache /private-cache/may-mail-evidence-bundle.private.json \
    --state-dir /uat-state
```

Do not commit the private corpus, private evidence-bundle cache, uploaded EML
files, or UAT event log. The private UAT state volume contains both the
feedback JSONL and `mail-human-uat-uploads.private/`.

## Verification

Run the Python service tests in the canonical dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests -p 'test_mail_human_uat_http.py'
```

Run the embedded browser JavaScript smoke in the isolated Node runtime:

```sh
docker run --rm -v "$PWD:/workspace:ro" -w /workspace \
  node:20-bookworm-slim node tests/js/mail_human_uat_ui_smoke.mjs
```

The JavaScript smoke executes the actual inline chat and upload scripts. It
covers modal open/close, recent-query ordering, IME Enter handling,
`postMessage` origin/source rejection, trusted iframe completion, upload
completion/close messages, and client-side file count/type/size preflight.
