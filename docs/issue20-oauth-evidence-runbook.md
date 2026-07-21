# Issue #20 OAuth Evidence Runbook

This runbook covers the bounded external-evidence input for
`scripts/oauth_mcp_harness.py`. The report validates a hash/status/count packet;
it never accepts raw OAuth material and it never decides whole-issue completion.

Current external-evidence state remains incomplete. All seven required packet
layers are explicitly `not_supplied`:

```text
live_postgresql = not_supplied
operator_cli_postgresql = not_supplied
production_container_lifecycle = not_supplied
mcp_inspector = not_supplied
live_chatgpt_google = not_supplied
reviewer_gate = not_supplied
completion_audit = not_supplied
```

Current local repository authority, verified on 2026-07-21, is:

```text
changed / manifested / onboarded = 689 / 689 / 689
pending = 0
requested / resolved / run / pass = 508 / 508 / 508 / 508
checked evidence pairs = 1,388
direct trace expected / covered / missing = 689 / 689 / 0
direct trace blockers = []
test_id_count = 1,521
canonical full suite = Ran 1521 tests in 964.613s
canonical full suite result = OK (skipped=7)
Ruff check = passed
Ruff format check = 306 files already formatted
runner shell syntax / JSON parse / git diff check = passed / passed / passed
```

The latest local harness artifact is
`/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json`, SHA-256
`1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`.
Its seven external layers remain `not_supplied`, and its
`supports_issue20_closure_claim` and `supports_production_ready_claim` values
remain `false`. Connector-confirmed GitHub current main is
`342e588aa6162ccbdd14a257bfc09e58e7a619ad`, with no newer remote main
reported; that branch state is baseline context, not external evidence.

Official OpenAI references used by this workflow:

- Authentication: <https://developers.openai.com/apps-sdk/build/auth>
- Connect from ChatGPT: <https://developers.openai.com/apps-sdk/deploy/connect-chatgpt>
- Testing: <https://developers.openai.com/apps-sdk/deploy/testing>

The official Apps SDK authentication guidance explicitly accounts for
predefined OAuth clients and token-endpoint authentication methods. It does not
establish whether this workspace's current ChatGPT Apps management UI exposes
entry or selection for FormOwl's exact predefined client ID. The FormOwl closed
beta intentionally uses one predefined OAuth client only: ChatGPT. Use the
operator-recorded client ID if the live UI supports it; otherwise stop before
live login and record the interoperability blocker. Do not claim predefined
clients are unsupported, and do not claim UI support without live evidence.
MCP Inspector is public-discovery and challenge evidence only; it must not
register another client, use CIMD or DCR, complete OAuth, or receive a real
bearer token.

## Governed A-E source workflow

The `formowl-issue20-evidence` entrypoint creates and validates bounded source
artifacts. It does not scrape ChatGPT, Google, Inspector, PostgreSQL, or Docker,
and it cannot turn placeholders into evidence.

Normal FormOwl deployment does not require host Python. From a clean clone,
build the canonical dev image before running any evidence CLI or Python
command; the packet/evidence Python dependencies live only in that image and
must not be installed on the host. Separately, the governed outer custody
runner has one explicit host prerequisite: executable `/usr/bin/python3` from
the Linux distribution, used only for its bounded lock/boundary helper, plus
Docker Engine/BuildKit/Compose v2 access through `/var/run/docker.sock`.

```sh
docker build --file containers/dev/Dockerfile --tag formowl-dev:local .
ISSUE20_SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$(id -u)"

issue20_dev() {
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    -w /workspace \
    formowl-dev:local "$@"
}

issue20_dev_with_scratch() {
  test -d "$ISSUE20_SCRATCH_ROOT" || {
    echo "run the containerized evidence campaign first" >&2
    return 1
  }
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    -v "$ISSUE20_SCRATCH_ROOT:$ISSUE20_SCRATCH_ROOT:ro" \
    -w /workspace \
    formowl-dev:local "$@"
}
```

Keep these shell functions in the same operator shell for the rest of this
runbook. The repository shell runner remains host-invoked because it is itself
the Docker custody/orchestration boundary. If `/usr/bin/python3`, Docker
Buildx, Compose v2, nested bind mounts, or permission to use the Docker socket
is unavailable, stop before starting a campaign; do not replace the runner
with direct host Python commands.

### A. Create private incomplete templates

```sh
umask 077
issue20_dev formowl-issue20-evidence template \
  --output-dir .test-tmp/issue20-governed-sources
```

The output directory must not already exist. The command stages the complete
four-file set, writes the directory as mode `0700` and files as mode `0600`,
then renames the staging directory into place. A write failure or existing
target leaves no new partial template set and never overwrites operator data.

Complete `mcp-inspector-source.json` and
`live-chatgpt-google-source.json` only from the real journeys in
`docs/closed-beta-runbook.md`. In ChatGPT, enable **Settings → Security and
login → Developer mode**, then create/manage the developer-mode app through
ChatGPT Apps management. The live source must attest that temporary discovery
retained the stable non-secret predefined client ID selected and recorded by
the operator before discovery, and used only
`https://invalid.example.invalid/formowl-discovery-only` as the redirect
sentinel. It must attest that discovery created no invitation or active
identity state and was not counted as completion. The same Compose `public-tls`
host-network service used by the final deployment must proxy through the
operator-controlled Caddyfile to the loopback backend during discovery.
ChatGPT app management must be configured to use the same predefined client ID
if its current UI supports entry or selection; if it does not, the campaign
must stop as an external live blocker. After ChatGPT shows the exact
`https://chatgpt.com/connector/oauth/{callback_id}`, replace only the redirect
sentinel, restart, pass preflight/`readyz`, choose **Refresh**, and start a new
conversation before recording OAuth evidence. Never claim ChatGPT generated or
displayed the client ID.

The production callback shape is strict: fixed lowercase HTTPS origin
`chatgpt.com`, exact `/connector/oauth/` prefix, and one non-empty
RFC-unreserved callback-id segment. Userinfo, ports, percent encoding, extra
segments, query, fragment, wildcards, arbitrary HTTPS origins, and any other
`.invalid` value are rejected before repository connection or runtime
composition. The exact redirect sentinel above is the only non-production callback
exception. Client-ID placeholders, the legacy client-ID sentinel, unsafe
identifiers, and non-exact redirect values fail closed. The redirect sentinel
alone selects discovery; the same real predefined client ID remains exact in
both discovery and final mode.

Set `callback_bootstrap_mode` to `direct_exact_callback` when app management
revealed the callback without a discovery sentinel, or
`reserved_invalid_discovery` when the reserved `.invalid` fallback was needed.
This reserved mode is the `discovery_only` boundary; any reachable placeholder
mode is rejected. In both modes, the source must
attest that no reachable third-party redirect was configured, no invitation or
active identity state was created before the exact callback was ready, no OAuth
transaction or authorization-code state was carried into evidence, and no
discovery-only activity was counted as completion.

