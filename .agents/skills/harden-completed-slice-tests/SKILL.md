---
name: harden-completed-slice-tests
description: Use when Codex must harden tests for completed implementation slices or newly completed work items through a strict one-finding-at-a-time workflow. Applies to completed-slice and per-item test review, reviewer-gated release criteria, dev-container-first verification, host-vs-container evidence separation, work-board checkbox tracking, and iterating with read-only reviewers until they explicitly agree there are no blocking test gaps.
---

# Harden Completed Slice Tests

## Overview

Use this skill to finish completed-slice or per-item test hardening without
drifting into unrelated feature work. The operating mode is strict: one reviewer
finding at a time, code and tests repaired by the main agent, and release only
after the configured reviewer gate has enough explicit read-only approvals.

## Startup

Read the repository agent instructions first. If the repo names a work board,
implementation breakdown, specs, or canonical verification commands, read those
before editing.

Treat the work board as the shared source of truth. Do not mark a checkbox
complete unless code, tests, relevant docs, canonical verification, and any
configured reviewer gate for that item are done. If a checkbox was marked
complete before the required reviewer gate, revert it to unchecked and add a
short pending-review note.

## One Finding At A Time

Pick exactly one unchecked hardening finding, newly completed work item awaiting
reviewer gate, or reviewer blocker.

For that finding:

1. Add or strengthen the narrowest tests that prove the risk.
2. Patch production code only when the test exposes a real behavior gap.
3. Assert returned values and persisted state.
4. Assert negative side effects, such as no stray audit records, no invalid
   records, no leaked raw paths, no scratch files, and no object-store payloads.
5. Run focused tests first, then the relevant module or suite.
6. Update the work board immediately. Leave the checkbox unchecked with a note
   if canonical verification is still blocked.

## Reviewer Gate

Use reviewers as read-only critics. They do not need to run tests, edit files,
or execute commands. Their job is to inspect code and tests, state whether the
tests can be released, and identify blocking gaps.

When a reviewer finds a blocker, the main agent fixes it and then returns to the
same reviewer for re-review. Count that reviewer only after they explicitly
agree there are no blocking findings. Close a reviewer only after recording its
final agreement or non-counted failure.

Start new reviewers only after the currently blocking reviewers have been
convinced or recorded as non-counting. Continue until the configured number of
effective reviewers have explicitly agreed.

When the user has configured a reviewer count for ongoing work, apply that gate
to every newly completed implementation item before calling it complete. The
default gate in this repository is the user-requested 9 effective read-only
reviewers unless the user changes it. Do not carry over approvals from a
previous item; each item gets its own reviewer count and findings.

Use `references/reviewer-prompt.md` for reviewer instructions and
`references/work-board-pattern.md` for gate bookkeeping.

## Verification Rules

Use the repo's canonical environment as completion evidence. If the repo says
dev-container tests are canonical, host tests are supplemental only.

Do not mark completion from host-only evidence. If canonical verification is
blocked by missing packages, Docker access, or external limits, record that
blocker in the work board and keep the checkbox unchecked.

## Test Quality Checklist

Cover malformed input, typed-field validation, duplicate and empty input,
lineage mismatch, permission-scope mismatch, partial failure, rollback or
no-partial-write behavior, not-found envelopes, and authorization filtering when
relevant.

Avoid tests that merely execute code. Each test should prove a behavior or
invariant.

## Comments

Add code comments for non-obvious invariants: validation ordering,
no-partial-write behavior, rollback policy, partial-failure policy,
reviewer-driven guardrails, and MCP-facing redaction. Do not add comments that
restate obvious assignments.
