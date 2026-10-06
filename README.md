# formowl

<!-- Future agents: read AGENTS.md first. Current methodology authority lives in docs/methodology-authority.json, docs/kg-research-method.md, and GitHub issue #56. Historical files and archived snapshots are not current instructions. -->

FormOwl is a source-preserving, graph-governed knowledge system for integrating
heterogeneous enterprise evidence. Email is the first source fixture, not the
product model. Calendar, ticket, project, document, database, media, and future
source adapters must enter the same evidence, governance, permission, and query
architecture.

## Active Architecture

Knowledge construction:

```text
heterogeneous sources
  -> Asset / EvidenceSnapshot
  -> ExtractorRun
  -> source-preserving Observation
  -> candidate mentions, entities, claims, relations, and frames
  -> reviewed canonical KG + scoped ontology mappings
  -> permission-filtered EffectiveGraphView
```

Query execution:

```text
user query
  -> typed router
  -> validated SemanticQueryPlan
  -> BM25 + dense retrieval
  -> entity linking + bounded graph traversal
  -> temporal, provenance, and coverage filtering
  -> capped soft ontology scoring
  -> evidence-bundle reranking
  -> deterministic executor or citation-grounded LLM answer
```

The layers have different jobs:

- **Strong RAG** retrieves source evidence and is both a required component and
  the competitive control.
- **The KG** contributes reviewed identity, cross-source joins, bounded paths,
  temporal/current-state structure, contradiction, provenance, and reusable
  integration semantics.
- **The ontology** is small-core, scoped, data-first, versioned, and a capped
  additive signal. An inferred mismatch does not remove admitted evidence.
- **Deterministic execution** handles exact sets, counts, inventories,
  aggregation, completeness, and definitive-negative claims.
- **The answer model** may explain only the authorized evidence produced by a
  validated plan; it may not fill missing evidence from model memory.

Sources and model output are not canonical truth. Extractors and LLMs may
create reviewable candidates, but they may not silently mutate canonical graph
or type state, user graph revisions, wiki revisions, or external systems.

## Active KG Research Program

GitHub issue #56 is the sole active KG methodology program:

```text
Implement graph-guided Hybrid KG + Ontology v2 that measurably outperforms
strong RAG.
```

Frozen target:

```text
method: evidence_to_knowledge_kg_ontology_v2_hybrid_v1
tokenizer: jieba_sentencepiece_frozen_profile_candidate_admission_v1
```

Current runtime truth on August 18, 2026:

```text
method: mail_candidate_kg_broad_ontology_diagnostic_v1
tokenizer: ascii_identifier_regex_v1
CJK support: false
methodology status: blocked
```

Check the executable authority before making a methodology claim:

```sh
python3 scripts/methodology_authority_check.py --check
python3 scripts/methodology_authority_check.py --require-ready
```

`--check` is currently valid. `--require-ready` is expected to exit nonzero
until runtime alignment, source completeness, execution-bound reports,
same-pipeline real-source ablation, and real-user final-answer acceptance all
pass. Diagnostic implementation may continue, but no active document or report
may claim that KG + ontology already beats strong RAG.

## Model Policy

There is no single “FormOwl KG LLM.” Every run records model roles separately:

```text
planner model, if any
candidate extraction or entity-linking model, if any
embedding model
reranker model, if any
final answer model
reasoning effort, decoding, prompt, schema, and context-budget hashes
```

Every comparison arm must use the same final answer model and settings. A model
change creates a new experiment; it is not a free improvement for one arm.
Historical `BAAI/bge-large-en-v1.5` and
`sentence-transformers/bert-base-nli-mean-tokens` runs are candidate-generation
experiments, not ontology models and not a production answer-model decision.

## Anti-Fitting Rule

Current UAT questions are not tokenizer training data, ontology source data,
alias dictionaries, graph rules, or prompt-tuning material. Use separate
calibration, development, frozen evaluation, independent holdout, and transfer
sets. The independent holdout must not influence tokenizer artifacts, aliases,
ontology mappings, thresholds, routing, traversal budgets, prompts, models, or
grading policy. A change motivated by holdout failure requires a new version
and a new holdout.

## Current Product Boundary

Implemented repository slices include:

