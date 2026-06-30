# Mail Preflight Readiness

This document is the readiness artifact for the synthetic `formowl-mail` phase
tracked by issue #5 and OpenProject work package `827`.

## Status

```text
synthetic_mail_phase_ready_production_parser_deferred
```

The repository is ready for the synthetic JSON fixture mail workflow. It is not
claiming production PST, OST, MSG, EML, MBOX, online mailbox, or real archive
parser readiness.

## Completed Scope

- Official Mail Evidence Adapter boundary is documented.
- JSON-backed fixture mail extraction emits thread, header, message, body
  segment, attachment occurrence, and folder occurrence observations.
- Message fingerprints and occurrence ids preserve duplicate folder/mailbox
  appearances without dropping lineage.
- Local mail evidence packs and deterministic search index are available over
  persisted observations.
- Mail observations can be converted into reviewable `SemanticMetadata`,
  `CandidateAtom`, and `CandidateRelation` proposals.
- Case-progress answers can report updates, blockers, owners, next actions,
  and deadlines with observation citations.
- Integration tests cover fixture mail source through observations, evidence
  pack, candidate proposals, case-progress answer, and readiness artifact.

## Dependencies

- `AssetStore`, `ObjectStore`, `IngestionJob`, `ExtractorRun`, and
  `ObservationStore`.
- `SemanticMetadataStore`, `CandidateAtomStore`, and `CandidateRelationStore`.
- FormOwl permission scopes, source references, and raw-path leak guards.
- The Mail Evidence Adapter boundary in `RESOURCE_EXTRACTION_SPEC.md`.

## Parser Risks

- Real PST/OST parsing can require large local scratch space.
- Malformed, encrypted, or partially corrupt archives need parser isolation and
  failure reporting.
- Duplicate exports must preserve every archive, mailbox, folder, message, and
  attachment occurrence.
- Attachment bytes require a separate policy for when they become independent
  assets.

## Privacy Guardrails

- Raw mailbox paths, local filesystem paths, account credentials, object-store
  roots, SQL, and parser scratch paths must not appear in public records.
- Mail search returns observation-backed snippets, not raw archive bytes.
- Candidate extraction remains proposal-only and cannot commit canonical graph
  state.
- Case-progress answers cite observations and do not grant raw asset access.

## Schedule Assumptions

The synthetic phase can be closed in project tracking after tests pass and the
repository change is merged. Real archive support requires a separate scheduled
assignment that chooses a parser, sandbox boundary, non-synthetic fixtures or
operator-approved replay packets, and privacy/scale/malformed-archive tests.
