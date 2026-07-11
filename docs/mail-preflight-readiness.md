# Mail Preflight Readiness

This document is the readiness artifact for the synthetic `formowl-mail` phase
tracked by issue #5 and OpenProject work package `827`.

Status: historical synthetic-fixture conformance profile. It does not describe
the repository's current PST capability; current mail ingestion and evidence
boundaries are documented in `README.md` and `docs/workflows.md`.

## Status

```text
synthetic_mail_phase_ready_production_parser_deferred
```

This profile is ready for the synthetic JSON fixture mail workflow. Its status
string intentionally does not claim PST, OST, MSG, EML, MBOX, online mailbox,
or real archive parser readiness for that historical phase.

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

At the time of issue #5, the synthetic phase could close after its tests passed
and the repository change merged. Real archive support then required a separate
assignment to choose a parser, sandbox boundary, non-synthetic fixtures or
operator-approved replay packets, and privacy/scale/malformed-archive tests.
That historical requirement was later addressed by the repository's PST path;
it is not a statement of the current capability boundary.
