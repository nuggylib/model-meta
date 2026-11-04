# model_meta/core/

Core business logic shared across categories: typed documents and their JSON
storage, and connections to the external apps Model Meta validates against.
**No Textual, no UI.**

## Files
- `app_connection.py` — the `AppConnection` base, a frozen dataclass holding
  one `path`: the app's executable, or for Godot the projects root (each Godot
  project is its own executable, so the root stands for them all). `state()` is
  the template method: it expands `~`, returns `PathState.MISSING` when nothing
  is there, and otherwise asks the subclass's `_accepts(path)` hook, giving
  `OK` or `INVALID` (present, but not what the app needs). It only stats, so it
  is safe on the event loop; a hook must stat only too, never run or walk.
  Slow, app-specific work (a Blender probe) is a subclass method, not a base
  hook.
- `blender_connection.py` — `BlenderConnection(AppConnection)`; `path` is the
  executable. `_accepts` is platform-aware: Windows takes any regular file (no
  exec bit), macOS also takes a `.app` bundle (a directory), elsewhere it needs
  a file with the POSIX exec bit. `candidates()` returns existing installs at
  the standard per-platform locations plus `shutil.which("blender")`, deduped,
  first entry best (macOS resolves `Blender.app` to its inner binary, Windows
  globs `Blender Foundation\*`). flatpak/snap wrappers aren't plain executable
  paths, so they are out of scope. `probe(timeout)` runs `<path> --version` and
  returns a `ProbeResult` (`ProbeOutcome`: OK / NOT_FOUND / NOT_EXE / TIMEOUT /
  UNPARSEABLE, plus the version and a message). It blocks on a subprocess, so
  callers run it in a Textual worker; every failure is a `ProbeResult`, never a
  raise or a hang.
  `is_running(timeout)` reports whether any Blender process is running: `ps -A
  -o comm=` matched on the basename (so macOS's full path matches and
  `blender-thumbnailer` doesn't), or `tasklist` filtered to `blender.exe` on
  Windows. It never checks which file is open: `blender_bridge` does. It blocks on a subprocess, so callers run it
  in a Textual worker; a failed lookup is `False`, never a raise.
- `blender_bridge.py` — the client for the `model-meta-blender-addon`
  protocol (TCP `127.0.0.1:7417`, one JSON object per line, `"protocol": 1`).
  `subscribe_armatures(port, timeout)` is an async generator: it sends
  `get_filepath` and `subscribe_armatures` in one write, so the add-on answers
  both in the same tick and the path is the file the subscription is on. It
  yields `OpenFile(path)` (`None` for a never-saved file), then each pushed
  `Armatures(names)` (the add-on pushes on subscribe and after a save/load that
  changes the list), with `names` `None` for a `busy` error. When a save/load
  leaves Blender on another file, the add-on pushes the new path and ends the
  subscription; the client sends the pair again and yields the new
  `OpenFile`, so it stays subscribed across files. It never ends normally: an
  unreachable add-on, any other error
  line, a malformed message or a closed socket raises `BridgeError`. Pure
  asyncio streams, so it runs on the event loop with no thread.
- `godot_connection.py` — `GodotConnection(AppConnection)`; `path` is the
  projects root, and `_accepts` takes a directory. `find_projects(max_depth=4)`
  returns the absolute, sorted directories under it holding a `project.godot`.
  It walks the tree, so callers run it in a Textual worker. The walk is
  depth-capped and tolerates `OSError` per directory (an unlistable dir is
  skipped) and per entry (a `0o444` parent makes stat-ing a child raise; that
  child is skipped, its siblings kept). It never descends a symlinked
  directory (loop guard) or a project directory. Zero projects is a valid
  result, not an error. It only locates projects: indexing and `.blend`→`.glb`
  export tracking are future work here.
- `json_document.py` — JSON file mechanics and the `JsonDocument` base.
  `read_json` checks only that the file holds a JSON object. `write_json` replaces
  atomically (sibling `.tmp` + `os.replace`), so a crash leaves the old file.
  `create_json` opens with `"x"` (`O_EXCL`), so it raises `FileExistsError`
  rather than overwrite, and makes missing parent dirs.
  `JsonDocument` is a dataclass base with `path` (keyword-only, ignored by `==`).
  Subclasses supply `from_dict(data, *, path)`, raising `ValueError` for a
  malformed document, and `to_dict()`. `load()` is a classmethod; `save()` and
  `create()` re-parse `to_dict()` through `from_dict()` before touching disk, so
  a field set to the wrong type raises instead of being written.
- `spec.py` — the spec document: `Spec(JsonDocument)` holding `model_type`, an
  `Armature`, `mesh_roles: dict[str, MeshRole]` and `Modifiers`. `from_dict` carries every
  shape check and error message. `Spec.path_for(specs_dir, model_type)` raises
  `ValueError` unless `naming.validate` passes and the name is already
  normalized.
  - `MeshRole`: a `None` field was absent and is omitted on write; an empty
    `material_slots` is omitted too. Keys are written as `mesh_regex`,
    `vtx_grp`, `count`, `weight`, `texture_maps`, `material_slots`.
  - `Armature`: absent keys default (`""`, `[]`, `{}`) and are written on save.
  - `Modifiers`: `required` (a `RequiredModifiers`), `allowed`, `warn` and
    `fail`, all four always written in that order. Lists default to `[]`,
    except `required.skinned_meshes`, which defaults to `["ARMATURE"]` **only
    when the key is missing** (or `required` / `modifiers` is): a `[]` that is
    present stays `[]`. Shape checks only: the vocabulary isn't enforced.
  - `Spec`: a missing `model_type` stays missing; `armature`, `mesh_roles` and
    `modifiers` are always written.

- `results.py` — `Results(JsonDocument)`, one model's results file:
  `model_file` (the model's absolute path) and `spec` (the spec's
  `model_type`), both required strings, then one check result per spec root
  field: `armature` (`True` passed, `False` failed). A `None` check was never
  run and is omitted on write; a present one must be a boolean. It is the
  source of truth for the dashboard's icons: a new check is a field here.
  `Results.path_for(results_dir,
  model_file)` names it `<model stem>-<8-hex sha1 of the path>.json`, so
  same-named models in different directories get separate files.

## Conventions
- **Every level keeps an `extra` dict** of keys the model doesn't know, written
  back after the known ones. A hand-added or experimental field survives a
  round trip.
- **Load right before changing, then save.** Callers hold a `Spec` only for the
  length of one change. Screens never keep one to save later: a hand edit made
  in between would be overwritten.
- The first save of an older or hand-written spec reorders its keys and adds any
  missing `armature` / `mesh_roles` / `modifiers` keys.
- A new on-disk document is another `JsonDocument` subclass here.
