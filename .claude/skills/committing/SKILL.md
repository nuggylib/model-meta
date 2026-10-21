---
name: committing
description: Use whenever you are about to create a git commit in this repo.
---

# Commit changes

## Trigger
Use this skill whenever you are about to create a git commit in this repo.

## Pre-requisites
- Staged or unstaged changes that the developer wants committed.
- The category of the change, picked from the list below. Derive it from the diff.

Categories:
- `feat`: new or changed behavior
- `fix`: a bug fix
- `docs`: documentation only, including `CLAUDE.md` and skills that only describe things
- `chore`: tooling, build, dependencies, housekeeping
- `refactor`: restructuring with no behavior change
- `test`: adding or changing tests only

## Steps
1. Review the changes with `git status` and `git diff`. Commit only what belongs to the current request.
2. Pick a category from the list.
   - If none fits, don't force one. Suggest a new category to the developer, with a one-line
     definition and the reason none of the existing ones fit.
   - If they accept it, add it to the Categories list in this file, then use it.
   - If they reject it, use whichever existing category they choose.
3. Write the message: `<category>: <summary>`.
   - ONE line, roughly 50-70 characters in total, including the prefix.
   - The prefix is the bare category followed by a colon. NEVER add anything else to it: no
     `(scope)`, no `!`, no ticket number. `feat(tui): ...` is wrong; `feat: ...` is right.
   - Imperative, lowercase summary, no trailing period.
   - No body, no bullets, no second `-m`.
4. Never credit an AI agent. No `Co-Authored-By`, `Generated with`, `Claude-Session:` trailer, badge,
   or mention of an agent anywhere in the message.
5. Commit with a plain `git commit -m "<message>"`. Never use a heredoc or `$(cat <<EOF ...)`.
6. Keep history linear:
   - Never create merge commits. Don't run `git merge` or `git pull` without `--rebase`.
   - To pick up new `main` commits, rebase: `git fetch origin main && git rebase origin/main`.
   - Fix up earlier commits with a new commit or a non-interactive rebase, not a merge.

## Verification process
- `git log -1 --format=%B` prints exactly one line.
- That line matches `^(feat|fix|docs|chore|refactor|test): ` (plus any accepted new categories),
  with no `(` before the colon.
- Its length is roughly 50-70 characters.
- It contains no agent attribution.
- `git log --merges origin/main..HEAD` prints nothing.

## Example output
Request: "Commit the new mesh role count field."

```
feat: add count field to mesh role spec and editor
```
