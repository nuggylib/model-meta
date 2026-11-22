---
name: auto-fixing
description: Use whenever ruff reports formatting or lint problems in files you touched.
---

# Let ruff fix what it can

## Trigger
Use this skill whenever `ruff format --check` or `ruff check` reports a problem in a file this task
touched.

## Pre-requisites
- The files ruff reports, from `uv run ruff format --check <file> ...` and `uv run ruff check <file> ...`.

## Steps
1. Never fix by hand anything a tool can fix. Hand edits of layout and imports are fragile and waste
   tokens; the developer's editor applies the same fixes on save.
2. Run the lint fixes, then the formatter, on exactly the reported files:
   `uv run ruff check --fix <file> ...` then `uv run ruff format <file> ...`. Lint fixes first, because
   they can leave layout the formatter then cleans up.
3. Never run either over a whole directory or the repo, so files outside this task don't change.
4. Never pass `--unsafe-fixes`. An unsafe fix can change behavior.
5. Fix only what `uv run ruff check <file> ...` still reports with Edit. Those are the rules with no
   automatic fix, such as pylint's too-many-branches.

## Verification process
- `uv run ruff format --check <file> ...` prints `already formatted` for every file.
- `uv run ruff check <file> ...` prints `All checks passed!`.
- `git diff --name-only` lists no file outside the ones this task touched.

## Example output
Request: "`ruff format --check` flags `tests/test_dashboard.py`."

```
uv run ruff check --fix tests/test_dashboard.py
uv run ruff format tests/test_dashboard.py
```