### B. Freeze and validate the raw machine reports

Collect the final local harness report, raw live-PostgreSQL report, raw
operator-CLI/PostgreSQL report, and at least two distinct raw production
lifecycle reports. Do not provide prebuilt public layers to the packet builder.
The live-PostgreSQL report must pass its own validator. Operator and lifecycle
public layers are rebuilt by the current `oauth_mcp_harness` authority.

The authoritative raw live-PostgreSQL source report is artifact
`formowl_connected_runtime_postgres_live_e2e_v2`. Its exact top-level shape is:

```text
artifact_id
status
protocol_version
metrics
safe_counts
safe_hashes
live_postgresql_layer
claim_boundary
```

The report has no standalone `schema_version` field. An obsolete
`formowl_connected_runtime_postgres_live_e2e_v1` artifact or a
`schema_version: 1` expectation is not completion-eligible. The embedded
`live_postgresql_layer` remains the current public external-layer contract and
must pass its dedicated validator.

Final runtime evidence is image-ID bound. Runtime builds use Docker
`--iidfile`; the captured value must be exactly `sha256:<64 lowercase hex>` and
must be the image passed to every nested `docker run`. Lifecycle Compose
evidence exports that exact value as `FORMOWL_RUNTIME_IMAGE` and exports only
`pgvector/pgvector@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6`
as `FORMOWL_POSTGRES_IMAGE`. Rendered Compose must resolve both connected
services to the IID and PostgreSQL to that digest. A tag, short digest, changed
digest, or build/execute mismatch invalidates the raw report before packet
assembly.

The operator live-journey authority is schema v2. The packet builder delegates
its raw report to `build_operator_cli_postgresql_external_layer()`, which
requires the exact v2 command, denial, audit, rollback, membership-lifecycle,
runtime-IID, and pinned-PostgreSQL bindings. A schema-v1 diagnostic artifact or
a hand-edited/rehashed substitute is an explicit external blocker.

Use the containerized evidence runner as the campaign custodian. It keeps the
verifier-held authority and pin outside the report bundle:

```sh
OPERATOR_REPORT="$ISSUE20_SCRATCH_ROOT/reports/operator-postgresql.json"
OPERATOR_AUTHORITY="$ISSUE20_SCRATCH_ROOT/trust-inputs/operator-postgresql-execution-authority.json"
OPERATOR_AUTHORITY_PIN="$ISSUE20_SCRATCH_ROOT/trust-inputs/operator-postgresql-execution-authority-pin.json"
LIVE_POSTGRES_REPORT="$ISSUE20_SCRATCH_ROOT/reports/live-postgresql.json"
LIFECYCLE_REPORT_A="$ISSUE20_SCRATCH_ROOT/reports/production-lifecycle-a.json"
LIFECYCLE_REPORT_B="$ISSUE20_SCRATCH_ROOT/reports/production-lifecycle-b.json"
LIFECYCLE_LAYER="$ISSUE20_SCRATCH_ROOT/reports/production-lifecycle-external-layer.json"
LOCAL_HARNESS_REPORT="$ISSUE20_SCRATCH_ROOT/reports/local-oauth-harness.json"

scripts/issue20_containerized_evidence_runner.sh preflight
scripts/issue20_containerized_evidence_runner.sh operator
scripts/issue20_containerized_evidence_runner.sh operator-layer
scripts/issue20_containerized_evidence_runner.sh live-postgresql
scripts/issue20_containerized_evidence_runner.sh lifecycle-a
scripts/issue20_containerized_evidence_runner.sh lifecycle-b
scripts/issue20_containerized_evidence_runner.sh lifecycle-aggregate
scripts/issue20_containerized_evidence_runner.sh local-harness
```

Run all eight modes only after implementation, Compose/deploy files, runbooks,
manifest/onboarding authority, tests, and the final post-cleanup source snapshot
are frozen. Before `preflight`, preserve any scratch root produced from older
source as non-authoritative history, then perform the governed reset required
for the fixed active path; never relabel stale artifacts as current.
`preflight` must be first. The remaining modes must run in the shown order
against one governed scratch root. Any later bound-source change stales every
report and derived layer; preserve the stale campaign, reset the active path,
and start a new governed campaign.

`trust-inputs` is mode `0700`; both fixed files are created once with exclusive
creation and mode `0400` before PostgreSQL or the raw inner journey starts. The
runner never removes, overwrites, reconstructs, or recovers either file from a
report. If either fixed path already exists, `operator` aborts before the raw
journey. If creation stops after only one file is durable, that partial pair is
deliberately retained and the campaign is locked. Do not fill in the missing
file or reuse the surviving file. Stop all campaign work, perform a
governed reset of the entire scratch root, and begin a fresh campaign. In this
custody model, the reports directory is never the trust source; it contains
only reports, validations, and derived layers.

The operator journey also receives one fixed final failure-diagnostic filename
under the governed `private-logs` directory. It is not a report, trust input,
external layer, completion source, or packet input. The inner runtime UID
`10001` never writes this final path. On failure it may create only an
ephemeral, private handoff in the journey's existing temporary directory:
exclusive mode `0200` while writing, `fsync`, then mode `0444`. The outer
process requires the handoff to remain a regular single-link file owned by
`10001:10001`, pins its inode and metadata across no-follow descriptor reads,
accepts only an exact `inside_*` stage, and rejects a leftover handoff after a
successful child run. Missing, malformed, raced, replaced, or otherwise
untrusted handoff content falls back to `outer_inner_journey`.

Only after that validation may the outer process create the runner-owned mode
`0400` final diagnostic at the fixed `private-logs` path. The temporary
handoff is not retained as a campaign artifact, and the runner never removes
or reconstructs the final diagnostic. Its complete schema is exactly:

```text
artifact_id
failure_code
schema_version
stage
status
```

The constants are
`formowl_connected_operator_postgres_live_journey_failure_diagnostic_v1`,
`stage_failed`, schema version `1`, and `failed`. `stage` must be exactly one
of:

```text
inside_migration
inside_operator_commands
inside_report
inside_runtime_setup
inside_seed
inside_verification
outer_authority
outer_inner_journey
outer_postgresql
outer_report
outer_runtime_cleanup
outer_runtime_setup
outer_secret_set
```

The outer runner accepts a stage only after a no-follow open verifies one
regular, single-link, runner-owned mode-`0400` file, the same inode at the
fixed path, bounded UTF-8 JSON, no duplicate keys, the exact five-field schema,
the exact constants, and the finite stage enum. Missing, malformed, unknown,
extra-key, symlinked, replaced, wrong-owner, wrong-mode, oversized, or
duplicate-key diagnostics are untrusted.

