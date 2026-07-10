# Agent Handoff Log

Use this log for short cross-session and cross-machine notes. Keep detailed
status in each role's goal file and task completion in
`docs/implementation-task-breakdown.md`.

## 2026-07-10

- No-training programmatic ontology ablation completed for the accepted active
  goal. The EXM/PST 50,000-case evaluator now compares regex, raw
  `jieba + SentencePiece`, data-driven programmatic ontology, frozen-profile
  programmatic ontology, and the prior weak-label MLP programmatic ontology in
  one run over the same generated benchmark shape. Safe tracked aggregate:
  `experiments/kg_ontology_v2_coordination/results/exm_no_training_programmatic_ontology_50000_summary_2026-07-10.json`.
  Result: regex current ontology 10,000/50,000; raw `jieba + SentencePiece`
  ontology 18,176/50,000 with 0/5,000 no-match guards; data-driven
  programmatic ontology 33,277/50,000 with all guards passing; frozen-profile
  programmatic ontology 43,976/50,000 with 33,976/40,000 positive cases,
  5,000/5,000 no-match guards, and 5,000/5,000 denied guards; weak-label MLP
  programmatic ontology 43,369/50,000 with 33,369/40,000 positives and all
  guards passing. Current method judgment: the executable programmatic
  ontology layer is effective, but the self-trained weak-label MLP is not
  justified as the stable default because the zero-training frozen profile is
  +607 passed cases better in this run. Engineering reviewer `Meitner` blocked
  once because the frozen profile model hash did not include the actual
  scoring coefficients; the blocker was fixed by data-binding
  `_FROZEN_PROFILE_SCORE_RULES` into both scoring and `model_hash`, then
  rerunning the 50,000-case evaluation. Verification after the fix:
  dev-container focused lexical ontology tests 21 OK, full 50,000-case
  evaluation completed, saved public report validation blockers=[], full
  unittest 630 OK, Ruff check/format-check passed, KG acceptance
  `passed_with_explicit_limits`, tracked summary JSON parse passed, and
  `git diff --check` passed. Reviewer gate passed 3/3: `Meitner`
  engineering agreed after the hash-binding fix, `Singer` governance/safety
  agreed, and `Gibbs` research method agreed. BGE-M3 through FlagEmbedding is
  documented as the preferred future optional true frozen neural adapter, but
  it was not executed in this default-dev-container slice. Claim remains
  candidate-only and excludes raw mail content, query payloads, private rows or
  paths, canonical graph/type/user-graph/wiki mutation, BGE execution evidence,
  parser readiness, business answer generation, and production readiness.

## 2026-07-09

- Programmatic ontology redesign slice completed after the user rejected the
  prior ontology as ineffective. The EXM 50,000-case evaluator now includes
  `graph_neural_programmatic_ontology`, which compiles ontology behavior before
  KG edge construction using document-frequency graph gates, protected mention
  typing, deterministic weak-label MLP CJK candidate scoring, and
  exact-candidate-only ontology retrieval. Safe tracked aggregate:
  `experiments/kg_ontology_v2_coordination/results/exm_programmatic_ontology_50000_summary_2026-07-09.json`.
  Result: regex current ontology 10,000/50,000, raw `jieba + SentencePiece`
  ontology 18,176/50,000 with 0/5,000 no-match guards, and graph-neural
  programmatic ontology 43,369/50,000 with 33,369/40,000 positive cases,
  5,000/5,000 no-match guards, and 5,000/5,000 denied guards. The slice also
  fixed an identifier-regex bug where plain lowercase words were being
  promoted into `id:*` candidates. Maxwell's reviewer blocker on tampered arm
  summaries led to validator recomputation of summary hashes, pass-rate math,
  bucket totals, best-arm selection, and aggregate deltas. Descartes's
  reviewer blocker on unsupported "neural" wording led to replacing the
  hand-weighted sigmoid heuristic with deterministic weak-label MLP scorer
  `formowl_exm_weak_label_cjk_mlp_v1` and model-hash/training-count evidence.
  Darwin's follow-up blocker on result-kind summary counts led to validator
  checks that positive/no-match/permission-denied passed counts sum correctly,
  stay within case-kind totals, and match bucket passed counts.
  Canonical verification passed for the rebuilt dev-container focused lexical
  ontology tests 12 OK, full 50,000-case evaluation, saved public report
  validation blockers=[], and full unittest 621 OK; full verification is
  recorded in the KG goal file.
  Claim remains candidate-only and excludes raw
  mail content, query payloads, private rows/paths, canonical graph/type/user-
  graph/wiki mutation, parser readiness, and production readiness.
  Arendt's follow-up blocker on negative public counts was fixed by rejecting
  negative or bool arm summary and bucket counts before validating derived
  sums. Euclid's follow-up blocker on fake bucket passed keys was fixed by
  requiring bucket passed keys to be bucket-count subsets and requiring each
  bucket passed count to stay within its bucket total. Galileo's follow-up
  blocker on fake bucket totals was fixed by requiring each arm's bucket totals
  to match the report-level `case_bucket_counts`. Latest canonical
  verification: focused lexical ontology tests 16 OK, full unittest 625 OK,
  full 50,000-case evaluation completed, saved public report validation
  blockers=[], Ruff check/format-check passed, tracked summary JSON parse
  passed, and `git diff --check` passed.
  Confucius's follow-up blocker on report-level fake buckets was fixed by
  restricting report-level case buckets to the case generator's allowed bucket
  set and checking access/no-match/positive bucket totals against case-kind
  counts. Latest canonical verification after that fix: focused lexical
  ontology tests 17 OK, full unittest 626 OK, saved public report validation
  blockers=[], Ruff check/format-check passed, and `git diff --check` passed.
  Reviewer gate passed 3/3 after fixes: `Halley` engineering agreed,
  `Socrates` governance/safety agreed, and `Bohr` research method agreed.

- EXM 50,000-case lexical ontology evaluation completed for the user's
  `jieba + SentencePiece` tokenizer plan over all currently available EXM PST
  parsed corpora. The safe tracked aggregate is
  `experiments/kg_ontology_v2_coordination/results/exm_lexical_ontology_50000_summary_2026-07-09.json`.
  Result: regex KG and regex ontology each passed 10,000/50,000, with 0/40,000
  positive cases and all no-match/denied guards passing; the jieba plus
  SentencePiece KG and ontology arms each passed 16,811/50,000, with
  11,811/40,000 positive cases, 0/5,000 no-match guards, and all denied guards
  passing. This
  proves a positive lexical retrieval effect but also a severe false-positive
  risk; ontology added no incremental lift over lexical KG in this run. The
  experiment script now uses indexed component evidence and bounded fallback
  scans so 50,000-case scoring completes, and SentencePiece trainer output is
  redirected to private logs. Ptolemy's reviewer blocker on saved-report
  validation was fixed by recomputing completion during validation and adding
  a tamper regression test. Reviewer gate passed 3/3 with `Ptolemy`, `Dalton`,
  and `Lagrange`. Canonical verification passed: focused lexical ontology
  tests 6 OK, full unittest 615 OK, full Ruff check/format-check, saved public
  report validation, tracked summary JSON parse, and `git diff --check`.
  Claim remains candidate-only: no raw mail content, query text, private rows,
  private paths, canonical graph/type/user-graph/wiki mutation, or production
  readiness is claimed.

## 2026-07-07

- #21 ontology-native factorial redesign started after the user challenged the
  negative ontology ablation as unfairly KG-first. The pre-registration draft
  is `docs/mail-ontology-native-factorial-design.md`. Four math/research
  subagents shaped the design: `Jason` and `Maxwell` required a rework toward
  typed proof graphs and deterministic mail-native frames before graph fusion;
  `Hypatia` allowed the design only as pre-registered/exploratory unless
  holdout or correction supports confirmatory claims; and `Planck` proposed a
  staged 324-arm ontology-native grid plus 8 controls instead of arbitrary
  ordered permutations. The next implementation must build typed segment,
  entity, mail-frame, value, and message-context state before opening the
  private hard-case manifest; compare identical case hashes against KG-only;
  preserve the `.test-tmp` intermediates; emit only safe public aggregates; and
  share the redacted result packet back to those four reviewers before any
  final claim. No ontology-native result is claimed yet.

- #21 checkpoints T/U non-BERT KG and ontology-guided ablation completed as
  measurements over the preserved domain-hard full-PST work directory.
  `scripts/mail_full_pst_domain_hard_kg_fusion_eval.py` rescored checkpoint S
  with deterministic candidate-only mail components built from body
  observations before reading the private manifest. Latest preserved-workdir
  run plus saved-report validation exited 0 with `blockers=[]`: baseline
  20/100, candidate KG 30/100, positive 20/80, no-match 0/10,
  permission-denied 10/10, candidate nodes `4965`, candidate relations `3460`,
  components `1505`, largest component `1193`, and total rescore `14360ms`.
  `scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py` then compared
  the same 100 case hashes across baseline retrieval, candidate KG, and
  ontology-guided candidate KG. It uses formal FormOwl `TypeDefinition` and
  `TypeMapping` contracts, hash-bound ontology revision evidence, and
  business-function lens mappings into the closed core supertype lattice as
  candidate scoring/gating only. Latest preserved-workdir ablation plus
  saved-report validation exited 0 with `blockers=[]`: baseline 20/100,
  candidate KG 30/100, ontology-guided KG 29/100, positive KG 20/80 versus
  ontology 19/80, no-match 0/10 for both, permission-denied 10/10 for both,
  ontology type definitions `10`, type mappings `10`, typed candidate nodes
  `784`, typed components `229`, type-evidence coverage `1579` basis points,
  ontology-supported relations `1571`, missing type-evidence nodes `4181`,
  conflicting type-evidence nodes `412`, and total ablation `11164ms`. This is
  a negative ontology ablation: the broad business-function ontology lens did
  not beat the simpler candidate KG. Canonical dev-container verification now
  passed for focused KG tests 9 OK, focused ontology-ablation tests 9 OK,
  touched-file Ruff check/format-check, and saved-report validation for both
  container-generated public reports with `blockers=[]`. The container
  bind-mount runs preserved the same counts but were slower: KG total
  `190596ms`, ontology ablation total `190695ms`, both dominated by
  observation loading. Full dev-container unittest ran 573 OK in 835.841s, and
  full Ruff check/format-check passed with 217 files already formatted. The
  #21 reviewer gate passed 6/6 with read-only reviewers `Rawls`, `Galileo`,
  `Pascal`, `Plato`, `Chandrasekhar`, and `Confucius`; all returned
  `RELEASE_DECISION: AGREE` with no blocking findings. No intermediate
  `.test-tmp` data was deleted.

- #21 checkpoint S domain-hard full PST baseline measurement completed.
  `scripts/mail_full_pst_domain_hard_case_eval.py` now runs the
  operator-provided full PST through the governed Phase 1 mail evidence path,
  builds 100 harder retrieval cases across ten business-function lenses, keeps
  public case taxonomy hash-keyed, and preserves the private manifest/work
  directory under `.test-tmp` for follow-up experiments. The baseline is
  intentionally a measurement, not a 99/100 completion gate. Latest
  dev-container run and saved-report validation both exited 0 with
  `blockers=[]`. Safe counts/timings: fixture size `3152323584`, full parse
  true, parser workers `8`, message count `2746`, observation count `28163`,
  body segment count `4965`, mail evidence row count `13861`, parse warning
  count `3350`, 100 cases scored, 20 passed, 80 failed, pass rate `2000`
  basis points, 80 positive cases, 10 no-match cases, 10 permission-denied
  cases, duplicate response hash count `0`, upload `308409ms`, import
  `3160357ms`, bundle read `50147ms`, manifest generation `1938ms`, scoring
  `66156ms`, query runner setup `319ms`, query loop `65824ms`, retained
  artifact bytes `72849`, staging/scratch leftovers `0`, and work dir cleaned
  false. All permission-denied probes passed redaction; no-match probes failed
  as near-miss retrieval cases; only 10 of 80 positive retrieval cases passed.
  Focused hard-domain tests ran 11 OK in the dev container, and touched-file
  Ruff check/format-check passed. Claim only this hard-domain
  evidence-retrieval baseline measurement; do not claim business answer
  generation, general parser readiness, actual ChatGPT upload/file transfer,
  production iframe readiness, live PostgreSQL readiness, production worker
  leasing, raw mail access, KG/wiki writes, or production readiness.

- #21 checkpoint R full PST 100-case evidence-reading evaluation is
  implemented, reviewer-gated, and canonically verified.
  The new `scripts/mail_full_pst_100_case_eval.py` harness runs the
  operator-provided full PST fixture with no sampling, builds a normalized
  `MailEvidenceBundle`, generates 100 deterministic manifest-bound retrieval
  cases, preflights selected cases through the same governed JSON-RPC
  `query_mail_evidence` path, scores a fresh pass over the final manifest, and
  publishes only hash/status/count report fields. Hardening includes reusable
  in-memory mail query indexing, reusable case query runner, top-k-retrievable
  positive cases, no-match and permission-denied meaning checks, case-bound
  response hashes, row-derived aggregate/category/hash validation, and a
  narrower SQL leak guard that no longer rejects ordinary progress-update
  mail phrases. Maxwell's reviewer blocker added sentinel-guarded work-dir
  behavior so the harness refuses unmarked non-empty work dirs and refuses
  recursive cleanup without a valid harness sentinel. Latest dev-container full
  eval and saved-report validation after that fix both exited 0 with
  `blockers=[]`. Safe counts/timings:
  fixture size `3152323584`, full parse true, sample limit `0`,
  parser workers `8`, message count `2777`, observation count `28477`,
  body segment count `5041`, mail evidence row count `14050`, parse warning
  count `3401`, 100 cases scored, 100 passed, 0 failed, 5 no-match, 5
  permission-denied, 5 AI/progress-related cases all passed, duplicate
  response hash count `0`, import `160410ms`, manifest preflight `32121ms`,
  scoring `13712ms`, staging/scratch leftovers `0`, and work dir cleaned.
  Canonical verification: focused full-PST eval tests 14 OK before reviewer
  gate and 17 OK after the sentinel cleanup blocker fix, PST extractor tests 7
  OK, semantic JSON-RPC tests 12 OK, mail evidence gateway tests 18 OK,
  full-PST eval plus `--validate-report` exited 0, full Ruff
  check/format-check passed, and full unittest ran 539 OK in 842.996s. Three
  onboarding test-design subagents (`Gibbs`, `Tesla`, and `Zeno`) shaped the
  harness. Reviewer gate passed 6/6 with `Euler`, `Mendel`, `Huygens`,
  `Copernicus`, `Euclid`, and `Maxwell`; `Maxwell` initially blocked cleanup,
  then agreed after the sentinel fix. Claim only this operator-provided full
  PST 100-case deterministic evidence-reading evaluation; do not claim general
  PST/OST/MSG/EML/MBOX readiness, actual ChatGPT upload/file transfer,
  production iframe readiness, live PostgreSQL readiness, production worker
  leasing, raw mail access, delete-after-success retention, KG/wiki writes, or
  production readiness until separate evidence exists.

## 2026-07-06

- #21 checkpoint Q real PST sampled parser proof is implemented, reviewer-gated,
  and canonically verified. The slice adds `PstMailArchiveExtractor`, dev-container
  `pst-utils`, and `scripts/mail_real_pst_smoke.py` for the operator-provided
  `tests/pst-exm/archive.pst` fixture. Latest dev-container sampled smoke with
  limit 25 exited 0 and validation passed: fixture size `3152323584`,
  `message_count=25`, `observation_count=234`, `mail_evidence_row_count=132`,
  owner query `ok` with one citation, denied query `permission_denied` with
  zero visible results and hidden bundle count one, staging/scratch leftovers
  zero, and no public-report leak-scan hits for PST path, object-store locator,
  parser command, scratch path, traceback, or Windows drive path. Reviewer
  blockers fixed cover retention honesty (`retain_7_days` /
  `retained_by_policy`, not deleted), full-parser overclaim rejection,
  bool-as-int count rejection, malformed validate-report bounded failure,
  `query_mail_evidence` dual-selector AND matching, JSON-RPC pre-dispatch
  argument allowlisting, recursive control-key rejection before handler
  dispatch, public `session_id` trusted override behavior, and PST `readpst`
  argv/timeout/scratch cleanup tests. The issue-specific 6/6 reviewer gate
  passed with `Hilbert`, `Hubble`, `Hooke`, `Einstein`, `Hypatia`, and
  `Fermat`. Final canonical verification: focused semantic JSON-RPC tests ran
  12 OK; mail upload session gateway tests ran 8 OK; mail evidence MCP smoke
  tests ran 15 OK; `test_mail_*.py` ran 155 OK; sampled real PST smoke plus
  `--validate-report` exited 0; Ruff check/format check passed; full
  `python -m unittest discover -s tests` ran 524 OK in 781.345s. Claim only
  sampled real PST parser integration; do not claim full PST/OST/MSG/EML/MBOX
  readiness, actual ChatGPT upload/file transfer, production iframe readiness,
  live PostgreSQL readiness, production worker leasing, raw mail access,
  delete-after-success retention, KG/wiki writes, or production readiness.

- #21 checkpoint P completes the scoped Phase 1 Mail Evidence Reading via
  FormOwl MCP proof for fixture-backed ChatGPT testing readiness. Added
  bounded operator-supplied ChatGPT MCP mail evidence result-packet intake in
  `scripts/mail_evidence_chatgpt_result_intake.py` with focused tests in
  `tests/test_mail_evidence_chatgpt_result_intake.py`. The intake validates
  only hashes, statuses, counts, checkpoint-O smoke binding, owner/denied
  `query_mail_evidence` and `answer_mail_case_progress` result shapes,
  request-shape hashes, and operator attestation; it rejects raw transcripts,
  raw tool payloads, mail text/snippets, concrete mail identifiers, upload
  locators, environment values, paths, SQL, parser/storage/worker internals,
  bool counts, duplicate hashes, permission-bypass claims, KG/wiki claims, and
  production overclaims. Three onboarding subagents (`Ohm`, `Raman`, and
  `Confucius`) shaped the harness. The issue-specific 6/6 reviewer gate passed
  with `Hume`, `Carson`, `Nietzsche`, `Mencius`, `Newton`, and `Meitner` after
  selector-kind and smoke/request/report binding blockers were fixed. Canonical
  verification after reviewer fixes and formatting passed: focused P tests ran
  12 OK, direct result-intake CLI and `--validate-report` exited 0, direct
  checkpoint-O mail evidence MCP smoke exited 0, `test_mail_*.py` ran 144 OK,
  full Ruff check/format check passed for `python`, `tests`, and `scripts`,
  and full `python -m unittest discover -s tests` ran 505 OK in 682.461s.
  This completes the local fixture-backed #21 Phase 1 MCP evidence-reading and
  result-intake goal, while still not claiming direct Codex-controlled ChatGPT
  verification, cryptographic ChatGPT proof, actual upload/file transfer,
  production iframe readiness, real PST/OST/MSG/EML/MBOX parser readiness,
  live PostgreSQL deployment readiness, production worker leasing, raw mail
  access, KG/wiki writes, or production readiness.