- shared Python contracts for sources, observations, candidates, canonical
  graph objects, effective views, projections, identity, permissions, and
  audit;
- Asset, ingestion-job, extractor-run, and Observation workflows with
  deterministic heterogeneous-source fixture adapters;
- governed mail ingestion and evidence-query fixtures, plus bounded real-PST
  parser diagnostics;
- candidate extraction and review contracts, canonical graph lifecycle
  contracts, scoped ontology contracts, user/effective graph views, and
  graph-derived wiki drafts;
- PostgreSQL/pgvector adapter contracts and file-backed compatibility stores;
- Project MCP and Wiki MCP compatibility services;
- the connected FormOwl MCP Gateway on exact `/mcp` with Google-backed FormOwl
  OAuth 2.1 and a fresh gateway-controlled `ActorContext`.

These slices do not establish production readiness, source-complete
heterogeneous integration, automatic canonical writes, general parser
coverage, or KG + ontology superiority.

The connected closed-beta identity path uses one stable non-secret predefined
client ID selected and recorded by the deployment operator before discovery.
ChatGPT supplies and displays only the production callback
`https://chatgpt.com/connector/oauth/{callback_id}`. If the current ChatGPT UI
cannot use the recorded predefined client, the live flow stops as an external
live blocker. The reserved
`https://invalid.example.invalid/formowl-discovery-only` callback is only the
`discovery_only` state for `initialize` and `tools/list`; `/readyz` remains
unready, protected tools return an OAuth challenge without authorization audit,
and bootstrap is blocked until the production callback is configured and the
runtime is restarted. The external evidence and review campaign required for
Issue #20 closure has not yet passed.

Issue #41 separately owns generic Asset tenant/owner binding, byte storage,
occurrence lineage, upload recovery, retention, purge, and authorization. A
source adapter must not create a parallel asset or permission system.

## Storage and Runtime Direction

FormOwl is container-first. Python remains the Phase 0 orchestration and policy
language. PostgreSQL is the canonical authority for metadata, provenance,
permissions, graph/ontology revisions, reviews, jobs, and audit; pgvector is
the default dense-retrieval baseline. Raw and large binary assets live behind
an object-store abstraction. A graph data model does not require migration to a
graph database.

All user-facing access goes through governed MCP/service operations. Raw paths,
SQL, object-store administration, parser controls, worker scratch locations,
or hidden oracle values must not appear in public tool schemas or results.

## Historical Compatibility Evidence

Legacy benchmark readers and tests retain two candidate-matching numbers:
`0.758664` and `0.757744`. They are **candidate-only** historical evidence.
They do not compare the frozen issue #56 runtime, do not measure final-answer
quality against strong RAG, and do not authorize a hard ontology gate.

## Documentation Map

Current authority:

- `AGENTS.md` — startup rules, active role, and current methodology boundary.
- `SPEC.md` — canonical product and architecture specification.
- `RESOURCE_EXTRACTION_SPEC.md` — source-complete heterogeneous extraction and
  Observation contract.
- `docs/methodology-authority.json` — machine-readable readiness authority.
- `docs/kg-research-method.md` — active research hypothesis, comparison arms,
  metrics, anti-fitting rules, and decision gates.
- `docs/kg-ontology-v2-rd-boundary.md` — Hybrid v2 implementation boundary.
- `docs/kg-ontology-v2-runtime-evaluation-plan.md` — issue #56 work packages and
  same-pipeline evaluation plan.
- `docs/kg-ontology-pretrained-model-explanation.md` — plain-language model,
  RAG, KG, ontology, and fitting explanation.
- `docs/architecture.md`, `docs/workflows.md`, `docs/mcp-boundaries.md`,
  `docs/provenance.md`, and `docs/infra-spec.md` — aligned system boundaries.
- `docs/implementation-task-breakdown.md` and `docs/agent-goals/` — bounded
  active work and durable role state.

Diagnostic integration:

- `docs/kg-eval-package.md` — compatibility boundary for the packaged
  evaluation facade; it is not a substitute for methodology authority.
- `docs/kg-bert-runtime.md` — optional candidate-generation model runtimes and
  historical artifact compatibility.

Historical pointer files:

