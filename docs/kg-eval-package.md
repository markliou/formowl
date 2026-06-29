# FormOwl KG Eval Package

`formowl_kg_eval` is the packaged facade for the Knowledge Graph Research
Agent's broad real-evidence acceptance harness. The authoritative validators
remain under `.formowl/kg-eval`; the package provides stable API and CLI entry
points so the System Backbone Agent does not need to import repo-local scripts
directly.

## What This Package Owns

- Running the KG research-evaluation authority commands.
- Reading persisted broad acceptance reports.
- Producing a redacted summary for downstream integration.
- Preserving the research claim boundary:
  broad KG real-evidence acceptance may be complete while full product
  production readiness, top-tier scientific validation, raw asset access,
  canonical graph writes, autonomous business judgment, and enterprise-scale
  latency/scalability remain unclaimed.

## What This Package Does Not Own

- MCP transport, gateway, session, or tool-schema plumbing.
- Database, object-store, worker, or backend adapter implementation.
- Raw file, NAS, object-store, database, or worker-scratch access.
- Canonical graph mutation.
- Wiki publication.

Those remain System Backbone or product integration responsibilities.

## CLI

After installing the editable package, use:

```sh
formowl-kg-eval summary
formowl-kg-eval total
formowl-kg-eval objective
formowl-kg-eval preflight
formowl-kg-eval work-orders
formowl-kg-eval progress
formowl-kg-eval all
```

In a dev container that has not refreshed console scripts after this package was
added, use the equivalent module entry point:

```sh
python -m formowl_kg_eval summary
```

Use `--repo-root` when calling from outside the checkout:

```sh
formowl-kg-eval --repo-root /workspace summary
python -m formowl_kg_eval --repo-root /workspace summary
```

`summary` is the preferred integration command. It prints a stable JSON object
with these top-level sections:

```text
artifact_id
claim_boundary
total_acceptance
objective_audit
remaining_evidence
preflight
work_orders
progress
integration_boundary
```

The summary intentionally reports no raw workspace path. It points downstream
systems to the stable authority workspace `.formowl/kg-eval`.

## Python API

```python
from formowl_kg_eval import build_acceptance_summary, run_kg_eval_command

summary = build_acceptance_summary(repository_root="/workspace")
result = run_kg_eval_command("preflight", repository_root="/workspace")
```

`run_kg_eval_command()` supports:

```text
total
objective
preflight
work-orders
progress
```

The command result carries `command`, `script`, `returncode`, `stdout`,
`stderr`, and `passed`.

## System Backbone Integration Contract

The System Backbone Agent should call the package facade, not repo-local
validator modules:

```text
System Backbone Agent
  -> formowl-kg-eval summary
  -> reads claim_boundary and total_acceptance
  -> decides whether product-level integration can proceed
```

Do not expose `.formowl/kg-eval` internals through ChatGPT-facing MCP tools.
If a user needs status, expose the package summary or a narrower product-owned
status object. Do not expose raw evidence artifacts, local filesystem paths,
database locators, object-store keys, SQL, worker scratch paths, or canonical
graph write controls.

## Current Authority State

The current local broad KG real-evidence state is 12/12:

```text
overall_passed=true
passed_gate_count=12
failed_gate_count=0
remaining_gates=[]
```

Current hashes:

```text
gate_status_sha256=9e68c2a78681c86ff52f6ef25f20d3f6112183dcb681f137f6d349e7e4c96aba
objective_audit_sha256=b37edc1a2cf5d9891557f91f669608204998d3a8112fa0a299e3a99d082bb44d
```

## Verification

Canonical verification remains dev-container first:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m unittest discover -s tests -p 'test_kg_eval_package.py'

docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python -m formowl_kg_eval summary

docker run --rm -v "$PWD:/workspace" -w /workspace/.formowl/kg-eval formowl-dev:local \
  python -m unittest discover -s . -p 'test_*.py'
```
