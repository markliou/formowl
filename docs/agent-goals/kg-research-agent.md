# Knowledge Graph Research Agent Goal

## Role

Knowledge Graph Research Agent.

Durable role definition: `docs/agent-roles.md`.

## Current Objective

Complete the FormOwl Knowledge Graph method exploration and acceptance work:
fill in external recent literature comparison, ontology integration method,
multi-user KG and KG fusion experiments, multimodal enterprise-data validation,
human operation / annotation / adjudication workflow, production adapter gate,
and a total acceptance suite that clearly marks passed and failed items.

Historical source: Codex session `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.

Status: `complete`

## Context Budget Rule

The user requested frequent compaction when executing this goal, even though it
can reduce conversational accuracy, because token budget is the limiting
resource. Treat this goal as compact-friendly work:

- Keep in-chat updates concise and avoid reprinting long artifacts.
- After each meaningful substep, record enough state in durable files to resume
  without relying on chat history.
- Update this goal file or the work-board note after each reviewer attempt,
  blocker, test/verification result, or acceptance-status change.
- Append to `docs/agent-goals/handoff-log.md` when the checkpoint affects a
  future session or another agent.
- Before a planned pause, external approval wait, or likely compaction, write a
  short checkpoint with current status, exact next action, verification state,
  and remaining blocker.

The agent cannot force the external environment to compact on demand, but it
should make every restart cheap and safe by checkpointing more often than usual.

## Abstract

This goal exists because FormOwl's knowledge graph layer must be more than a
method sketch. It must define and test an ontology-grounded, source-preserving,
permission-aware graph fusion workflow for heterogeneous enterprise resources,
including documents, tables, slides, audio/video meetings, images, mail,
project systems, wiki pages, and conversations.

The expected result is not a claim of production readiness by assertion. The
agent must produce reproducible evidence: literature-backed design choices,
baselines, evaluation fixtures, metrics, ablations, error analysis, and clear
limits. Any algorithmic package or LLM may only generate candidates or review
proposals; canonical graph, canonical type, user graph, and wiki state remain
governed outputs.

## Scope

Owned by this agent:

- Candidate graph extraction and preview semantics.
- Ontology/type governance, scoped alignment, and type lifecycle.
- Atom granularity policy, split/merge/coarsening behavior, and lifecycle
  mappings.
- Entity and relation resolution as permission-aware proposal workflows.
- Reviewed canonical graph commit behavior and lineage requirements.
- User graph assembly, effective graph views, graph-derived wiki semantics,
  and projection lineage.
- Evaluation harnesses, datasets, baselines, ablations, reviewer critiques,
  and reproducibility artifacts for KG quality and governance claims.

Not owned by this agent unless explicitly assigned:

- MCP transport implementation.
- Storage backend plumbing.
- Worker execution boundaries.
- Database migrations and production service operations.
- Real OpenProject or wiki backend adapter plumbing.

## Acceptance Criteria

The goal is not complete until the repository contains:

- A recent external literature and system comparison that justifies the chosen
  KG fusion, ontology, and evaluation approach.
- A concrete ontology integration method that keeps core supertypes, scoped
  extension types, promoted types, and type alignment candidates separate.
- Experiments or deterministic fixtures for different users, different private
  scopes, graph overlays, and cross-scope fusion without silent access grants or
  canonical merges.
- Multimodal enterprise-resource validation covering at least document/table,
  mail/conversation, project/wiki, and audio/video-style observations or
  fixtures.
- Human review, annotation, adjudication, and reviewer-disagreement workflow
  evidence where governance claims depend on human judgment.
- A production adapter gate that clearly separates candidate-only algorithm
  outputs from canonical graph/type mutations and backend service readiness.
- Metrics for extraction quality, fusion quality, ontology/type alignment,
  provenance completeness, permission safety, latency, and scalability where
  applicable.
- Ablations for ontology guidance, policy gates, candidate review, and
  permission-aware filtering.
- Error analysis and explicit limitations.
- A total acceptance suite or checklist that marks each requirement as passed,
  failed, or blocked with evidence.
- The reviewer gate in `docs/agent-goals/reviewer-gate.md` is satisfied for
  each newly completed KG implementation or research slice.

## Verification Baseline

Use the dev container as canonical evidence:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```