- `docs/mail-ontology-native-factorial-design.md`
- `docs/ontology-v2-coordination-plan.md`
- `docs/ontology-v2-coordination-frames.md`
- `docs/ontology-v2-review-comments.md`
- `docs/agent-goals/dual-track-uat-kg-coordinator.md`

Those filenames remain only to redirect readers to current authority and the
immutable pre-rewrite snapshot under `docs/archive/2026-08-18/`. They are not
work orders.

## Development

Build the dev container image:

```sh
docker build -f containers/dev/Dockerfile -t formowl-dev:local .
```

### Connected OAuth/MCP operator sequence

The production-shaped repository entrypoint is `formowl-connected-mcp`. Start
from a clean clone by building the runtime image and generating the six local
FormOwl/PostgreSQL secrets:

```sh
docker build -f containers/runtime/Dockerfile -t formowl-runtime:local .
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  formowl-runtime:local init-secrets --output-dir /secrets
```

This creates a single-active-key manifest plus an unused
`signing-previous.pem` standby mount slot. It does not create the Google OAuth
client secret and it does not prove preflight readiness. Import the real Google
client secret separately as a mode-`0400` file. The tracked non-secret
`deploy/connected/compose.env.example` is the field/template contract; the
operator copies it to the real ignored, mode-`0600`
`.formowl/issue20/compose.env`; the containerized operator helper validates and
rewrites that same operator file, which every Compose command receives through
`--env-file`. Before discovery, the operator uses the containerized helper to
derive or validate and record one stable non-secret predefined client ID; this
requires no host Python. ChatGPT Apps management must use that same ID if its
current predefined-client UI supports entry or selection. If it does not, stop
and record an external live blocker. ChatGPT supplies and displays only the
production callback; never invent the ID or claim ChatGPT generated/displayed
it, and do not claim migration to a different client-registration model. Full
creation commands, file meanings, safe interrupted-initialization recovery,
and the no-placeholder rule are in `docs/closed-beta-runbook.md` and
`deploy/connected/secrets/README.md`. Do not put secret values on the command
line, in environment variables, tracked files, screenshots, logs, evidence
packets, or ChatGPT messages.

`deploy/connected/Caddyfile.example` is the concrete TLS reverse-proxy sample.
It keeps FormOwl published only on `127.0.0.1:8000`; Compose publishes no
PostgreSQL port. The exact discovery-only start/check/stop/finalize commands,
standalone Caddy command, final Compose TLS profile, and official public-only
MCP Inspector flow are in `docs/closed-beta-runbook.md`. Launch Inspector from
the operator workstation and connect it to the public HTTPS `/mcp` endpoint:

```sh
npx @modelcontextprotocol/inspector@latest
```

Production accepts only
`https://chatgpt.com/connector/oauth/{callback_id}` with one non-empty
RFC-unreserved callback-id segment. The sole placeholder is
`https://invalid.example.invalid/formowl-discovery-only`, used only when public
`initialize`/`tools/list` discovery is required to reveal the real callback.
This sentinel state is the literal `discovery_only` boundary. In sentinel mode,
`/readyz` returns 503, protected tools only challenge without audit, and
bootstrap/OAuth/operator mutations are blocked. Stop and remove the discovery
containers, replace the sentinel with the exact callback, restart the final
configuration, and only then start PostgreSQL, migrate, run normal preflight,
bootstrap, or OAuth.

```sh
COMPOSE_ENV=.formowl/issue20/compose.env
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  up -d postgres
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-migrate
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp preflight
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp bootstrap-owner \
  --workspace-id <workspace-id> \
  --email <invited-owner-email> \
  --expires-at <RFC3339-expiry> \
  --idempotency-key <operator-generated-idempotency-key> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  up -d connected-mcp
```

After the first real Google login creates the invited owner, an authorized
deployment shell can obtain stable IDs without temporary SQL:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp lookup-user \
  --email <owner-email> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp list-users \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp lookup-token-session \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp list-token-sessions \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Use the returned owner `user_id` for an operator-authorized invitation:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp invite-user \
  --workspace-id <workspace-id> \
  --email <invited-user-email> \
  --role member \
  --invited-by-user-id <owner-user-id> \
  --operator-service-id <authorized-operator-service-id> \
  --expires-at <RFC3339-expiry>
