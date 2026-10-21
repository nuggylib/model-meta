# Model Meta

Model Meta is a Python-based TUI for creating Godot-compatible 3D model specs and validating the
currently-open modeling scene against them. Blender is the only supported modeling tool today; Godot
is the focus, so the app is not named after Blender.

## Skills
* Before writing a new skill, read `.claude/skills/skill-writing/SKILL.md`

## Project Structure

Although Python does not enforce any sort of hard-and-fast project structure, this project uses a
**flat layout**: all application code lives in the `model_meta/` package directory at the repository
root (not under a `src/` directory). The `model_meta/` directory _is_ Model Meta — everything in
it is packaged together into the published, downloadable Model Meta binary.

The repository root also holds `model-meta.spec`, the committed PyInstaller build definition (see the
README's "Building a standalone binary"). It is build tooling, not application code — packaging happens
_from_ it, but it is not part of the shipped package.

### Code Organization & Documentation Conventions

1. **Separate code by category within `model_meta/`.** Group source files into meaningful category
   subpackages (by domain, feature, or responsibility) rather than placing everything at the top
   level of `model_meta/`. When adding new code, put it in the directory that matches its purpose,
   and create a new category directory when none fits.
2. **Write a `CLAUDE.md` whenever a new directory is created** — whether it is a direct child of
   `model_meta/` or nested any number of levels below it. Each new directory gets its own
   `CLAUDE.md` describing what the directory holds and any conventions specific to it.
3. **Keep `CLAUDE.md` files current as the project evolves.** When a directory's contents change
   meaningfully (new files, changed responsibilities, new patterns), make a genuine attempt to update
   that directory's `CLAUDE.md` so the documentation stays accurate.

### Code Conventions

#### Comments and docstrings

Default: **none**. The assumed reader knows Python, Textual, and this codebase, including every
directory's `CLAUDE.md`. Write one only when that reader would still be stuck. This applies equally
to `#` comments, function and class docstrings, and module docstrings, and takes precedence over any
global comment skill.

**Keep:**
- A reason that isn't visible in the code: an outside constraint, an order that matters, a library
  quirk, a deliberate deviation.
  ```python
  # "x" is O_EXCL: a replace would overwrite the file this exists to protect.
  with path.open("x", encoding="utf-8") as f:
  ```
  ```python
  if not isinstance(count, int) or isinstance(count, bool):  # bool is an int
  ```
- A one-line docstring for a contract the signature can't show: what it raises, what the caller
  must do first ("Pass it trimmed."), what `None` means.

**Cut:**
- What a line does, or a name restated in prose.
- Narration of UI flow or behavior the directory's `CLAUDE.md` already covers.
- Multi-paragraph module docstrings. Use one line, or nothing.
- `Args:`/`Returns:` sections that repeat type hints.
- Dates and authors.
- New section banners. The existing `# -- name ---` dividers in `tui/screens/` can stay, but don't
  add banners of any other kind.

**Existing code:** older comments and docstrings were written before these rules, so don't copy
their length. Trim one only when you're already editing that code. Don't do standalone cleanups.

**Check** each comment or docstring with two questions:
1. Would a senior dev who knows this repo be stuck without it? If not, delete it.
2. Does it refer to something that isn't in the repo, like a conversation, plan, review, or ticket?
   If so, replace the comment with a link or reference to that source so there's a breadcrumb trail.

### Feature Development Practices

Keep PRs as small as possible by ensuring each branch is purpose-built for a specific sub-task of a feature.

## General Workflow

> This workflow is intended to fast-track development of many similar models that leverage a similar
> setup. For example, a game with a range of standard vehicles will need a model for each car, but
> each model will have the same core components. That being said, this tool CAN benefit one-off model
> development as well as the checklist is intended to be very comprehensive.

1. User builds a base model in Blender
2. User starts up Model Meta
3. User selects (or creates) the spec to use
4. Model Meta opens a connection to active Blender scene
5. Model Meta shows a live dashboard with simple display of validation results
6. User can select a category to see full details
7. Each full-details page has steps at the bottom for how to fix the issues that can occur
8. As the user makes changes, validation results live-update