- #21 checkpoint O completes the scoped local Phase 1 Mail Evidence Reading via
  FormOwl MCP proof. Added governed `answer_mail_case_progress` behavior over
  normalized `MailEvidenceBundle` data, exposed it through
  `SemanticMcpGateway` / JSON-RPC, extended
  `scripts/mail_evidence_mcp_smoke.py` with owner/denied/forged/trusted and
  bundle-id case-progress probes, and hardened the smoke report to hashes,
  statuses, counts, and explicit false claim boundaries only. Three onboarding
  test-design subagents (`James`, `Arendt`, `Curie`) shaped the final harness.
  The issue-specific 6/6 reviewer gate passed with `Kuhn`, `Ampere`, `James`,
  `Arendt`, `Curie`, and `Pascal`; `Curie`'s dual-id lookup blocker and
  `Arendt`'s claim-boundary enforcement blocker were fixed and re-reviewed.
  Canonical dev-container verification is no longer blocked after Docker
  restart: focused case-progress MCP tests ran 16 OK, focused smoke-validator
  tests ran 15 OK, the direct mail evidence MCP smoke exited 0, touched-file
  Ruff check/format check passed, `test_mail_*.py` ran 132 OK, and full
  `python -m unittest discover -s tests` ran 493 OK in 743.175s. This checks
  off issue #21's scoped local synthetic MCP evidence-reading and
  case-progress proof for ChatGPT testing readiness; it does not claim actual
  ChatGPT connected upload or file transfer, production iframe readiness, real
  PST/OST/MSG/EML/MBOX parser readiness, live PostgreSQL deployment readiness,
  production worker leasing, KG writes, wiki projection, or production
  readiness.

## 2026-07-05

- PM decision from GitHub #22 is now the #21 Phase 1 mail standard. Ordinary
  Phase 1 users must be able to upload a full PST through a session-bound
  FormOwl upload surface / iframe. The raw PST enters ingest staging; a
  server-side worker parses incrementally; PostgreSQL normalized mail evidence
  is the Phase 1 operational evidence layer; and the raw PST is deleted or
  retained only under configured retention after successful extraction.
  Local Companion is optional / advanced / policy-triggered for repeated
  rolling PST, privacy-sensitive imports, bandwidth limits, or
  manifest-first workspace policy, not the ordinary baseline.
- #21 must preserve one mail ingestion contract across parser locations:
  server-side parser and optional Companion parser both emit
  `MailEvidenceBundle`. Dedup is archive/message/attachment-level while still
  preserving message, attachment, archive, folder, embedded-message, and
  quoted-message candidate occurrence lineage. KG construction is explicitly
  Phase 2 and must not be a Phase 1 parser side effect.
- User-specific #21 reviewer gate override: every completed implementation or
  durable handoff slice for #21 requires 6 effective read-only Codex/GPT
  subagent reviewers with explicit `RELEASE_DECISION: AGREE`. Antigravity/`agy`
  remains disabled unless explicitly re-enabled after policy/platform/MCP
  changes, so do not count fake Antigravity reviewers or carry approvals across
  slices.
- #21 MailEvidenceBundle contract checkpoint: added the Phase 1
  `MailEvidenceBundle` contract/builder surface for fixture mail observations,
  including parser producer type parity, explicit server-side upload-session
  identity, occurrence-preserving archive/message/folder/attachment lineage,
  archive-independent logical message fingerprints, duplicate carrier import
  identity, required lineage-array validation, retention enum validation,
  raw/backend/SQL/secret public guards, and no tree side effects. Supplemental
  host checks passed: touched-file `py_compile`, focused mail tests 17 OK,
  extraction edge tests 13 OK, and `git diff --check`. The #21 slice-specific
  6-reviewer code/test gate agreed after blocker fixes with `Goodall`,
  `Curie`, `Mill`, `Hilbert`, `Euclid`, and `Jason`. This does not complete
  #21: canonical dev-container verification is blocked because Docker Desktop
  reports `Docker Desktop is unable to start`, and the governed MCP/JSON-RPC
  evidence-query path remains to be implemented.
- #21 MCP/JSON-RPC mail evidence query checkpoint B is implemented and passed
  the issue-specific 6/6 reviewer gate, but it is not a #21 completion claim.
  The slice adds normalized-bundle mail evidence querying through
  `query_mail_evidence`, Semantic MCP handler injection, JSON-RPC tool
  list/call coverage, session identity binding, trusted server-side grants
  only, permission-denied and not-found envelopes, `mail_import_session_id` and
  `mail_evidence_bundle_id` lookup, hash-only transcripts, and
  raw/backend/SQL/secret guards. It does not implement real PST parsing, the
  upload UI, PostgreSQL mail persistence, case-progress QA, KG writes, or wiki
  projection. Latest supplemental host checks passed after grant-forgery
  hardening: mail evidence MCP tests 9 OK, semantic gateway tests 8 OK,
  semantic JSON-RPC tests 5 OK, `test_mail_*.py` 26 OK, extraction edge tests
  13 OK, touched-file `py_compile`, long-line scan, and `git diff --check`.
  Reviewers `Socrates`, `Cicero`, `Euler`, `Ptolemy`, `Hume`, and `Halley`
  returned `RELEASE_DECISION: AGREE` after blockers were fixed. Canonical
  dev-container verification remains blocked by Docker Desktop unable to start.
- #21 checkpoint C is implemented and passed the issue-specific 6/6 reviewer
  gate: added
  `scripts/mail_evidence_mcp_smoke.py` and
  `tests/test_mail_evidence_mcp_smoke_script.py` as a ChatGPT-free local smoke
  for the normalized mail evidence MCP path. It runs synthetic mail fixture
  ingestion through Asset/ObjectStore, IngestionJob, FixtureMailArchiveExtractor,
  persisted observations, MailEvidenceBundle, and JSON-RPC `query_mail_evidence`
  owner/denied/forged-grant/trusted-grant/bundle-id probes. Public output is
  hash/status/count only and carries false claims for real PST parser, upload
  UI, PostgreSQL mail persistence, KG writes, wiki projection, and production
  readiness. Accepted reviewer blockers fixed CLI coverage, report validation,
  body-leak checks, work-directory sentinel behavior, deterministic safe
  outputs, owner-matched trusted grants, exact report contracts, and
  unknown-key no-echo behavior. Effective reviewers `Poincare`, `Hooke`,
  `Schrodinger`, `James`, `Gibbs`, and `Pasteur` returned
  `RELEASE_DECISION: AGREE` before the post-gate host portability fix. A
  follow-up Windows host portability hardening changed `tests/_paths.py` to
  avoid `os.getuid()` when unavailable and changed the smoke CLI default work
  directory from hard-coded `/tmp` to the platform temp directory. A fresh
  recheck of the latest diff passed 6/6 with `Poincare`, `Hooke`,
  `Schrodinger`, `James`, `Gibbs`, and `Pasteur`. Supplemental host checks
  after latest validation hardening and host portability fix: smoke tests 13
  OK, direct smoke CLI exited 0 with validation passed, mail evidence MCP tests
  9 OK, semantic gateway tests 8 OK, semantic JSON-RPC tests 5 OK,
  `test_mail_*.py` 39 OK, extraction edge tests 13 OK, touched-file
  `py_compile`, long-line scan, and `git diff --check` passed. Canonical
  dev-container verification remains blocked by Docker Desktop unable to
  start, so #21 stays open for canonical verification and the
  upload/parser/PostgreSQL/full path requirements.
- #21 checkpoint D is implemented and reviewer-gated: added
  `python/formowl_mail/postgres.py`,
  `python/formowl_graph/storage/migrations/004_mail_evidence.sql`, package
  exports, and `tests/test_mail_evidence_postgres.py` for the normalized
  PostgreSQL mail evidence adapter-contract slice. The slice stores
  `MailEvidenceBundle` data across all 12 Phase 1 mail evidence tables,
  rehydrates bundles by import session or bundle id, exposes a store-backed
  `query_mail_evidence` handler, uses parameterized SQL, adds import-session
  query indexes, preserves duplicate logical message/attachment rows while
  retaining occurrence rows, round-trips attachment, quoted candidate,
  embedded relation, and parse-warning rows, validates unsafe ids and unsafe
  public query inputs before store side effects, and covers rollback through
  `PostgreSQLUnitOfWork`. The checkpoint D reviewer gate passed 6/6 after
  blocker fixes with `Anscombe`, `Erdos`, `Dirac`, `Plato`, `Maxwell`, and
  `Planck` agreeing.
  Supplemental host checks passed: focused mail evidence PostgreSQL tests 6
  OK, PostgreSQL adapter contract tests 11 OK, mail tests 45 OK, PostgreSQL
  tests 20 OK, focused mail evidence MCP tests 9 OK, touched-file
  `py_compile`, long-line scan, and `git diff --check`. This remains a
  mocked-connection adapter-contract slice only and does not implement real PST
  parsing, upload UI / iframe, live PostgreSQL readiness, production worker
  leasing, KG writes, wiki projection, or ChatGPT-facing DB controls.
  Canonical dev-container verification remains blocked because Docker Desktop
  reports `Docker Desktop is unable to start`, so #21 stays open for canonical
  verification plus upload/parser/full-path requirements.
- #21 checkpoint E is implemented and passed the issue-specific 6-reviewer
  gate: added `python/formowl_mail/import_workflow.py`, package exports, and
  `tests/test_mail_upload_import_workflow.py` for an UploadSession-bound
  server-side mail import workflow. The helper requires an existing matching
  mail `UploadSession` before side effects, registers the staged archive as a
  normal `Asset`, creates/runs an `IngestionJob` through
  `FixtureMailArchiveExtractor`, builds a server-side `MailEvidenceBundle`
  with `upload_session_id`, writes normalized evidence through
  `PostgreSQLMailEvidenceStore` inside `PostgreSQLUnitOfWork`, verifies the
  store-backed JSON-RPC `query_mail_evidence` owner path, and updates the
  UploadSession only after the store-backed query succeeds. Focused tests cover
  invalid-session no-write behavior, duplicate rolling upload object-payload
  sharing plus occurrence-preserving logical mail dedup, public-summary
  leak/overclaim rejection, and evidence-store rollback/session failure
  handling. Reviewer blockers strengthened the session binding contract so new
  `UploadSession` records persist `session_id` and the workflow rejects a
  mismatched session before side effects; focused coverage also proves
  parser/job failure marks the UploadSession failed without PostgreSQL mail
  evidence side effects. Reviewer gate passed 6/6 after blocker fixes with
  `Carson`, `Galileo`, `Einstein`, `Ohm`, `Sartre`, and `Laplace` returning
  explicit `RELEASE_DECISION: AGREE`; no blocking findings remain.
  Supplemental host checks passed: upload import
  workflow tests 7 OK, upload session tests 3 OK, contract tests 8 OK, mail
  tests 52 OK, PostgreSQL tests 20 OK, semantic MCP tests 13 OK, touched-file
  `py_compile`, directly touched-file long-line scan, and `git diff --check`.
  Host `ruff` is unavailable; full host unittest is not clean due unrelated
  Windows temp-directory permission errors in KG-eval/benchmark tests and one
  pre-existing local-folder observation ordering difference. Canonical
  dev-container verification remains blocked because Docker Desktop reports
  `Docker Desktop is unable to start`. This remains a synthetic/internal
  workflow slice and does not implement real PST parsing, upload UI / iframe,
  live PostgreSQL readiness, production worker leasing, KG writes, wiki
  projection, or production readiness.
- #21 checkpoint F is implemented and passed the issue-specific 6-reviewer
  gate: added `python/formowl_mail/upload_session.py`, exported the mail upload
  session helpers from `formowl_mail`, and wired
  `SemanticMcpGateway.open_upload_session` so ChatGPT-facing callers can
  receive a session-bound mail archive upload task card. The task card accepts
  PST/OST/MSG/EML/MBOX profiles, exposes a
  `formowl_upload_session:<upload_id>` public locator, attaches source
  preparation guidance, and creates an audited `UploadSession` without
  exposing storage backends, parser controls, worker queues, raw paths, SQL, or
  object-store details. Reviewer blockers fixed exact public input
  allowlisting, camelCase ignored-key rejection, nested infrastructure-control
  rejection, restricted matching `permission_scope`, owner/visibility
  allowlists, embedded validation overclaim checks, audit failure no-write
  behavior, and audit rollback when session-store creation fails. Reviewer gate
  passed 6/6 after blocker fixes with `Hegel`, `Pauli`, `Leibniz`, `Kuhn`,
  `Volta`, and `Avicenna` returning explicit `RELEASE_DECISION: AGREE`;
  no blocking findings remain. Supplemental host checks passed: mail upload
  session gateway tests 8 OK, upload session tests 5 OK, semantic MCP tests
  8 OK, semantic JSON-RPC tests 5 OK, mail upload import workflow tests 7 OK,
  mail evidence MCP tests 9 OK, ingestion package tests 1 OK, contract glob
  tests 8 OK, touched-file `py_compile`, touched-file long-line scan, and
  `git diff --check`. Canonical dev-container verification remains blocked
  because Docker Desktop reports `Docker Desktop is unable to start`. This is
  only the upload task-card/session-entrypoint slice; it does not implement the
  real upload iframe, real PST parser, live PostgreSQL readiness, production
  worker leasing, KG writes, wiki projection, production readiness, or a
  completed ChatGPT smoke test.
- #21 checkpoint G is implemented and passed the issue-specific 6-reviewer
  gate: added a configured semantic JSON-RPC runtime entrypoint for
  ChatGPT-facing mail upload session task cards. `python/formowl_gateway/jsonrpc.py`
  now exposes `create_mail_upload_semantic_jsonrpc_gateway()`,
  `python/formowl_gateway/cli.py` provides the command wrapper, and
  `pyproject.toml` registers `formowl-semantic-mcp-jsonrpc`. The runtime wires
  `open_upload_session` to the mail upload session handler with
  file-backed `UploadSessionStore` and `FileAuditLogStore`, binds sanitized
  environment session identity, and accepts stdin/stdout JSON-RPC so a ChatGPT
  MCP command can reach the configured task-card path instead of the
  unconfigured `upload_handler_not_configured` stub. Reviewer blockers fixed
  the direct module `RuntimeWarning`, non-object JSON traceback behavior,
  secret-like env session value leakage, and bad `FORMOWL_DATA_DIR` startup
  tracebacks. Reviewer gate passed 6/6 after blocker fixes with
  `Kierkegaard`, `Helmholtz`, `Beauvoir`, `Carver`, `Hubble`, and
  `Chandrasekhar` returning explicit `RELEASE_DECISION: AGREE`; no blocking
  findings remain. Supplemental host checks passed: semantic JSON-RPC gateway
  tests 11 OK, mail upload session gateway tests 8 OK, semantic MCP gateway
  tests 8 OK, upload session tests 5 OK, touched-file `py_compile`, and
  `git diff --check` with CRLF warnings only. Canonical dev-container
  verification remains blocked because Docker Desktop reports
  `Docker Desktop is unable to start`. This is only runtime wiring for the
  task-card/session workflow; it does not implement the real upload iframe,
  real PST parser, live PostgreSQL readiness, production worker leasing,
  KG writes, wiki projection, production readiness, or a completed ChatGPT
  smoke test.
- #21 checkpoint H is implemented and passed the issue-specific 6-reviewer
  gate: added `scripts/mail_upload_mcp_command_smoke.py` and
  `tests/test_mail_upload_mcp_command_smoke_script.py` for a
  ChatGPT-compatible MCP command preflight. The smoke launches the documented
  `formowl-semantic-mcp-jsonrpc` console command, sends JSON-RPC
  `initialize`, `tools/list`, and `tools/call open_upload_session`, verifies
  `open_upload_session` is listed, returns a valid `status=ok` mail upload
  task card, and persists an `UploadSession` bound to the configured MCP
  session identity. It verifies the task-card upload id and
  `formowl_upload_session:<upload_id>` locator resolve to that persisted
  record. Reviewer blockers fixed the console-command surface, task-card
  persisted-session resolution, non-object report validation, exact
  response/count validation, audit no-side-effect checks, bool count bypasses,
  duplicate response hashes, stale command docstring, and secret-like report
  values. Reviewer gate passed 6/6 with `Gauss`, `Singer`, `Aquinas`,
  `Aristotle`, `Epicurus`, and `Godel` returning explicit
  `RELEASE_DECISION: AGREE`; no blocking findings remain. Supplemental host
  checks passed: H smoke tests 10 OK, direct PATH-shim command smoke and
  `--validate-report` exited 0, semantic JSON-RPC tests 11 OK, mail upload
  session gateway tests 8 OK, `test_mail_*.py` 70 OK, touched-file
  `py_compile`, direct line-length scan, and `git diff --check` with CRLF
  warnings only. Host Ruff remains unavailable. Canonical dev-container
  verification remains blocked because Docker Desktop reports
  `Docker Desktop is unable to start`. This is only the subprocess command
  preflight for the upload task-card runtime; it does not implement the real
  upload iframe/surface, file transfer, real PST/OST/MSG/EML/MBOX parser,
  live PostgreSQL deployment readiness, production worker leasing, KG writes,
  wiki projection, production readiness, or an actual ChatGPT connected smoke
  test.
