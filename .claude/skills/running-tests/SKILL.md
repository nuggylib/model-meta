---
name: running-tests
description: Use whenever you are about to run tests locally in this repo.
---

# Run the fewest tests that cover a change

## Trigger
Use this skill whenever you are about to run `pytest` locally in this repo.

## Pre-requisites
- The changed files: `git diff --name-only` plus `git diff --name-only --cached`, or the files you just
  edited.
- CI (`.github/workflows/test.yml`) runs the whole suite on every pull request and on every push to
  `main`. That is what makes skipping the full local run safe.

## Steps
1. Never run the whole suite locally: no bare `uv run pytest`, no `uv run pytest tests/`.
2. Find the blast radius:
   - every changed module under `model_meta/`, and
   - every module under `model_meta/` that imports one of them directly. For
     `model_meta/<pkg>/<mod>.py`, match the import, not the bare word (escape the dots in a nested
     `<pkg>`, e.g. `tui\.screens`):
     `grep -rlE "model_meta\.<pkg>\.<mod>\b|from model_meta\.<pkg> import .*\b<mod>\b" model_meta`
3. Count it against the production code: `git ls-files 'model_meta/*.py' | grep -v __init__ | wc -l`.
   - If the blast radius is **more than half** of that count, run no tests locally. Push and let CI run,
     then fix failures as CI reports them.
4. Otherwise pick the test files that import a module in the blast radius (the same `grep`, run over
   `tests`), plus any test file you changed. Leave out everything else.
5. Never run more than **10** test files in one task. When step 4 picks more, keep the 10 closest to the
   change, in this order: test files you changed or added, then the tests of the modules you changed,
   then the tests of their importers. Leave the rest to CI.
6. Run only those files: `uv run pytest -q <file> [<file> ...]`. Narrow further with `-k` when one test
   covers the change.
7. In your report, list the files you ran and say the full suite is left to CI.

## Verification process
- No local run in this task was a bare `uv run pytest`, and none passed `tests/` as a whole.
- Every test file you ran imports a module in the blast radius, or is a test file you changed.
- No more than 10 test files ran in the task.
- When the blast radius was more than half the production modules, no tests ran locally and the report
  says CI covers them.

## Example output
Request: "Change how `model_meta/specs/bones.py` splits a bone name."

```
uv run pytest -q tests/test_bones.py tests/test_mesh_roles.py tests/test_armature_form.py \
  tests/test_spec_detail_screen.py
```
