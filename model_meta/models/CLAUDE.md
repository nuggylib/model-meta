# model_meta/models/

Source-model discovery: finding the `.blend` files behind the configured models
directories. This category only *locates* models — reading what is inside one
(meshes, armatures, vertex groups) needs Blender itself and belongs to the
`blender` category's still-stubbed scene connection. No Textual, no UI.

## Contents
- `discovery.py` — `find_blend_files(directory, max_depth=DEFAULT_MAX_DEPTH)`,
  a bounded, permission-tolerant, symlink-guarded walk returning sorted absolute
  paths. `DEFAULT_MAX_DEPTH` is exported so the UI can tell the user where the
  scan stopped looking instead of hard-coding a number that would drift.
  `relative_label(model, root)` is a found model's path relative to its
  directory (just its name when a symlinked root puts it outside), shared by
  the Models screen rows and the dashboard's Model Directories tabs.

## Conventions
- **Mirrors `GodotConnection.find_projects` (`core/godot_connection.py`).** Same shape and same guarantees — bounded by
  depth, a directory we can't list is skipped rather than fatal, symlinked
  directories are never descended (no loops), results sorted for deterministic
  display, zero results a valid outcome. Read that module alongside this one;
  they are deliberately the same scan with a different predicate.
- **One deliberate divergence: the root's listing is unguarded.** An unreadable
  `directory` *raises* instead of returning `[]`, because the caller has to tell
  "I could not read this" from "there is nothing here" — different problems with
  different fixes, and the Models screen renders them as different states.
  Descendant failures are still swallowed. A *missing* directory is the caller's
  to check cheaply with `is_dir()` before scanning.
- **`.blend1` is not a model.** Blender writes `foo.blend1`, then `foo.blend2`,
  next to `foo.blend` on every save, so a `*.blend*` match reports each model
  two or three times. The test is an exact suffix match, case-insensitive
  (`.BLEND` is real). If a new file type is ever recognized, keep the match
  exact for the same reason.
- A symlink *to* a `.blend` is kept — sharing one model across directories is
  legitimate, and a linked file can't loop the walk the way a linked directory
  can. A broken symlink fails `is_file()` and drops out on its own.
- Call it from a Textual `@work` worker via `asyncio.to_thread`; it walks the
  filesystem and must not run on the event loop.