- #21 checkpoint I is implemented and passed the issue-specific 6-reviewer
  gate: added `python/formowl_mail/upload_surface.py`,
  `tests/test_mail_upload_surface.py`, file-backed asset/object rollback
  helpers, `upload_session_file_received` audit logging, public exports from
  `formowl_mail`, and an import-workflow path that consumes an
  UploadSession already bound to a registered `asset_id`. The slice lets a
  trusted server upload surface receive a server-staged PST/OST/MSG/EML/MBOX
  upload for an existing matching mail `UploadSession`, reject mismatched
  actor/session/profile/status and user-supplied infrastructure controls
  before side effects, register the upload as a governed `Asset` and
  ObjectStore payload, bind `UploadSession.asset_id`, audit the receipt, reuse
  duplicate object payload bytes, and return only hash/status/count public
  receipt data. Reviewer blockers fixed during the gate: duplicate-preexistence
  detection now uses verified object payload state instead of metadata
  presence; metadata-only or corrupt object records are rolled back as newly
  written side effects; bound-asset import requires `uploading` /
  `archive_uploaded` receipt state and an Asset `source_ref` bound to the same
  UploadSession before job/run/observation/evidence side effects; and the
  public receipt explicitly denies actual ChatGPT connected upload with
  `supports_actual_chatgpt_connected_upload_claim=false`. Reviewer gate passed
  6/6 with `Pascal`, `Bacon`, `Mencius`, `Locke`, `Faraday`, and `Tesla`
  returning explicit `RELEASE_DECISION: AGREE`; no blocking findings remain.
  Supplemental host checks after reviewer blocker fixes passed: upload surface
  tests 8 OK, mail upload import workflow tests 9 OK, `test_mail_*.py` 80 OK,
  semantic JSON-RPC gateway tests 11 OK, mail upload session gateway tests
  8 OK, upload session tests 5 OK, ingestion package regression 1 OK, object
  store tests 7 OK, store edge tests 7 OK, workflow edge tests 8 OK, upload
  asset reference tests 2 OK, touched-file `py_compile`, touched-file
  line-length scan, and `git diff --check` with CRLF warnings only. This is
  backend upload intake / file-transfer receipt only, not the actual iframe UI,
  actual ChatGPT connected upload, real mail parser, live PostgreSQL
  deployment, production worker leasing, KG writes, wiki projection,
  production readiness, or a completed #21 claim. Canonical dev-container
  verification remains blocked by Docker Desktop unable to start.
- #21 checkpoint J is implemented and passed the issue-specific 6-reviewer
  gate: added
  `python/formowl_mail/upload_http.py` and
  `tests/test_mail_upload_http_surface.py` for a local stdlib HTTP upload
  surface contract harness. The handler renders `GET
  /mail/upload/<upload_session_id>` as a session-bound mail archive form and
  accepts `POST /mail/upload/<upload_session_id>` multipart uploads with one
  `mail_archive` file, validates route/form/workspace binding, request size,
  multipart boundary, duplicate file/field parts, parser defects such as
  missing close boundary, short HTTP body reads, actor/session/status,
  supported filename, and user-supplied storage/parser/worker controls before
  durable side effects, stages bytes only temporarily, calls
  `receive_mail_archive_upload()`, removes the temporary staged body, and
  returns a safe JSON receipt. Supplemental host checks before reviewer gate
  passed: HTTP upload surface tests 11 OK, backend
  upload surface regression tests 8 OK, mail upload session gateway tests
  8 OK, mail upload import workflow tests 9 OK, clean-temp-root
  `test_mail_*.py` 91 OK, touched-file `py_compile` passed, touched-file
  line-length scan passed, and `git diff --check` passed with CRLF warnings
  only. Reviewer blockers fixed during the gate: wrong and missing
  `workspace_id` route/form binding tests, duplicate `mail_archive` file and
  duplicate hidden-field tests, and truncated multipart / short-read parser
  hardening with no durable side effects. Reviewer gate passed 6/6 with
  `Popper`, `Russell`, `Peirce`, `Huygens`, `Turing`, and `Heisenberg`
  returning explicit `RELEASE_DECISION: AGREE`; no blocking findings remain.
  This is a local HTTP contract harness for future iframe/portal integration
  only; it does not claim actual ChatGPT
  connected upload, production iframe readiness, real PST/OST/MSG/EML/MBOX
  parser readiness, live PostgreSQL deployment, production worker leasing, KG
  writes, wiki projection, production readiness, or a completed #21 claim.
  Canonical dev-container verification remains blocked by Docker Desktop unable
  to start.
- #21 checkpoint K is implemented and passed the issue-specific 6-reviewer
  gate: added
  `scripts/mail_upload_mcp_http_smoke.py` and
  `tests/test_mail_upload_mcp_http_smoke_script.py` for a local
  MCP-command-to-HTTP upload smoke. The smoke launches the configured
  `formowl-semantic-mcp-jsonrpc` command, sends JSON-RPC `initialize`,
  `tools/list`, and `tools/call open_upload_session`, resolves the persisted
  `UploadSession`, starts the local HTTP upload surface with the same data
  directory and trusted session identity, posts synthetic multipart PST bytes
  to `/mail/upload/<upload_session_id>`, verifies `UploadSession.asset_id`,
  Asset/ObjectStore/audit side effects, staging cleanup, and safe
  hash/status/count report output. Negative probes cover missing route, wrong
  session route, wrong workspace, user-supplied infrastructure fields,
  duplicate multipart files, malformed multipart, oversized bodies, and
  command startup redaction with no durable upload side effects. Supplemental
  host checks before reviewer gate passed: MCP HTTP smoke tests 7 OK, MCP
  command preflight regression 10 OK, local HTTP upload surface tests 11 OK,
  `test_mail_*.py` 98 OK, touched-file `py_compile`, touched-file line-length
  scan, and `git diff --check` with CRLF warnings only. Reviewer gate passed
  6/6 with `Descartes`, `Bohr`, `Ampere`, `Hypatia`, `Sagan`, and `Rawls`
  returning explicit `RELEASE_DECISION: AGREE`; no blocking findings remain.
  This is a local
  MCP-command-to-HTTP upload contract smoke only; it does not claim actual
  ChatGPT connected upload, production iframe readiness, real mail parser,
  live PostgreSQL deployment, production worker leasing, KG writes, wiki
  projection, production readiness, or a completed #21 claim. Canonical
  dev-container verification remains blocked by Docker Desktop unable to
  start.
- #21 checkpoint L is implemented and passed the issue-specific 6-reviewer
  gate: added `scripts/mail_upload_mcp_http_import_smoke.py` and
  `tests/test_mail_upload_mcp_http_import_smoke_script.py`, updated
  `README.md` and `docs/workflows.md`, hardened
  `python/formowl_mail/import_workflow.py` so mail evidence writes and
  verification query share one transaction, and hardened
  `python/formowl_ingestion/storage/records.py` against Windows host temp-file
  replace locks. The smoke extends the local MCP-command-to-HTTP upload path:
  it opens an `UploadSession` through the configured JSON-RPC command, uploads
  a synthetic JSON-backed mail fixture through the local HTTP surface, runs the
  UploadSession-bound server-side import against the bound `asset_id`, writes
  normalized evidence through the PostgreSQL adapter contract, verifies
  store-backed owner and denied `query_mail_evidence` JSON-RPC behavior, and
  reports only hashes/statuses/counts. Negative probes cover missing asset,
  wrong asset `source_ref`, parser failure, evidence-store failure, and
  query-verification failure. Reviewer blockers fixed during the gate: query
  failure now rolls back mail evidence rows instead of leaving committed
  partial evidence, and denied query validation now proves zero visible results
  with strict integer checking. Supplemental host checks after blocker fixes
  passed: L smoke tests 7 OK, upload import workflow tests 9 OK, K smoke tests
  7 OK, local HTTP upload tests 11 OK, MCP command smoke tests 10 OK,
  `test_mail_*.py` 105 OK, touched-file `py_compile`, touched-file long-line
  scan, and `git diff --check` with CRLF warnings only. Reviewer gate passed
  6/6 with `Kepler`, `Archimedes`, `Kant`, `Dewey`, `Dalton`, and `Confucius`
  returning explicit `RELEASE_DECISION: AGREE` after blocker fixes. This is a
  local synthetic contract smoke only; it does not claim actual ChatGPT
  connected upload, production iframe readiness, real mail parser, live
  PostgreSQL deployment, production worker leasing, KG writes, wiki projection,
  production readiness, or #21 completion. Canonical dev-container verification
  remains blocked by Docker Desktop unable to start.
- #21 checkpoint M is implemented and passed the issue-specific 6-reviewer
  gate: added `scripts/mail_upload_chatgpt_connection_preflight.py` and
  `tests/test_mail_upload_chatgpt_connection_preflight.py`, and updated
  `README.md` and `docs/workflows.md`. The preflight reuses the configured
  `formowl-semantic-mcp-jsonrpc` command smoke, validates a bounded manual
  ChatGPT MCP attach package shape, and emits only hash/status/count report
  data for the required environment-name count, required tool count, expected
  JSON-RPC sequence, command-smoke report, upload-session shape, and task-card
  shape. Negative package probes reject environment values, concrete upload
  locators, raw command paths, and actual ChatGPT-connected upload overclaims.
  Reviewer blocker fixed during the gate: static contract hash fields now
  validate against exact `sha256_json(...)` values for required environment
  names, required tool names, expected JSON-RPC sequence, and negative package
  probe names; focused tests cover tampered static hashes, duplicate probe
  hashes, and embedded validation overclaims. Supplemental host checks after
  blocker fixes passed: M focused tests 8 OK, M touched-file `py_compile`,
  MCP command smoke tests 10 OK, K smoke tests 7 OK, L smoke tests 7 OK,
  `test_mail_*.py` 113 OK, new-file long-line scan, and `git diff --check`
  with CRLF warnings only. Reviewer gate passed 6/6 with `Bernoulli`,
  `Boole`, `Copernicus`, `Wegener`, `Nietzsche`, and `Arendt` returning
  explicit `RELEASE_DECISION: AGREE` after blocker fixes. This is only a local
  connection-readiness package for the next manual ChatGPT test; it does not
  claim actual ChatGPT connected upload, production iframe readiness, real
  parser readiness, live PostgreSQL deployment, production worker leasing, KG
  writes, wiki projection, production readiness, or #21 completion. Canonical
  dev-container verification remains blocked by Docker Desktop unable to
  start.
- #21 checkpoint N is implemented and passed the issue-specific 6-reviewer
  gate: added `scripts/mail_upload_chatgpt_result_intake.py` and
  `tests/test_mail_upload_chatgpt_result_intake.py`, and updated `README.md`
  and `docs/workflows.md`. After an operator manually connects ChatGPT to the
  configured `formowl-semantic-mcp-jsonrpc` MCP server and calls
  `open_upload_session`, the intake validates a bounded hash/status/count
  result packet for the preflight static contract, expected JSON-RPC sequence,
  observed required tool, task-card shape, upload-session shape, and operator
  attestation. It rejects environment values, concrete upload locators or
  upload session IDs, private mail payload fields, raw command paths,
  static-contract hash tampering, duplicate response hashes, and actual upload
  / production overclaims. Supplemental host checks passed: focused
  result-intake tests 7 OK, `test_mail_*.py` 120 OK, touched-file
  `py_compile`, new-file long-line scan, and `git diff --check` with CRLF
  warnings only. Reviewer blocker fixes then made negative packet probes
  valid-packet-only, malformed nested packets safe, packet-derived safe outputs
  sanitized, CLI JSON load failures bounded, `--input` and `--validate-report`
  mutually exclusive, and packet-level duplicate hash / bool count / invalid
  hash / asset-type / non-object / KG-overclaim coverage explicit.
  Supplemental host checks after blocker fixes passed: focused result-intake
  tests 10 OK, `test_mail_*.py` 123 OK, touched-file `py_compile`, new-file
  long-line scan, and `git diff --check` with CRLF warnings only. Host Ruff is
  unavailable. Canonical dev-container
  verification remains blocked: unprivileged Docker access returned npipe
  permission denied, and the escalated canonical focused command reached
  Docker but returned `Docker Desktop is unable to start`. Reviewer gate
  passed 6/6 with `Linnaeus`, `Raman`, `Herschel`, `Fermat`, `Harvey`, and
  `Mendel` returning explicit `RELEASE_DECISION: AGREE` after blocker fixes.
  This is result-packet intake only; it does not let Codex directly control
  ChatGPT, prove actual file transfer, prove production iframe readiness,
  implement real mail parsing, prove live PostgreSQL deployment readiness,
  implement production worker leasing, write KG/wiki state, claim production
  readiness, or complete #21.

## 2026-07-04

- Mail priority reset after PM review: the user explicitly made GitHub issue
  #21, `Mail Evidence Reading via FormOwl MCP`, the main mail target. Do not
  continue issue #5 as the active product direction. Treat #5's synthetic mail
  phase only as reusable foundation: normalized JSON fixture observations,
  local mail evidence packs/search, candidate-only bridge helpers,
  case-progress QA helpers, and synthetic preflight artifact. Issue #21 remains
  open until the governed FormOwl MCP / JSON-RPC evidence-query path is proven
  with fixture-backed mail evidence, permission-filtered allowed/denied cases,
  citations, audit/logging behavior, raw/internal leak guards, and a
  ChatGPT-free local harness. Do not use live mailbox access, parser-side QA,
  parser-side candidate writes, canonical graph writes, or direct wiki
  projection to satisfy #21.
- GitHub issue #5 was merged into #21 and closed as a duplicate on
  2026-07-04. The merged #21 body now carries #5's OpenProject #827 /
  #828-#835 mapping, reusable #828/#830 foundation, remaining mail contract /
  retrieval / QA / candidate / preflight requirements, and sequencing guidance.

## 2026-06-30

- #13 code-review follow-up on branch `complete-remaining-backbone-slices`:
  current KG-eval authority was corrected back to blocked 8/12 with failed
  gates `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`. `formowl_kg_eval summary` now fails closed with
  `authority_state.state=blocked`, `consistent=true`, and
  `completion_claim_supported=false`; stale 9/12, 10/12, and 12/12 notes are
  marked historical/superseded. Legacy JSON-line Project/Wiki MCP console
  scripts were renamed to explicit `*-jsonline-compat` entry points, and the
  contract primitive hash/id/serialization helpers were split from
  `formowl_contract.models` into `formowl_contract.primitives` while preserving
  existing imports. Ignored `.test-tmp/` and interrupted KG-eval real-root test
  artifacts were removed after verification. Dev-container verification
  passed: focused #13 KG-eval unittest 132 OK, full main repo unittest 353 OK,
  package summary reported blocked/consistent with four work orders and four
  progress gates, refreshed broad reports were synchronized, gate progress
  `--check` returned `up_to_date=true`, and Ruff check/format-check passed.
  Full KG-eval unittest discovery was attempted twice but exceeded 10 and 15
  minute timeouts; the timed-out container was stopped and its ignored test
  artifacts were cleaned.

## 2026-06-29

- Public enterprise 50,000-pair BGE benchmark and ontology-guidance ablation
  completed on branch `kg-bert-ablation-experiment`. 50k artifact:
  `experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json`.
  Dataset: 50,000 labeled candidate pairs, with 22,500 CUAD
  contract-document pairs, 15,000 SEC financial-report/company pairs, and
  12,500 BEIR FiQA financial-QA pairs; 24,837 positives and 25,163 negatives.
  Lexical baseline scored accuracy 0.5225, precision 0.921930, recall
  0.042316, F1 0.080918, latency 10,171.713ms, and 4,915.593 pairs/s. BGE
  large GPU (`BAAI/bge-large-en-v1.5`, threshold 0.62,
  `sentence-transformers=3.3.1`, `torch=2.10.0+cu126`, `model_device=cuda:0`)
  scored accuracy 0.79986, precision 0.945935, recall 0.633289, F1 0.758664,
  latency 783,070.479ms, and 63.851 pairs/s. Deltas versus lexical: accuracy
  +0.277360, F1 +0.677746, recall +0.590973, precision +0.024005. 50k chart:
  `experiments/kg_bert_ablation/results/charts/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg`.
  Ontology artifact:
  `experiments/kg_bert_ablation/results/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json`.
  Dataset: 20,000 pairs, with 4,500 contract-document pairs, 3,000
  financial-report pairs, 2,500 financial-QA pairs, and 10,000 cross-type
  ontology stress negatives. BGE-only scored accuracy 0.3999, precision
  0.235272, recall 0.631759, F1 0.342860, and 10,000 stress false positives.
  BGE plus hard or soft ontology guidance scored accuracy 0.8999, precision
  0.946493, recall 0.631759, F1 0.757744, and 0 stress false positives.
  Ontology charts:
  `experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg`
  and
  `experiments/kg_bert_ablation/results/charts/kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg`.
  Claim boundary: these are candidate-only benchmark and ablation artifacts.
  They support the BGE neural profile and ontology-aware matching, but do not
  claim production readiness, production latency, canonical graph/type writes,
  raw-access grants, or completed human adjudication. The 50k artifact reaches
  the manifest's stakeholder evidence size target; the ontology artifact is a
  stress ablation and not a stakeholder-grade production-quality claim.
- Public enterprise BGE benchmark completed on branch
  `kg-bert-ablation-experiment`. Artifact:
  `experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json`.
  Dataset: 10,000 labeled candidate pairs, with 7,000 CUAD contract-document
  pairs and 3,000 SEC financial-report/company pairs; 4,976 positives and
  5,024 negatives. Lexical baseline scored accuracy 0.5216, precision
  0.940367, recall 0.041198, F1 0.078937, latency 2,654.877ms, and
  3,766.652 pairs/s. BGE large GPU (`BAAI/bge-large-en-v1.5`, threshold 0.62,
  `sentence-transformers=3.3.1`, `torch=2.10.0+cu126`, `model_device=cuda:0`)
  scored accuracy 0.7183, precision 0.931627, recall 0.468248, F1 0.623245,
  latency 418,861.960ms, and 23.874 pairs/s. Deltas versus lexical: accuracy
  +0.196700, F1 +0.544308, recall +0.427050, precision -0.008740. A prior
  batch-size-32 GPU run failed around 60% with CUDA illegal memory access; the
  completed run used one GTX 1080 Ti and batch size 8. This is model-selection
  evidence only: candidate-only, no canonical graph/type writes, no raw-access
  grants, no production latency claim, and no 50,000-pair stakeholder-grade
  claim. FiQA, Enron, and RVL-CDIP are source-locked/probed but not yet labeled
  pairs in this runner.