Add narrower focused test commands as work lands, but do not report host-only
checks as completion evidence.

## Reviewer Gate

Use the default cross-agent reviewer gate from
`docs/agent-goals/reviewer-gate.md`: 6 effective read-only reviewers per newly
completed slice, split as 3 Codex/GPT reviewers and 3 Antigravity Gemini
reviewers through the real local `agy` CLI.

Gemini reviewers must be invoked with Antigravity, for example:

```sh
agy --model "Gemini 3.5 Flash (High)" --print "<review prompt>" --print-timeout 5m
```

This is not Codex `multi_agent_v1`, not a GPT model override, and not an
"agy folder" GPT substitute.

On any future start or resume of this KG goal, if the remaining work is likely
to need Antigravity Gemini reviewers, ask the user at the beginning for
permission to send a bounded read-only review packet through `agy`. The prompt
must explicitly allow only relevant file paths, design/test summaries,
verification results, claim boundaries, and non-sensitive code or docs
excerpts. It must explicitly exclude secrets, credentials, raw private source
payloads, raw backend paths, NAS or object-store admin endpoints, raw SQL,
worker scratch paths, and unrelated private data. Running `agy` is a separate
sandbox-escalation permission from sending that bounded packet to an external
model.

## Current Handoff Notes

- This file records the durable goal imported from session
  `019eda5f-7dd6-74a2-ac56-4f84e5d58560`.
- On 2026-06-27, the user changed the reviewer gate from 9 effective reviewers
  to 6 effective reviewers: 3 Codex/GPT reviewers and 3 Antigravity Gemini
  reviewers through the local `agy` CLI.
- The current session did not inherit that session-local goal automatically.
  Future sessions should read this file instead of relying on local Codex goal
  state.
- Keep `docs/implementation-task-breakdown.md` as the checkbox work board.
  This file records the objective, acceptance gates, and handoff state.
- 2026-06-27 update: scoped ontology/type governance contracts,
  `formowl_graph.ontology`, KG research acceptance suite,
  `scripts/kg_research_acceptance_suite.py`, and
  `docs/kg-research-method.md` are implemented. Dev-container verification
  passed: changed-file Ruff check and format check, focused ontology contract
  tests (4 OK), focused KG acceptance tests (4 OK), full unittest (246 OK),
  and the default acceptance script. The acceptance suite intentionally reports
  `production_adapter_readiness` as failed and
  `latency_scalability_enterprise_claims` as blocked, with no unexpected
  failed or blocked items.
- Reviewer gate status for the KG research acceptance slice is complete at
  6/6. GPT/Codex reviewers `Kuhn`, `Goodall`, and `Pasteur` agreed after
  blocker fixes. Antigravity Gemini reviewers `Ada-Sandbox`,
  `Lamport-Sandbox`, and `Curie-Sandbox` agreed through the real local `agy`
  CLI using sandboxed, closed-book, bounded review packets authorized by the
  user. `Raman` found initial blockers and was replaced for re-review after
  being closed. Initial Antigravity attempts rejected by sandbox policy, the
  `Ada` timeout, and the aborted/timed-out `Ada-Retry` run do not count.
- 2026-06-27 update: the user requested that future resumes of this goal ask
  for Antigravity Gemini bounded-review authorization at the start of the run,
  not after local work is complete. Treat this as the first action before
  substantial work whenever the reviewer gate is expected to need `agy`.
- 2026-06-27 update: the user requested frequent compaction for this goal to
  conserve token budget. Use short, durable checkpoints in this file, the work
  board, and the handoff log so future compact/resume cycles recover state
  without large chat history.
- 2026-06-27 completion checkpoint: current-state verification passed in the
  dev container: default KG research acceptance suite returned
  `passed_with_explicit_limits` with only expected
  `production_adapter_readiness` failed and
  `latency_scalability_enterprise_claims` blocked; focused KG acceptance tests
  ran 4 OK; focused ontology tests ran 4 OK; full
  `python -m unittest discover -s tests` ran 246 tests OK. The work-board KG
  Research Evaluation and Acceptance item is checked complete.
