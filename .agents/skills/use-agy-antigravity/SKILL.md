---
name: use-agy-antigravity
description: Historical FormOwl Antigravity/`agy` workflow and safety rules. As of 2026-08-11, `agy` is temporarily removed from the worker, reviewer, and subagent pool because its quota is exhausted; do not invoke or dispatch it until the user explicitly re-enables it.
---

# Use Agy Antigravity

## Overview

Use this skill when the user asks for Antigravity, Gemini-through-Antigravity,
Claude-through-Antigravity, `agy`, or "gpt之外的工具".

## Current Status — Temporarily Disabled

As of 2026-08-11, the user reported that the `agy` quota is exhausted and
temporarily removed it from the FormOwl worker, reviewer, implementation
subagent, UAT, and subagent-coordinator pool. Do not invoke the `agy` CLI, send
Herdr assignments to `agy`, wait for it, or count it toward a reviewer gate.
Use Codex/GPT subagents instead.

This temporary suspension overrides every later historical statement in this
file that describes the 2026-08-05 authorization as active. Preserve those
sections as workflow history, but treat the authorization as dormant until the
user explicitly says the quota is restored and re-enables `agy`.

As of 2026-08-05, the user explicitly re-enabled `agy` as a normal FormOwl
worker/subagent after the Herdr file-bus route was verified. Codex may use it
for bounded read-only review, diagnosis, implementation, UAT, and coordination.
`agy` may also use its own subagents when that materially advances the assigned
task, provided every descendant remains inside the same evidence scope, write
scope, claim boundary, and acceptance criteria.

The earlier 2026-06-28 tenant-policy and missing-MCP findings remain historical
context, not the current disablement rule. Sandboxed Codex cannot call the
Herdr Unix socket directly and should send atomic JSON messages through
`/tmp/herdr-bus/outbox/` when the verified relay is available.

Do not duplicate the same implementation across `agy`, Codex subagents, or the
main agent. Assign disjoint tasks and verify every resulting diff and claim in
the canonical FormOwl environment.

This repo-local skill lives at `.agents/skills/use-agy-antigravity/SKILL.md`.
Keep the FormOwl `agy` workflow here so it is available after a normal git
clone on another machine.

## Clone-Portable Location

This is the canonical FormOwl Antigravity skill. Do not replace it with a
machine-local copy under `~/.codex/skills` unless the user explicitly asks for a
personal override. Future agents should update this tracked repo path:

```text
.agents/skills/use-agy-antigravity/SKILL.md
```

After a normal `git clone` that includes `.agents/`, start Codex from the repo
root and confirm `$use-agy-antigravity` appears in `/skills`. If it does not,
read this tracked `SKILL.md` directly before making any Antigravity decision.

## FormOwl KG Resume Checklist

At the start of every FormOwl Knowledge Graph goal resume, before long-running
local work:

1. Read `AGENTS.md`, the KG goal file, reviewer gate, and current
   `.formowl/kg-eval/SESSION_RESTART.md`.
2. Treat the standing 2026-08-05 authorization as active. `agy` may be selected
   whenever it is a useful, non-duplicative worker or reviewer.
3. Prefer the verified Herdr file bus from sandboxed Codex. Direct `agy` CLI
   execution remains a fallback and must follow sandbox-escalation rules.
4. State the exact task, write scope, evidence scope, claim boundary, and
   verification. If `agy` uses subagents, those descendants inherit all limits
   and must be reported.
5. The user authorizes all current agents to inspect MAY sample files for this
   internal UAT. Do not paste raw mail text, private answer sets, credentials,
   or unrelated private data into prompts, reports, commits, or public output.
6. If approval review, tenant policy, Herdr, or Antigravity rejects delivery,
   record the blocker in `docs/agent-goals/kg-research-agent.md`,
   `docs/agent-goals/handoff-log.md`, and any affected work-board note. Do not
   bypass it through a broader packet, another external channel, a GPT
   substitute, or an "agy folder" substitute.

## Quick Start

For ordinary FormOwl Knowledge Graph goal starts or resumes, the standing
2026-08-05 authorization is sufficient for bounded `agy` worker/subagent use.
Do not repeatedly ask for the same authorization. Ask again only when a task
would exceed the standing evidence scope, write scope, or claim boundary.

When fresh authorization is required, use a concise request like:

```text
This KG goal needs 3 Antigravity Gemini reviewers through `agy`. Please
authorize sending a bounded read-only review packet to Gemini reviewers:
relevant file paths, design/test summaries, verification results, claim
boundaries, and non-sensitive code or docs excerpts. I will not send secrets,
credentials, raw private source payloads, raw backend paths, NAS/object-store
admin endpoints, raw SQL, worker scratch paths, or unrelated private data.
```

This is separate from command escalation. The skill records the historical
workflow, but it cannot bypass sandbox approval for running `agy`, approval
review for external data disclosure, tenant policy, or the absence of a
Codex-exposed Antigravity MCP tool.

## Standing FormOwl KG Authorization