- KG BERT ablation follow-up on branch `kg-bert-ablation-experiment`: added
  stable optional neural runtimes instead of ad hoc host installs. CPU runtime
  `containers/kg-bert-cpu/Dockerfile` built as `formowl-kg-bert-cpu:local`,
  imported `sentence_transformers 3.3.1`, `torch 2.5.1+cpu`, and
  `transformers 4.46.3`, and produced
  `experiments/kg_bert_ablation/results/kg_bert_ablation_bert_cpu.json`.
  On the fixed 16-pair fixture, lexical non-BERT scored
  precision 1.0, recall 0.1, F1 0.181818, accuracy 0.4375; CPU BERT scored
  precision 0.888889, recall 0.8, F1 0.842105, accuracy 0.8125. Added GPU
  runtime files under `containers/kg-bert-gpu/` using
  `pytorch/pytorch:2.5.1-cuda11.8-cudnn9-runtime` for GTX 10-series
  compatibility. This host has two GTX 1080 Ti GPUs and driver `580.159.04`,
  but `docker run --gpus all` is blocked before FormOwl code runs by NVIDIA
  Container Toolkit `ldconfig` config looking for `/sbin/ldconfig.real`.
  Blocker artifact:
  `experiments/kg_bert_ablation/results/kg_bert_ablation_gpu_runtime_2026-06-29_blocked_nvidia_ldconfig.json`.
  The GPU image manifest resolved, but the local image build was stopped after
  a slow 3.17GB base-layer download; no Dockerfile failure was observed.
  A later explicit outside-sandbox rerun produced the same
  `/sbin/ldconfig.real` NVIDIA prestart-hook failure, and a non-mutating bind
  mount attempt to provide `/sbin/ldconfig.real` inside the container also
  failed before container mounts took effect. This confirms the blocker is host
  NVIDIA Container Toolkit configuration, not the Codex sandbox.
- 2026-06-29 GPU follow-up after operator fixed NVIDIA Docker: `docker run
  --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` now succeeds and
  sees two GTX 1080 Ti GPUs. The default 2.5.1/cu118 GPU Dockerfile remains in
  place, and it now supports build args for host-specific CUDA bases. The local
  host-specific image `formowl-kg-bert-gpu:cu126-host` was built from
  `pytorch/pytorch:2.10.0-cuda12.6-cudnn9-devel`, with pinned
  `sentence-transformers==3.3.1` and `transformers==4.46.3`. The GPU ablation
  artifact
  `experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu_cu126_host.json`
  completed with `model_device=cuda:0`, `torch=2.10.0+cu126`, CUDA 12.6, and
  two visible GTX 1080 Ti devices. Matching quality equals the CPU BERT result
  on the fixed fixture: precision 0.888889, recall 0.8, F1 0.842105, accuracy
  0.8125. Embedding latency improved from CPU 499.969ms to GPU 217.73ms, but
  total runtime is still dominated by model load/CUDA initialization on this
  tiny 16-pair fixture, so do not use it to claim end-to-end GPU latency
  superiority.
- 2026-06-29 BERT hit-rate improvement: the ablation harness now gates BERT
  cosine-similarity matches through ontology core-supertype compatibility.
  This changed the neural algorithm id to
  `sentence_transformer_cosine_similarity_with_core_type_gate_v2`. The prior
  false positive `Maya Chen` versus `Maya Chen` is now preserved as
  `type_mismatch` because the fixture types are `Person` and `Project`.
  Regenerated CPU/GPU artifacts now report precision 1.0, recall 0.8,
  F1 0.888889, accuracy 0.875, and false positives 0. Compared with the
  non-BERT lexical baseline, overall accuracy rises from 0.4375 to 0.875
  (+43.75 percentage points), while positive-pair recall rises from 0.1 to
  0.8 (+70 percentage points). GPU remains confirmed with `model_device=cuda:0`
  in `kg_bert_ablation_bert_gpu_cu126_host.json`; current tiny-fixture latency
  remains startup dominated and should not be used for end-to-end GPU speed
  claims.
- 2026-06-29 KG BERT ablation benchmark/model-profile upgrade on branch
  `kg-bert-ablation-experiment`: selected a larger public enterprise benchmark
  source pool in
  `experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json`.
  The manifest covers mail/conversation, office documents, financial QA, SEC
  financial reports, and contract documents, targets at least 10,000 labeled
  pairs for model selection and 50,000 pairs for stakeholder-facing evidence,
  and explicitly does not claim the large benchmark has been executed. The
  ablation harness now records the manifest hash in result artifacts, adds
  model profiles, preserves `legacy_cpu_bert` with
  `sentence-transformers/bert-base-nli-mean-tokens`, and sets the GPU default
  profile to `gpu_bge_large_en_v1_5` / `BAAI/bge-large-en-v1.5` with a local
  floor of one NVIDIA GeForce GTX 1080 Ti class GPU and 11GB VRAM. The BGE
  profile uses preliminary threshold 0.62; the legacy CPU BERT profile keeps
  threshold 0.70.
  `containers/kg-bert-cpu/` defaults to the legacy CPU BERT profile;
  `containers/kg-bert-gpu/` defaults to the BGE large GPU profile.
  `formowl_kg_eval summary` now exposes both model profiles for System
  Backbone worker routing. Dev-container verification passed: focused ablation
  tests 6 OK, focused capability tests 5 OK, focused runtime container tests
  4 OK, full main-repo unittest 273 OK, Ruff check passed, Ruff format-check
  passed, and package summary smoke passed. New dev-container no-neural-deps
  artifact:
  `experiments/kg_bert_ablation/results/kg_bert_ablation_2026-06-29_devcontainer_bge_manifest_no_bert_dependency.json`.
  Actual host GPU BGE evidence is also preserved at
  `experiments/kg_bert_ablation/results/kg_bert_ablation_bge_large_gpu_cu126_host.json`:
  `model_device=cuda:0`, two visible GTX 1080 Ti devices, threshold 0.62,
  precision 1.0, recall 0.9, F1 0.947368, accuracy 0.9375. This improves over
  the old 16-pair BERT+type-gate artifact, but it remains only a small-fixture
  result; the public enterprise benchmark still must be executed before
  stakeholder-grade model-selection claims.
  Reviewer gate passed 3/3: `Descartes` agreed on engineering correctness
  after stale active artifact paths were fixed and covered by regression tests,
  `Boole` agreed on governance/safety, and `Lagrange` agreed on research
  method/benchmark validity. Final verification after reviewer fixes: full
  main-repo unittest 273 OK, Ruff check passed, Ruff format-check passed, and
  JSON artifacts parsed.

## 2026-06-27

- Created durable goal registry under `docs/agent-goals/`.
- Agy authorization checkpoint: before continuing KG implementation, the user
  asked to resolve the Antigravity/Gemini reviewer permission issue. Standing
  scoped authorization is now recorded in the repo-local
  `use-agy-antigravity` skill, `docs/agent-goals/reviewer-gate.md`, and
  `docs/agent-goals/kg-research-agent.md`. Codex may run the local `agy` CLI
  with sandbox escalation and may send bounded read-only FormOwl KG reviewer
  packets containing only relevant repo-relative paths, design/test summaries,
  verification results, claim boundaries, and non-sensitive code/docs excerpts.
  The authorization excludes secrets, credentials, raw private source payloads,
  raw backend paths, NAS/object-store admin endpoints, raw SQL, database dumps,
  worker scratch paths, local filesystem internals, and unrelated private data.
  If `agy` is slow, confirm it is still running and wait; if tenant policy or
  approval review rejects external disclosure before execution, record the gate
  blocker and do not bypass it with alternate channels or substitute reviewers.
- Bounded Antigravity write-delegation checkpoint: the user also authorized
  Codex to ask Antigravity to write bounded implementation slices to save Codex
  token budget. Future invocations must state exact owned files/directories,
  keep the workspace minimal, avoid unrelated changes, and leave Codex
  responsible for diff inspection, canonical dev-container verification,
  durable docs, and final commit. Do not use
  `--dangerously-skip-permissions` without separate exact approval.
- Agy policy/write test result: local `agy` availability works
  (`agy --version` returned `1.0.13`, and `agy models` listed
  `Gemini 3.5 Flash (High)`). A minimal bounded FormOwl KG read-only reviewer
  packet was rejected before execution by tenant policy as external disclosure
  to an untrusted reviewer service; no packet was sent and no workaround was
  attempted. Plain one-shot `--add-dir` was not reliable for intended
  workspace writes, while `--new-project --add-dir` successfully wrote to an
  empty intended workspace. Future bounded write delegation should use
  `--new-project --add-dir <smallest-scope>` and Codex must verify local diff
  and tests before accepting Antigravity output.
- Imported the Knowledge Graph Research Agent goal from session
  `019eda5f-7dd6-74a2-ac56-4f84e5d58560` into
  `docs/agent-goals/kg-research-agent.md`.
- Added `docs/agent-goals/system-backbone-agent.md` as an abstract placeholder
  for the System Backbone Agent running on another machine. The owning agent
  should fill in its exact objective, status, blockers, commit, and next
  action.
- Updated the default reviewer gate to 6 effective read-only reviewers: 3
  Codex/GPT reviewers plus 3 Antigravity Gemini reviewers through the real
  local `agy` CLI. The user authorized `agy` reviewer use. See
  `docs/agent-goals/reviewer-gate.md`.
- Knowledge Graph Research Agent implemented the scoped ontology/type
  governance contracts and KG research acceptance suite. Dev-container
  verification passed, and GPT/Codex reviewer gate progress is 3/3 agreed for
  that reviewer class (`Kuhn`, `Goodall`, `Pasteur`) after blocker fixes.
  Overall gate remains 3/6 because Antigravity Gemini reviewer calls through
  `agy` were rejected for external model data-egress risk and require explicit
  user approval before retrying.
- Historical upfront authorization rule for KG goal resumes: if the reviewer
  gate was expected to need Antigravity Gemini reviewers through `agy`, ask the
  user at the start for bounded external review-packet approval before doing
  long-running local work. This rule is superseded by the 2026-06-28 agy MCP
  route and gate-policy checkpoint below; ordinary KG resumes should not ask
  for Antigravity authorization unless the user explicitly re-enables `agy`.
- Added a compact-friendly execution rule for the KG goal: checkpoint durable
  state more often than usual, especially after reviewer attempts, blockers,
  verification results, and acceptance-status changes, so future compaction or
  resume cycles do not depend on long chat history.
- Completed the KG research method/acceptance-harness slice. Current-state dev-container
  verification passed: default KG research acceptance suite returned
  `passed_with_explicit_limits` with only expected failed/blocked items,
  focused KG acceptance tests ran 4 OK, focused ontology tests ran 4 OK, and
  full unittest ran 246 OK. Reviewer gate passed 6/6:
  `Kuhn`, `Goodall`, `Pasteur`, `Ada-Sandbox`, `Lamport-Sandbox`, and
  `Curie-Sandbox`. The KG Research Evaluation and Acceptance work-board item is
  now checked complete.
- Correction: the previous entry completed only the scoped ontology and KG
  research method/acceptance-harness slice, not the user's full KG
  real-evidence objective. `docs/agent-goals/kg-research-agent.md` is reset to
  `active`. The stricter `.formowl/kg-eval` broad acceptance snapshot still has
  `overall_passed=false` with failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
- Added an unchecked work-board item for the full KG real-evidence objective.
  Future KG sessions must not treat `passed_with_explicit_limits` or a checked
  method-slice item as total completion. Completion requires broad KG-eval
  gates to pass, strict main-repo KG research acceptance to pass, canonical
  dev-container verification, and the configured reviewer gate for newly
  completed slices.
- 2026-06-27 review return: the reviewed canonical graph commit workflow was
  unchecked for rework. Current code builds child graph revisions from only the
  newly committed candidate atoms/relations and resolves candidate relations
  only against atoms in the same commit, so incremental canonical graph history
  can drop prior graph membership. Also, the stricter `.formowl/kg-eval`
  harness/snapshot is ignored by Git, so future sessions on another machine
  cannot rely on it unless the essential acceptance artifacts are moved to a
  tracked path or explicitly unignored.
- 2026-06-27 portability follow-up: `.gitignore` now allows the sanitized
  `.formowl/kg-eval` strict acceptance harness, restart note, fixtures,
  templates, work orders, preview packets, and non-authoritative blocked-state
  snapshots under `snapshots/current_blocked/` to be tracked. Runtime
  `.formowl/kg-eval/results/`, the long local `.formowl/kg-eval/HANDOFF.md`,
  operator real roots under `inputs/*_real/`, and canonical real evidence
  packets remain ignored. This makes the broad acceptance harness reproducible
  across sessions while avoiding stale generated results as completion
  evidence. The KG objective is still active with the same four failed
  real-evidence gates.
- 2026-06-27 portability verification: dev-container KG-eval unittest ran
  360 tests OK and main repo unittest ran 246 tests OK. Broad KG-eval reports
  `overall_passed=false`, 8 passed gates, 4 failed gates, and synchronized
  blocked real-evidence preflight/work orders. Main-repo KG acceptance default
  reports `passed_with_explicit_limits`; strict mode fails as expected on the
  known failed/blocked readiness claims.
- 2026-06-27 portability reviewer result: 3 final-version Antigravity Gemini
  reviewers agreed after one reviewer found and re-reviewed a real blocker.
  The fixed blocker was stale/private-data tracking risk from broad `inputs/`
  and runtime `results/` unignore rules. The final ignore policy tracks only
  sanitized harness/fixtures/templates/work orders/work packets and
  non-authoritative blocked snapshots while excluding runtime results,
  operator real roots, canonical evidence packets, and local long-form handoff
  history.
- 2026-06-27 canonical commit rework result: reviewed canonical graph commit
  workflow rework completed. Child graph revisions now preserve same-scope
  committed parent atom/entity/relation membership, relation commits can
  resolve endpoints through parent/current candidate-to-canonical atom mappings,
  relation-only commits require reviewed relations with resolvable endpoints,
  empty commits are rejected, and corrupt parent relation endpoints are rejected
  before child writes. Dev-container verification passed: changed-file Ruff
  check and format check, focused canonical workflow unittest 16 OK, full main
  repo unittest 252 OK, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance failed only on the known expected failed/blocked items,
  and KG-eval unittest 360 OK. GPT/Codex reviewers `Kuhn-GPT`,
  `Goodall-GPT`, and `Pasteur-GPT` agreed on the final diff after Pasteur's
  parent entity/relation membership test-coverage blocker was fixed.
  Antigravity Gemini reviewers `Lamport-Sandbox`, `Ada-Sandbox`, and
  `Curie-Sandbox` agreed through real `agy` on the implementation diff; a
  later attempt to send the test-only final diff to `agy` was blocked by
  sandbox/tenant data-egress policy, and no workaround was attempted. The full
  KG real-evidence objective remains active with the same four failed broad
  gates.
- 2026-06-27 fair-baseline response-intake progress: added a candidate-only
  fair external-baseline response intake path and work-order command. The new
  intake writes only candidate artifacts under
  `inputs/fair_baseline_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`, records custody hashes, rejects unsafe
  payloads/paths/overwrites/symlinks, and never writes the canonical fair
  baseline packet. GPT reviewer blockers for manifest custody hashing,
  post-write assembler failures, parent-file partial writes, and
  production-shaped test cleanup were fixed. Dev-container KG-eval unittest ran
  372 tests OK; main repo unittest ran 252 tests OK; changed-file Ruff check
  and format-check passed; KG-eval acceptance/preflight/work-order reports were
  refreshed and remain blocked/synchronized with the same four failed broad
  gates. GPT/Codex reviewers `Poincare`, `Popper`, and `Carson` agreed after
  blocker fixes. Antigravity Gemini review is blocked at 0/3 because tenant
  policy rejected both a code/diff bounded packet and a closed-book bounded
  summary through real `agy`; no workaround was attempted.
- 2026-06-27 production-adapter response-intake progress: added a
  candidate-only production adapter response intake path and work-order
  command. The new intake writes only candidate artifacts under
  `inputs/production_adapter_real/<operator-run-id>` and optional candidate
  manifests under `work_packets/`, records custody hashes, rejects unsafe
  payloads/paths/overwrites/symlinks/parent-file collisions and
  duplicate/missing adapter components, and never writes
  `inputs/production_adapter_evidence_packet.json`. Dev-container verification
  passed so far: KG-eval focused 27 OK, KG-eval full 383 OK, main repo 252 OK,
  changed-file Ruff check and format-check passed, and refreshed reports still
  show `overall_passed=false` with the same four failed broad gates. GPT/Codex
  reviewers `Gauss`, `Archimedes`, and `Noether` returned blockers for
  sandbox/nested output-dir rejection, top-level response field allowlisting,
  missing-component coverage, and work-order side-effect snapshots; the fixes
  passed dev-container focused 30 OK, full KG-eval 386 OK, main repo 252 OK,
  changed-file Ruff check and format-check, and all three reviewers returned
  `RELEASE_DECISION: AGREE`. Antigravity Gemini review is blocked at 0/3:
  `agy --version` and `agy models` succeeded, but three bounded read-only
  review-packet attempts through real `agy` were rejected before execution by
  tenant policy as external data disclosure to an untrusted reviewer service,
  even with user authorization. No packet was sent and no workaround was
  attempted.
- 2026-06-27 enterprise-multimodal response-intake hardening progress:
  hardened the candidate-only enterprise multimodal response intake path for
  `multimodal_semantic_validation`. The intake now rejects unsupported
  top-level response fields, unsafe/nested/sandbox output dirs, symlinks,
  overwrites, parent-file collisions, raw/internal/template payload values,
  raw/internal field names, and promotion arguments; it writes only candidate
  artifacts under `inputs/enterprise_multimodal_real/<operator-run-id>` plus
  optional work-packet manifests, custody-hashes the optional manifest, and
  rolls back intake-created files on assembler, validation, custody,
  serialization, or write failures including after exclusive create/open.
  Dev-container verification passed: focused KG-eval 35 OK, full KG-eval
  396 OK, main repo 252 OK, changed-file Ruff check and format-check, and
  refreshed broad reports still show `overall_passed=false` with the same four
  failed gates. GPT/Codex reviewers `Aristotle`, `Huygens`, and `Lovelace`
  agreed after blocker fixes. Antigravity Gemini review is blocked at 0/3:
  `agy --version` and `agy models` succeeded, but a bounded read-only
  review-packet attempt was rejected before execution by tenant policy as
  external data disclosure to an untrusted reviewer service. No packet was
  sent and no workaround was attempted.
- 2026-06-27 current-state re-execution: after the user asked to execute the
  original agent's latest state, Codex reran the broad KG-eval and main-repo
  verification in the dev container without local code changes. Refreshed
  commands: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`, and
  `real_evidence_collection_work_orders.py`. Dev-container KG-eval unittest
  ran 396 tests OK, and main repo unittest ran 252 tests OK. Main-repo KG
  research acceptance default remains `passed_with_explicit_limits`; strict
  mode still fails only on the known `production_adapter_readiness` failed
  item and `latency_scalability_enterprise_claims` blocked item. Broad
  KG-eval remains incomplete: `overall_passed=false`, 8 passed gates, and the
  same 4 failed real-evidence gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`). Preflight
  reports `inputs/*_real` roots exist but currently contain zero real or
  candidate artifacts, and all four canonical input packets are missing.
