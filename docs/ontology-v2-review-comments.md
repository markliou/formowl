# Historical Ontology Review — Not Current Instructions

**Lifecycle:** `immutable-history-pointer`
**Superseded:** 2026-08-18 by GitHub issue #56

The former root-cause review correctly documented why noisy hard ontology gates
can destroy recall, but it is no longer an active plan. Its full text and
references are preserved at:

`docs/archive/2026-08-18/active/docs/ontology-v2-review-comments.md`

The accepted current correction is already incorporated into:

- `docs/kg-research-method.md`
- `docs/kg-ontology-v2-rd-boundary.md`
- `docs/kg-ontology-v2-runtime-evaluation-plan.md`

In short: use strong RAG as the control, use KG for integration and bounded
reasoning, use ontology as scoped/data-first/capped soft scoring, and retain the
legacy hard gate only as a negative ablation.