The public failure remains the runner-owned generic
`runner_command_failed` envelope. A validated finite stage may be added to
that envelope; no child exception, stderr, command output, account, token,
payload, SQL, URL, backend detail, or path may be copied into it. If diagnostic
creation or validation fails, the original command failure remains generic;
diagnostic handling does not replace it with a new public error.

Any existing diagnostic path locks the whole campaign, including preflight,
operator, operator-layer, live-PostgreSQL, lifecycle, and local-harness modes,
before Docker build or run. A successful operator journey must leave the fixed
path absent. After a failed journey, do not delete the diagnostic and continue
with another mode. Perform a governed reset of the complete scratch root and
start a fresh campaign.

### C. Prepare the exact reviewer packet

```sh
issue20_dev_with_scratch formowl-issue20-evidence prepare-reviewer-source \
  --local-harness-report "$LOCAL_HARNESS_REPORT" \
  --live-postgresql-evidence "$LIVE_POSTGRES_REPORT" \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-execution-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_A" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_B" \
  --operator-attest-postgresql \
  --operator-attest-lifecycle \
  --mcp-inspector-source .test-tmp/issue20-governed-sources/mcp-inspector-source.json \
  --live-chatgpt-google-source .test-tmp/issue20-governed-sources/live-chatgpt-google-source.json \
  --output-dir .test-tmp/issue20-core-review
```

Both operator attestation flags are mandatory and explicit. The command
atomically creates `core-review-packet.json` and a
`reviewer-gate-source.json` template whose
`review_packet_commitment_hash` is bound to that exact core source set. Three
distinct read-only reviewers must fill the fixed areas in order:

```text
engineering_protocol
security_governance
operator_chatgpt_e2e
```

Each reviewer must return `AGREE`, zero blocking findings, and an independently
committed output. Any source/report change makes the reviewer packet stale and
requires a new review packet and new reviews.

The three read-only source reviews completed before the final
warning/snapshot cleanup are historical readiness evidence only. They do not
satisfy `reviewer_gate`. The final packet must be freshly generated from and
bind the frozen post-cleanup source plus the completed live campaign artifacts.

### D. Prepare a separate independent completion audit

After the three-reviewer source is complete, run:

```sh
issue20_dev_with_scratch formowl-issue20-evidence prepare-completion-audit-source \
  --local-harness-report "$LOCAL_HARNESS_REPORT" \
  --live-postgresql-evidence "$LIVE_POSTGRES_REPORT" \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-execution-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_A" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_B" \
  --operator-attest-postgresql \
  --operator-attest-lifecycle \
  --mcp-inspector-source .test-tmp/issue20-governed-sources/mcp-inspector-source.json \
  --live-chatgpt-google-source .test-tmp/issue20-governed-sources/live-chatgpt-google-source.json \
  --reviewer-gate-source .test-tmp/issue20-core-review/reviewer-gate-source.json \
  --output .test-tmp/issue20-completion-audit-source.json
```

This output is still incomplete evidence. It pins the current implementation,
local harness, `ActorContext`, documentation, journey manifest, and reviewed
layer-artifact set so an independent read-only completion auditor can inspect
the exact reviewed state. The auditor and operator must attest separately;
`auditor_attested=true` never implies `operator_attested=true`. The auditor
identity/output commitments, every journey commitment, and all fixed
attestations must be real and distinct where required. Reviewer gate and
completion audit are separate governed sources.

### E. Build and pair-validate from the same sources

Optionally validate the four completed governed sources first:

```sh
issue20_dev formowl-issue20-evidence validate-sources \
  --mcp-inspector-source .test-tmp/issue20-governed-sources/mcp-inspector-source.json \
  --live-chatgpt-google-source .test-tmp/issue20-governed-sources/live-chatgpt-google-source.json \
  --reviewer-gate-source .test-tmp/issue20-core-review/reviewer-gate-source.json \
  --completion-audit-source .test-tmp/issue20-completion-audit-source.json \
  --output .test-tmp/issue20-governed-source-validation.json
```

Then build the public packet and validate it using the exact same reports,
original verifier-held authority paths, sources, and explicit attestation
flags:

```sh
issue20_dev_with_scratch formowl-issue20-evidence build-packet \
  --local-harness-report "$LOCAL_HARNESS_REPORT" \
  --live-postgresql-evidence "$LIVE_POSTGRES_REPORT" \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-execution-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_A" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_B" \
  --operator-attest-postgresql \
  --operator-attest-lifecycle \
  --mcp-inspector-source .test-tmp/issue20-governed-sources/mcp-inspector-source.json \
  --live-chatgpt-google-source .test-tmp/issue20-governed-sources/live-chatgpt-google-source.json \
  --reviewer-gate-source .test-tmp/issue20-core-review/reviewer-gate-source.json \
  --completion-audit-source .test-tmp/issue20-completion-audit-source.json \
  --output .test-tmp/issue20-external-evidence.json

issue20_dev_with_scratch formowl-issue20-evidence validate-packet \
  --packet .test-tmp/issue20-external-evidence.json \
  --local-harness-report "$LOCAL_HARNESS_REPORT" \
  --live-postgresql-evidence "$LIVE_POSTGRES_REPORT" \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-execution-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_A" \
  --production-container-lifecycle-report "$LIFECYCLE_REPORT_B" \
  --operator-attest-postgresql \
  --operator-attest-lifecycle \
  --mcp-inspector-source .test-tmp/issue20-governed-sources/mcp-inspector-source.json \
  --live-chatgpt-google-source .test-tmp/issue20-governed-sources/live-chatgpt-google-source.json \
  --reviewer-gate-source .test-tmp/issue20-core-review/reviewer-gate-source.json \
  --completion-audit-source .test-tmp/issue20-completion-audit-source.json \
  --output .test-tmp/issue20-external-evidence-validation.json
```

`validate-packet` rebuilds the expected packet from every raw report and
governed source, requires canonical equality with the supplied packet, and then
runs the current schema-v5 authority validator. Changing even one source after
build fails with `packet_source_rebuild_mismatch`. Missing attestations or any
preparation/build error leave no newly created reviewer directory, completion
source, or packet artifact; the safe error is written to stdout instead.

The frozen-source order is therefore strict: preserve stale scratch, freeze the
final post-cleanup repository authority, run the eight runner modes once,
complete the real Inspector and ChatGPT/Google
source templates; prepare the reviewer source; obtain three independent
reviewer decisions; prepare the completion-audit source; obtain the distinct
independent auditor decision; validate all four governed sources; build the
packet; pair-validate it from the identical raw reports/trust inputs/sources;
then run the final external-packet-bound harness. A change at any earlier stage
invalidates every later artifact. Never prepare the completion audit before the
reviewer source is complete, and never treat a built-but-unvalidated packet as
completion evidence.

## Canonical command

First run the local harness without an external packet. Copy these three safe
output hashes into the completion-audit layer of the operator packet:

```text
local_completion_audit_report_hash
actor_context_contract_hash
documentation_contract_hash
```

The report also emits `issue20_completion_journey_manifest_hash`, which must
match the packet's `journey_manifest_hash`.

After the production, migration, runtime-image, operator-command, and evidence
diff is frozen, run the bounded operator campaign through the containerized
runner. The following explicit commands show the same original trust paths that
the runner passes to raw validation and layer conversion:

```sh
issue20_dev_with_scratch python \
  scripts/connected_operator_postgres_live_journey.py \
  --validate-report "$OPERATOR_REPORT" \
  --trusted-execution-authority "$OPERATOR_AUTHORITY" \
  --trusted-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --output .test-tmp/issue20-operator-postgresql-validation.json
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --operator-attest-postgresql \
  --output .test-tmp/issue20-operator-postgresql-external-layer.json
```

The converter requires explicit operator attestation, recomputes the current
implementation and journey-script hashes, requires source schema version `2`,
validates exactly ten successful CLI operations, three denials, thirteen
persisted audits (ten allowed and three denied), and the rollback and complete
membership-lifecycle counts, then self-binds the v2 public layer artifact hash.
It also binds the exact runtime IID, pinned PostgreSQL image digest, and current
v2 authority contract. The external layer does not contain the private report
path or operator outputs. The standalone journey validator may read a legacy
schema-v1 diagnostic report, but neither this converter nor a final packet may
consume it.

The section-B runner sequence already produced and validated
`LIVE_POSTGRES_REPORT`, `LIFECYCLE_REPORT_A`, `LIFECYCLE_REPORT_B`,
`LIFECYCLE_LAYER`, and `LOCAL_HARNESS_REPORT`. Do not run those modes a second
time. A report created before the freeze is diagnostic only: the validators
recompute `implementation_contract_hash`, so any later change to bound
production, container, migration, operator-journey, evidence, or documentation
authority invalidates the reports and requires a wholly new governed campaign.

The aggregator rejects a duplicated report and rejects different static image,
Compose, migration, readiness, JWKS, security, command, or implementation
fingerprints. To bind only this completed layer into the local OAuth authority
report while the other external gates remain outstanding, first copy the
runner-produced governed layer to the ignored container-readable receipt path.
The scratch-root artifact remains the campaign source; the `.test-tmp` copy is
revalidated content and never replaces the governed source:

```sh
install -d -m 0700 .test-tmp
install -m 0600 "$LIFECYCLE_LAYER" \
  .test-tmp/issue20-lifecycle-external-layer.json
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --production-container-lifecycle-evidence \
  .test-tmp/issue20-lifecycle-external-layer.json \
  --output .test-tmp/issue20-oauth-lifecycle-bound.json
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --validate-report .test-tmp/issue20-oauth-lifecycle-bound.json \
  --production-container-lifecycle-evidence \
  .test-tmp/issue20-lifecycle-external-layer.json \
  --output .test-tmp/issue20-oauth-lifecycle-bound-validation.json
```

That bounded command may set only
`supports_production_container_lifecycle_claim=true`. It must keep the whole
external-packet, issue-closure, live ChatGPT/Google, MCP Inspector, and
production-readiness claims false until those independent layers are supplied.
Revalidating this lifecycle-bound report requires the same bounded lifecycle
layer; omitting it or substituting a changed layer must fail closed.

Then place the packet in ignored local test state and run the harness in the
dev container:

```sh
docker run --rm \
  -v "$PWD:/workspace" \
  -v "$ISSUE20_SCRATCH_ROOT:$ISSUE20_SCRATCH_ROOT:ro" \
  -w /workspace formowl-dev:local \
  python scripts/oauth_mcp_harness.py \
    --external-evidence .test-tmp/issue20-external-evidence.json \
    --operator-cli-postgresql-authority "$OPERATOR_AUTHORITY" \
    --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
    --output .test-tmp/issue20-oauth-mcp-harness.json
docker run --rm \
  -v "$PWD:/workspace" \
  -v "$ISSUE20_SCRATCH_ROOT:$ISSUE20_SCRATCH_ROOT:ro" \
  -w /workspace formowl-dev:local \
  python scripts/oauth_mcp_harness.py \
    --validate-report .test-tmp/issue20-oauth-mcp-harness.json \
    --external-evidence .test-tmp/issue20-external-evidence.json \
    --operator-cli-postgresql-authority "$OPERATOR_AUTHORITY" \
    --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
    --output .test-tmp/issue20-oauth-mcp-harness-validation.json
```

An explicitly supplied packet makes the command exit nonzero when any required
layer, field, count, attestation, sequence hash, or artifact binding is invalid.
The output remains the normal safe harness report and does not include the
input path or packet contents. A local-only report can still be revalidated
without a packet. Once a report contains any external packet- or layer-derived
status, artifact hash, blocker count, or claim, standalone revalidation must be
paired with the original bounded packet, or with the original bounded lifecycle
layer for a lifecycle-only report, so the validator can recompute every binding.
Hashes copied into the report are safe receipts, not trusted revalidation
inputs.

## Packet boundary

The packet has exactly three top-level fields:

```text
packet_type
schema_version
layers
```

`layers` must contain all of these exact evidence layers.

The current packet `schema_version` is `5`. Version 4 predates the verifier-held
pre-run execution-authority pin and receipt binding. Version 3 predates the
required `operator_cli_postgresql` layer and its completion-audit artifact
binding. Version 2 also predates the current implementation-contract binding.
Older packets must be rejected rather than upgraded by changing only the
version number.

- `live_postgresql`: fresh database, migrations, first-owner bootstrap,
  persisted authentication/upload/audit state, restart recovery, second-user
  invitation, revocation, expiry/relink, signing-key rotation, rollback, and
  production smoke. Rotation evidence must use a real bounded overlap: the old
  token remains valid while both public keys are published, new tokens use the
  new active key, and the old key is removed only after the old token and its
  configured verification overlap have actually expired.
- `operator_cli_postgresql`: one current-authority clean-temp raw journey report
  for the runtime image, generated secret initialization, fresh PostgreSQL,
  migration, exact operator allow/deny lifecycle, persisted service audit, and
  transactional rollback. Only raw schema v2 is completion-eligible: ten
  successful CLI operations, three denials, thirteen audits, one rollback
  probe, and one preserved-state result. The layer remains bound to the current
  implementation, runtime image identity, pinned PostgreSQL digest, v2
  authority contract, journey script, private journey report,
  initialization/migration results, output set, and denial result. A schema-v1
  report is diagnostic-only even if its label, counts, and public hashes are
  recomputed.
