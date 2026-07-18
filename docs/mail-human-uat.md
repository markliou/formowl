# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a shared browser surface for colleagues to test FormOwl
mail retrieval without connecting ChatGPT. The page follows the familiar
ChatGPT interaction skeleton: collapsible conversation sidebar, centered
new-chat prompt, starter cards, bottom-docked composer after the first
question, and a same-origin upload iframe opened from the composer.

## Behavior

- Uses one server-loaded `MailEvidenceBundle` plus private UAT-upload bundles.
- Opens directly into a FormOwl-style conversation without login or an access
  code.
- Uses a high-fidelity ChatGPT-style light layout while retaining FormOwl
  branding and the mail-evidence-only behavior boundary.
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
- Records submitted questions together with an anonymous browser visitor id,
  anonymous tab/session id, a browser-side sequence number, and whether the
  question came from the composer or a starter prompt. The submitted-question
  event is written before retrieval begins, so failed queries remain available
  for diagnosis.
- Records a closed set of exploration actions: page view, sidebar toggle, new
  chat, starter prompt, the visible ChatGPT-style shell controls, upload
  open/close, coarse upload selection/validation, upload
  submission/completion, and query result/error.
- Visible shell controls never fail silently: controls not implemented in this
  temporary UAT show a small in-page explanation and record only a closed
  control name. This lets the operator see which familiar controls colleagues
  try while preventing arbitrary DOM labels or click coordinates from entering
  analytics.
- Does not call ChatGPT, write Project/Wiki systems, or mutate
  candidate/canonical graph state.

## UAT behavior capture

The temporary UAT intentionally captures enough private evidence to understand
how colleagues discover the interface and what they ask:

- Question text is recorded only after the user sends it.
- Button and workflow events use closed action names and bounded enum/count
  details.
- Anonymous visitor and session ids are random browser-local identifiers. They
  are analytics labels, not authenticated identities and never authorize mail
  access.
- Client events include a monotonic per-tab sequence number so the operator can
  reconstruct user action order even when the threaded HTTP server persists
  concurrent requests in a different physical order.
- The browser rotates the anonymous visitor id after 30 days. The private event
  store removes events older than 30 days at startup and daily compaction, and
  caps the active JSONL file at 16 MiB by retaining the newest complete events.
- The page does not record draft/typing text, individual keystrokes, mouse
  coordinates, original upload filenames, IP-derived identity, device
  fingerprint, or attachment content.
- Events remain in `mail-human-uat-events.private.jsonl` with mode `0600` in the
  private UAT state volume and are not committed to Git.
- `/api/session-summary` exposes only aggregate counts. Raw submitted questions
  and event sequences remain in the private event log for later UX analysis.

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

All mutating browser requests require an exact same-origin `Origin`/`Host`
match, and cross-site `Sec-Fetch-Site` requests are rejected. This preserves the
no-login UAT experience while preventing another LAN webpage from silently
submitting queries, feedback, analytics, or generated EML into the shared test
index.

Keyboard users can focus the composer, shell controls, feedback controls, and
the visually hidden file input through its visible “選擇 EML” label. Mobile new
chat/current-conversation actions close the sidebar drawer before returning
focus to the chat.

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
