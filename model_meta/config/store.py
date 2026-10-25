"""Load and save the config file.

``load`` never raises into the caller: it maps every failure to a state so boot
routing can decide (run wizard / boot dashboard / show recovery notice). ``save``
writes once, atomically, so a crash mid-write can never leave a half-written file
that later reads as "setup is done".

``load`` also performs the one-time v1→v2 schema migration — the single
sanctioned exception to this layer being read-only on load (see the category's
``CLAUDE.md``).
"""

import os
import tomllib
from pathlib import Path

import tomli_w

from model_meta.config.settings import SCHEMA_VERSION, Settings

# load() outcomes.
ABSENT = "absent"
VALID = "valid"
CORRUPT = "corrupt"

# Required (table, key) pairs every schema version shares. The models key is
# version-specific (v1 `directory` scalar, v2 `directories` array) and is
# validated per-version below.
REQUIRED_SHARED = (
    ("blender", "executable"),
    ("godot", "projects_root"),
)


def load(path: Path) -> tuple[str, Settings | None]:
    """Read the config, returning ``(state, settings)``.

    - ``(ABSENT, None)``  — no file yet; run first-time setup.
    - ``(VALID, Settings)`` — parses, known ``schema_version``, all keys present.
      A **v1** file is upgraded to v2 in memory and re-saved (see
      ``_migrate_v1``); any other known-good version is returned as-is.
    - ``(CORRUPT, None)`` — unreadable, unknown version, or missing/mistyped
      keys; the caller shows a recovery notice and never auto-overwrites.
    """
    try:
        with path.open("rb") as f:  # binary mode required by tomllib
            raw = tomllib.load(f)
    except FileNotFoundError:
        return ABSENT, None
    except (tomllib.TOMLDecodeError, OSError):
        return CORRUPT, None
    return _classify(path, raw)


def _classify(path: Path, raw: dict) -> tuple[str, Settings | None]:
    if not _shared_keys_present(raw):
        return CORRUPT, None

    version = raw.get("schema_version")
    # v1 must be intercepted *before* the unknown-version gate below, which
    # would otherwise reject every pre-v2 config outright.
    if version == 1:
        return _migrate_v1(path, raw)
    if version == SCHEMA_VERSION:
        directories = raw["models"].get("directories")
        if not _is_directory_list(directories):
            # Missing, empty, non-list, or non-string entries. An empty list is
            # corrupt on purpose: a config with zero model dirs is meaningless.
            return CORRUPT, None
        return VALID, _settings(raw, tuple(directories))
    return CORRUPT, None  # unknown or future version — never auto-overwritten


def save(path: Path, settings: Settings) -> None:
    """Write the config once, atomically.

    Creates the parent directory, writes to a temp file in the same directory,
    then ``os.replace`` (atomic on POSIX and Windows). On failure nothing is
    replaced, so no partial config is left behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:  # binary mode required by tomli_w
        tomli_w.dump(settings.to_toml_dict(), f)
    os.replace(tmp, path)


# --- internals -------------------------------------------------------------


def _shared_keys_present(raw: dict) -> bool:
    """Whether the tables common to every schema version are well-formed.

    Also requires a `[models]` table, so the per-version models checks can index
    it without re-testing its shape.
    """
    if not isinstance(raw.get("models"), dict):
        return False
    return all(
        isinstance(raw.get(table), dict) and key in raw[table]
        for table, key in REQUIRED_SHARED
    )


def _is_directory_list(value: object) -> bool:
    """Whether `value` is a usable v2 `directories` array: non-empty, all strings."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(entry, str) for entry in value)
    )


def _settings(raw: dict, directories: tuple[str, ...]) -> Settings:
    """Build `Settings` from already-validated raw tables."""
    return Settings(
        blender_executable=raw["blender"]["executable"],
        blender_version=raw["blender"].get("version", ""),
        models_directories=directories,
        godot_projects_root=raw["godot"]["projects_root"],
    )


def _migrate_v1(path: Path, raw: dict) -> tuple[str, Settings | None]:
    """Upgrade a v1 config to v2: wrap its single models dir in a one-item tuple.

    A v1 file can itself be invalid, so its required shape is checked first — a
    missing or non-string ``[models] directory`` is ``CORRUPT``, never a garbage
    one-entry migration.
    """
    directory = raw["models"].get("directory")
    if not isinstance(directory, str):
        return CORRUPT, None
    settings = _settings(raw, (directory,))
    _try_migrate_write(path, settings)
    return VALID, settings


def _try_migrate_write(path: Path, settings: Settings) -> None:
    """Persist an upgrade, best-effort, so it happens once and not every launch.

    ``load`` must never raise into the caller, and an unwritable config is no
    reason to refuse to boot: on failure the upgraded settings are still
    returned in memory (unpersisted) and the write retries next launch. That is
    safe because the in-memory upgrade is idempotent.

    Overwriting a *valid* v1 file here is the intended upgrade, not the
    corrupt-clobber the "never auto-overwrite" rule guards against, so it needs
    no backup.
    """
    try:
        save(path, settings)
    except OSError:
        pass
