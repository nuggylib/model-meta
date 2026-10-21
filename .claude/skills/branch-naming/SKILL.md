# Name and create a new branch

## Trigger
Use this skill whenever you are about to create a new git branch in this repo.

## Pre-requisites
- `<developer_name>`: the lowercased first word of `git config user.name` (e.g. `Armando Vasquez` → `armando`).
  If `user.name` is unset, ask the developer.
- `<ticket_number>`: the ticket the work belongs to, exactly as the developer gives it. If they haven't
  given one, ask. Don't invent one.
- `<feature_or_task>`: a short kebab-case summary of the work (e.g. `mesh-role-count`). Derive it from
  the request.

## Steps
1. Gather the three values above.
2. Build the name: `<developer_name>/<ticket_number>/<feature_or_task>`.
   - Lowercase, kebab-case, no spaces.
   - Don't add a type prefix like `feat/`; the commit message carries the type.
3. Check the name isn't taken: `git branch -a --list "*<developer_name>/<ticket_number>/<feature_or_task>"`.
4. Create the branch off an up-to-date `main` unless the developer names another base:
   `git fetch origin main && git switch -c <branch_name> origin/main`.

## Verification process
- `git branch --show-current` prints the new name.
- The name has exactly three `/`-separated segments, and the first is `<developer_name>`.

## Example output
Request: "Add a mesh role count field, ticket 42."

```
armando/42/mesh-role-count
```