- `production_container_lifecycle`: two distinct final-implementation runs of
  the actual runtime Dockerfile image and packaged `formowl-connected-mcp`
  entrypoint against fresh PostgreSQL. It covers file-mounted secrets, real
  Google metadata/JWKS preflight, OAuth seeding through the production bridge,
  official MCP client calls, stateful bearer restart, upload/forgery/audit
  persistence, four SIGTERM/database-release cycles, and JWKS `1 -> 2 -> 1`
  manifest reload. Rendered Compose evidence must keep PostgreSQL, migration,
  and serving services bound to their required secret files; pre-secret
  initialization remains the separate exact built-image `docker run`
  bootstrap, not `docker compose run connected-mcp`. Each run additionally
  proves seven operator-owned mode-`0400` secret sources, Compose migrate and
  preflight, three ready/healthy secret-snapshot generations, two retired prior
  instances, runtime UID `10001`, and independently bound Compose journey,
  security, and snapshot hashes.
- `mcp_inspector`: real MCP Inspector against the remote HTTPS endpoint using
  the official `npx @modelcontextprotocol/inspector@latest` launcher, limited
  to public initialization, public tool listing, an unauthenticated
  protected-tool challenge, and a synthetic invalid-bearer challenge. It
  contains no OAuth login, authenticated call, semantic result,
  forgery/cross-workspace result, DCR/CIMD registration, or second OAuth
  client. The operator-governed bounded Inspector artifact is committed
  separately as
  `source_evidence_artifact_hash`; the layer's `evidence_artifact_hash` is the
  reproducible public-layer self-binding.
- `live_chatgpt_google`: real ChatGPT app and Google login, followed by
  upload, cross-workspace/forgery denial, revocation denial, expiry denial, and
  relink journeys. The operator-governed bounded source evidence is committed
  separately as `source_evidence_artifact_hash`; `evidence_artifact_hash` is
  the reproducible public-layer self-binding.
- `reviewer_gate`: the configured three read-only reviewers, three explicit
  agreements, and zero blocking findings. The governed reviewer outputs and
  review packet are committed as `source_evidence_artifact_hash`; the public
  reviewer summary uses a separate reproducible `evidence_artifact_hash`.
- `completion_audit`: cross-bound hashes for every preceding layer, the local
  harness report, the exact whole-journey manifest, the `ActorContext` contract,
  and relevant documentation state.

The seven independent governed source commitments are:

```text
live_postgresql.source_report_commitment_hash
operator_cli_postgresql.journey_report_hash
production_container_lifecycle.run_report_set_hash
mcp_inspector.source_evidence_artifact_hash
live_chatgpt_google.source_evidence_artifact_hash
reviewer_gate.source_evidence_artifact_hash
completion_audit.source_evidence_artifact_hash
```

All seven must be present, valid SHA-256 values, and pairwise distinct. Each must
come from its own governed evidence artifact or run set; a source commitment
from one layer must not be reused in another layer even when both public-layer
artifacts and the completion audit are coherently recomputed.

The seven-value source set must also be completely disjoint from every public
`evidence_artifact_hash` in all seven layers, including `completion_audit`.
A governed source commitment cannot reuse an Inspector, ChatGPT/Google,
reviewer, PostgreSQL, operator, lifecycle, or completion public-summary
artifact hash. Full packet validation enforces this domain separation even
when the affected public layer and completion audit have both been coherently
rebound.

Every artifact reference must be a `sha256:<64 lowercase hex>` value. The
completion-audit references must equal the corresponding layer artifact hashes;
the exact journey-manifest hash is fixed by the harness.

`implementation_contract_hash` is required in the live-PostgreSQL,
operator-CLI/PostgreSQL, production container lifecycle, and completion-audit
layers. The local harness recomputes it from the current issue #20
production/auth/gateway/contract sources, container and Compose definitions,
migration SQL, runtime evidence scripts, and their shared evidence-contract
helper. The deploy portion binds the tracked
`deploy/connected/Caddyfile.example`,
`deploy/connected/compose.env.example`,
`deploy/connected/operator_config.py`,
`deploy/connected/secrets/README.md`, and
`deploy/connected/signing-key-set.example.json`. It deliberately does not bind
ignored operator-local Caddy/env copies. The real BuildKit regression freezes
the current build context and requires the implementation-contract hash from
that frozen snapshot to equal the current-source hash. The exact runner
authority is also part of the source set:
`scripts/issue20_containerized_evidence_runner.sh` and
`scripts/issue20_runner_boundary.py` are both bound independently. Changing
either one invalidates previously generated raw reports, external layers,
completion sources, and packets; all affected evidence must be regenerated
through the paired source workflow. A stale schema, runner, boundary, or
pre-freeze image artifact cannot pass by supplying a different well-formed
SHA-256 value. The lifecycle probe also labels the built runtime image with
that exact hash and verifies the label through image inspection before the
process journey starts. The completion documentation hash is also recomputed
from the operator-critical runbook, infrastructure specification, secret setup
guidance, signing-key manifest example, and the other listed issue #20
documents.

### `live_postgresql` required hashes and counts

The layer requires independently bound hashes for the command contract, schema,
rollback, first-owner bootstrap, persisted auth/upload/audit state, restart,
second-user invitation, revocation/expiry/relink, and signing-key rotation:

```text
source_report_commitment_hash
implementation_contract_hash
command_contract_hash
schema_state_hash
rollback_state_hash
first_owner_bootstrap_state_hash
persisted_auth_upload_audit_state_hash
restart_state_hash
second_user_invitation_state_hash
revocation_expiry_relink_state_hash
signing_key_rotation_state_hash
evidence_artifact_hash
```

One passing live run must report zero failures and skips, one fresh database,
one migration journey, one bootstrap, one persisted auth/upload journey, one
restart recovery, one second-user invitation, one revocation, one expiry
denial, one relink, one rollback probe, and one production smoke probe. The
persisted audit count must be positive.

Signing-key rotation additionally requires these exact counts:

```text
signing_key_rotation_count = 1
overlap_old_token_verification_count = 1
overlap_jwks_public_key_count = 2
new_key_token_verification_count = 1
post_overlap_old_token_denial_count = 1
post_overlap_jwks_public_key_count = 1
post_overlap_new_token_verification_count = 1
private_signing_key_exposure_count = 0
```

The rotation hash must bind the actual overlap ordering and public response
shapes. It must not contain private key bytes, bearer values, raw JWKS key
material, timestamps that identify operator infrastructure, or endpoint URLs.
`source_report_commitment_hash` binds the complete bounded safe source report
without including the embedded public layer, so a report changed after layer
construction cannot reuse the old commitment. The v3 `evidence_artifact_hash`
is recomputed only from every complete public layer field except the artifact
itself. The dedicated live-PostgreSQL validator checks the current
implementation hash and this public self-binding, and full schema-v5 packet
validation invokes that validator before accepting the completion-audit
reference.

### `operator_cli_postgresql` required hashes and counts

The layer requires these independently bound hashes:

```text
implementation_contract_hash
runtime_image_id_hash
postgres_image_digest_hash
operator_authority_contract_hash
journey_script_hash
journey_report_hash
secret_initialization_contract_hash
migration_result_hash
operator_output_set_hash
operator_denial_hash
evidence_artifact_hash
```

`source_schema_version` must be exactly `2`. The completion-eligible operator
counts are:

```text
operator_cli_success_count = 10
operator_cli_denial_count = 3
operator_audit_total_count = 13
operator_audit_allowed_count = 10
operator_audit_denied_count = 3
owner_bootstrap_success_count = 1
member_invitation_success_count = 1
member_approval_denial_count = 1
explicit_token_revocation_count = 1
last_owner_removal_denial_count = 1
membership_remove_success_count = 1
membership_restore_success_count = 1
post_restore_active_session_count = 0
post_restore_inactive_session_count = 2
transaction_rollback_probe_count = 1
transaction_rollback_preserved_state_count = 1
```

The common run, image-build, database, secret, and migration counts remain one
passing run, zero failures/skips, one immutable runtime image build, one fresh
database, six generated secrets, one idempotent initializer rerun, and one
migration success. `postgres_image_digest_hash` binds the repository-pinned
PostgreSQL digest without exposing a mutable tag, while
`operator_authority_contract_hash` binds schema v2, the exact output-label set,
counts, attestations, and pinned-image commitment.

The public layer must attest that the actual runtime image, installed runtime
package, clean secret bootstrap, fresh PostgreSQL database, allow/deny CLI
paths, and persisted audits were observed. Its `evidence_artifact_hash` is a
self-binding over every other layer field. A stale implementation or journey
script, a duplicate hash, a coherently altered count, a missing attestation, or
any added path/output field fails validation.

### `production_container_lifecycle` required hashes and counts

The layer requires these current-implementation-bound hashes:

```text
implementation_contract_hash
sequence_hash
run_report_set_hash
runtime_image_contract_hash
compose_runtime_wiring_hash
compose_live_journey_hash
compose_live_security_contract_hash
compose_secret_snapshot_set_hash
oauth_seed_state_hash
first_client_result_hash
restart_client_result_hash
persistent_core_state_hash
readiness_shape_hash
jwks_phase_set_hash
runtime_log_hash
```

Two distinct passing reports must aggregate to zero failures and skips. Each
run contributes exactly three Compose readiness/healthcheck successes, one
Compose migration, one Compose preflight, three secret snapshots, two retired
prior Compose instances, one PostgreSQL mode-`0400` secret read, seven
operator-owned mode-`0400` secret sources, runtime UID `10001` in both Compose
and direct runtime evidence, at least five resolved Compose services, four
process starts, four readiness successes, four
clean SIGTERM exits, four database releases, one stateful restart, two bearer
`whoami` successes, one upload, one forgery denial, one persisted user,
external identity, token session, upload session, and file audit, three allowed
and one denied PostgreSQL MCP audit rows, two persisted state snapshots, and
JWKS public-key counts `1, 2, 1`.
The public layer contains only these counts, independently bound hashes, fixed
attestations, and the `container` endpoint scope. `run_report_set_hash` is a
safe commitment to the sorted hashes of the distinct validated private run
reports; the private hashes themselves are not copied into the layer. The
layer's v4 `evidence_artifact_hash` is recomputed solely from every complete
public layer field except that artifact field itself. Both dedicated layer
validation and full schema-v5 packet validation recompute this self-binding,
so changing a lifecycle hash or count while retaining the old artifact and
completion-audit reference fails closed.

### `mcp_inspector` source and public artifact binding

The Inspector layer requires distinct SHA-256 values for:

```text
source_evidence_artifact_hash
evidence_artifact_hash
inspector_version_hash
sequence_hash
negotiated_protocol_version_hash
public_initialize_shape_hash
public_tools_list_shape_hash
protected_tool_challenge_hash
invalid_bearer_challenge_hash
```

`source_evidence_artifact_hash` identifies the operator-governed bounded source
artifact retained by the external evidence process; it is not a transcript,
path, URL, token, or copy of private evidence. Populate that source commitment
and every other public Inspector field first. Then compute
`evidence_artifact_hash` as SHA-256 of this canonical JSON object:

```text
{
  "binding_type": "issue20_mcp_inspector_external_layer_v1",
  "layer_without_artifact_hash": <complete public Inspector layer except evidence_artifact_hash>
}
```

The deterministic harness helper `build_mcp_inspector_external_layer()` uses
that exact algorithm. Dedicated Inspector validation and full schema-v5 packet
validation both recompute the public artifact, require a valid distinct source
hash, and apply the packet leak guard. Changing an Inspector hash while
retaining the old public artifact and completion-audit reference fails closed.

The exact public counts are one unauthenticated `initialize`, one
unauthenticated `tools/list`, one protected-tool challenge, one synthetic
invalid-bearer challenge, zero semantic results, and zero partial-state writes.
The source must attest that the official
`npx @modelcontextprotocol/inspector@latest` launcher was used and the resolved
package-version commitment was recorded; that **List Tools** and **Call Tool**
were used; that per-tool
`securitySchemes`, the required metadata mirror, and
`mcp/www_authenticate` error plus `error_description` were observed; and that
Inspector OAuth login, authenticated tools, raw bearer use, DCR, and CIMD were
not attempted.

### `live_chatgpt_google` source and public artifact binding

The live ChatGPT/Google layer uses the same two-hash boundary:

```text
source_evidence_artifact_hash
evidence_artifact_hash
sequence_hash
audit_lineage_hash
negotiated_protocol_version_hash
```

`source_evidence_artifact_hash` identifies the operator-governed bounded source
artifact for the real ChatGPT app/login journey without exposing a transcript,
email, identifier, callback, token, URL, path, or payload. After every public
hash, exact count, and attestation field is populated, compute
`evidence_artifact_hash` from this canonical JSON object:

```text
{
  "binding_type": "issue20_live_chatgpt_google_external_layer_v1",
  "layer_without_artifact_hash": <complete public live ChatGPT/Google layer except evidence_artifact_hash>
}
```

The deterministic helper `build_live_chatgpt_google_external_layer()` uses
that algorithm. Its dedicated validator enforces the exact field set, expected
journey sequence and counts, all required attestations, a valid distinct source
hash, the public self-binding, and the leak guard. Full schema-v5 packet
validation calls the dedicated validator, so changing `audit_lineage_hash` or
another public field while retaining the old artifact and completion reference
fails closed.