- 2026-06-27 operator-guide progress: added a generated, tracked human-readable
  guide for collecting the remaining broad KG real-evidence packets at
  `.formowl/kg-eval/work_packets/remaining_real_evidence_operator_guide.md`.
  The generator is `.formowl/kg-eval/real_evidence_operator_guide.py` and is
  sourced only from the non-authoritative work-order report. It lists blockers,
  required artifacts, candidate-only intake commands, validation commands, and
  safety boundaries for all four remaining gates, while explicitly accepting
  no evidence, promoting no packets, writing no canonical packets, and counting
  as no acceptance gate. Verification passed in the dev container: focused
  operator-guide unittest 6 OK, full KG-eval unittest 402 OK, changed-file Ruff
  check and format check, refreshed broad KG-eval reports, main repo unittest
  252 OK, and main KG acceptance remains unchanged
  (`passed_with_explicit_limits`; strict fails only on known limits). The full
  KG objective is still active and broad KG-eval remains `overall_passed=false`
  with the same four failed real-evidence gates.
- 2026-06-27 operator-guide sync check: added `--check` mode to
  `.formowl/kg-eval/real_evidence_operator_guide.py`, and the tracked guide now
  documents `python3 real_evidence_operator_guide.py --check`. The focused
  tests cover both an up-to-date guide and a stale guide that fails without
  being rewritten. Dev-container verification passed: guide `--check`, focused
  operator-guide unittest 8 OK, full KG-eval unittest 404 OK, changed-file Ruff
  check and format check, refreshed broad KG-eval reports, main repo unittest
  252 OK, and main KG acceptance state remains unchanged. Broad KG-eval is
  still `overall_passed=false` with the same four failed real-evidence gates.
- 2026-06-27 submission-manifest preflight and skill-portability progress:
  added `.formowl/kg-eval/real_evidence_submission_manifest.py`, focused tests,
  and the tracked non-evidence template
  `.formowl/kg-eval/work_packets/remaining_real_evidence_submission_manifest.template.json`.
  The operator guide now tells future operators to run
  `python3 real_evidence_submission_manifest.py --check-template` and validate
  an operator-filled manifest before running candidate-only intake commands.
  This preflight checks response paths directly under the matching ignored
  `inputs/*_real/<operator_run_id>/` run directory, run ids, response packet
  types, output dirs, and non-authoritative claim boundaries only; it reads no
  response-packet contents, writes no candidate artifacts, promotes no
  evidence, and writes no canonical input packets. The repo-local
  `$use-agy-antigravity` skill was
  updated in `.agents/skills/use-agy-antigravity/SKILL.md` so the KG `agy`
  authorization/reviewer/write-delegation workflow is explicitly portable after
  git clone. Template emit/check is restricted to the tracked `.template.json`
  path so it cannot overwrite arbitrary `work_packets/*.json` manifests.
  Dev-container verification passed: submission template check, operator guide
  check, focused submission/guide unittest 17 OK, full KG-eval unittest
  413 OK, changed-file Ruff check and format check, refreshed broad reports,
  main repo unittest 252 OK, and default KG acceptance
  `passed_with_explicit_limits`; strict still fails only on known limits. The
  full KG objective remains active and broad KG-eval is still
  `overall_passed=false` with the same four failed real-evidence gates.
  Antigravity Gemini review for this slice is blocked at 0/3: a bounded
  read-only `agy` reviewer packet containing only relevant paths, summaries,
  verification results, and claim boundaries was rejected before execution by
  tenant policy as external disclosure to an untrusted reviewer service. No
  packet was sent and no workaround or alternate external channel was
  attempted. Codex/GPT reviewers `Dalton`, `Galileo`, `Volta`, and `Feynman`
  returned `RELEASE_DECISION: AGREE`; Dalton's non-blocking template-output
  narrowing suggestion was implemented with a regression test.

## 2026-06-28

- Submission-manifest CLI/work-packet tracking hardening: `--manifest` now
  validates the operator-filled manifest path before reading it and accepts
  only safe repo-relative JSON files under `work_packets/`; templates,
  tracked preview-packet names, absolute/raw/dot-segment paths,
  non-work-packet paths, and symlink components are rejected. `.gitignore` now
  ignores arbitrary operator-generated `work_packets/*.json` outputs and only
  re-includes the four fixed preview packets, the tracked submission template,
  and the tracked operator guide. The guide states that operator-filled
  manifests and generated candidate manifests under `work_packets/` are
  intentionally ignored. This is operator-flow hardening only: it reads no
  response contents, writes no candidate artifacts, promotes no evidence,
  writes no canonical packets, and does not count as an acceptance gate.
  Dev-container verification passed: submission template check, guide check,
  focused submission/guide unittest 20 OK, full KG-eval unittest 416 OK, main
  repo unittest 252 OK, changed-file Ruff check and format check, refreshed
  broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and 4 failed gates
  (`fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`);
  `inputs/*_real` contains no files and the four canonical broad packets are
  absent. GPT/Codex reviewers `Godel`, `Gibbs`, and `Ohm` agreed after
  blockers for dot-segment normalization and broad `*_preview.json` tracking
  were fixed. A bounded `agy` write-delegation attempt for `.formowl/kg-eval`
  was rejected before execution by tenant policy as private repository
  disclosure to an untrusted external Antigravity service; no packet was sent
  and no workaround was attempted.