```

Membership removal and restore are explicit operator commands, not MCP tools:

```sh
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp remove-workspace-member \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
docker compose --env-file "$COMPOSE_ENV" --file compose.yaml \
  run --rm connected-mcp restore-workspace-member \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Removal preserves membership history and revokes every unrevoked token session
for that user/workspace. Restore never reactivates those sessions; the user must
complete the Google-backed FormOwl OAuth flow again. Use a returned active
`token_session_id` for `revoke-token-session`. Lookup/list results omit email,
display name, bearer/JTI material, scopes, provider subject, raw paths, SQL, and
backend details. Allow and deny decisions are audited; an audit write failure
returns no result or membership mutation.

`operator_service_id` is an attribution identifier, not a password or remote
authorization credential. These commands are not MCP tools. Their actual
security boundary is access to the controlled deployment shell, Docker daemon,
Compose configuration, and mounted secret files. The full migrate, bootstrap,
lookup, invite, restart, revocation, signing-key rotation, MCP Inspector, and
live ChatGPT/Google sequence is in `docs/closed-beta-runbook.md`. Those external
journeys are not yet accepted completion evidence, so issue #20 remains open
and no production-readiness claim is made.

Issue #20 establishes connected identity and fresh `ActorContext` only. Issue
#41 separately owns generic Asset tenant/owner binding, byte storage,
occurrence lineage, upload recovery, lifecycle, retention, purge, and
authorization. Issue #21 is a downstream governed mail-evidence consumer of
that generic Asset boundary and does not define another identity or connected
transport path.

Run tests inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m unittest discover -s tests"
```

Run tests with coverage inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "coverage run -m unittest discover -s tests && coverage report"
```

The coverage report enforces the minimum threshold configured in
`pyproject.toml`.

Run the KG research acceptance suite inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/kg_research_acceptance_suite.py"
```

Use `--strict` when the command should fail on any failed or blocked acceptance
item. The default command exits successfully while clearly marking known limits
such as production adapter readiness and enterprise latency/scalability.

The `.formowl/kg-eval` workspace and packaged `formowl_kg_eval` interface are
legacy diagnostic compatibility surfaces. They are retained for repository
tests, historical artifact readers, and redacted integration output; they are
not the issue #56 work board or methodology authority. The package field named
`authority_state` describes only legacy-harness self-consistency. It cannot
override `docs/methodology-authority.json` or a nonzero
`methodology_authority_check.py --require-ready` result.

The CLI entry point remains `formowl-kg-eval`, with
`python -m formowl_kg_eval` as the module fallback. `summary` and `benchmarks`
may expose historical candidate-generation capabilities and candidate-level
benchmark results. They do not establish source completeness, a strong-RAG
control, the frozen tokenizer, final-answer quality, independent holdout
acceptance, transfer-domain acceptance, or KG + ontology superiority. See
`docs/kg-eval-package.md` for the exact compatibility boundary.

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval summary"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python -m formowl_kg_eval benchmarks"
```

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local bash -c "python kg_total_acceptance_suite.py && python real_evidence_preflight.py"
```

The third command runs the historical broad harness only. Treat its output as a
legacy diagnostic even if it passes.

Run lint and formatting checks inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "ruff check python tests scripts && ruff format --check python tests scripts"
```

Run the closed-beta readiness smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json"
```

Run the issue #21 mail evidence MCP smoke inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_evidence_mcp_smoke.py --output /tmp/formowl-mail-evidence-mcp-smoke.json"
```

This smoke uses a synthetic mail fixture to exercise the ChatGPT-free local path
from asset/job/extractor records to governed JSON-RPC `query_mail_evidence` and
`answer_mail_case_progress` calls. It validates permission filtering,
citations, hash-only transcripts, and hash/status/count public reporting. It
does not claim actual ChatGPT connected upload, production iframe readiness,
real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL deployment readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

The local semantic JSON-RPC compatibility command for #21 mail upload task-card
testing is:

```sh
FORMOWL_DATA_DIR=.formowl/data formowl-semantic-mcp-jsonrpc
```

Set `FORMOWL_MCP_SESSION_ID`, `FORMOWL_MCP_ACTOR_USER_ID`, and
`FORMOWL_MCP_WORKSPACE_ID` to bind the trusted internal session context for a
local smoke. Unsafe secret-like values are rejected to safe defaults. These
variables are forbidden by the connected runtime and must never be used to
configure the formal ChatGPT connection.

