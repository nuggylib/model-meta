# model_meta/config/

The app's persistence layer — the on-disk config that first-time setup writes and
every later launch reads. This is the first persistence category in the project.

## Files
- `settings.py` — the `Settings` frozen dataclass (the captured anchors plus the
  recorded Blender version) and `SCHEMA_VERSION`, the migration anchor written on
  every save. `models_directories` is a **tuple** (not a list): the dataclass is
  frozen, and a mutable field would undercut that. `to_toml_dict` converts it to
  a list so `tomli_w` writes a TOML array. The `blender` and `godot` properties
  build `core`'s `BlenderConnection` / `GodotConnection` from the stored strings; it only constructs, never
  stats or runs, and TOML stays on the strings.
- `paths.py` — `config_file()` resolves where the config lives: `$MODEL_META_CONFIG`
  wins (the test/injection seam), else the `platformdirs` per-user config dir.
  `specs_dir(config_path=None)` is `specs/` beside that file — derived from the
  config *path*, never its contents, so it resolves with an absent or corrupt
  config and needs no `$MODEL_META_SPECS` of its own. Spec files are
  addressed by this path convention, not by a stored setting, which is why
  they cost no schema bump.
- `store.py` — `load(path)` returns `(ABSENT | VALID | CORRUPT, Settings | None)` and
  never raises into the caller; `save(path, settings)` writes once, atomically
  (temp file + `os.replace`).
- `legacy_dir.py` — `migrate()` renames the pre-rename `blender-buddy` per-user
  config dir to `model-meta` (config + `specs/` move together). Called once at
  boot from `app.main()` (never `--check`, never inside `load`). Skipped under
  `$MODEL_META_CONFIG`, never merges or overwrites an existing `model-meta` dir,
  and swallows `OSError` so a failed move just falls back to first-run setup.

## Schema versions
- **v1** — `[models] directory`: exactly one source-models path.
- **v2** (current) — `[models] directories`: a non-empty array of them. A missing,
  empty, non-list, or non-string-entry `directories` is `CORRUPT` — a config with
  zero model directories is meaningless, so it is not quietly tolerated.

`load` accepts both. A **v1** file is upgraded in memory (its single directory
wrapped in a one-item tuple) and re-saved as v2, so existing users gain
multi-directory support with no re-setup. v1 is matched *before* the
unknown-version gate, which would otherwise reject every pre-v2 config; and a v1
file is itself validated first — a missing or non-string `[models] directory` is
`CORRUPT`, never a garbage one-entry migration. Any other version (0, 3, `"1"`, …)
stays `CORRUPT`.

### The sanctioned exception to load-is-read-only
`load` performs **exactly one** bounded, atomic write — the v1→v2 migration — and
no other mutation. It is best-effort: an `OSError` during that write is swallowed
and the upgraded `Settings` are still returned (unpersisted), because `load` must
never raise into the caller and an unwritable config is no reason to refuse to
boot. The write retries next launch, which is safe because the in-memory upgrade
is idempotent. Overwriting a *valid* v1 file this way is the intended upgrade, not
the corrupt-clobber the "never auto-overwrite" rule guards against, so it takes no
backup. Do not add further writes to `load`.

## Conventions
- **No Textual, no subprocess, no filesystem walking here.** This category produces
  and persists plain data; UI and I/O live in their own categories (`tui/`,
  `core/`). The wizard screen calls into this package, not vice versa.
- **Never auto-overwrite a CORRUPT config** — surface it and let the user choose to
  re-run setup (which overwrites deliberately).
- **Write-once-atomic only.** Never write the config incrementally; a half-written
  file that parses would read as "setup done" and boot the app broken.
- Stored paths are already-normalized absolute strings; normalization happens at
  capture time, not in this package.
