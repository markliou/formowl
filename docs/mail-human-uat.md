# Mail Human UAT Web Surface

Lifecycle: temporary development/UAT harness.

This branch provides a small browser surface for May or Maggie to test
permission-bound mail evidence retrieval without connecting ChatGPT.

## Behavior

- Uses one server-loaded `MailEvidenceBundle`.
- Binds the requester user and workspace from that bundle on the server.
- Accepts a question, PO, material number, supplier, or Pull-in keyword.
- Shows bounded evidence context and stable observation citations.
- Records query and tester feedback events in a private runtime directory.
- Does not upload mail, call ChatGPT, write Project/Wiki systems, or mutate
  candidate/canonical graph state.

## Access boundary

The page itself contains no mail evidence. Every evidence and feedback API call
requires a server-configured UAT access code in the
`X-FormOwl-UAT-Code` header. The code is entered in the page and retained only
in browser `sessionStorage`; it is not placed in the URL.

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

Do not commit the private corpus, private evidence-bundle cache, access code, or
UAT event log.