Run the #21 mail upload MCP command preflight:

```sh
python scripts/mail_upload_mcp_command_smoke.py --output /tmp/formowl-mail-upload-mcp-command-smoke.json
```

This preflight checks the configured command path and upload task-card session
creation only. It does not claim actual ChatGPT connection, file transfer, real
upload iframe readiness, real mail parser readiness, live PostgreSQL readiness,
production worker leasing, KG writes, wiki projection, or production readiness.

Run the #21 mail upload-surface intake focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_surface.py"
```

These tests cover backend receipt and rollback for a session-bound upload
surface. They do not perform an actual iframe or ChatGPT connected upload.

Run the #21 local HTTP upload-surface contract focused tests:

```sh
python -m unittest discover -s tests -p "test_mail_upload_http_surface.py"
```

These tests exercise the stdlib local HTTP GET/POST multipart harness and its
handoff into backend upload intake. They still do not perform an actual ChatGPT
connected upload or production iframe test.

Run the #21 MCP-command-to-local-HTTP upload smoke:

```sh
python scripts/mail_upload_mcp_http_smoke.py --output /tmp/formowl-mail-upload-mcp-http-smoke.json
```

This smoke proves the configured command can open the upload task and that the
local HTTP surface can receive one synthetic session-bound mail archive upload.
It still does not perform an actual ChatGPT connected upload, production iframe
test, real mail parsing, live PostgreSQL deployment, production worker leasing,
KG writes, wiki projection, or production readiness.

Run the #21 local upload-to-import-and-query smoke:

```sh
python scripts/mail_upload_mcp_http_import_smoke.py --output /tmp/formowl-mail-upload-mcp-http-import-smoke.json
```

This smoke extends the local command-to-HTTP path through the synthetic
server-side import workflow and store-backed `query_mail_evidence` JSON-RPC
surface. It still does not perform an actual ChatGPT connected upload,
production iframe test, real PST/OST/MSG/EML/MBOX parsing, live PostgreSQL
deployment, production worker leasing, KG writes, wiki projection, or
production readiness.

Run the #21 sampled real PST ingestion smoke inside the dev container after
placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --output .test-tmp/formowl-real-pst-sampled-smoke.json --mode sampled --sample-message-limit 25"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_real_pst_smoke.py --validate-report .test-tmp/formowl-real-pst-sampled-smoke.json --output .test-tmp/formowl-real-pst-sampled-validation.json"
```

This smoke requires `readpst` from the dev image's `pst-utils` package. The
report must remain hash/status/count-only: do not paste PST contents, concrete
message identifiers, subjects, senders, attachment names, body text, object
store locators, parser command lines, scratch paths, SQL, or environment values
into public reports. The sampled smoke may set
`supports_real_pst_sampled_parser_claim=true` only after the report validator
passes. It must keep full-parser, production, ChatGPT upload/file-transfer,
iframe, worker-leasing, raw-mail-access, KG, and wiki claims false.

Run the #21 full PST 100-case mail evidence evaluation inside the dev container
after placing the operator-provided PST at `tests/pst-exm/archive.pst`:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_100_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --output .test-tmp/formowl-mail-full-pst-100-case-eval.json"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_100_case_eval.py --validate-report .test-tmp/formowl-mail-full-pst-100-case-eval.json --output .test-tmp/formowl-mail-full-pst-100-case-validation.json"
```

This evaluation performs a full parse with no message sampling, then scores 100
manifest-bound governed `query_mail_evidence` cases. The public report must
remain hash/status/count-only and must not include query text, PST contents,
concrete message identifiers, subjects, senders, attachment names, body text,
object-store locators, parser command lines, scratch paths, SQL, or
environment values. Passing this evaluator supports only the operator-provided
full PST 100-case evidence-reading evaluation claim; it is not a general mail
parser, ChatGPT upload, production iframe, live PostgreSQL, worker-leasing,
raw-mail-access, KG, wiki, or production readiness claim.

Run the #21 domain-hard full PST mail evidence baseline inside the dev
container:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_CASE_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --output .test-tmp/formowl-mail-domain-hard-case-baseline.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work"
```

