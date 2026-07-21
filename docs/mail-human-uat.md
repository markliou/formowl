# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a shared browser surface for colleagues to test the
FormOwl-plus-conversation experience without connecting the ChatGPT product UI.
The page follows the familiar ChatGPT interaction skeleton: collapsible
conversation sidebar, centered new-chat prompt, bottom-docked composer after
the first question, and a same-origin upload iframe opened from the composer.
The landing page intentionally has no starter prompts so the UAT log captures
how colleagues word their own requests.

## Behavior

- Uses one server-loaded `MailEvidenceBundle` plus private UAT-upload bundles.
- Sends each submitted chat turn through a private Unix socket to an isolated
  `codex app-server` sidecar. Codex is the conversation engine: it can answer
  conversationally, ask a clarification question, re-render the latest
  governed evidence, or invoke the one structured
  `search_formowl_evidence` dynamic tool.
- Uses persistent app-server threads so failed-turn cleanup can delete actual
  server state. Pinned Codex `0.144.6` emits the authoritative final agent
  message through `item/completed`; `turn/completed` may report
  `itemsView=notLoaded` with an empty `items` list.
- Treats FormOwl as governed MCP-style evidence tooling rather than as the
  chatbot. Explanations, `我看不懂`, summaries, and presentation changes do
  not automatically trigger another evidence search.
- Keys bounded conversation history, latest governed evidence, compatibility
  task frames, and turn serialization to the same hash of anonymous visitor id
  plus tab/session id. New chat clears only that exact visitor/session pair.
- Uses source-neutral structured tool arguments: standalone `query_text`,
  literal `required_terms`, `sort`, and `limit`. Literal constraints are
  checked against the complete source record's subject and body, not
  against procurement-specific routing rules.
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
- Accepts ordinary conversation plus evidence requests across the preloaded and
  uploaded source adapters. The browser does not classify the prompt or choose
  retrieval ordering; the conversation orchestrator decides whether a FormOwl
  tool is needed and supplies the structured tool arguments.
- Shows bounded evidence context and stable observation citations.
- Records upload, chat, FormOwl tool query, orchestration outcome, and tester
  feedback events in a private runtime directory.
- Records submitted questions together with an anonymous browser visitor id,
  anonymous tab/session id, and a browser-side sequence number. Questions come
  from the composer because the example prompt menu is intentionally absent.
  The submitted-question event is written before model or retrieval work
  begins, so failed turns remain available for diagnosis.
- Records a closed set of exploration actions: page view, sidebar toggle, new
  chat, the visible ChatGPT-style shell controls, upload open/close, coarse
  upload selection/validation, upload
  submission/completion, and query result/error.
- Visible shell controls never fail silently: controls not implemented in this
  temporary UAT show a small in-page explanation and record only a closed
  control name. This lets the operator see which familiar controls colleagues
  try while preventing arbitrary DOM labels or click coordinates from entering
  analytics.
- Does not connect to the ChatGPT product UI, write Project/Wiki systems, or
  mutate candidate/canonical graph state. The HTTP container starts only
  Codex's stdio-to-Unix-socket proxy. The actual app-server runs in a separate
  non-root container that never mounts the FormOwl repository, private corpus,
  evidence cache, upload state, or authentication input during serving.
- Runs Codex from a dedicated empty workspace with a generated, integrity-
  checked home. Authentication is provisioned in a separate one-shot container
  from either an API key or an explicitly authorized existing Codex ChatGPT
  auth cache. Effective config, MCP inventory, skills, and apps are attested
  after every app-server connection; startup fails if MCP servers, enabled
  skills, accessible apps, unsafe sandbox settings, or non-FormOwl capability
  config is found.
- Disables shell, unified exec, browser, computer use, apps, plugins, hooks,
  image generation, subagents, memories, goals, remote plugins, tool
  suggestions, and workspace dependency tools. Threads use `read-only`; turns
  use the `readOnly` sandbox policy with model-tool network access disabled.
  The FormOwl dynamic tool is the only model-visible business-data capability.

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
- Orchestration traces record the closed action, model name, tool-call flag,
  tool name, query/required-term hashes, result count, and assistant-response
  hash. They do not store credentials, raw Codex protocol stream, reasoning, or
  dynamic-tool payload.
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

## Isolated container run

Build the non-root UAT runtime target. The application source is baked into the
image, so neither runtime container mounts the repository:

```sh
docker build --progress=plain \
  -f containers/dev/Dockerfile \
  --target formowl-uat-runtime \
  -t formowl-may-uat:local .
```

Prepare four separate host directories owned by runtime uid/gid `65532`.
`<private-cache>` must be writable because the evidence bundle is rebuilt when
the cache is absent. Remove an outdated cache deliberately before restart; the
loader does not silently decide that an existing cache is stale:

```sh
sudo install -d -m 0700 -o 65532 -g 65532 \
  "<codex-state>" \
  "<codex-socket-dir>" \
  "<private-cache>" \
  "<private-uat-state>"
```

Provision the explicitly authorized existing Codex ChatGPT login once. The
auth cache is streamed over stdin into the isolated runtime state; the
one-shot container does not mount the developer's normal Codex home and sees
no FormOwl corpus, cache, repository, upload state, or HTTP port:

