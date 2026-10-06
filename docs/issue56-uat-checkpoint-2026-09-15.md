# Issue #56 UAT WIP Checkpoint — 2026-09-15

**Status: WIP checkpoint; not release-ready.**

## Purpose

This docs-only checkpoint records repository and handoff records from the
temporary provider-backed browser UAT for the ChatGPT MCP server. It is a
progress note for PM, not fresh acceptance evidence, not a
methodology-quality acceptance report, and not a release claim. The existing
baseline is `a933a04`.

## Recorded historical evidence

- On **2026-09-06**, the integrated Chromium LAN path was recorded as
  producing 12 same-row CRI part-number/L/T pairs and 24 citations. This is a
  dated repository/handoff record of one bounded path, not fresh acceptance.
- Local bridge and contract tests exist for the relevant path; they are local
  implementation evidence, not external-provider acceptance.
- On **2026-09-15**, a benign greeting reached the provider with HTTP `200`
  and non-empty text in about `11.8 s`. The same greeting through the FormOwl
  `/api/chat` path returned HTTP `200` but projected
  `status=error`, `reason_code=http_error`, and `citation_count=0` in about
  `47.95 s`. This was a transport smoke observation, not business-prompt
  acceptance.

These observations are recorded historical evidence only. They do not
establish external-provider acceptance, production readiness, or superiority
of any retrieval method.

## What is not proven

- External provider acceptance.
- ChatGPT connector, public HTTPS, or OAuth acceptance.
- Stable real-source full-index acceptance.

## Recorded failure observations and limitations

- A prior, distinct handoff record reported provider timings of approximately
  `9.856 s` and `11.621 s`, and MCP timeouts of approximately `50.142 s` and
  `48.376 s`. These values are a different record from the 2026-09-15
  greeting observation above; they are not asserted to be the same run or
  all on the provider `/responses` path.
- A separate, intermittent external/root HTTP `200` zero-body observation
  remains explicitly separate and unresolved. It must not be conflated with
  provider response timing or with the FormOwl `/api/chat` result.
- A zero-citation/finalization clarification path remained unresolved.
- Source/index incompleteness and resource pressure affected the run.
- Process-memory sessions were observed and are not evidence of durable
  external-service acceptance.

## Methodology authority status

As of **2026-09-15**, the **host** authority probe reported:

- `authority_valid=false`
- `methodology_ready=false`
- The following four gates remained blocked:
  - `evaluation_reports_bind_execution_fingerprint`
  - `real_user_end_answer_acceptance`
  - `same_pipeline_real_source_ablation`
  - `source_completeness_compared_with_raw_oracle`

The host probe reported missing tokenizer dependencies. Therefore
`authority_valid=false` is a host-probe result and is not canonical-container
readiness proof. The canonical container suite was not rerun for this
docs-only checkpoint. Methodology remains blocked, and no completion,
comparative advantage, or superiority claim is made here.

These methodology-gate results are **not evidence that the product demo path
itself failed**. They define a separate KG research-readiness boundary.

## Proposed separation for PM

Propose separating **product demo acceptance** from **KG research
readiness**. The browser UAT records may inform a narrowly scoped demo
decision, while the blocked methodology gates remain an independent
research-readiness decision. This is a proposal for PM, not a claim that PM
has agreed.

## Scope and commit boundary

This is a docs-only correction checkpoint. Implementation changes remain
uncommitted because the working tree contains broad mixed changes and private
artifacts. This document intentionally does not include those changes.