The user previously gave standing scoped authorization for this repository's
Knowledge Graph goal reviewer gate:

- Codex may run the local `agy` CLI, including `agy --version`, `agy models`,
  and `agy --model "Gemini 3.5 Flash (High)" --print ... --print-timeout 5m`,
  with sandbox escalation when required.
- Codex may send bounded read-only review packets to Antigravity/Gemini
  reviewers for FormOwl KG reviewer gates.
- Allowed packet content is limited to relevant repo-relative file paths,
  design summaries, test summaries, verification results, claim boundaries,
  and necessary non-sensitive code or documentation excerpts.
- Forbidden packet content includes secrets, credentials, tokens, private keys,
  raw private source payloads, raw backend paths, NAS or object-store admin
  endpoints, raw SQL, database dumps, worker scratch paths, local filesystem
  internals, and unrelated private data.
- If `agy` runs for a long time, confirm the process is still active and wait
  for completion instead of treating silence as a review result.
- If sandbox, approval review, tenant policy, or Antigravity rejects the
  external disclosure before execution, record the reviewer-gate blocker in
  the KG goal/work-board state. Do not bypass it with a broader packet,
  another external channel, Codex `multi_agent_v1`, a GPT model override, or
  an "agy folder" substitute.

This authorization is active as of 2026-08-05. It covers bounded review,
diagnosis, UAT, implementation, and use of `agy`-managed subagents under the
same constraints. It does not waive local verification or authorize broader
disclosure, unrelated writes, canonical promotion, or acceptance-gate changes.

## Bounded Write Delegation

The user allows Codex to delegate bounded implementation work to Antigravity
when it advances the active FormOwl goal. This path is active as of 2026-08-05.
`agy` may further delegate to its own subagents only within the parent
assignment's exact write and evidence scope.

Rules for write delegation:

- State the exact owned files or directories before invoking `agy`.
- Use `--new-project --add-dir <smallest-scope>` for repo or workspace writes.
  A plain one-shot `--add-dir` may not give Antigravity an active writable
  workspace.
- Tell Antigravity that other agents may be editing the repository and it must
  not revert unrelated changes.
- Ask for small, reviewable patches plus the tests it expects Codex to run.
- Codex must inspect the diff, run the relevant dev-container checks, and own
  the final commit. Antigravity output is never accepted without local
  verification.
- Do not allow Antigravity to promote real-evidence packets, write canonical
  KG/type/user-graph/wiki state, relax acceptance gates, change secrets, or
  broaden external disclosure.
- Do not use `--dangerously-skip-permissions` unless the user explicitly
  approves that exact command and write scope.

Observed tests on 2026-06-27:

- `agy --version` and `agy models` work, and `Gemini 3.5 Flash (High)` is
  available.
- A minimal bounded FormOwl KG read-only reviewer packet was rejected before
  execution by tenant policy as external disclosure to an untrusted reviewer
  service. No packet was sent; do not retry the same packet shape unless policy
  or platform configuration changes.
- A write test with plain `--add-dir .` did not write to the intended empty
  workspace and instead used Antigravity scratch. Do not count that as a
  successful bounded repository write.
- A strict write test that forbade scratch correctly returned
  `current_workspace_write_unavailable`.
- A write test with `--new-project --add-dir .` successfully wrote the
  requested file into the intended empty workspace. Use this form for future
  bounded write delegation, then verify the local diff yourself.

Observed MCP route probe on 2026-06-28:

- Codex tool discovery exposed Gmail, Apple Music, and Codex subagent tools,
  but no Antigravity or `agy` MCP tool.
- Codex config had no Antigravity MCP server entry.
- Antigravity global `mcp_config.json` was empty, and this repository had no
  `.agents/mcp_config.json`.
- `agy --help` listed no MCP server subcommand, and `agy plugin list` showed no
  imported plugins.
- A no-repository-content `agy --new-project --print "/mcp"` probe from `/tmp`
  returned general MCP configuration guidance rather than an active server/tool
  list.

Conclusion: Antigravity can be configured to use MCP tools inside an
Antigravity session, but this Codex environment currently has no MCP path for
Codex to call Antigravity/`agy`. Do not retry FormOwl KG reviewer/write
delegation through MCP unless an Antigravity MCP server is explicitly installed
and exposed to Codex.

Verify the CLI and model names first:

```bash
command -v agy
agy --version
agy models
```

If sandboxing blocks `agy`, rerun with escalation. The CLI may need to write
logs under `~/.gemini/antigravity-cli` and open a localhost language-server
socket before it can list models or call a model.

Use exact model names from `agy models`. Observed names include:

```text
Gemini 3.5 Flash (High)
Gemini 3.5 Flash (Medium)
Gemini 3.5 Flash (Low)
Gemini 3.1 Pro (High)
Gemini 3.1 Pro (Low)
Claude Sonnet 4.6 (Thinking)
Claude Opus 4.6 (Thinking)
GPT-OSS 120B (Medium)
```

Run a one-shot prompt with:

```bash
agy --model "Gemini 3.5 Flash (High)" --print "Prompt text" --print-timeout 5m
```

Use `--prompt-interactive`, `--continue`, `--conversation`, `--project`, and
`--add-dir` only when an ongoing Antigravity session is needed. Prefer
one-shot `--print` for bounded critique, planning, or comparison tasks.

## Delegation Workflow

Before calling `agy`, write a narrow prompt:

1. State the exact requested model.
2. State whether the task is discussion-only, patch suggestion, or allowed
   workspace modification.
3. Include the relevant FormOwl role boundary: this Codex thread is the
   Knowledge Graph Research Agent unless reassigned.
4. Tell Antigravity that other agents may be editing the repo and it must not
   revert unrelated changes.
5. Ask for concrete output: findings, proposed patch shape, changed files, test
   plan, or unresolved questions.
6. Treat Antigravity output as external advice. Verify it locally before
   applying code or marking work complete.

Do not use `--dangerously-skip-permissions` unless the user explicitly approves
that risk for the exact operation.

## Reviewer Use

The user re-authorized Antigravity `agy` reviewer and worker use on 2026-08-05.
It may be used during ordinary FormOwl KG goal resumes without another
authorization prompt, including as an independent UAT reviewer or as a
coordinator of bounded specialist subagents.

When the Herdr relay is unavailable and direct CLI use is necessary, use the
real local Antigravity CLI, for example:

```bash
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

Do not substitute Codex `multi_agent_v1`, a GPT model override, or an "agy
folder" GPT substitute when the gate requires Antigravity Gemini reviewers.

Use bounded review packets, diffs, file excerpts, test summaries, and design
claims. Do not send secrets, credentials, raw backend paths, raw SQL, NAS paths,
object-store admin endpoints, worker scratch paths, raw private source payloads,
or unrelated private data without fresh user approval.

When resuming the KG research goal, use the standing authorization and Herdr
file bus when available. If delivery or external-data policy rejects a
specific task, record that task-specific blocker; do not work around it by
sending a broader packet or using a different external channel.

## FormOwl Algorithm Gates

When using `agy` for FormOwl knowledge-graph, ontology, graph-fusion,
canonical-governance, user-graph, or graph-derived wiki work, preserve these
original pass conditions:

- Keep layers separate: raw resources, assets, evidence snapshots, observations,
  semantic metadata, candidate graph, canonical graph, user graph, and wiki
  projection are not one direct pipeline.
- External tools and LLMs may create observations, semantic metadata,
  candidate atoms, candidate relations, fusion candidates, type candidates, or
  review proposals. They must not directly mutate canonical graph state,
  canonical type state, user graph revisions, or wiki revisions.
- Preserve provenance to stable FormOwl identifiers: `asset_id`,
  `observation_id`, `extractor_run_id`, `evidence_snapshot_id`, citations,
  policy ids, graph revision ids, ontology revision ids, review events, and
  grants where applicable.
- Keep access, matching, and merge separate: entity matching does not grant
  access; data access does not imply canonical merge; canonical merge does not
  grant raw asset access.
- Never expose raw NAS, SMB, NFS, WebDAV, object-store admin, PostgreSQL, raw
  SQL, local filesystem, or worker scratch paths through ChatGPT-facing tools.
- Treat ontology/type state as scoped and versioned. Only closed core
  supertypes are hard compatibility gates; extension and promoted types are
  governed signals or mapped types, not automatic global truth.
- Make algorithmic output explainable: record score breakdowns, candidate
  sources, confidence, policy decisions, ambiguity, conflict notes, and why a
  split, merge, archive, supersede, or defer action is justified.
- Cover adversarial and lifecycle cases in tests: same-name different entity,
  insufficient evidence, permission denial, stale or version-changed extractor
  output, policy mismatch, cross-scope type alignment, and no-partial-write or
  no-canonical-mutation behavior.
- Mark a work-board item complete only after code, tests, relevant docs, and
  canonical dev-container verification are complete. Host checks are
  supplemental only.

## Prompt Template

Use this shape for discussion:

```text
You are an Antigravity agent called by Codex through agy.
Model requested: Gemini 3.5 Flash (High).
Task: <specific task>.
Repository: FormOwl.
Role boundary: Knowledge Graph Research Agent work only unless explicitly reassigned.
Constraints: preserve FormOwl layer boundaries, source provenance, permission
rules, candidate-before-canonical governance, and dev-container verification.
Do not modify files unless explicitly asked. Return concise findings and a
concrete next-step recommendation.
```

Use this shape for implementation help:

```text
You are an Antigravity agent called by Codex through agy.
Model requested: Gemini 3.5 Flash (High).
Task: <bounded implementation task>.
Owned files/modules: <explicit write scope>.
You are not alone in the codebase; do not revert unrelated changes.
Respect FormOwl KG gates: candidate-only external output, governed canonical
commit, scoped ontology, grant-aware access, no raw path leaks, source
provenance, and dev-container test evidence.
Return the patch plan, changed files, tests to run, and any blocker.
```
