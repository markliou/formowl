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
