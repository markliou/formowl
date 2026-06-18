# Work Board Pattern

Keep reviewer gate status separate from implementation status.

## Gate Fields

Use fields like these in the repository work board:

```md
- [ ] Reach the reviewer test-release gate.
  - Proof: N effective read-only reviewers agree there are no blocking test gaps.
  - Effective reviewer count: 0/N.
  - Reviewer agreement count: 0/N.
  - Reviewers with blocking findings: none.
  - Non-counted agents: none.
  - Active reviewers: none.
```

## Finding Fields

Each accepted blocker gets its own checkbox:

```md
- [ ] Fix reviewer finding: <specific behavior>.
  - Owner paths: `<production path>`, `<test path>`
  - Proof: <specific assertion and canonical verification command>.
  - Note: <partial status, if any>.
```

## Checkbox Rules

Mark `[x]` only after:

- Production code, tests, and relevant docs are complete.
- The repository's canonical verification has passed.
- The reviewer who raised the blocker has agreed it is fixed, when a reviewer
  gate is active.

Leave the item unchecked when only host-side supplemental tests have passed.

## Reviewer Loop

1. Ask the current blocking reviewer to re-review the fix.
2. If they still disagree, add or update one checkbox per concrete blocker.
3. Fix the next blocker.
4. Ask the same reviewer again.
5. Once they agree, record the agreement, close them, and start the next reviewer.
6. Stop only when the configured reviewer count has agreed.
