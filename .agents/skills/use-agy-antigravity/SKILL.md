---
name: use-agy-antigravity
description: Use when Codex must call the local Antigravity CLI `agy` for non-GPT model delegation, discussion, critique, or implementation help, especially Gemini 3.5 Flash High. Applies to checking available Antigravity models, running `agy --model ... --print ...`, asking upfront for FormOwl KG goal reviewer data-egress authorization, preserving FormOwl repository boundaries while using external agents, and enforcing the original knowledge-graph algorithm acceptance gates before treating delegated output as useful.
---

# Use Agy Antigravity

## Overview

Use the local `agy` CLI when the user asks for Antigravity, Gemini,
Claude-through-Antigravity, or "gpt之外的工具". Do not substitute Codex
`multi_agent_v1` for Antigravity unless the user explicitly changes the target.

## Quick Start

For a FormOwl Knowledge Graph goal start or resume that is likely to require
the reviewer gate, ask the user for Antigravity Gemini bounded-review
authorization before doing long-running implementation or verification work.
This avoids finishing local work and then blocking while the user is away.

Use a concise request like:

```text
This KG goal needs 3 Antigravity Gemini reviewers through `agy`. Please
authorize sending a bounded read-only review packet to Gemini reviewers:
relevant file paths, design/test summaries, verification results, claim
boundaries, and non-sensitive code or docs excerpts. I will not send secrets,
credentials, raw private source payloads, raw backend paths, NAS/object-store
admin endpoints, raw SQL, worker scratch paths, or unrelated private data.
```

This is separate from command escalation. The skill records the workflow, but
it cannot bypass sandbox approval for running `agy` or approval review for
external data disclosure.

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

The user authorized Antigravity `agy` reviewer use on 2026-06-27 for FormOwl
review gates. Use the real local Antigravity CLI, for example:

```bash
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

Do not substitute Codex `multi_agent_v1`, a GPT model override, or an "agy
folder" GPT substitute when the gate requires Antigravity Gemini reviewers.

Use bounded review packets, diffs, file excerpts, test summaries, and design
claims. Do not send secrets, credentials, raw backend paths, raw SQL, NAS paths,
object-store admin endpoints, worker scratch paths, raw private source payloads,
or unrelated private data without fresh user approval.

When resuming the KG research goal, do not wait until the end of the run to ask
for the bounded review-packet approval if Gemini reviewers will probably be
needed. Ask at the start, then proceed with the local work while approval is
fresh in the conversation. If the approval reviewer still rejects the external
data disclosure, record that as a reviewer-gate blocker in the goal file and
work board; do not work around it by sending a broader packet or using a
different external channel.

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
