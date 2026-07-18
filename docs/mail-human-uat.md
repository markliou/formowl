# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a small browser surface for May or Maggie to upload new
RFC822 mail and test permission-bound mail evidence retrieval without
connecting ChatGPT.

## Behavior

- Uses one server-loaded `MailEvidenceBundle` plus private UAT-upload bundles.
- Binds the requester user and workspace from that bundle on the server.
- Accepts up to 20 `.eml` files per request, with a 25 MB per-file limit.
- Parses searchable subject, sender, sent time, plain-text/HTML body, and
  source observations immediately after upload.
- Stores uploaded EML bytes by content hash in the private UAT state volume so
  they remain queryable after a service restart.
- Accepts a question, PO, material number, supplier, or Pull-in keyword.
- Shows bounded evidence context and stable observation citations.
- Records upload, query, and tester feedback events in a private runtime
  directory.
- Does not call ChatGPT, write Project/Wiki systems, or mutate
  candidate/canonical graph state.

## Upload format boundary

The temporary UAT upload path supports `.eml` only. It intentionally rejects
`.msg`, `.pst`, `.ost`, and `.mbox` rather than pretending that an unsupported
format was parsed. The current container has `readpst` for governed PST batch
work but no MSG parser. If May's real workflow cannot produce EML, add a
separately tested server-side MSG conversion adapter instead of accepting MSG
as opaque EML.

Attachments remain part of the stored EML carrier, but attachment file content
is not indexed by this UAT surface. The response reports a warning when an EML
contains attachments.

## Access boundary

The page itself contains no mail evidence. Every upload, evidence, and feedback
API call requires a server-configured UAT access code in the
`X-FormOwl-UAT-Code` header. The code is entered in the page and retained only
in browser `sessionStorage`; it is not placed in the URL.

The browser cannot provide user, workspace, grant, storage, parser, worker, or
raw-path controls. Uploaded mail is always bound to the May bundle's
server-configured owner and workspace. Upload responses expose counts and
warnings only; original filenames and mail content are not echoed.

This is a temporary HTTP surface for an internal LAN or VPN. It is not a
replacement for the connected FormOwl OAuth and HTTPS boundary, and it must not
be exposed through an unauthenticated public tunnel.

## Container run

The canonical runtime is the repository dev container:

```sh
docker run --rm \
  -p 8088:8088 \
  -v "$PWD:/workspace:ro" \
  -v "<private-corpus>:/private-corpus:ro" \
  -v "<private-cache>:/private-cache:ro" \
  -v "<private-uat-state>:/uat-state" \
  -e FORMOWL_MAIL_UAT_ACCESS_CODE="<temporary-code>" \
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
files, access code, or UAT event log. The private UAT state volume now contains
both the feedback JSONL and `mail-human-uat-uploads.private/`.
