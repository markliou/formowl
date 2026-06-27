# Cross-Agent Reviewer Gate

This file defines the default reviewer gate for future FormOwl agent work.

## Default Gate

Use 6 effective read-only reviewers for each newly completed implementation or
research slice unless the user explicitly changes the count for that slice.

Reviewer composition:

- 3 Codex/GPT reviewers.
- 3 Antigravity Gemini reviewers through the local `agy` CLI.

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
6. Send a compact bounded packet to Antigravity Gemini reviewers through
   `agy` for independent method, governance, and adversarial critique.
7. Only after blockers are closed, fill the remaining reviewer count.

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

Antigravity Gemini reviewers must be called through the real Antigravity CLI,
not through Codex `multi_agent_v1`, not through a GPT model override, and not
through any "agy folder" GPT substitute.

Expected command shape:

```sh
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

Observed CLI path:

```text
/home/markliou/.local/bin/agy
```

## User Authorization

The user authorized `agy` / Antigravity reviewer use on 2026-06-27.

This authorization covers sending bounded review packets, diffs, file excerpts,
test summaries, and design claims to Antigravity Gemini reviewers when needed
for FormOwl review. It does not authorize sending secrets, credentials, raw
private source payloads, raw backend paths, raw SQL, NAS paths, object-store
admin endpoints, worker scratch paths, or unrelated private data.

If a review requires broader external disclosure than a bounded review packet,
ask the user for fresh approval.

### Standing Scoped Authorization

For FormOwl Knowledge Graph goal reviewer gates, the user has explicitly
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

If `agy` is slow, confirm the process is still running and wait for completion.
Do not treat silence as an approval or a completed review. If sandbox approval
review, tenant policy, or Antigravity rejects the external disclosure before
execution, record the gate as blocked in the relevant goal file and work-board
note. Do not bypass the blocker through a broader packet, another external
channel, Codex `multi_agent_v1`, a GPT model override, or an "agy folder"
substitute.

### Bounded Write Delegation

The user also permits Codex to ask Antigravity to write code or docs for
bounded implementation tasks when this saves Codex token budget. This is not a
blanket repository write grant. Each invocation must state the exact owned
files or directories, keep the write scope task-local, and avoid unrelated
changes.

Use `--new-project --add-dir <smallest-scope>` for bounded write delegation.
Observed testing showed that plain one-shot `--add-dir` may not create an
active writable workspace, while `--new-project --add-dir` can write to the
intended added workspace. Codex must verify the resulting local diff instead of
trusting Antigravity's text summary alone.

Codex remains responsible for inspecting Antigravity's diff, running the
relevant canonical dev-container checks, updating durable FormOwl docs, and
making the final commit. Antigravity must not promote canonical real-evidence
packets, mutate canonical KG/type/user-graph/wiki state outside the assigned
task, relax acceptance gates, change secrets, or broaden external disclosure.
Do not use `--dangerously-skip-permissions` unless the user explicitly approves
that exact command and write scope.

Observed 2026-06-27 policy/write tests: `agy --version` returned `1.0.13`,
and `agy models` listed `Gemini 3.5 Flash (High)`. A minimal bounded FormOwl KG
read-only reviewer packet was rejected before execution by tenant policy as
external data disclosure to an untrusted reviewer service. No packet was sent.
For writing, plain `--add-dir` was not sufficient for reliable bounded
workspace writes; `--new-project --add-dir` successfully wrote to an empty
intended workspace and must be paired with local diff verification.

### Upfront Authorization Rule

When starting or resuming a Knowledge Graph Research Agent goal that is likely
to require this gate, ask the user for explicit Antigravity Gemini
bounded-review authorization at the beginning of the run, before long-running
implementation or verification work. The goal is to avoid completing local work
and then blocking while the user is away.

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

If approval review still rejects the external data disclosure, record the gate
as blocked in the relevant goal file and work-board note. Do not bypass the
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

For Knowledge Graph Research Agent work, distribute the 6 reviewers across these
risk surfaces when practical:

- Engineering correctness: contracts, stores, tests, rollback behavior, raw path
  leaks, and no partial writes.
- Governance and safety: candidate-before-canonical, scoped ontology,
  permission, grants, access overlays, audit, and no silent merges.
- Research method: literature comparison, baseline validity, metrics,
  ablations, error analysis, and claim limits.

The 3 Antigravity Gemini reviewers should be used for real critique, not as
duplicate summaries of the Codex/GPT reviewers.