Validate the saved public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_case_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-case-baseline.json --output .test-tmp/formowl-mail-domain-hard-case-baseline-validation.json"
```

This baseline intentionally allows low pass rates so difficult cases can expose
retrieval and performance gaps. The public report must remain
hash/status/count/timing-only. Do not paste query text, PST contents, concrete
message identifiers, subjects, senders, body text, private manifest contents,
object-store locators, parser command lines, scratch paths, SQL, or environment
values into public reports.

Run the #21 non-BERT candidate-only KG fusion rescore over a preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_KG_FUSION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json"
```

Validate the saved KG fusion public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_kg_fusion_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-kg-fusion-eval-v1-validation.json"
```

This rescore does not reparse the PST and does not use BERT or any neural
package. It is a candidate-only graph-structure experiment over existing
observations; the current implementation has not yet integrated formal ontology
governance or canonical graph state.

Run the #21 ontology-guided non-BERT ablation over the same preserved
domain-hard work directory:

```sh
docker run --rm -e FORMOWL_RUN_FULL_PST_DOMAIN_HARD_ONTOLOGY_ABLATION_EVAL=1 -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --baseline-report .test-tmp/formowl-mail-domain-hard-case-baseline-v4.json --work-dir .test-tmp/formowl-mail-domain-hard-case-baseline-work-v4 --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json"
```

Validate the saved ontology ablation public report:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "python scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py --validate-report .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1.json --output .test-tmp/formowl-mail-domain-hard-ontology-ablation-eval-v1-validation.json"
```

The ontology arm is a candidate-only ablation. It validates formal ontology
contract usage and a revision hash, but it does not claim completed ontology
governance, canonical type writes, canonical KG writes, raw access, wiki
projection, business answer generation, or production readiness.

Run the historical #21 local-compatibility stdio attachment preflight package:

```sh
python scripts/mail_upload_chatgpt_connection_preflight.py --output /tmp/formowl-mail-upload-chatgpt-connection-preflight.json
```

This preflight proves the local compatibility command can be packaged without
exposing environment values, local paths, upload
locators, parser controls, storage controls, or backend internals in its public
report. A bounded local compatibility test may use the stdio command
`formowl-semantic-mcp-jsonrpc` and operator-supplied local values for
`FORMOWL_DATA_DIR`, `FORMOWL_MCP_SESSION_ID`,
`FORMOWL_MCP_ACTOR_USER_ID`, `FORMOWL_MCP_WORKSPACE_ID`, and
`FORMOWL_MAIL_UPLOAD_EXPIRES_AT`. This is not the formal connected path. The
live test must use the public HTTPS `/mcp` resource, FormOwl OAuth, and Google
OIDC as specified in `docs/closed-beta-runbook.md`.

Run the historical #21 result-packet intake after a manual local-compatibility test:

