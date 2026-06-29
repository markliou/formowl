# Local Data Resource Inbox

The local data resource inbox is a trusted internal ingress helper for Phase 0
deployments. It watches a caller-specified local folder only from inside trusted
service code and turns stable files into normal FormOwl ingestion records.

It is not a ChatGPT-facing file browser, NAS browser, object-store control
surface, or parser configuration UI.

## MVP Flow

```text
trusted local folder
  -> stable file detection
  -> Asset registration
  -> managed ObjectStore copy/hash
  -> IngestionJob
  -> deterministic extractor when configured
  -> ExtractorRun
  -> persisted Observation
  -> safe public scan report
```

The implementation lives in `python/formowl_ingestion/folder_inbox.py` and
reuses the existing ingestion spine:

- `register_asset_from_local_file()`
- `create_ingestion_job()`
- `run_ingestion_job()`
- `PlainTextObservationExtractor`

The first supported deterministic path is intentionally narrow: `.txt` and
`.md` files can run through the plain-text extractor when the caller configures
that adapter.

## Stability Policy

The scanner is deterministic and does not sleep. A file is considered stable
only when the caller provides a previous `FolderFileStabilitySnapshot` for the
same source-file token and the current snapshot matches:

- file size
- modified time in nanoseconds
- SHA-256 content hash

If no matching previous snapshot exists, or any field differs, the file is
reported as `deferred_unstable`.

Unstable files have zero durable pipeline side effects:

- no `Asset`
- no ObjectStore payload or metadata copy
- no `IngestionJob`
- no `ExtractorRun`
- no `Observation`
- no durable audit event claiming ingestion happened

## Idempotency

The scanner computes expected FormOwl asset and job identities before writing.
Re-scanning the same stable content does not create duplicate asset or job
records.

Asset identity is content-oriented for this inbox MVP. The source reference uses
`source_system=local_folder_inbox`, `source_type=file_content`, and
`source_id=<content_hash>`, so the public resource identity is not tied to a raw
folder path or filename.

If a matching asset or job already exists, the scanner reports the existing
record instead of overwriting completed job state or rerunning a succeeded
extractor job.

## Public Report Boundary

`FolderInboxScanResult.to_dict()` is the safe public scan report. It may expose:

- FormOwl asset and job ids
- governed `formowl://object/...` locators
- content hashes
- file size
- MIME type
- status values
- extractor run ids
- observation counts
- aggregate counts

It must not expose:

- trusted folder paths
- source file paths or filenames
- ObjectStore local roots
- parser-local paths
- worker scratch paths
- database or storage backend internals

The caller-held stability snapshots are separate from the public report and are
passed back into the next scan.

## Out Of Scope

This inbox is generic infrastructure. It does not implement mail parsing,
financial statement reconciliation, canonical graph writes, wiki publishing, or
business-domain validation.

`formowl-mail` should consume registered assets and ingestion jobs from this
shared ingress path instead of implementing a separate mail-only folder scanner.
