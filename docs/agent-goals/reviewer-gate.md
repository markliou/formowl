# Cross-Agent Reviewer Gate

This file defines the default reviewer gate for future FormOwl agent work.

## Default Gate

Use 3 effective read-only Codex/GPT reviewers for each newly completed
implementation or research slice unless the user explicitly changes the count
for that slice.

Reviewer composition:

- 3 Codex/GPT reviewers.

## Issue #56 Time-Boxed POC Proof — 2026-08-18

The current issue #56 operating team is one Master plus exactly two
implementation subagents. Both workers use `gpt-5.6-sol` with
`reasoning_effort=ultra`; they are implementers, not substitutes for the
independent release reviewers below.

During the approximately six-hour pre-outage window, the Master may advance a
bounded POC after both workers provide inspectable evidence for their
non-overlapping write sets and the integrated real end-to-end path succeeds.
The proof must traverse the intended source/Observation, retrieval or execution,
and result/answer boundary. API, contract, schema, mock, or isolated unit wiring
alone does not count as a working POC.

This fast POC proof:

- may defer optional production hardening, onboarding tests, and broad suites;
- does not satisfy or reduce the default three-reviewer gate;
- does not mark an implementation/research slice complete or justify a release;
- does not justify production, comparative-superiority, or methodology-
  completion claims; and
- does not relax permission, privacy, provenance, candidate-before-canonical,
  no-secret, no-raw-path, audit, redaction, or fail-closed methodology gates.

Formal implementation completion, release, and production hardening still
require three effective independent read-only Codex/GPT reviewers across
engineering, governance/safety, and research methodology unless the user later
changes that reviewer count explicitly. Evidence produced by the two
implementation workers remains implementation evidence and does not count as
those three reviewer decisions.

## Temporary Agy Quota Suspension

As of 2026-08-11, the user temporarily removed Antigravity/`agy` from the
worker, reviewer, implementation-subagent, UAT, and subagent-coordinator pool
because its quota is exhausted. Do not invoke it, dispatch Herdr work to it,
wait for it, or count it toward a reviewer gate. Use the default 3 effective
Codex/GPT reviewers instead.

This temporary suspension overrides the later historical 2026-08-05
authorization text until the user explicitly confirms that quota is restored
and re-enables `agy`.

As of 2026-08-05, the user explicitly re-enabled Antigravity/`agy` as a normal
FormOwl worker/subagent through the verified Herdr file bus. It may perform
bounded review, diagnosis, implementation, UAT, or coordination of its own
bounded subagents. Its descendants inherit the same evidence scope, write
scope, claim boundary, and acceptance criteria.

The default release count remains 3 effective read-only Codex/GPT reviewers
unless the user changes the composition for a slice. An `agy` review may count
when it was explicitly assigned as one of those reviewers, inspected the
relevant packet, and returned the required decision. `agy` output never
replaces local diff inspection and canonical verification.

## Cost Control And Staging

Reviewer cost is part of the engineering budget. Do not spend reviewer calls to
discover issues the implementing agent can find locally.

For the time-boxed POC, first run the narrow real end-to-end path and only the
focused safety checks needed to trust that proof. Defer broad hardening and
onboarding campaigns until the POC works; then use the default completion
sequence below.

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
an "agy folder" substitute. Use the real Herdr-connected `agy` worker when an
assignment calls for it, and do not duplicate the same implementation across
agent systems.

Historical direct-CLI command shape when the Herdr relay is unavailable:

```sh
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

Observed CLI path:

```text
/home/markliou/.local/bin/agy
```

## Historical Agy Blocker And Current Authorization

The user authorized `agy` / Antigravity reviewer use on 2026-06-27, but later
requested that the FormOwl KG workflow stop wasting time on a route that could
not execute. That 2026-06-28 disablement is superseded by the explicit
2026-08-05 authorization and verified Herdr file-bus route.

Historical authorization covered sending bounded review packets, diffs, file
excerpts, test summaries, and design claims to Antigravity Gemini reviewers
when needed for FormOwl review. It did not authorize sending secrets,
credentials, raw private source payloads, raw backend paths, raw SQL, NAS
paths, object-store admin endpoints, worker scratch paths, or unrelated
private data.

Current rule: `agy` may be used as a bounded reviewer, worker, implementation
subagent, UAT agent, or coordinator of its own bounded subagents. Sandboxed
Codex should communicate through atomic JSON files under
`/tmp/herdr-bus/outbox/` rather than attempting the Herdr Unix socket.

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

This authorization is active as of 2026-08-05. Slow `agy` runs must still be
monitored until completion; silence does not count as approval. A delivery or
tenant-policy rejection for one task must not be bypassed through a broader
packet, another external channel, Codex `multi_agent_v1`, a GPT model override,
or an "agy folder" substitute.

### Bounded Write Delegation

The user permits Codex to ask Antigravity to write code or docs for bounded
implementation tasks. This path is active as of 2026-08-05. `agy` may further
delegate to its own subagents only within the parent assignment's exact write
scope, evidence scope, claim boundary, and acceptance criteria.

Use `--new-project --add-dir <smallest-scope>` for bounded write delegation.
Observed testing showed that plain one-shot `--add-dir` may not create an
active writable workspace, while `--new-project --add-dir` can write to the
intended added workspace. Codex must verify the resulting local diff instead of
trusting Antigravity's text summary alone.

Codex remains responsible for inspecting Antigravity's diff, running the
relevant canonical dev-container checks, updating durable FormOwl docs, and
making the final commit. Antigravity and any descendants must not promote
canonical real-evidence packets, mutate canonical KG/type/user-graph/wiki state
outside the assigned task, relax acceptance gates, change secrets, or broaden
external disclosure. Do not use `--dangerously-skip-permissions` unless the
user explicitly approves that exact command and write scope.

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

If approval review rejects external data disclosure for a specific `agy` task,
record the rejection and stop that task; do not bypass the gate by using a
broader packet, a different external channel, Codex `multi_agent_v1`, a GPT
model override, or an "agy folder" substitute.

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

When `agy` is not assigned as one of the effective reviewers, distribute the 3
Codex/GPT reviewers across the highest-risk engineering,
governance/safety, and research-method surfaces for the slice.