- Candidate-manifest validation guidance: collection work orders and the
  tracked operator guide now direct post-intake validation to the ignored
  candidate manifests emitted by response intake under
  `work_packets/*_candidate_manifest.json`, while keeping
  `work_orders/*_assembly_manifest.json` generation as optional non-evidence
  scaffold inspection only. `_common_commands` now fails closed if a remaining
  gate lacks a response-intake candidate manifest mapping instead of falling
  back to scaffold validation. This is operator-flow guidance only; it writes
  no candidate artifacts, promotes no evidence, writes no canonical packets,
  and does not count as an acceptance gate. Dev-container verification passed:
  guide check, focused work-order/guide unittest 26 OK, full KG-eval unittest
  417 OK, main repo unittest 252 OK, changed-file Ruff check and format check,
  refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`. Broad KG-eval remains incomplete:
  `overall_passed=false`, 8 passed gates, and 4 failed gates; `inputs/*_real`
  contains no files and the four canonical broad packets are absent.
  GPT/Codex reviewers `Bohr`, `Euler`, and `Lorentz` agreed after Lorentz's
  scaffold-fallback blocker was fixed. Antigravity remains blocked by tenant
  policy for bounded FormOwl KG repository disclosure; no workaround was
  attempted.
- Current-state execution after reviewer request: `git fetch origin` found no
  newer `complete-slice-1` commit beyond `f3ba5f8`, and the worktree was clean.
  Codex reran the broad KG-eval and main-repo verification in the dev
  container: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`,
  `real_evidence_collection_work_orders.py`, full KG-eval unittest 417 OK,
  main repo unittest 252 OK, default main KG acceptance
  `passed_with_explicit_limits`, and strict main KG acceptance exited nonzero
  only for the known `production_adapter_readiness` failed item and
  `latency_scalability_enterprise_claims` blocked item. Broad KG-eval remains
  incomplete with `overall_passed=false`, 8 passed gates, and 4 failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`.
  `inputs/*_real` contains zero files and the four canonical broad packets are
  absent. No completion claim is supported.
- Candidate intake execution-plan slice: `real_evidence_submission_manifest.py`
  can now emit a non-evidence candidate intake execution plan from a validated
  operator-filled submission manifest using `--emit-intake-plan`. The plan is
  restricted to safe ignored `work_packets/*.json` outputs, records exact
  candidate-only intake argv/commands, executes nothing, reads no response
  packet contents during planning, writes no candidate artifacts, writes no
  canonical packets, promotes no evidence, and counts as no acceptance gate.
  The operator guide documents the optional plan step. Tests now assert no
  changes to real roots, canonical broad packets, or
  `work_packets/*_candidate_manifest.json`, and invalid-manifest plan emission
  writes no plan file. Dev-container verification passed: focused
  submission/guide unittest 24 OK, full KG-eval unittest 421 OK, main repo
  unittest 252 OK, changed-file Ruff check and format check, guide/template
  checks, refreshed broad reports, and default main KG acceptance
  `passed_with_explicit_limits`; strict still exits nonzero only for known
  limits. Broad KG-eval remains incomplete with the same 4 failed gates.
  GPT/Codex reviewers `Boole`, `Maxwell`, and `Avicenna` agreed after Boole's
  blocker was fixed and Maxwell's hardening note was implemented. Antigravity
  Gemini review is blocked at 0/3 because tenant policy rejected a bounded
  closed-book `agy` reviewer packet before execution as private
  repository-derived disclosure to an untrusted external reviewer service; no
  packet was sent and no workaround was attempted.
- Agy MCP route and gate-policy checkpoint: at the user's request, Codex tested
  whether Antigravity/`agy` can be reached through MCP. Current Codex tool
  discovery exposes no Antigravity/`agy` MCP tool; Codex config has no
  Antigravity MCP server; Antigravity global `mcp_config.json` is empty; this
  repo has no `.agents/mcp_config.json`; `agy --help` exposes no MCP server
  subcommand; `agy plugin list` shows no imported plugins; and a
  no-repository-content `agy --new-project --print "/mcp"` probe from `/tmp`
  returned general MCP configuration guidance rather than an active server/tool
  list. Conclusion: Antigravity can use MCP tools inside its own session, but
  this Codex environment currently has no MCP path for Codex to call
  Antigravity/`agy`. The default FormOwl KG reviewer gate is now 3 Codex/GPT
  reviewers only, and `agy` reviewer/write delegation is disabled unless the
  user explicitly re-enables it after policy, platform, or MCP configuration
  changes. This policy checkpoint does not change broad KG-eval acceptance:
  `overall_passed=false` with the same four failed real-evidence gates.
- Current-state execution after user request: `git fetch origin` found no
  newer commit beyond `63df752` (`Document agy MCP route disablement`) on
  `complete-slice-1`, and the branch matched `origin/complete-slice-1`.
  Codex reran the broad KG-eval and main-repo verification in the dev
  container: `kg_total_acceptance_suite.py`,
  `kg_objective_completion_audit.py`, `real_evidence_preflight.py`,
  `real_evidence_collection_work_orders.py`, full KG-eval unittest, operator
  guide `--check`, submission template `--check-template`, main repo unittest,
  default main KG acceptance, and strict main KG acceptance. KG-eval reports
  exited 0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0;
  main repo unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and 4 failed gates:
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements. No completion claim is supported.
- Follow-up current-state execution after user request: `git fetch origin`
  found no newer commit beyond `bf0fc2b` (`Record KG current verification
  run`) on `complete-slice-1`, and the branch matched
  `origin/complete-slice-1`. Codex reran broad KG-eval and main-repo
  verification in the dev container without code changes:
  `kg_total_acceptance_suite.py`, `kg_objective_completion_audit.py`,
  `real_evidence_preflight.py`, `real_evidence_collection_work_orders.py`,
  full KG-eval unittest, operator guide `--check`, submission template
  `--check-template`, main repo unittest, default main KG acceptance, strict
  main KG acceptance, and full Ruff lint/format checks. KG-eval reports
  exited 0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0;
  main repo unittest ran 252 tests OK; default main KG acceptance remains
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Full Ruff lint passed, but full Ruff format-check
  still reports 33 pre-existing files that would be reformatted. Broad KG-eval
  remains incomplete with `overall_passed=false`, 8 passed gates, and 4 failed
  gates: `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Objective
  audit remains `objective_complete=false`, with 5 proved and 4 incomplete
  requirements; all four real roots have no files and the four canonical broad
  packets are absent. No completion claim is supported.
- Formatting cleanup: Codex mechanically formatted the 33 files previously
  reported by full Ruff format-check, using the dev container and an external
  `/tmp` Ruff cache to avoid the root-owned `.ruff_cache` permission issue.
  Verification passed after formatting: full Ruff lint and format-check, full
  KG-eval unittest 421 OK, main repo unittest 252 OK, operator guide
  `--check`, submission template `--check-template`, refreshed broad KG-eval
  reports, and default main KG acceptance `passed_with_explicit_limits`;
  strict main KG acceptance still exits nonzero only for known limits. This was
  format-only cleanup and does not change broad KG acceptance:
  `overall_passed=false` with the same four failed real-evidence gates.
- Operator submission-manifest input hardening: `--manifest` now rejects
  generated `*_candidate_manifest.json` and `*_intake_plan.json` paths so
  downstream non-evidence outputs cannot be mistaken for operator-filled
  submission manifests. The operator guide documents this boundary, and tests
  cover the rejected names and guide warning. This does not accept evidence,
  write candidate artifacts, promote canonical packets, or change acceptance
  state. Verification passed: host focused submission/guide unittest 24 OK,
  dev-container focused submission/guide unittest 24 OK, guide/template
  checks, full KG-eval unittest 421 OK, main repo unittest 252 OK, full Ruff
  check and format-check, refreshed broad reports, and default main KG
  acceptance `passed_with_explicit_limits`; strict still exits nonzero only
  for known limits. Broad KG-eval remains `overall_passed=false` with the same
  four failed real-evidence gates. GPT/Codex reviewers `Dirac`, `Zeno`, and
  `Hypatia` agreed; Hypatia re-reviewed the final test-only assertion with
  `RELEASE_DECISION: AGREE`.
- Post-`27ff851` verification checkpoint: local Git state was clean at
  `27ff851` (`Harden KG submission manifest input guard`) on
  `complete-slice-1`, and the branch matched `origin/complete-slice-1`.
  Dev-container verification reran the broad KG-eval reports, full KG-eval
  unittest, operator guide `--check`, submission template `--check-template`,
  main repo unittest, full Ruff check/format-check, default main KG
  acceptance, and strict main KG acceptance. Results: KG-eval reports exited
  0; KG-eval unittest ran 421 tests OK; guide/template checks exited 0; main
  repo unittest ran 252 tests OK; Ruff passed with `200 files already
  formatted`; default main KG acceptance remains `passed_with_explicit_limits`;
  strict main KG acceptance still exits nonzero only for known limits. Broad
  KG-eval remains incomplete with `overall_passed=false`, 8 passed gates, and
  4 failed gates: `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`. Objective audit remains
  `objective_complete=false`, with 5 proved and 4 incomplete requirements.
  Work-board unchecked engineering item count remains 9: 1 KG-owned full
  real-evidence objective and 8 System Backbone/product-infra items. No
  completion claim is supported.
- Submission-manifest hardlink-alias guard: `real_evidence_submission_manifest.py
  --manifest` now rejects hardlink aliases for the operator-filled manifest
  input and required `response_packet` files before candidate intake. The
  check inspects only regular-file existence and link count; it still reads no
  response packet contents, writes no candidate artifacts, promotes no
  evidence, writes no canonical packets, and counts as no acceptance gate. The
  tracked operator guide documents the hardlink boundary. Verification passed:
  host focused submission/guide unittest 26 OK; dev-container focused
  submission/guide unittest 26 OK; guide/template checks; full KG-eval
  unittest 423 OK; main repo unittest 252 OK; full Ruff check and
  format-check; refreshed broad reports; and default main KG acceptance
  `passed_with_explicit_limits`. Strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with the same four
  failed real-evidence gates. GPT/Codex reviewers `Confucius`, `Mendel`, and
  `Leibniz` returned `RELEASE_DECISION: AGREE`.
- Canonical broad-packet path guard: the four broad real-evidence validators
  now reject direct symlinks, hardlink aliases (`st_nlink > 1`), and
  non-regular canonical input packet paths before JSON parsing. The blocker
  propagates through `validate_packet()` so reports remain failed and
  claim-boundary flags stay false. Added
  `.formowl/kg-eval/test_canonical_evidence_packet_path_guards.py` for
  symlink, hardlink, and directory packet paths across fair baseline, human
  annotation, enterprise multimodal, and production adapter validators. This
  is acceptance hardening only: it accepts no evidence, writes no candidate
  artifacts, promotes no packets, writes no canonical broad packets, and
  changes no broad gate status. Verification passed: host focused validator
  unittest 107 OK; dev-container focused validator unittest 107 OK; full
  KG-eval unittest 426 OK; main repo unittest 252 OK; full Ruff check and
  format-check; operator guide `--check`; submission template
  `--check-template`; refreshed broad reports; and default main KG acceptance
  `passed_with_explicit_limits`. Strict main KG acceptance still exits
  nonzero only for known limits. Broad KG-eval remains incomplete with the
  same four failed real-evidence gates and empty real roots. GPT/Codex
  reviewer gate passed 3/3: `Nietzsche`, `Bacon`, and `Copernicus`; a no-op
  `Averroes` spawn is not counted.
- Preflight canonical packet path-hazard guard: `real_evidence_preflight.py`
  now detects symlink, hardlink, and non-regular canonical packet paths before
  refreshing total acceptance, objective audit, or per-gate validators. It
  reports `canonical_packet_path_hazards`, leaves the preflight blocked, skips
  validator refreshes under hazards, and avoids reading or hashing alias packet
  paths. Dev-container verification passed: focused preflight unittest 17 OK,
  full KG-eval unittest 428 OK, main repo unittest 252 OK, full Ruff
  check/format-check, refreshed broad reports, operator guide `--check`,
  submission template `--check-template`, and default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance still exits nonzero
  only for known limits. Broad KG-eval remains incomplete with the same four
  failed real-evidence gates, empty real roots, and absent canonical packets.
  GPT/Codex reviewer gate passed 3/3: `Beauvoir`, `Dewey`, and `Rawls` after
  `Beauvoir`'s total/audit refresh blocker and `Dewey`'s test-cleanup /
  no-validator-run blockers were fixed and re-reviewed. A mistakenly spawned
  no-op `Laplace` agent is not counted.
- Candidate-intake execution runner: `real_evidence_submission_manifest.py`
  now supports explicit `--execute-candidate-intakes` for a validated
  operator-filled submission manifest. It uses fixed manifest-derived argv,
  runs existing candidate-only intake helpers without a shell, requires
  existing response packets, rejects path-only execution mode, stops on first
  failed intake, and reports that successful earlier candidate artifacts remain
  for operator review. This runner can read operator response contents and
  write candidate artifacts, but it does not promote evidence, pass promotion
  flags, write canonical broad packets, or count as acceptance. The tracked
  operator guide documents the command and claim boundary. Verification
  passed: focused dev-container submission/guide unittest 33 OK, full KG-eval
  unittest 435 OK, main repo unittest 252 OK, guide/template checks,
  changed-file Ruff check and format-check, refreshed total/preflight reports,
  and default main KG acceptance `passed_with_explicit_limits`; strict still
  exits nonzero only for known limits. Broad KG-eval remains incomplete with
  the same four failed real-evidence gates and empty real roots. Reviewer gate
  passed 3/3 with `Nash`, `Pauli`, and `Locke`; `Hegel`'s docstring/help
  blocker was fixed and re-reviewed by replacement reviewer `Locke`.
  Non-counted agents: `Pascal`, `Sagan`, `Bernoulli`, `Arendt`, and blocker-only
  `Hegel`.
- Candidate-manifest validate-only runner: `real_evidence_submission_manifest.py`
  now supports `--validate-candidate-manifests` after candidate-only intake.
  It validates the operator submission manifest first, requires the four fixed
  emitted `work_packets/*_candidate_manifest.json` files to exist as safe
  regular non-symlink/non-hardlink files, then runs fixed assembler argv in
  `--validate` mode only with no shell. The runner reads candidate manifests
  and candidate artifacts through the assemblers, summarizes validation output
  without echoing assembled candidate packets, writes no candidate artifacts,
  passes no `--promote`, writes no canonical broad packets, promotes no
  evidence, and does not count as acceptance. Verification passed: focused
  dev-container submission/guide unittest 41 OK, full KG-eval unittest 443 OK,
  main repo unittest 252 OK, guide/template checks, full Ruff check/format
  check, refreshed broad reports, default KG acceptance
  `passed_with_explicit_limits`, and strict KG acceptance exits 1 only for the
  known `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked limits. Broad KG-eval
  remains incomplete with the same four failed real-evidence gates, empty real
  roots, and absent canonical packets. Reviewer gate passed 3/3:
  `Einstein`, `Sartre`, and `Heisenberg`; all three suggested direct hardlink
  test coverage for emitted candidate manifests, the test was added, and
  `Einstein` re-reviewed the final delta with `AGREE`.
- Candidate-validation report output: `real_evidence_submission_manifest.py
  --validate-candidate-manifests` now accepts optional
  `--emit-candidate-validation-report` to persist the validate-only result as
  an ignored non-evidence `work_packets/*_candidate_validation_report.json`
  review aid. The output must be a direct child of `work_packets/`, cannot use
  template/preview/candidate-manifest/intake-plan/tracked names, cannot
  overwrite an existing file, and is written through a same-directory
  temporary file plus atomic no-overwrite link so interrupted writes leave no
  final partial JSON report. Invalid operator manifests and missing emitted
  candidate manifests do not write a report; failed assembler validation after
  preflight may write a failure report for manual review only. Verification
  passed: host focused submission/guide unittest 48 OK; dev-container focused
  submission/guide unittest 48 OK; full KG-eval unittest 450 OK; main repo
  unittest 252 OK; guide/template checks; full Ruff check/format-check;
  refreshed broad reports; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for the known
  `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked limits. Broad KG-eval
  remains incomplete with the same four failed real-evidence gates, empty real
  roots, and absent canonical packets. Reviewer gate state: `Turing` agreed;
  `Cicero` agreed after nested-path and partial-write blockers were fixed;
  `Boyle` agreed after missing-durable-doc and stale-checkpoint blockers were
  fixed. Reviewer gate passed 3/3. A no-op `McClintock` spawn is not counted.
- Intake-plan output path hardening: `real_evidence_submission_manifest.py
  --emit-intake-plan` now rejects nested `work_packets/...` output paths.
  Intake plans must be safe direct children of `work_packets/`, matching the
  ignored operator work-packet surface used by candidate-validation reports.
  Focused regression coverage was added. Verification passed: host focused
  submission-manifest unittest 40 OK; dev-container focused
  submission-manifest unittest 40 OK; full KG-eval unittest 450 OK; main repo
  unittest 252 OK; refreshed broad reports; guide/template checks; full Ruff
  check/format-check; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for known limits. Broad KG-eval remains
  incomplete with the same four failed real-evidence gates, empty real roots,
  and absent canonical packets. Reviewer gate passed 3/3: `Anscombe` agreed
  on engineering path safety, `Epicurus` agreed on governance and non-evidence
  boundaries, and `Ptolemy` agreed on durable docs/status honesty.
- 2026-06-28 status-only resume checkpoint: after the user asked for remaining
  engineering-item count, Codex confirmed the work board still has 9 unchecked
  items: 1 KG-owned full real-evidence objective and 8 System
  Backbone/product-infra items. Dev-container verification in this resume
  passed for KG-eval unittest 450 OK and main repo unittest 252 OK. A later
  dev-container report refresh command was rejected by the approval reviewer
  because it required unsandboxed Docker socket access with workspace writes;
  sandbox host-level supplemental report commands exited 0 and still showed
  the same blocked broad KG state. Host `ruff` is unavailable, so lint/format
  was not rerun in this resume. Safety checks found all four `inputs/*_real`
  roots empty and the four canonical broad evidence packets absent. The full
  KG objective remains active and incomplete with the same four failed broad
  gates.
- 2026-06-28 intake-plan partial-write hardening: the candidate-only
  `real_evidence_submission_manifest.py --emit-intake-plan` path now writes
  ignored non-evidence intake plans through a temporary file plus atomic
  no-overwrite link, matching the candidate-validation report writer. A
  regression test now simulates interrupted intake-plan writes and asserts
  that neither a final partial plan nor a temporary partial file remains. This
  accepts no evidence, writes no candidate artifacts, promotes no evidence,
  writes no canonical broad packet, and does not count as acceptance. Host
  verification passed: focused submission-manifest unittest 41 OK, full
  KG-eval unittest 451 OK, main repo unittest 252 OK, guide check after
  regeneration, template check, and host main KG acceptance default
  `passed_with_explicit_limits`; strict exits 1 only for the known failed /
  blocked items. Broad KG-eval remains incomplete with the same four failed
  gates, empty real roots, and absent canonical packets. Canonical
  dev-container verification, Git commit/push, and reviewer gate are pending
  because escalated Docker/Git/network permissions were rejected in this
  resume.
- 2026-06-28 real-root churn preflight hardening: `real_evidence_preflight.py`
  now treats files that disappear during `inputs/*_real` scanning as unstable
  non-evidence. The scanner records `disappeared_file_count` and
  `disappeared_file_paths`, does not count those paths as files or candidate
  artifacts, keeps `root_ready=false`, and makes the hazard summary non-clear.
  This prevents concurrent operator/test cleanup from crashing preflight or
  accepting transient files. A regression test simulates a disappearing real
  artifact during scan. This accepts no evidence, writes no candidate
  artifacts, promotes no evidence, writes no canonical broad packets, and does
  not count as acceptance. Host verification passed: focused preflight unittest
  18 OK, focused submission-manifest unittest 41 OK, full KG-eval unittest
  452 OK, main repo unittest 252 OK, guide/template checks, refreshed broad
  reports, and host main KG acceptance default `passed_with_explicit_limits`;
  strict exits 1 only for known failed / blocked items. Broad KG-eval remains
  incomplete with the same four failed gates, empty real roots, absent
  canonical packets, and zero disappeared-file hazards in the current scan.
  Canonical dev-container verification, Git commit/push, and reviewer gate are
  still pending because escalated Docker/Git/network permissions were rejected
  in this resume.
- 2026-06-28 work-order disappeared-file contract hardening:
  `real_evidence_collection_work_orders.py` now carries
  `real_root_disappeared_file_count` in each work-order preflight snapshot and
  fails closed if per-gate preflight rows omit, mistype, or report nonzero
  `disappeared_file_count`. This keeps unstable real-root scans from being
  treated as clean missing-evidence absence in operator work orders. Reviewer
  blocker fix: real-root scanning now uses `lstat()` before file-type
  classification, so a path that disappears before the old `is_file()` check
  is reported through `disappeared_file_count` instead of being silently
  treated as clean absence. The tracked operator guide remains synchronized
  after the work-order report schema/hash changed. This accepts no evidence,
  writes no candidate artifacts, promotes no evidence, writes no canonical
  broad packets, and does not count as acceptance. Canonical dev-container
  verification passed: focused current-slice KG-eval unittest 79 OK, full
  KG-eval unittest 454 OK, main repo unittest 252 OK, guide/template checks,
  refreshed broad reports, default main KG acceptance
  `passed_with_explicit_limits`, strict main KG acceptance exits 1 only for
  known limits, full Ruff check and format-check, and `git diff --check`.
  Broad KG-eval remains incomplete with `overall_passed=false`, 8 passed
  gates, and the same four failed gates. Reviewer gate passed 3/3 after blocker
  fixes: `Curie`, `Erdos`, and `Hume` returned `RELEASE_DECISION: AGREE`.
  This slice was committed and pushed on `complete-slice-1` as `8fc5a55`
  (`Harden KG real-evidence preflight work orders`).
- 2026-06-28 restart-note cleanup: `.formowl/kg-eval/SESSION_RESTART.md`
  still had an older "Next Best Work" section saying broad validators needed
  real-root path-helper hardening. That target is complete, with tests covering
  `results/`, `inputs/test_*`, templates, and template-named artifacts under
  real roots. The restart note now treats that as historical and points the
  next action back to canonical dev-container verification plus real
  operator/user-supplied evidence for the four failed gates. Host consistency
  checks passed: `git diff --check`, operator guide `--check`, submission
  template `--check-template`, and focused work-order unittest 19 OK.
- 2026-06-28 historical blocked audit, superseded later the same day by user
  authorization and canonical verification: the same external blocker repeated
  across continuation turns, with canonical dev-container Docker verification
  rejected by the approval reviewer and Git commit/push blocked. This is no
  longer the current Docker/Git state for this run; it remains only as audit
  history. The four broad gates still require real operator/user-supplied
  evidence packets.
- 2026-06-28 resume authorization: the user explicitly authorized collecting
  failed-gate evidence, Docker/dev-container access, and Git commit/push.
  Durable KG goal status is active again for this run, and canonical
  dev-container verification plus the 3 Codex/GPT reviewer gate for the
  current work-order/preflight hardening slice have passed. Reviewer gate
  result: `Curie`, `Erdos`, and `Hume` returned `RELEASE_DECISION: AGREE`
  after blocker fixes. The slice was pushed as `8fc5a55` on
  `complete-slice-1`. The broad KG objective still remains incomplete until
  real operator/user-supplied artifacts and governed canonical packets make the
  four broad gates pass.
- 2026-06-28 post-push checkpoint: local `HEAD` and
  `origin/complete-slice-1` both point to `8fc5a55`
  (`Harden KG real-evidence preflight work orders`) with a clean worktree
  before this status-doc update. The next KG-owned work remains real
  operator/user-supplied evidence collection and governed packet validation for
  `fair_external_baseline_comparison`,
  `annotation_adjudication_protocol`,
  `multimodal_semantic_validation`, and `production_adapter_paths`. Do not
  treat work orders, candidate manifests, intake plans, or validation reports
  as acceptance evidence.
- 2026-06-28 candidate-runner canonical packet integrity: the controlled
  submission-manifest runners now snapshot all four canonical broad packet
  paths before subprocess execution and fail closed if candidate-only intake or
  validate-only assembler subprocesses exit with a canonical packet path
  created or changed. The output reports `canonical_packet_integrity`; this is
  final-state surface integrity, not a live transient-write audit. The tracked
  operator guide documents that boundary. Verification passed in the dev
  container: focused submission/guide unittest 51 OK, full KG-eval unittest
  456 OK, main repo unittest 252 OK, guide/template checks, refreshed broad
  reports, default KG acceptance `passed_with_explicit_limits`, strict KG
  acceptance exits 1 only for known limits, and full Ruff check/format-check.
  Reviewer gate passed 3/3 with `Sagan`, `Hooke`, and `Laplace`; a mistaken
  no-op `Banach` subagent is not counted. Broad KG-eval remains incomplete
  with `overall_passed=false`, 8 passed gates, and the same four failed gates.
- 2026-06-28 candidate-runner pre-existing canonical packet hazard guard: the
  controlled `real_evidence_submission_manifest.py
  --execute-candidate-intakes` and `--validate-candidate-manifests` runners
  now refuse to launch subprocesses if any canonical broad packet path is
  already a symlink, hardlink alias, non-regular file, or unreadable /
  metadata-unavailable surface. The refusal path returns
  `executed_gate_count=0`, reports `canonical_packet_baseline`, reads no
  response packet or candidate manifest contents, writes no candidate
  artifacts, promotes no evidence, and writes no canonical broad packets. The
  tracked operator guide documents the boundary. Canonical dev-container
  verification passed: focused submission/guide unittest 55 OK, full KG-eval
  unittest 460 OK, main repo unittest 252 OK, guide/template checks,
  refreshed broad reports, default KG acceptance `passed_with_explicit_limits`,
  strict KG acceptance exits 1 only for known limits, full Ruff
  check/format-check, and `git diff --check`. Broad KG-eval remains
  incomplete with the same four failed real-evidence gates. Reviewer gate
  passed 3/3: `Wegener` agreed on engineering correctness after the canonical
  packet test helper was changed to preserve pre-existing path surfaces by
  rename; `Feynman` agreed on governance/safety; and `Kuhn` agreed on status
  honesty.
- 2026-06-28 governed approval-bridge hardening: added the non-evidence
  governance approval runner, focused tests, and tracked approval template.
  The runner validates an operator-filled approval manifest before any
  canonical packet update by binding the candidate validation report hash,
  candidate manifest hash, target gate, canonical packet, exact validate-only
  validation argv, exact approval scope / claim boundary, and human approver.
  Execute mode uses fixed assembler `--promote` argv, rechecks candidate
  manifest hash after the subprocess, verifies only the target canonical
  packet changed, and rolls back a newly created target packet on
  candidate-manifest drift. The four packet assemblers now promote through a
  temporary file plus atomic no-overwrite hard link; candidate validation
  reports include `candidate_manifest_sha256`; canonical packet surface checks
  reject hazardous parent components; and the operator guide documents the
  controlled approval flow. Canonical dev-container verification passed:
  focused approval/submission unittest 57 OK; approval-template,
  operator-guide, and submission-template checks; full KG-eval unittest
  470 OK; main repo unittest 252 OK; full Ruff check/format-check; refreshed
  broad reports; default KG acceptance `passed_with_explicit_limits`; strict
  KG acceptance exits 1 only for known limits. Real roots remain empty,
  canonical broad packets remain absent, and broad KG-eval remains incomplete
  with the same four failed gates. Reviewer gate is pending final 3 Codex/GPT
  re-review for this slice; do not claim the goal complete.
- 2026-06-28 governed approval-bridge reviewer-blocker follow-up:
  Bernoulli found a candidate-manifest TOCTOU blocker: post-subprocess rehash
  alone could miss a transient swap/restore before assembler read. The fix
  adds an approved `--assembly-manifest-sha256` guard to approved promotion
  argv and makes all four packet assemblers hash the manifest bytes they read
  before assembly/promotion. The operator guide and durable docs now state this
  boundary. Canonical dev-container verification after the fix passed:
  focused approval/assembler/operator-guide unittest 78 OK; full KG-eval
  unittest 474 OK; main repo unittest 252 OK; approval-template,
  operator-guide, and submission-template checks; full Ruff check/format-check;
  refreshed broad reports; default KG acceptance `passed_with_explicit_limits`;
  strict KG acceptance exits 1 only for known limits. Broad KG-eval remains
  incomplete with the same four failed gates; all four real roots remain empty
  and canonical broad packets remain absent. Reviewer gate passed 3/3:
  `Bernoulli` agreed after the TOCTOU blocker fix, `Popper` agreed after the
  final hash-guard delta, and `Dalton` agreed after durable docs/tracking were
  updated and staged.
- 2026-06-28 human annotation response-intake hardening: the candidate-only
  `human_annotation_response_intake.py` path now requires response-packet
  top-level allowlisting, `operator_run_id` to match the output directory
  final segment, unsupported nested field rejection, raw/internal field-name
  rejection, parent directory preflight, nested default real-root output-dir
  rejection, after-open partial write cleanup, and rollback of already-created
  candidate artifacts plus optional candidate manifests when assembler
  assembly or validation execution raises after writes. A completed
  validate-only report with `passed=false` remains candidate-only evidence
  state, not canonical evidence. It emits a non-authoritative response custody
  receipt binding response packet, candidate packet, candidate artifact, and
  optional candidate-manifest hashes, and the tracked operator guide lists the
  controls for `annotation_adjudication_protocol`. Canonical dev-container
  verification passed: focused human-intake/work-order/operator-guide unittest
  48 OK, full KG-eval unittest 482 OK, main repo unittest 252 OK, guide and
  submission-template checks, refreshed broad reports, default KG acceptance
  `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
  limits, full Ruff check/format-check, and `git diff --check`. Broad KG-eval
  remains incomplete with `overall_passed=false`, 8 passed gates, and the same
  four failed gates; all real roots are empty and canonical broad packets are
  absent. Reviewer gate passed 3/3: `Socrates` agreed on engineering
  correctness, `Gibbs` agreed on governance/safety after the validation-report
  wording was narrowed, and `Pascal` agreed on status honesty after the same
  wording update.
- 2026-06-28 fair-baseline response-intake hardening: the candidate-only
  `fair_baseline_response_intake.py` path now requires response-packet
  top-level allowlisting, `operator_run_id` to match the output directory
  final segment, baseline-run and adjudication/graph-quality/permission-probe
  wrapper-field allowlisting, raw/internal field-name rejection throughout the
  response payload, parent directory preflight, default real-root output-dir
  restriction to `inputs/fair_baseline_real/<operator_run_id>`, after-open
  partial write cleanup, and rollback of already-created candidate artifacts
  plus optional candidate manifests when assembler assembly or validation
  raises after writes. It emits a non-authoritative response custody receipt
  binding response packet, candidate packet, candidate artifact, and optional
  candidate-manifest hashes, and the tracked operator guide lists the controls
  for `fair_external_baseline_comparison`. Canonical dev-container
  verification passed: focused fair-intake/work-order/operator-guide unittest
  46 OK, full KG-eval unittest 490 OK, main repo unittest 252 OK, guide,
  submission-template, and governance-approval-template checks, refreshed
  broad reports, default KG acceptance `passed_with_explicit_limits`, strict
  KG acceptance exits 1 only for known limits, full Ruff check/format-check,
  and `git diff --check`. Broad KG-eval remains incomplete with
  `overall_passed=false`, 8 passed gates, and the same four failed gates; all
  real roots are empty and canonical broad packets are absent. Reviewer gate
  passed 3/3 after blocker fixes: `Arendt` agreed on engineering correctness
  after the final delta, `Confucius` agreed on governance/safety after the
  work-order report stopped emitting an absolute local workspace path, and
  `Lorentz` agreed on status honesty after the operator guide/control
  inventory listed parent-dir preflight, after-open cleanup, and rollback
  controls.
- 2026-06-28 production-adapter response-intake parity hardening:
  `production_adapter_response_intake.py` now recursively rejects raw/internal
  field names in operator-supplied artifact payloads, including backend
  connection-string field names, and removes outputs created by exclusive open
  when serialization or write fails after open. The intake rollback path now
  also catches raw `OSError` write and custody-hash failures so earlier
  candidate artifacts are cleaned up. Focused tests cover raw/internal
  field-name rejection with benign values, backend connection-string
  field-name rejection, assembler-failure rollback, raw `OSError` rollback,
  custody-phase hash failure rollback, and after-open OSError/TypeError
  cleanup. The
  production work-order response contract and tracked operator guide now list
  output-dir binding, top-level/adapter wrapper allowlisting, parent-dir
  preflight, after-open cleanup, rollback, raw/internal field-name rejection,
  and optional manifest custody hashing. Canonical dev-container verification
  passed: focused production-intake/work-order/operator-guide unittest 47 OK,
  full KG-eval unittest 497 OK, main repo unittest 252 OK, guide/template
  checks, refreshed broad reports, default KG acceptance
  `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
  limits, full Ruff check/format-check, and `git diff --check`. Broad KG-eval
  remains incomplete with `overall_passed=false`, 8 passed gates, and the
  same four failed real-evidence gates; all real roots are empty and the four
  canonical broad packets are absent. Reviewer gate passed 3/3:
  `Heisenberg` agreed on status honesty after the restart note stopped
  claiming commit/push readiness, `Curie` agreed after backend
  connection-string field-name rejection was added, and `Raman` agreed after
  raw write and custody-phase rollback gaps were fixed.
- 2026-06-28 governed approval promotion failure rollback: the approval
  bridge now rolls back a newly created target canonical broad packet when
  `real_evidence_governance_approval.py --execute-approved-promotion` fails
  after subprocess launch, including nonzero return, subprocess `OSError`, and
  Pasteur's hardlink-alias blocker where the assembler fails after linking the
  temporary packet to the canonical target but before unlinking the temporary
  file. The execution report includes `subprocess_error` and
  `rollback_after_failed_promotion`; the operator guide documents that failed
  approved promotion removes the newly created target packet before reporting
  failure. Canonical dev-container verification passed after the hardlink fix:
  focused approval/operator-guide/submission unittest 68 OK, full KG-eval
  unittest 500 OK, main repo unittest 252 OK, guide/template checks, refreshed
  broad reports, default KG acceptance `passed_with_explicit_limits`, strict
  KG acceptance exits 1 only for known limits, full Ruff check/format-check,
  and `git diff --check`. Broad KG-eval remains incomplete with the same four
  failed real-evidence gates, empty real roots, absent canonical broad packets,
  and no packet/artifact hazards. Reviewer gate passed 3/3 after Pasteur's
  hardlink-alias rollback blocker was fixed and re-reviewed:
  `Chandrasekhar`, `Pasteur`, and `Locke` returned
  `RELEASE_DECISION: AGREE`.
- 2026-06-28 gate-progress report: added
  `.formowl/kg-eval/real_evidence_gate_progress.py`, focused tests, and an
  operator-guide section for a compact non-authoritative stage report over the
  four remaining real-evidence gates. It reads persisted preflight/work-order
  reports and tracks safe `work_packets/` candidate manifest,
  candidate-validation report, and approval-manifest surfaces without
  refreshing preflight, reading operator response packets or candidate artifact
  contents, and without writing candidate artifacts, promoting evidence,
  writing canonical packets, replacing validators, or counting as acceptance.
  Current refreshed
  state remains all four gates at `missing_operator_response`, with zero
  candidate manifests, zero clear validation reports, zero valid approvals,
  empty real roots, and absent canonical broad packets. Canonical
  dev-container verification after reviewer blocker fixes passed: focused
  progress/operator-guide unittest 20 OK, full KG-eval unittest 512 OK, main
  repo unittest 252 OK, guide/progress checks, refreshed broad reports, default
  KG acceptance
  `passed_with_explicit_limits`, strict KG acceptance exits 1 only for known
  limits, full Ruff check/format-check, and `git diff --check`. Reviewer gate
  passed 3/3: `Plato`, `Carson`, and `Russell` returned
  `RELEASE_DECISION: AGREE` after blocker fixes. No completion claim is
  supported.
- 2026-06-28 enterprise-multimodal response-intake parity hardening:
  `enterprise_multimodal_response_intake.py` now rejects the same broader
  raw/internal field-name surface as the other hardened candidate-only intake
  paths, including backend connection-string, database/object-store, raw SQL,
  raw path, and worker scratch field names with otherwise benign values.
  Custody receipt construction, optional assembly-manifest hashing, custody
  write, and custody receipt hashing are inside rollback handling, so
  candidate artifacts and optional candidate manifests are removed if custody
  hashing or custody write fails after writes. The enterprise work-order
  response contract and tracked operator guide now list output-dir binding,
  top-level/validation wrapper allowlisting, raw/internal field-name rejection,
  parent-dir preflight, after-open cleanup, rollback, and optional manifest
  custody hashing. Canonical dev-container verification passed: focused
  enterprise-intake/work-order/operator-guide unittest 47 OK, full KG-eval
  unittest 514 OK, main repo unittest 252 OK, guide/progress checks, full Ruff
  check/format-check, and `git diff --check`. Broad KG-eval remains
  incomplete with `overall_passed=false`, 8 passed gates, and the same four
  failed real-evidence gates; all real roots are empty and canonical broad
  packets are absent. Reviewer gate passed 3/3 with `Socrates`, `Gibbs`, and
  `Pascal`. No goal completion claim is supported.
- 2026-06-28 operator response-packet templates:
  added `.formowl/kg-eval/real_evidence_response_packet_templates.py`,
  focused tests, and four tracked non-evidence response-packet templates under
  `work_packets/`. These templates give operators a machine-checkable starting
  shape for the first missing response packets, but they include
  `template_only`, `do_not_submit_as_evidence`, false claim-boundary fields,
  and operator instructions, so response-intake helpers reject them as-is.
  Focused tests prove the templates create no candidate artifacts, no
  candidate manifests, and no canonical packets. The tracked operator guide
  lists the templates and `--check-templates` command. Canonical dev-container
  verification passed: focused response-template/operator-guide unittest
  11 OK, full KG-eval unittest 517 OK, main repo unittest 252 OK,
  response-template/operator-guide/submission-template/approval-template/
  progress checks, full Ruff check/format-check, and `git diff --check`.
  Broad KG-eval remains incomplete with 8 passed gates and the same four
  failed gates. Reviewer gate passed 3/3 with `Euclid`, `Schrodinger`, and
  `Franklin`. No goal completion claim is supported.
- 2026-06-28 operator response-packet preflight:
  all four candidate-only response-intake CLIs now support
  `--preflight-response`, and the submission-manifest intake plan, work orders,
  and operator guide now expose paired response-preflight commands before
  candidate-only intake. The preflight validates response packet shape,
  work-packet/output binding, planned artifact surfaces, raw/internal guards,
  and no-overwrite/parent-dir surfaces without writing candidate artifacts,
  candidate manifests, or canonical broad packets. Nash's reviewer blocker was
  fixed by making enterprise-multimodal and production-adapter intake reject
  forged same-type work packets through generated work-packet state, roots,
  canonical target, collection-plan, validator-expectation, and
  `work_packet_sha256` comparisons. Dev-container verification passed so far:
  focused response-intake/submission/work-order/operator-guide unittest
  162 OK, full KG-eval unittest 524 OK, main repo unittest 252 OK,
  guide/template checks, refreshed broad reports, full Ruff check,
  format-check, and `git diff --check`. Broad KG-eval remains incomplete:
  8 passed gates, 4 failed gates, all four stages
  `missing_operator_response`, empty real roots, and absent canonical broad
  packets. Reviewer gate passed 3/3: `Euler` agreed on engineering
  correctness, `Nash` agreed after the enterprise/production work-packet
  binding blocker was fixed and re-reviewed, and `Beauvoir` agreed on status
  honesty.
- 2026-06-28 submission-manifest response-preflight runner:
  `real_evidence_submission_manifest.py --preflight-responses` validates the
  operator-filled submission manifest, then runs the four fixed intake helper
  `--preflight-response` argv without a shell. It requires existing response
  packets, refuses pre-existing canonical broad-packet path hazards, stops on
  the first failed response preflight, and fails closed if final-state
  canonical packet or candidate-output surfaces change. It reads response
  contents only through existing preflight helpers, writes no candidate
  artifacts or candidate manifests, promotes no evidence, writes no canonical
  broad packets, and does not count as acceptance. Dev-container verification
  passed: focused submission/guide unittest 63 OK, full KG-eval unittest
  531 OK, main repo unittest 252 OK, guide/template/progress checks, refreshed
  broad reports, default KG acceptance `passed_with_explicit_limits`, strict
  exits 1 only for known limits, and full Ruff check/format-check. Reviewer
  gate passed 3/3 with `Huygens`, `Gauss`, and `Ohm`. Broad KG-eval remains
  8/12 with the same four failed gates, all still
  `missing_operator_response`; real roots are empty and canonical broad
  packets are absent.
- 2026-06-28 blocked audit after `1e2010f`: Codex reloaded the KG goal state
  and inspected current real-evidence surfaces. The four ignored real roots
  contain no files, no operator-filled submission/candidate/approval work
  packets are present, and all four canonical broad packets are missing.
  Gate progress remains four `missing_operator_response` stages with zero
  candidate manifests, zero clear validation reports, zero valid approvals,
  and zero canonical validator clears. The durable KG goal is blocked on
  external operator/user evidence; do not continue repository-side hardening as
  if it changes checkpoint progress. Resume only when a real operator response
  packet is supplied, then run submission validation, response preflight,
  candidate intake, candidate validation, governance approval, approved
  promotion, broad validators, and total acceptance.
- 2026-06-28 Plan B provisional adjudication result: the user authorized
  LLM-assisted provisional adjudication with four specialist subagents and
  required all four to pass. Read-only subagents returned 0/4 PASS:
  `Halley` blocked fair baseline, `Sartre` blocked annotation adjudication,
  `Erdos` blocked multimodal validation, and `Avicenna` blocked production
  adapter paths. Each blocker was due to missing real/candidate evidence, not
  because of a human-only requirement: real roots are empty, candidate
  manifests/reports/approvals are absent, and canonical broad packets are
  missing. Plan B cannot advance until there is actual response/candidate
  material for the subagents to judge.
- 2026-06-28 four-specialist LLM panel target correction: after the user
  clarified that adjudication must pass four professional subagents, not any
  generic LLM, the shared KG-eval LLM panel contract now requires
  `four_specialist_llm_subagent_adjudication_v1` artifacts to contain exactly
  four distinct specialist subagents with specialties
  `baseline_methodology`, `annotation_adjudication`, `multimodal_semantics`,
  and `production_governance`, plus fixed professional roles
  `external_baseline_methodologist`,
  `annotation_adjudication_protocol_specialist`,
  `multimodal_semantics_validation_specialist`, and
  `production_governance_adapter_specialist`. All four must independently
  return `PASS`, bind reviewed artifact hashes, have no blocking findings, and
  not claim human adjudication. Legacy human evidence remains
  validator-compatible only for backwards compatibility; the current Plan B
  target is the four-professional-subagent LLM panel route. This correction
  still does not make any broad gate pass because real/candidate evidence is
  missing.
- 2026-06-28 four-specialist LLM route hardening checkpoint: the Plan B route
  is now wired through KG-eval response templates, response intakes,
  assemblers, validators, work orders, preview packets, and durable docs for
  all four failed broad gates. The shared
  `four_specialist_llm_subagent_adjudication_v1` contract rejects generic or
  single-LLM judgments, duplicate subagent/run/prompt/output evidence, missing
  fixed professional roles, missing reviewed-artifact hashes, non-PASS
  subagent decisions, blockers, and any human-adjudication claim. Main-repo KG
  acceptance now names the neutral
  `review_adjudication_claim_boundary` item and does not claim completed legacy
  human labels or completed four-specialist LLM panel decisions. Dev-container
  verification passed: KG-eval unittest 577 OK; main repo unittest 252 OK;
  full Ruff check and format-check; refreshed broad KG-eval reports; response
  template, operator guide, submission template, approval template, and gate
  progress checks; default main KG acceptance
  `passed_with_explicit_limits`; strict main KG acceptance exits 1 only for
  known limits. Broad KG-eval remains incomplete at 8/12 with the same four
  failed gates, all still `missing_operator_response`; real roots are empty,
  candidate manifests/reports/approvals are absent, and canonical broad packets
  are absent. No completion claim is supported.
- 2026-06-28 four-specialist reviewer gate result: the user-requested
  professional subagent gate passed 4/4 for the Plan B route hardening slice.
  Baseline methodology, annotation adjudication, multimodal semantics, and
  production governance reviewers each returned `RELEASE_DECISION: AGREE` with
  no blocking findings. This does not change broad acceptance: KG-eval remains
  8/12 with four failed gates, all still `missing_operator_response`.
- 2026-06-28 fair-baseline cleared and status-tool drift fix, historical and
  superseded by the 2026-06-30 #13 authority correction: at this checkpoint
  broad KG-eval moved to 9/12, not 8/12.
  `fair_external_baseline_comparison` has
  public reproducible evidence, a validator-clear canonical packet, and
  four-specialist LLM subagent approval. Remaining failed gates are
  `annotation_adjudication_protocol`, `multimodal_semantic_validation`, and
  `production_adapter_paths`, all still at `missing_operator_response`.
  Preflight still monitors the historical four-gate evidence surface, but
  work orders and gate progress now use the current three failed gates for
  remaining work. Canonical dev-container verification passed: full KG-eval
  unittest 586 OK, main repo unittest 252 OK, refreshed broad reports,
  operator-guide/submission-template/approval-template/response-template/
  progress checks, and full Ruff check/format-check. The KG objective remains
  incomplete; next gate-changing work is to create or collect real response
  packets through `operator_private` or `public_reproducible` evidence mode for
  one of the remaining three gates, then run candidate intake, validate-only
  assembly, governance approval, approved promotion, per-gate validators, and
  total acceptance. This is no longer current authority; the 2026-06-30 #13
  correction restores the current blocked state to 8/12 with four failed gates.
- 2026-06-28 annotation gate cleared and remaining-gate contraction,
  historical and superseded by the 2026-06-30 #13 authority correction: broad
  KG-eval was recorded as 10/12 at that checkpoint. `annotation_adjudication_protocol` has an
  operator-private canonical packet at `inputs/human_annotation_results_v1.json`,
  validator-clear status, and four-specialist LLM subagent approval without
  claiming completed human annotation. Remaining failed gates are only
  `multimodal_semantic_validation` and `production_adapter_paths`; both remain
  at `missing_operator_response` with empty real roots, zero candidate
  manifests, zero clear candidate-validation reports, zero valid approvals, and
  absent canonical packets. Current hashes: gate status
  `7aaca410e3849053f895ec1cf7c03b5ced1b62cdad0e95030a56bfed42ac0468`,
  objective audit `d6282bc8529c2f4dbf82dbf41789419a54c72b695fd79ae3f3e87254dea86ce2`.
  That 10/12 status is stale and supports no current completion claim. Current
  gate-changing work must use the four failed gates listed in the 2026-06-30
  #13 correction.
- 2026-06-28 broad KG real-evidence completion, retracted 2026-06-30:
  this historical entry previously recorded a local 12/12 state,
  `overall_passed=true`, `passed_gate_count=12`, `failed_gate_count=0`, hashes
  `9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba` and
  `b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d`,
  `validator_clear_for_all_broad_gates`, `work_order_count=0`, and
  `gate_count=0`. Treat this entry as stale and superseded by the 2026-06-30
  #13 authority correction: current KG-eval authority is blocked at 8/12 with
  four failed gates. The historical 12/12 note is not current authority and
  supports no broad completion claim.
- 2026-06-29 KG eval package facade for system integration: added
  `python/formowl_kg_eval/` and the `formowl-kg-eval` console script as a thin
  packaged facade over `.formowl/kg-eval`. The stable downstream entry is
  `formowl-kg-eval summary`, which returns redacted JSON with broad acceptance,
  objective audit, remaining evidence, preflight, work-order, progress, and
  claim-boundary sections. The System Backbone Agent should use this package API
  or CLI instead of importing repo-local evaluator scripts directly. Added
  `docs/kg-eval-package.md` with the integration contract and
  `tests/test_kg_eval_package.py` for workspace resolution, authoritative
  script invocation, summary redaction, and CLI output.
- 2026-06-29 KG candidate-generation capability profiles: added
  `python/formowl_graph/capabilities.py` and surfaced
  `candidate_generation_capabilities` through `formowl_kg_eval summary`.
  The package now tells downstream integration which remote-worker tiers can
  use deterministic CPU generation, local SentenceTransformer/BERT-family
  embedding adapters, or accelerated neural adapters for BERT-family NER,
  relation extraction, local LLM graph extraction, multimodal semantic
  candidates, and large embedding batches. This is a candidate-only contract:
  profiles forbid canonical graph/type writes and raw access, and no default
  BERT runtime claim is made. Dev-container verification passed for focused
  capability tests 5 OK, focused KG-eval package tests 4 OK, full main-repo
  unittest 261 OK, full Ruff check/format-check, and package summary smoke.
  Follow-up BERT vs non-BERT ablation work should start from the pushed commit
  on a new experiment branch and persist benchmark artifacts.
- 2026-06-29 KG benchmark API handoff: the BGE/lexical public enterprise
  benchmark and ontology-ablation artifacts now have a package-level
  integration API. System Backbone should call `formowl-kg-eval summary` and
  read `kg_benchmark_results`, or call `formowl-kg-eval benchmarks` /
  `formowl_kg_eval.build_benchmark_summary()` for benchmark-only output. The
  summary is redacted for integration: it includes dataset counts, metrics,
  deltas, claim boundaries, and repo-relative SVG chart paths, but omits
  per-pair samples and raw labels. Claim boundary remains candidate-only with
  no canonical graph/type writes, no raw-access grants, no production latency
  claim, and no completed human-adjudication claim.
  Reviewer gate passed 3/3 after blocker fixes: `Ramanujan` agreed that the
  clean-checkout artifact blocker was resolved by staging the referenced JSON
  and SVG artifacts; `Epicurus` agreed that the workspace/path exposure blocker
  was resolved by removing top-level `kg_eval_workspace` export, redacting
  command stdout/stderr, and documenting raw command output as developer
  diagnostic only; `Chandrasekhar` agreed on research-method accuracy and
  claim limits.
- 2026-06-29 System Backbone resume after Docker update and KG merge: pulled
  and fast-forwarded `origin/complete-slice-1` to `9ba1528`, applied the
  pre-merge local stash, and resolved shared conflict files by keeping the
  merged upstream versions so KG/contract/wiki work from the other agent is not
  overwritten. The active backbone slice is real OpenProject adapter
  completion. Implementation and the user-requested 6/6 reviewer gate are
  locally present, but the work-board item remains unchecked pending focused
  and full canonical dev-container verification against the merged tree.
  Untracked `.test-tmp-resume/` host artifacts and stale pre-merge graph/wiki
  files should be separated from this OpenProject completion claim.
- 2026-06-29 System Backbone Project MCP adapter milestone complete: after the
  user clarified that OpenProject is only a FormOwl subcomponent, the
  work-board language was tightened to treat it as the Project MCP
  real-backend adapter milestone, not the whole FormOwl plan. Canonical
  dev-container verification passed: focused adapter tests ran 22 OK,
  OpenProject slice Ruff check and format check passed, and the full
  `python -m unittest discover -s tests` suite ran 278 OK. The next System
  Backbone focus should return to FormOwl-wide plumbing, especially Project/Wiki
  MCP JSON-RPC compatibility or gateway coverage, tool schemas/error envelopes,
  retrieval completion, storage configuration, worker boundaries, and
  database-backed stores. Stale untracked pre-merge graph/wiki test artifacts
  that caused discovery import failures were removed.
- 2026-06-29 System Backbone JSON-RPC compatibility milestone complete:
  `McpServerJsonRpcGateway` now wraps existing Project MCP and Wiki MCP server
  objects through JSON-RPC 2.0 `initialize`, `tools/list`, and `tools/call`
  without rewriting their tool behavior. Tests cover Project context snapshot
  creation, Wiki draft generation, proposal-only wiki publish, session context,
  hash-only transcripts, and raw/internal payload rejection before tool side
  effects. Dev-container verification passed: Project/Wiki JSON-RPC focused
  tests 4 OK, semantic JSON-RPC focused tests 5 OK, and gateway Ruff
  check/format check passed. Full canonical unittest after this change ran
  282 OK. The next System Backbone target should be public tool schemas and
  safe error envelopes across upload, ingestion, observation, candidate graph,
  access, and wiki projection workflows.
- 2026-06-29 System Backbone public schema/error-envelope milestone:
  `python/formowl_gateway/semantic.py` now exposes public workflow schemas for
  upload, ingestion, observation listing, candidate graph, access, and wiki
  projection. `safe_workflow_error_envelope` and the pending-review workflow
  stubs keep unconfigured handlers inside `McpResultEnvelope` outputs without
  echoing raw paths, SQL, worker scratch strings, or backend internals. Focused
  dev-container verification passed: semantic gateway tests 8 OK, semantic
  JSON-RPC tests 5 OK, Project/Wiki JSON-RPC regression tests 4 OK, and gateway
  Ruff check/format check passed. Full canonical unittest after this change ran
  283 OK. Next backbone target: complete retrieval gateway raw-asset/evidence
  flow through governed FormOwl locators and permission checks.
- 2026-06-29 System Backbone retrieval gateway milestone: completed the
  governed raw-asset/evidence retrieval path in `python/formowl_retrieval/`.
  Raw-asset mode still requires explicit `asset_scoped_access`, returns
  `content_returned=false`, and now emits only safe `formowl://asset/...`
  locators through `RawAssetLocatorResolver` / `MetadataRawAssetLocatorResolver`.
  Unsafe locator values and resolver failures are redacted without echoing raw
  paths or backend internals. Dev-container verification passed: retrieval
  gateway tests 8 OK, retrieval Ruff check/format check passed, and the full
  `python -m unittest discover -s tests` suite ran 286 OK. Next backbone
  targets are storage backend registry configuration, worker execution
  boundaries, and database-backed stores.
- 2026-06-29 System Backbone storage backend registry configuration:
  completed `python/formowl_ingestion/storage/config.py` and public exports for
  local-first registry setup plus metadata-only MinIO/S3-compatible
  descriptors. Configuration can load from env or structured JSON descriptors,
  keeps local roots/internal endpoints/private adapter metadata out of public
  MCP-facing backend envelopes, rejects secret-like registry config, and
  requires explicit stable backend ids for non-local descriptors so future
  object-store adapters can be added without changing asset contract ids.
  Dev-container verification passed: storage registry focused tests 7 OK,
  ingestion package export regression 1 OK, changed-file Ruff check/format
  check passed, and the full `python -m unittest discover -s tests` suite ran
  289 OK. Next backbone target: worker execution boundary.
- 2026-06-29 System Backbone ingestion worker boundary: added
  `python/formowl_worker/` with an `IngestionWorker` that pulls pending
  `IngestionJob` records from the existing `JobStore`, respects storage
  backend `allowed_workers`, and runs jobs through the existing
  `run_ingestion_job` transition path without adding lease fields or changing
  the job record contract. Worker result summaries avoid raw source paths,
  object roots, and worker scratch internals. Dev-container verification
  passed: worker focused tests 3 OK, worker Ruff check/format check passed,
  and the full `python -m unittest discover -s tests` suite ran 292 OK. Next
  backbone target: database-backed stores behind the existing file-store
  interfaces.
- 2026-06-29 System Backbone PostgreSQL ingestion-store contract slice:
  added `python/formowl_ingestion/storage/postgres.py` plus migration
  `003_ingestion_records.sql` for database-backed `AssetStore`, `JobStore`,
  `ExtractorRunStore`, `ObservationStore`, and `UploadSessionStore`
  create/get/list surfaces over the internal connection protocol. The slice
  uses parameterized SQL, validated contract payloads, safe record ids, scope
  and asset indexes, and `PostgreSQLUnitOfWork` rollback behavior under mocked
  connection tests. It does not expose database controls through MCP and does
  not claim live PostgreSQL readiness. Dev-container verification passed:
  focused `test_postgres*.py` ran 20 OK, ingestion package export regression
  ran 1 OK, touched-file Ruff check/format check passed, and full
  `python -m unittest discover -s tests` ran 302 OK. The database-backed
  stores work-board item remains unchecked pending remaining repository and
  production end-to-end adapter evidence.
- 2026-06-29 System Backbone closed-beta readiness smoke:
  added `scripts/closed_beta_smoke.py`, `tests/test_closed_beta_smoke_script.py`,
  and `docs/closed-beta-runbook.md`. The smoke uses synthetic fixtures to
  validate the trusted internal closed-beta backbone path through Project/Wiki
  JSON-RPC, storage backend public-envelope redaction, worker ingestion,
  observation-to-wiki draft bridging, governed retrieval grant checks and
  raw-asset references, and the packaged KG-eval facade. It explicitly does
  not claim production readiness, live database readiness, automatic
  publishing, raw asset content access, canonical graph writes, or mail adapter
  readiness. Dev-container verification passed after reviewer-driven
  validation hardening: focused closed-beta smoke tests 14 OK; smoke CLI exited
  0; Ruff check and format-check passed for
  `python`, `tests`, and `scripts`; full `python -m unittest discover -s tests`
  ran 316 OK. The user-authorized 3-reviewer test-hardening gate passed 3/3:
  `closed_beta_reviewer_engineering`, `closed_beta_reviewer_safety`, and
  `closed_beta_reviewer_release` all returned `RELEASE_DECISION: AGREE` after
  validation/status blockers were fixed and re-reviewed. The closed-beta smoke
  work-board item is checked complete.
- 2026-06-29 System Backbone local folder inbox MVP:
  completed issue #9 on branch `local-folder-ingestion-mvp` with
  `python/formowl_ingestion/folder_inbox.py`,
  `tests/test_local_folder_ingestion.py`, and
  `docs/local-data-resource-inbox.md`. The scanner uses caller-held stability
  snapshots before durable writes, defers unstable files with zero asset,
  object, job, run, observation, or audit side effects, registers stable files
  as normal assets, creates idempotent ingestion jobs, can run the configured
  deterministic text extractor, and returns a public scan report without raw
  folder paths, source filenames, object-store roots, parser-local paths, or
  internal stability tokens. This is generic infrastructure only; mail parsing
  and financial reconciliation remain future consumers. Dev-container
  verification passed: local folder focused tests 10 OK, ingestion package
  export regression 1 OK, Ruff check/format-check passed, and full
  `python -m unittest discover -s tests` ran 326 OK. The default 3-reviewer
  gate passed with `folder_inbox_gate_engineering_v2`,
  `folder_inbox_gate_safety_v2`, and `folder_inbox_gate_release_v3`; the
  safety blocker about public `source_file_token` exposure was fixed and
  re-reviewed.
- 2026-06-30 System Backbone remaining backbone slices complete on branch
  `complete-remaining-backbone-slices`: added backend-specific Wiki MCP publish
  proposal adapters under `python/formowl_wiki_mcp/adapters/`, wired
  `publish_wiki_page` through `WikiPublishAdapterRegistry`, and added an
  OpenProject Wiki `upsert_wiki_page` proposal adapter that keeps
  `publish_mode=proposal_only`, `automatic_publish_enabled=false`, and
  `external_write_performed=false` while omitting target API URLs, tokens, raw
  paths, SQL-like values, and backend-internal fields from public proposals.
  Also added shared ingestion record store protocols and a same-workflow test
  proving asset registration, job creation, extractor execution, run
  persistence, and observation persistence run against both file-backed stores
  and PostgreSQL-backed stores. This closes the database-backed stores item as
  container-backed same-interface adapter evidence only; it still does not
  claim live PostgreSQL readiness or expose database controls through MCP.
  Dev-container verification passed: focused Wiki tests 4 OK, database
  workflow tests 3 OK, ingestion package export regression 1 OK,
  Project/Wiki JSON-RPC regression 4 OK, closed-beta smoke script tests 14 OK,
  closed-beta smoke CLI exited 0, Ruff check/format-check passed, and full
  `python -m unittest discover -s tests` ran 352 OK. User-requested
  3-reviewer gate passed 3/3 with
  `remaining_slices_engineering_reviewer`,
  `remaining_slices_safety_reviewer`, and
  `remaining_slices_release_reviewer`; no blocking findings remained.
- 2026-06-30 Issue #5 mail adapter boundary checkpoint: by explicit user
  assignment, the Mail Evidence Adapter scope was documented as an official
  `ExtractorAdapter` boundary in `RESOURCE_EXTRACTION_SPEC.md`, with workflow
  and README entry points. This completes only the OpenProject child item `828`
  scope/contract alignment: mail parsing starts from governed `Asset` /
  `IngestionJob` records and ends at versioned `ExtractorRun`, mail
  `Observation`, and attachment asset outputs. It does not start or complete
  the production PST/OST/MSG/EML parser, normalized mail schema,
  retrieval/index flow, candidate bridge, case-progress QA, or preflight
  readiness work.
- 2026-06-30 Issue #5 synthetic mail phase completion: by explicit user
  assignment, the remaining formowl-mail checklist items were completed for
  synthetic JSON-backed fixtures. `FixtureMailArchiveExtractor` now emits
  `email_thread`, `email_header`, fingerprinted `email_message`,
  `email_body_segment`, `email_attachment_occurrence`, and
  `mail_folder_occurrence` observations while preserving duplicate occurrence
  ids. `python/formowl_mail/` adds mail evidence pack/search helpers,
  candidate-only semantic/candidate proposal bridging, case-progress QA with
  observation citations, and a preflight readiness artifact. Docs now include
  the synthetic completion profile and `docs/mail-preflight-readiness.md`.
  Verification passed in the canonical dev container after reviewer hardening:
  focused mail tests ran 20 OK, Ruff check/format-check passed, and full
  `python -m unittest discover -s tests` ran 360 OK. Claim boundary: this
  closes issue #5 child items `829`, `831`, `832`, `833`, `834`, and `835` for
  synthetic fixtures only; real PST/OST/MSG/EML parser readiness and real
  mailbox support remain deferred. Reviewer gate passed fresh user-requested
  6/6 after every earlier blocker was fixed and the count reset: code
  reviewers `Godel`, `Franklin`, and `Bacon` agreed; hardness board test
  reviewers `Hooke`, `Arendt`, and `Euclid` agreed. Earlier blocking reviewers
  `Sagan`, `Dalton`, `Laplace`, `Einstein`, `Aristotle`, `Kierkegaard`, and
  `Bohr` were re-reviewed after their blockers were fixed and are not counted
  in the final fresh 6/6.
- 2026-07-07 Issue #21 checkpoint R performance follow-up: after the user
  flagged full-PST evaluation runtime, `MailEvidenceQueryGateway` now builds a
  reusable per-bundle inverted snippet index so repeated governed
  `query_mail_evidence` calls score only token-candidate snippets instead of
  scanning every snippet. Focused tests now prove non-matching snippets are not
  scanned/materialized and that the index is built once per bundle across
  repeated owner, no-match, and denied queries. Latest dev-container full-PST
  100-case eval plus saved-report validation exited 0 with `blockers=[]` and
  100/100 cases; safe timings were import `161583ms`, manifest `31320ms`, and
  scoring `11091ms`, with cleanup counts zero. Full dev-container unittest ran
  544 OK in 711.056s, and full Ruff check/format-check passed. The performance
  follow-up passed a fresh 6/6 read-only reviewer gate with `Euler`, `Mendel`,
  `Euclid`, `Copernicus`, `Huygens`, and `Maxwell`. This is only a Python
  query-index optimization; the main runtime bottleneck remains the full PST
  import/parser pipeline, so the next speed slice should add safe phase
  profiling before considering a native parser or systems-language module.
- 2026-07-08 issue #28 10,000-case redacted stress expansion:
  added runner-generated `redacted_stress_benchmark_10000` from the fixed
  100-case redacted hard-challenge templates instead of committing a giant
  fixture. The generated benchmark has 10,000 cases, split 1,000 dev / 9,000
  holdout, with bucket counts scaled by 100 from the 100-case design. Current
  10,000-case result: KG without ontology exact `0.46`, KG + hard ontology
  `0.22`, KG + soft gate `0.74`, v2 frame `0.82`, hybrid soft gate + v2
  `0.90`. Absolute counts expose 3,000 hard false rejects for hard ontology,
  1,100 false positives for KG without ontology, and 100 false positives plus
  900 partial answers for hybrid. This is deterministic redacted stress
  evidence from repeated template families, not independent PST/parser holdout
  evidence or production parser proof. Canonical verification passed: focused
  coordination-frame tests 27 OK, runner passed, full unittest 374 OK, Ruff
  check/format-check passed, default KG acceptance
  `passed_with_explicit_limits`, and `git diff --check` passed. Issue #28
  follow-up comment: `4913032708`. Reviewer gate passed 3/3: `Anscombe`
  engineering correctness, `Pauli` governance/safety, and `Russell` research
  method. Anscombe's optional seed-shape validation note and Russell's optional
  explicit claim-boundary assertion note were implemented before final
  verification.
- 2026-07-09 procurement full-PST real-case follow-up: the user supplied a
  larger operator-provided procurement PST fixture in ignored private test
  data. The same preserved-workdir full-PST domain-hard pattern was run without
  exposing raw mail content or private paths in public reports. Safe counts:
  21,150,409,728 bytes, 27,912 messages, 60,923 body segments, 306,741
  observations, 163,764 mail evidence rows, and 46,562 parser warnings.
  Validated public reports all had `blockers=[]`. Baseline retrieval scored
  11/100, candidate KG fusion scored 19/100, ontology-guided KG scored 19/100,
  and the 326-arm ordered ontology factorial search also topped out at 19/100.
  No factorial arm beat KG-only, 2 tied it, and 324 were worse; the best arm
  used zero ontology operators. The current ontology layer therefore does not
  improve this real procurement corpus, though KG structure still adds 8
  passed cases over baseline. Claim boundary remains candidate-only
  retrieval/KG/ontology measurement: no business answer generation, no general
  parser readiness, no raw-mail access, no canonical graph/type/user-graph/wiki
  writes, no production readiness, and no broad KG completion claim.
- 2026-07-09 multimodal ontology upstream decision: added
  `docs/multimodal-ontology-term-extraction-decision.md` to fix the next method
  boundary before future audio, PDF, PowerPoint, OCR, and mixed-language inputs.
  The decision is data-driven first: add a shared term/mention extraction layer
  before ontology selection, keep tokenizer adapters replaceable, use raw
  corpora for phrase mining and weak labels, require governed labels before
  supervised typed classification claims, and keep LLM/model outputs
  candidate-only. This is a design decision only, not a production tokenizer or
  multimodal extraction claim.
- 2026-07-10 issue #16 KG-first cross-resource fusion started on
  `issue-16-kg-first-fusion` from `origin/main` `832bea2`. The KG Research Agent
  owns the graph-hit, evidence-lineage, fallback, candidate-seed, fixture, and
  acceptance behavior. The slice also adds the narrow Semantic MCP tool
  `query_effective_graph_view` because the user explicitly assigned the
  cross-role issue; it does not absorb issue #19's general adapter
  certification/staged-write scope. Current focused retrieval, Semantic
  MCP/JSON-RPC, and deterministic mail + slide + project smoke checks pass;
  full dev-container verification and the 3-reviewer gate remain pending.
- 2026-07-10 issue #16 KG-first cross-resource fusion completed on
  `issue-16-kg-first-fusion`. The final slice performs query-scored KG lookup
  before vector fallback, resolves permission-visible and asset-lineage-verified
  Observations, filters caller-supplied graph objects again at retrieval time,
  requires audited target-scoped raw-asset grants, derives Candidate KG proposal
  seeds only from permission-resolved fallback Observations, rejects embedded
  relative/internal slash and backslash paths, and exposes a strict
  `query_effective_graph_view` MCP/JSON-RPC contract. The deterministic mail +
  slide + project smoke uses same-query complete/incomplete scenarios, a visible
  distractor, an irrelevant-query control, explicit vector-search counts, and
  verified fixture/semantic hashes. Final canonical evidence: full unittest
  `652 tests OK`; full Ruff passed with `307 files already formatted`; smoke
  build and saved-report validation both `status: ok`; `git diff --check`
  passed. Reviewer gate passed 3/3 with final `RELEASE_DECISION: AGREE` from
  `Galileo`, `Hilbert`, and `Euler`. No candidate-store or canonical-graph write
  is performed, and issue #19 certification/staged-write scope remains excluded.
