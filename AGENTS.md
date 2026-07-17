# Agent Instructions

This repository is built from the FormOwl specification. At the start of every
new agent session, and again after any context compaction, resume, or long
interruption, read this file first. Before changing code, read these files in
order:

1. `docs/implementation-task-breakdown.md`
2. `docs/agent-roles.md`
3. `docs/agent-goals/README.md`
4. The active role's goal file under `docs/agent-goals/`
5. `docs/agent-goals/handoff-log.md`
6. `docs/agent-goals/reviewer-gate.md`
7. `SPEC.md`
8. `RESOURCE_EXTRACTION_SPEC.md`
9. `README.md`

Use `docs/implementation-task-breakdown.md` as the shared work board. Use
`docs/agent-goals/` as the durable cross-session and cross-machine goal
registry. These startup files are intentionally bounded active views. Read
`docs/archive/README.md` only when historical completion detail or older
handoffs are needed; archived files are not additional startup instructions.

## Active Agent Role

This thread's Codex agent is the Knowledge Graph Research Agent. The durable
role split is documented in `docs/agent-roles.md`.

Prioritize knowledge graph, ontology, graph fusion, canonical graph governance,
lifecycle, user graph, graph-derived wiki semantics, and research-evaluation
work. Leave broad system backbone work to the FormOwl System Backbone Agent
unless the user explicitly assigns it here.

## Default Candidate Evidence Retrieval

All new retrieval, hardness, benchmark, ablation, and harness work must start
from the source-neutral `CandidateEvidenceIndex` contract in `SPEC.md` Section
9.7.2. The default counts a stable logical source item rather than parser
chunks, binds access before query vocabulary, requires explicit context and
time admissibility, permits anchor aggregation only inside one logical source,
and limits ontology to a capped additive rerank.
A `CandidateEvidenceTextPolicyRuntime` owned by the index must bind the actual
query tokenizer to a structured policy proving Unicode NFKC/script
normalization, protected ASCII extraction, Jieba, corpus-bound SentencePiece,
frozen-profile admission, and exact admission/model/corpus SHA-256 hashes.
The binding also pins the runtime id and tokenizer implementation hash; runtime
code mismatch fails closed. Default callers pass query text only. Raw caller
tokens, free-form or placeholder hashes, and regex-only declarations are not
acceptable substitutes. Access plus explicit context and time admissibility
must finish before the runtime tokenizer or ontology resolver runs.

Regex-only retrieval, observation/chunk cardinality, lexical or thread
transitive components, and ontology hard-pruning are historical baselines or
explicit ablation arms only. They must never be silently used as the current
method or as gold construction. Before accepting a new evaluator, run
`tests/test_candidate_evidence_hardness.py` and
`tests/test_candidate_evidence_harness_onboarding.py` in the dev container.
Any non-default token, eligibility, or ontology transform must use the named
`retrieve_ablation` entrypoint and may not remove the runtime-produced default
tokens.
Raw query text may identify control intent, evidence count, and chronology
syntax only. Retrieval anchors, actor/topic vocabulary, and supported content
terms must come from runtime-produced tokens or a named `retrieve_ablation`
extension; regex-parsed raw terms must never be added back. Access uses a real
`CandidateEvidenceAccessBinding` whose four eligibility collections are
`frozenset` values of exact nonblank strings. Cross-context comparison
authorization must be an actual boolean; string values fail closed.

## Working Rules

- Treat these instructions as session startup requirements, not one-time
  background context. If a session has already started and you are unsure
  whether the files above were read in the current context, read them again
  before editing.
- Pick one unchecked task or the task explicitly assigned by the user.
- Treat session-local goal state as temporary. If a goal must survive a new
  session, a different computer, or a manual merge, record it in
  `docs/agent-goals/`.
- Repo-scoped Codex skills live under `.agents/skills/`. If the user names a
  repo-local skill that is not visible in the active `@skills` list, check
  `.agents/skills/<skill-name>/SKILL.md` before declaring it unavailable.
- Stay inside the listed owner paths when possible.
- Do not create parallel replacement modules, schemas, or documents when the
  specification already names an expected path.
- Keep resource extraction, graph governance, user graph assembly, and wiki
  projection as separate layers.
- Do not expose raw filesystem, NAS, object-store, database, worker, or parser
  internals through ChatGPT-facing MCP tools.
- Mark a checklist item `[x]` only after code, tests, and relevant docs are
  complete.
- If a task is partially done, leave it unchecked and add a short note in the
  task breakdown file.
- Before pausing, handing work to another agent, or resuming a long-running
  goal, update the relevant `docs/agent-goals/*.md` file and append a concise
  note to `docs/agent-goals/handoff-log.md` when the change affects another
  agent or future session.
- Enforce the retention limits documented in the active board and goal
  registry. Archive complete dated history losslessly before an active file
  exceeds its limit; never edit an immutable dated archive in place.
- Use the dev container as the canonical development and verification
  environment. Host commands may be used only for quick inspection or as clearly
  labeled supplemental checks; do not report host-only results as completion
  evidence.
- If a required test, linter, or helper is missing from the dev container, treat
  that as a container/tooling bug to fix or document before reporting the task
  complete.

## Current Starting Point

The current tested baseline is:

```text
Project MCP
  -> ContextPackage and EvidenceSnapshot
  -> Wiki MCP
  -> sourced markdown draft
```

The next small core starts at:

```text
Asset
  -> IngestionJob
  -> ExtractorRun
  -> Observation
  -> ContextPackage bridge
  -> Wiki MCP draft
```

Run the existing Python tests before reporting completion:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests
```