The governed live source also binds the two-stage app bootstrap. Before app
creation, the operator selects, validates, and records one stable non-secret
predefined client ID. Discovery retains that exact ID and uses only
`https://invalid.example.invalid/formowl-discovery-only` as the redirect
sentinel. The named backend must start with `--no-deps --service-ports`, and
Compose `public-tls` must start with
`--profile public-tls up -d --no-deps public-tls`, use `network_mode: host`,
mount the ignored operator Caddyfile, and proxy only to the loopback backend.
Discovery keeps `/readyz` at 503 and uses `/healthz` only for process health.
It must create no bootstrap, invitation, identity, OAuth transaction,
authorization code, client authorization, token session, revocation, or
denial audit. It may perform only public `initialize`/`tools/list`; protected
tools return a standard OAuth challenge without bearer validation or audit.
ChatGPT app management must use the same predefined client ID if its current UI
supports entry or selection; if it does not, the campaign stops as an external
live blocker. The TLS service and backend must then be stopped and removed
before only the exact ChatGPT-displayed callback replaces the redirect
sentinel. The client ID must remain unchanged. Legacy/template client IDs,
unsafe IDs, and non-exact redirect values fail closed. Only after final Compose
rendering may PostgreSQL, migration, normal preflight, bootstrap, or ready
serving begin. Metadata must be refreshed through ChatGPT Apps management, and
a new conversation opened before any OAuth evidence begins. This remains a
predefined-client design; the source must not claim ChatGPT generated or
displayed the client ID, migration to another OAuth client-registration model,
or a DCR fallback.

Expiry evidence must use the production fixed 3600-second access-token lifetime
and fixed 30-second clock skew. The source must bind one newly linked session's
safe `issued_at` and `expires_at` values and attest that the difference is
exactly 3600 seconds. It must not shorten the lifetime, patch configuration, or
move clocks. The existing ChatGPT app session is reused only after trusted UTC
is strictly later than `expires_at + 30 seconds`; that call must produce an
OAuth denial/challenge with zero semantic results and zero state writes.
Relinking then traverses the complete FormOwl OAuth and Google flow, creates a
different token-session ID, restores `whoami`, and leaves the expired session
unusable.

The owner-only denial is the controlled operator-service `invite-user` probe
whose approval is attributed to the second user's member identity. It is not an
MCP tool. Its safe audit row requires service actor binding, a distinct
`approval_user_binding_hash`, `invitation_owner_required`, and an absent MCP
tool-call binding. The identity-forgery denial counts only when the request
reaches the Gateway and a server-side denied audit exists; a client-side schema
rejection is not evidence. Current connected tool descriptors intentionally
exclude caller identity/session/workspace fields and use closed input schemas.
If the real ChatGPT client rejects or strips the forgery arguments before an
HTTP request reaches FormOwl, the forgery event, `live_chatgpt_google` source,
and final packet remain incomplete. Inspector or raw-HTTP diagnostics cannot be
substituted for this required real-client event; this is a fail-closed external
blocker, not a repository pass.

The live source carries exactly 47 ordered safe audit rows. Each
`audit_record_hash` is recomputed from every safe row field except itself,
including `approval_user_binding_hash` and `previous_audit_record_hash`, using:

```text
{
  "binding_type": "issue20_live_chatgpt_google_safe_audit_record_v1",
  "record_without_audit_record_hash": <the complete safe row except audit_record_hash>
}
```

The first `previous_audit_record_hash` uses the fixed absent-value commitment;
every later row must point to the immediately preceding row hash. All 47 row
hashes must be distinct. A changed row requires a coherent rebuild of that row
and every later link, and the resulting governed source still requires explicit
operator attestation.

Produce this manifest through the connected runtime's governed operator
command, not private SQL:

```sh
docker compose run --rm --no-deps \
  --user 10001:10001 \
  --entrypoint /bin/sh \
  connected-mcp \
  -c 'umask 077; install -d -m 0700 /data/operator-evidence'

docker compose run --rm connected-mcp \
  export-issue20-live-audit \
  --workspace-id "$FORMOWL_ISSUE20_WORKSPACE_ID" \
  --started-at "$FORMOWL_ISSUE20_AUDIT_STARTED_AT" \
  --ended-at "$FORMOWL_ISSUE20_AUDIT_ENDED_AT" \
  --operator-service-id "$FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID" \
  --output /data/operator-evidence/issue20-live-audit.json
```

The start and end values must be timezone-aware UTC timestamps that bound only
the real Issue #20 journey. The output directory must already exist, be owned
by the runtime service user, and have mode `0700`. The destination must be
absent or an owned regular non-symlink file with no group/other permissions.
The private artifact contains the exact `audit_records` list plus its manifest
hash and may be used to populate the governed live source. The command's public
output is limited to generic status, the exact count `47`, and the manifest
hash. A malformed, missing, duplicate, out-of-order, wrong-workspace,
wrong-lineage, over-broad, unreadable, or uncommitted audit set produces only
`connected_issue20_audit_export_failed` and must not be repaired with manual
SQL or fabricated rows.

### `reviewer_gate` source and public artifact binding

The reviewer gate requires distinct hashes for the governed source review
evidence, reviewer set, review packet, and public-layer artifact:

```text
source_evidence_artifact_hash
reviewer_set_hash
review_packet_hash
evidence_artifact_hash
```

`source_evidence_artifact_hash` commits to the governed reviewer outputs and
bounded review packet retained by the review process; it must not contain or be
replaced by a path, transcript, private payload, or reviewer prompt text. Once
the public hashes, exact `3/3/0` reviewer/agreement/blocker counts, and required
attestations are populated, compute `evidence_artifact_hash` from:

```text
{
  "binding_type": "issue20_reviewer_gate_external_layer_v1",
  "layer_without_artifact_hash": <complete public reviewer-gate layer except evidence_artifact_hash>
}
```

`build_reviewer_gate_external_layer()` implements this deterministic binding.
The dedicated validator requires the exact field set, three configured
reviewers, three explicit agreements, zero blockers, all required attestations,
independently bound hashes, and no sensitive material. Full schema-v5 packet
validation invokes it, so changing `review_packet_hash`, coherently reducing
the reviewer/agreement count, or retaining the old artifact fails closed.

### `completion_audit` public self-binding

The completion-audit layer contains only public hashes, exact journey counts,
fixed attestations, and artifact references to the other required layers. Its
`evidence_artifact_hash` is the v1 self-binding over every complete public
completion-audit field except the artifact itself. Full schema-v5 packet
validation recomputes this value directly from the supplied layer; replacing
only the completion-audit artifact while leaving the implementation, local
harness, `ActorContext`, documentation, journey-manifest, layer-reference,
count, and attestation fields unchanged must fail. This check requires no raw
operator report, transcript, token, path, or other private evidence.

## Governed final closure transition

Do not enter this section until the final external packet and the final
external-packet-bound harness both validate with zero blockers. All seven
packet layers must be `passed`: `live_postgresql`,
`operator_cli_postgresql`, `production_container_lifecycle`, `mcp_inspector`,
`live_chatgpt_google`, `reviewer_gate`, and `completion_audit`. The reviewer
layer must be exactly 3/3 `AGREE` with zero blocking findings, and the distinct
independent completion auditor must report `passed` with zero blocking
findings. A locally passing harness, an unvalidated packet, an incomplete
reviewer source, or an unaudited packet is a stop condition.