```sh
docker run --rm -i \
  --read-only \
  --user 65532:65532 \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  -v "<codex-state>:/codex-state" \
  formowl-may-uat:local \
  python scripts/mail_human_uat_codex_engine.py init \
    --state-dir /codex-state \
    --chatgpt-auth-stdin \
  < "$HOME/.codex/auth.json"
```

Start the isolated Codex engine. It mounts only its dedicated state and the
private socket directory; the authentication input is no longer present:

```sh
docker run --rm -d \
  --name formowl-codex-uat-engine \
  --read-only \
  --user 65532:65532 \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m \
  -v "<codex-state>:/codex-state" \
  -v "<codex-socket-dir>:/run/formowl-codex" \
  formowl-may-uat:local \
  python scripts/mail_human_uat_codex_engine.py serve \
    --state-dir /codex-state \
    --socket-path /run/formowl-codex/app-server.sock
```

Finally, start the shared HTTP surface. It mounts the corpus/cache/UAT state and
the socket, but not Codex state or authentication input:

```sh
docker run --rm \
  --name formowl-mail-uat \
  --read-only \
  --user 65532:65532 \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m \
  -p 8088:8088 \
  -v "<private-corpus>:/private-corpus:ro" \
  -v "<private-cache>:/private-cache" \
  -v "<private-uat-state>:/uat-state" \
  -v "<codex-socket-dir>:/run/formowl-codex" \
  formowl-may-uat:local \
  python scripts/mail_human_uat.py \
    --host 0.0.0.0 \
    --port 8088 \
    --corpus-root /private-corpus \
    --private-manifest /private-corpus/artifacts/domain_hard_case_manifest.private.json \
    --bundle-cache /private-cache/may-mail-evidence-bundle.private.json \
    --state-dir /uat-state \
    --codex-socket /run/formowl-codex/app-server.sock \
    --codex-runtime-state-dir /codex-state
```

`FORMOWL_UAT_CODEX_MODEL` is optional; when omitted, Codex selects its current
default. `FORMOWL_UAT_CODEX_REASONING_EFFORT` defaults to `low`.
`FORMOWL_UAT_MODEL` and `FORMOWL_UAT_REASONING_EFFORT` remain compatibility
aliases. The HTTP server no longer accepts API-key, Codex-home, or
Codex-workspace arguments.

The one-shot initializer validates the streamed cache as a ChatGPT-mode Codex
`auth.json`, copies only that credential cache into isolated state, forces
`forced_login_method = "chatgpt"`, writes a locked-down `config.toml`, disables
all bundled system skills by their pinned-version paths, and records the login
method plus config hash. The serving sidecar refuses an unprovisioned,
modified, symlinked, or non-empty workspace. Never mount the developer's
normal `~/.codex`, session history, memories, plugin cache, ChatGPT browser
session, or other Codex state.

The older one-shot `--api-key-file` mode remains available for a future
dedicated UAT account. It is not required for the currently authorized
server-login deployment.

Codex app-server is an experimental Codex integration surface. Keep it pinned
to the version in `containers/dev/Dockerfile`, validate the JSON schemas when
upgrading, and never publish the app-server Unix socket to testers. Testers use
only the FormOwl HTTP page.

Do not commit the private corpus, private evidence-bundle cache, uploaded source
files, UAT event log, Codex state, or socket. The UAT state and Codex state are
separate secret-bearing directories.

## Verification

Run the focused Python service tests in the dedicated UAT image:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-may-uat:local \
  bash -lc \
  "python -m unittest discover -s tests -p 'test_mail_human_uat_orchestrator.py' \
  && python -m unittest discover -s tests -p 'test_mail_human_uat_http.py'"
```

Run the embedded browser JavaScript smoke in the isolated Node runtime:

```sh
docker run --rm -v "$PWD:/workspace:ro" -w /workspace \
  node:20-bookworm-slim node tests/js/mail_human_uat_ui_smoke.mjs
```

The JavaScript smoke executes the actual inline chat and upload scripts. It
covers modal open/close, `/api/chat` routing without browser-side retrieval
classification, direct-answer and evidence rendering, IME Enter handling,
`postMessage` origin/source rejection, trusted iframe completion, upload
completion/close messages, new-chat session rotation, and client-side file
count/type/size preflight.

The completed isolated-runtime verification includes:

- real direct-stdio and Unix-socket app-server runtime attestation;
- a non-root three-container smoke separating one-shot auth init, Codex
  serving, and the HTTP/client process; and
- a 951-test canonical dev-container suite, full Ruff, 275-file format check,
  and `git diff --check`.

Runtime attestation checks every feature disabled by the hardened command.
When response validation, durable result logging, or local history persistence
fails after a Codex turn, the service discards that persistent Codex thread so
the next request cannot inherit hidden divergent state.

The authenticated live deployment gate passed on the `8088` surface using the
isolated, explicitly authorized server Codex ChatGPT login. The active model
was `gpt-5.6-sol`: an ordinary greeting returned `answer_without_tool` with zero
FormOwl calls, while the source-backed 文顥/pull-in question invoked
`search_formowl_evidence` exactly once and returned six governed evidence
items. The verification conversation was deleted afterward.
