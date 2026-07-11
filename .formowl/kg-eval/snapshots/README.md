# KG-Eval Snapshots

This directory stores non-authoritative blocked-state snapshots for cross-session
review. Runtime acceptance scripts read and write `../results/`, not this
directory.

Do not treat a snapshot as completion evidence without rerunning the KG-eval
commands in the dev container against the current workspace.

Authority unittests use `authority_test_fixtures.py` to copy these blocked-state
snapshots into an isolated temporary workspace. Completed-state regression uses
a separate aggregate-only synthetic snapshot in that temporary workspace. Tests
must never inherit ignored `results/` or `inputs/*_real/` operator state.
