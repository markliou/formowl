# Cross-Agent Reviewer Gate

This file defines the default reviewer gate for future FormOwl agent work.

## Default Gate

Use 3 effective read-only Codex/GPT reviewers for each newly completed
implementation or research slice unless the user explicitly changes the count
for that slice.

Reviewer composition:

- 3 Codex/GPT reviewers.

Antigravity/Gemini reviewer calls through `agy` are no longer part of the
default FormOwl reviewer gate. They repeatedly fail before execution under the
current tenant policy because even bounded FormOwl repository-derived review
packets are treated as disclosure to an untrusted external reviewer service.
The MCP route was also checked on 2026-06-28 and is not currently available
from Codex. Do not spend time attempting `agy` for FormOwl KG reviewer gates
unless the user explicitly re-enables it after confirming the policy, platform,
or MCP configuration state has changed.

## Cost Control And Staging

Reviewer cost is part of the engineering budget. Do not spend reviewer calls to
discover issues the implementing agent can find locally.

Default sequence:

1. Run a self-audit against the slice's claim boundary, negative-path tests,
   no-partial-write behavior, raw/internal leak guards, and canonical
   non-mutation guarantees.
2. Run focused host checks only as quick feedback.
3. Run the required canonical dev-container focused checks.
4. Ask the first Codex/GPT reviewers for code/test blockers.
5. Fix any blocker and return to the same reviewer before expanding the pool.
6. Only after blockers are closed, fill the remaining Codex/GPT reviewer count.

Use narrow reviewer packets:

- Include changed file paths, relevant excerpts, claim boundaries, test
  summaries, and verification commands/results.
- Exclude unrelated repository history and large generated outputs.
- Exclude secrets, credentials, raw private source payloads, raw backend paths,
  NAS/object-store admin endpoints, raw SQL, worker scratch paths, and
  unrelated private data.

If a slice is only documentation or planning, the gate still applies when that
document will be used as a durable completion or handoff authority. Reviewers
should then focus on scope, status honesty, omitted acceptance gates, and
whether the next agent can execute the plan without chat memory.

Do not substitute Antigravity/Gemini reviewers with fake `agy` results,
Codex `multi_agent_v1` agents labeled as Antigravity, GPT model overrides, or
an "agy folder" substitute. Antigravity is simply disabled for the default
gate unless explicitly re-enabled by the user.

Historical command shape if the user later re-enables `agy`:

```sh
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

Observed CLI path:

```text
/home/markliou/.local/bin/agy
```

## Historical Agy Authorization And Current Disablement

The user authorized `agy` / Antigravity reviewer use on 2026-06-27, but later
requested that the FormOwl KG workflow stop wasting time on `agy` if it cannot
be used. As of 2026-06-28, `agy` is disabled for the default FormOwl KG
reviewer gate.

Historical authorization covered sending bounded review packets, diffs, file
excerpts, test summaries, and design claims to Antigravity Gemini reviewers
when needed for FormOwl review. It did not authorize sending secrets,
credentials, raw private source payloads, raw backend paths, raw SQL, NAS
paths, object-store admin endpoints, worker scratch paths, or unrelated
private data.

Current rule: do not call `agy` for FormOwl KG reviewer gates or write
delegation unless the user explicitly re-enables it after being told that prior
attempts were rejected by tenant policy before execution.

### MCP Route Probe

On 2026-06-28, Codex tested whether using `agy` through MCP is available:

- Codex tool discovery exposed Gmail, Apple Music, and Codex subagent tools,
  but no Antigravity or `agy` MCP tool.
- The Codex configuration had no MCP server entry for Antigravity or `agy`.
- Antigravity global `mcp_config.json` was empty, and this repository had no
  `.agents/mcp_config.json`.
- `agy --help` listed no MCP server subcommand; `agy plugin list` showed no
  imported plugins.
- A no-repository-content `agy --new-project --print "/mcp"` probe from
  `/tmp` returned general MCP configuration guidance rather than an active
  server/tool list.

Interpretation: Antigravity can be configured to use MCP tools inside an
Antigravity session, but this Codex environment currently has no MCP path for
Codex to call Antigravity/`agy`. This does not change the prior tenant-policy
blocker for sending bounded FormOwl KG reviewer packets through the `agy` CLI.

### Standing Scoped Authorization

For historical FormOwl Knowledge Graph goal reviewer gates, the user explicitly
authorized Codex to:

- Run the local `agy` CLI with sandbox escalation when needed, including
  `agy --version`, `agy models`, and
  `agy --model "Gemini 3.5 Flash (High)" --print ... --print-timeout 5m`.
- Send bounded read-only review packets to Antigravity/Gemini reviewers.

Allowed packet contents are limited to relevant repo-relative file paths,
design summaries, test summaries, verification results, claim boundaries, and
necessary non-sensitive code or documentation excerpts.

Forbidden packet contents remain secrets, credentials, tokens, private keys,
raw private source payloads, raw backend paths, NAS or object-store admin
endpoints, raw SQL, database dumps, worker scratch paths, local filesystem
internals, or unrelated private data.

This authorization is no longer active for default FormOwl KG reviewer gates.
If the user later explicitly re-enables `agy`, then slow `agy` runs must still
be monitored until completion; silence must not count as approval; and tenant
policy rejection must not be bypassed through a broader packet, another
external channel, Codex `multi_agent_v1`, a GPT model override, or an "agy
folder" substitute.

### Bounded Write Delegation

The user previously permitted Codex to ask Antigravity to write code or docs
for bounded implementation tasks when this saved Codex token budget. This path
is also disabled by default for FormOwl KG work as of 2026-06-28 because
repository-derived packets are rejected before execution. Do not use it unless
the user explicitly re-enables `agy`.

Use `--new-project --add-dir <smallest-scope>` for bounded write delegation.
Observed testing showed that plain one-shot `--add-dir` may not create an
active writable workspace, while `--new-project --add-dir` can write to the
intended added workspace. Codex must verify the resulting local diff instead of
trusting Antigravity's text summary alone.

If the user later re-enables bounded write delegation, Codex remains
responsible for inspecting Antigravity's diff, running the relevant canonical
dev-container checks, updating durable FormOwl docs, and making the final
commit. Antigravity must not promote canonical real-evidence packets, mutate
canonical KG/type/user-graph/wiki state outside the assigned task, relax
acceptance gates, change secrets, or broaden external disclosure. Do not use
`--dangerously-skip-permissions` unless the user explicitly approves that exact
command and write scope.

Observed 2026-06-27 policy/write tests: `agy --version` returned `1.0.13`,
and `agy models` listed `Gemini 3.5 Flash (High)`. A minimal bounded FormOwl KG
read-only reviewer packet was rejected before execution by tenant policy as
external data disclosure to an untrusted reviewer service. No packet was sent.
For writing, plain `--add-dir` was not sufficient for reliable bounded
workspace writes; `--new-project --add-dir` successfully wrote to an empty
intended workspace and must be paired with local diff verification.

### Deprecated Upfront Authorization Rule

Do not ask for Antigravity Gemini bounded-review authorization at the beginning
of ordinary FormOwl KG goal resumes. That rule is deprecated because repeated
attempts were rejected before execution and the user requested removal of the
`agy` step when it cannot be used.

The authorization request should distinguish two permissions:

- Running the local `agy` CLI may require sandbox escalation because the CLI can
  write Antigravity logs or open local sockets.
- Sending a bounded review packet to Gemini reviewers is external data
  disclosure and must be explicitly scoped.

Allowed bounded review-packet content:

- Relevant file paths.
- Design summaries, test summaries, verification results, and claim
  boundaries.
- Non-sensitive code or docs excerpts needed for read-only reviewer critique.

Forbidden without fresh approval:

- Secrets, credentials, tokens, private keys, or account material.
- Raw private source payloads.
- Raw backend paths, NAS paths, object-store admin endpoints, raw SQL, database
  dumps, worker scratch paths, or local filesystem internals.
- Unrelated private data.

If the user later re-enables `agy` and approval review still rejects external
data disclosure, record the rejection and stop using `agy`; do not bypass the
gate by using a broader packet, a different external channel, Codex
`multi_agent_v1`, a GPT model override, or an "agy folder" substitute.

## Reviewer Output

Every reviewer should return:

```text
RELEASE_DECISION: AGREE | BLOCK
Blocking findings:
- ...
Non-blocking notes:
- ...
```

A reviewer counts only after it explicitly states there are no blocking
findings. A timeout, tool failure, vague approval, or review that did not inspect
the relevant packet does not count.

## Blocking Findings

Address one blocking finding at a time:

1. Patch the implementation or docs.
2. Add or strengthen the narrowest tests or acceptance evidence.
3. Run focused checks first.
4. Run the canonical dev-container verification required for the slice.
5. Return to the same reviewer for re-review when possible.

Do not mark the work-board item complete until all effective reviewers have
agreed and the relevant goal file or handoff log records the gate result.

## KG Review Coverage

For Knowledge Graph Research Agent work, distribute the 3 reviewers across these
risk surfaces when practical:

- Engineering correctness: contracts, stores, tests, rollback behavior, raw path
  leaks, and no partial writes.
- Governance and safety: candidate-before-canonical, scoped ontology,
  permission, grants, access overlays, audit, and no silent merges.
- Research method: literature comparison, baseline validity, metrics,
  ablations, error analysis, and claim limits.

Because Antigravity is disabled by default, distribute the 3 Codex/GPT
reviewers across the highest-risk engineering, governance/safety, and research
method surfaces for the slice.