The finalization CLI does not edit documentation. It freezes the accepted
before state, validates that freeze, and then validates the exact governed
five-document transition after the operator applies it. Keep all substantive
documentation, reviewer-governance documentation, packet bytes, verifier-held
authority pin, and local harness hash unchanged throughout this sequence.
Any implementation-contract or other finalization computation fault must be
reported only as a generic failed validation. It must not expose exception,
path, filename, or computation detail, must not escape as an uncaught error,
and must not replace an existing output artifact. The strengthened regression
and its function-onboarding manifest update are part of the 508-test local
harness authority above.

Use these canonical ignored artifact paths:

```sh
EXTERNAL_EVIDENCE=.test-tmp/issue20-external-evidence.json
FINAL_HARNESS_REPORT=.test-tmp/issue20-oauth-mcp-harness.json
PRE_CLOSURE_MANIFEST=.test-tmp/issue20-preclosure-manifest.json
PRE_CLOSURE_VALIDATION=.test-tmp/issue20-preclosure-manifest-validation.json
COMPLETION_TRANSITION=.test-tmp/issue20-completion-transition.json
COMPLETION_TRANSITION_VALIDATION=.test-tmp/issue20-completion-transition-validation.json

EXPECTED_LOCAL_HARNESS_REPORT_HASH="$(
  issue20_dev_with_scratch python -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["safe_outputs"]["local_completion_audit_report_hash"])' \
    "$FINAL_HARNESS_REPORT"
)"
```

`OPERATOR_AUTHORITY_PIN` remains the verifier-held path established in section
B. The extracted value must be one real `sha256:<64 lowercase hex>` value and
must equal the local completion hash bound by the accepted packet.

### 1. Build and validate the frozen pre-closure manifest

```sh
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --issue20-finalization-action build-preclosure-manifest \
  --operator-attest-finalization \
  --external-evidence "$EXTERNAL_EVIDENCE" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --expected-local-harness-report-hash "$EXPECTED_LOCAL_HARNESS_REPORT_HASH" \
  --output "$PRE_CLOSURE_MANIFEST"

issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --issue20-finalization-action validate-preclosure-manifest \
  --preclosure-manifest "$PRE_CLOSURE_MANIFEST" \
  --external-evidence "$EXTERNAL_EVIDENCE" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --expected-local-harness-report-hash "$EXPECTED_LOCAL_HARNESS_REPORT_HASH" \
  --output "$PRE_CLOSURE_VALIDATION"
```

Both commands must exit zero. The manifest must have `status: passed`; the
validation must have `passed: true` and `blocker_count: 0`. If either command
fails, stop without editing completion-state documentation. Do not reuse a
manifest after any bound packet, pin, hash, source, reviewer-governance, or
substantive documentation change.

### 2. Apply the exact five-document completion transition

Apply one reviewed change to exactly these mutable completion-state documents:

```text
README.md
docs/implementation-task-breakdown.md
docs/agent-goals/system-backbone-agent.md
docs/agent-goals/handoff-log.md
docs/issue20-account-system-verification-status.md
```

The governed transform is implemented by
`_issue20_expected_completion_document_texts()` in
`scripts/oauth_mcp_harness.py` and is pinned by
`mutable_document_expected_after_hashes` in the pre-closure manifest. It
changes only the Issue #20 open/complete state and required closure markers,
preserves every non-Issue-#20 checklist line, keeps Issue #41 open, preserves
the pre-closure verification record, records all seven layers as accepted,
records reviewer 3/3 and the independent audit as passed, and does not expand
any production-readiness claim.

Do not edit any substantive pre-closure contract document during this step,
including this runbook or `docs/closed-beta-runbook.md`. Do not change another
checkbox, rewrite Issue #41, add a production-ready assertion, or apply only a
subset of the five documents. A concurrent edit or partial transition is a
stop condition: reconcile back to the exact frozen before state and restart
from a new pre-closure manifest rather than repairing hashes or continuing.

### 3. Build and validate the completion-transition artifact

```sh
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --issue20-finalization-action build-completion-transition \
  --preclosure-manifest "$PRE_CLOSURE_MANIFEST" \
  --operator-attest-finalization \
  --external-evidence "$EXTERNAL_EVIDENCE" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --expected-local-harness-report-hash "$EXPECTED_LOCAL_HARNESS_REPORT_HASH" \
  --output "$COMPLETION_TRANSITION"

issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --issue20-finalization-action validate-completion-transition \
  --preclosure-manifest "$PRE_CLOSURE_MANIFEST" \
  --completion-transition "$COMPLETION_TRANSITION" \
  --external-evidence "$EXTERNAL_EVIDENCE" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --expected-local-harness-report-hash "$EXPECTED_LOCAL_HARNESS_REPORT_HASH" \
  --output "$COMPLETION_TRANSITION_VALIDATION"
```

Both commands must exit zero. The transition must have
`artifact_type: issue20_post_audit_transition_v1` and `status: passed`; the
validation must have `passed: true`, `blocker_count: 0`, and
`supports_issue20_closure_claim: true`. Any mismatch is a stop condition and
does not support closure.

This validated transition is repository closure evidence only. It does not
create a Git commit, push a branch, publish evidence, or close GitHub Issue
#20. Commit/push and GitHub issue closure are separate operator publication
actions. Perform them only after reconciling the large shared worktree to a
clean, reviewed source state and receiving the required authorization for each
publication action. Until that reconciliation and authorization are complete,
leave GitHub Issue #20 open and do not present the transition artifact as a
published repository state.

## Forbidden packet contents

Do not include:

- access, refresh, or ID tokens;
- authorization codes, PKCE verifiers, client state, nonce, or credentials;
- raw ChatGPT or MCP Inspector transcripts;
- email addresses or private source payloads;
- local, NAS, object-store, database, or worker paths;
- SQL, environment values, endpoint URLs, or backend commands.

The packet records only fixed labels, booleans, counts, endpoint schemes, and
hashes. Evidence artifacts remain under the operator's governed evidence
process and are not copied into the public harness report.

## Claim boundary

A fully valid packet may set bounded external-layer claims and
`supports_external_evidence_packet_contract_claim=true`. It must still report:

```text
supports_issue20_closure_claim=false
requires_independent_issue20_completion_audit=true
supports_production_ready_claim=false
```

Issue #20 completion remains controlled by the work board, canonical local and
external evidence, relevant documentation, and the configured reviewer gate.
No self-authored packet or structurally valid set of hashes can close the issue.
Its definition of done includes a verified gateway-controlled `ActorContext`
contract that issue #41 can consume. It does not require implementing or
completing issue #41's planning-only Asset/storage/lifecycle work.
Issue #20 remains open while any required layer is `not_supplied`.