```sh
python scripts/mail_upload_chatgpt_result_intake.py --input /tmp/formowl-chatgpt-result-packet.json --output /tmp/formowl-mail-upload-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, expected `initialize` / `tools/list` /
`tools/call open_upload_session` sequence, task-card shape hashes, and explicit
attestation that raw ChatGPT detail payloads, environment values, upload
locators, and mail payloads were excluded. Do not paste raw ChatGPT transcripts,
PST contents, upload session IDs, local paths, or environment values into the
packet.

Run the historical #21 mail-evidence result-packet intake after a manual
fixture-backed local-compatibility evidence-reading smoke:

```sh
python scripts/mail_evidence_chatgpt_result_intake.py --input /tmp/formowl-mail-evidence-chatgpt-result-packet.json --output /tmp/formowl-mail-evidence-chatgpt-result-intake.json
```

The input packet must be a bounded operator summary of the ChatGPT MCP session:
hashes, statuses, counts, the expected `initialize` / `tools/list` /
`query_mail_evidence` owner/denied / `answer_mail_case_progress` owner/denied
sequence, fixture-smoke contract hashes, owner citation counts, denied
redaction counts, and explicit attestation that raw transcripts, raw tool
payloads, mail text, concrete mail identifiers, environment values, upload
locators, paths, SQL, and parser/storage/worker internals were excluded. Do
not paste raw ChatGPT transcripts, mail body/snippet text, concrete bundle or
message IDs, local paths, SQL, or environment values into the packet.

## Repository Skills

Reusable Codex workflow skills live under `.agents/skills/` so Codex can
discover them as repo-scoped skills when launched from this repository.
Available repo skills include `$harden-completed-slice-tests` for strict
completed-slice test hardening and `$use-agy-antigravity` for the historical
Antigravity `agy` workflow and bounded delegation rules. The 2026-08-05 Herdr
authorization is temporarily dormant as of 2026-08-11 because the `agy` quota
is exhausted; do not assign `agy` as a worker, reviewer, implementation
subagent, UAT agent, or coordinator until the user explicitly re-enables it. The canonical
tracked Antigravity skill file is
`.agents/skills/use-agy-antigravity/SKILL.md`; keep KG `agy` authorization,
reviewer, bounded write-delegation, MCP-route probe, and disablement notes
there so they travel with Git.

To use the same skill on another host, copy the repository with its `.agents`
directory intact, start a new Codex session from the repo, and confirm the skill
appears in `/skills`.

## Agent Goal Registry

Durable multi-agent goals live under `docs/agent-goals/`. These files make
long-running objectives portable across sessions and machines:

- `docs/agent-goals/kg-research-agent.md`
- `docs/agent-goals/system-backbone-agent.md`
- `docs/agent-goals/handoff-log.md`
- `docs/agent-goals/reviewer-gate.md`
- `docs/archive/README.md` - `immutable-history` index for lossless dated
  snapshots of completed board, goal, and handoff detail. It is consulted on
  demand and is not part of the default agent startup sequence.

Use `docs/implementation-task-breakdown.md` for checkbox task completion and
`docs/agent-goals/` for current objective, scope, blockers, status, and handoff
state. Active files are bounded: the board retains every unchecked item,
current phase summaries, and up to five recent completion summaries; role goals
retain role/objective/status/blockers/next action; handoffs retain 14 days and
at most 300 lines. The lifecycle labels are `active`, `active-blocked`,
`complete`, and `immutable-history`; detailed rules live in
`docs/agent-goals/README.md`.

Install and run pre-commit checks from inside the dev container:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local bash -c "pre-commit run --all-files"
```

The pre-commit suite checks credentials/secrets, merge conflict markers, large files, text whitespace, Python/JSON/TOML syntax, Python lint/format with Ruff, and Python unit tests. Host-side Python may be used for quick local inspection, but container results are the completion baseline.

The default commit-time secret checks include the lightweight local credential scanner and Gitleaks. For a deeper audit, run the manual secret scans:

```sh
pre-commit run gitleaks-history --hook-stage manual
pre-commit run trufflehog-history --hook-stage manual
```

The dev container installs Gitleaks for commit-time scanning. TruffleHog remains manual because it is heavier; this repo runs it with verification disabled so the scan stays local.

## MCP JSON Line Compatibility Entry Points

The legacy Python MCP server modules still accept one JSON request per stdin
line and print one JSON response per line for local compatibility testing only.
Packaged console scripts use explicit compatibility names:
`formowl-project-mcp-jsonline-compat` and
`formowl-wiki-mcp-jsonline-compat`. The FormOwl gateway package provides the
JSON-RPC compatibility wrapper for existing MCP server objects and semantic
gateway tools; Project/Wiki behavior is preserved through transport tests.

`formowl-semantic-mcp-jsonrpc` is likewise a hand-built local compatibility
runner. None of these commands is an approved connected ChatGPT authentication
or identity-selection path; connected clients use the public HTTPS `/mcp`
resource and FormOwl OAuth 2.1.

Project MCP compatibility example:

```sh
formowl-project-mcp-jsonline-compat
```

Request:

```json
{
  "tool": "get_work_item_context",
  "arguments": {
    "source_ref": {
      "source_system": "openproject",
      "source_type": "work_package",
      "source_id": "123"
    },
    "include_comments": true,
    "include_activities": true,
    "include_relations": true,
    "include_attachments": true,
    "create_evidence_snapshot": true
  }
}
```

Wiki MCP compatibility example:

```sh
formowl-wiki-mcp-jsonline-compat
```

Set `FORMOWL_DATA_DIR` to control evidence, draft, snapshot, and tool-call log storage. The default is `.formowl/data`.
