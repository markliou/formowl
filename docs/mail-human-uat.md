# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a shared browser surface for colleagues to test FormOwl
mail retrieval without connecting ChatGPT. The page follows the familiar
ChatGPT interaction skeleton: collapsible conversation sidebar, centered
new-chat prompt, bottom-docked composer after the first question, and a
same-origin upload iframe opened from the composer. The landing page
intentionally has no starter prompts so the UAT log captures how colleagues
word their own requests.

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
- Accepts up to 20 EML, PST, PDF, or TXT files per request. PST is limited to
  500 MB per file; the other formats are limited to 25 MB per file; the browser
  keeps the combined selection at or below 500 MB. This temporary stdlib HTTP
  surface still buffers the multipart request in memory and is not the final
  production streaming-upload implementation.
- Parses EML subject, sender, sent time, and plain-text/HTML body; expands a PST
  batch with the existing `readpst` adapter; extracts text from text-based PDF
  files with `pdftotext`; and decodes UTF-8/UTF-16/CP950 TXT references.
- Stores source bytes by content hash and format in the private UAT state
  volume so they remain queryable after a service restart.
- Accepts a question, PO, material number, supplier, or Pull-in keyword.
- Automatically prefers recent ordering for questions containing terms such as
  `最近`, `最新`, `近期`, `latest`, or `recent`; other questions use relevance
  ordering.
- Shows bounded evidence context and stable observation citations.
- Records upload, query, and tester feedback events in a private runtime
  directory.
- Records submitted questions together with an anonymous browser visitor id,
  anonymous tab/session id, and a browser-side sequence number. Questions come
  from the composer because the example prompt menu is intentionally absent.
  The submitted-question event is written before retrieval begins, so failed
  queries remain available for diagnosis.
- Records a closed set of exploration actions: page view, sidebar toggle, new
  chat, the visible ChatGPT-style shell controls, upload open/close, coarse
  upload selection/validation, upload
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

The shared UAT upload path currently supports `.eml`, `.pst`, `.pdf`, and
`.txt`. PST is a batch source and may create many searchable mail items from
one uploaded file. PDF support uses text extraction and does not yet perform
OCR for scanned/image-only PDFs. TXT supports UTF-8, UTF-16, and CP950.

The surface still rejects `.msg`, `.ost`, and `.mbox` rather than claiming an
unsupported parser. Attachments remain part of the stored EML carrier, but
embedded attachment content is not indexed automatically. A tester can upload
a PDF or TXT attachment separately when it should become searchable.

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
the visually hidden file input through its visible “選擇檔案” label. Mobile new
chat/current-conversation actions close the sidebar drawer before returning
focus to the chat.

This is a temporary HTTP surface for an internal LAN or VPN. It is not a
replacement for the connected FormOwl OAuth and HTTPS boundary, and it must not
be exposed through a public tunnel.

## Container run

Build a dedicated UAT image so another agent rebuilding the shared
`formowl-dev:local` tag cannot remove the PST/PDF parser dependencies:

```sh
docker build --progress=plain \
  -f containers/dev/Dockerfile \
  -t formowl-may-uat:local .
```

Run the shared surface from that dedicated image:

```sh
docker run --rm \
  -p 8088:8088 \
  -v "$PWD:/workspace:ro" \
  -v "<private-corpus>:/private-corpus:ro" \
  -v "<private-cache>:/private-cache:ro" \
  -v "<private-uat-state>:/uat-state" \
  -w /workspace \
  formowl-may-uat:local \
  python scripts/mail_human_uat.py \
    --host 0.0.0.0 \
    --port 8088 \
    --corpus-root /private-corpus \
    --private-manifest /private-corpus/artifacts/domain_hard_case_manifest.private.json \
    --bundle-cache /private-cache/may-mail-evidence-bundle.private.json \
    --state-dir /uat-state
```

Do not commit the private corpus, private evidence-bundle cache, uploaded source
files, or UAT event log. The private UAT state volume contains both the
feedback JSONL and `mail-human-uat-uploads.private/`.

## Verification

Run the focused Python service tests in the dedicated UAT image:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-may-uat:local \
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
