"""Resolve where the config file lives.

``$MODEL_META_CONFIG`` (a full file path) overrides the per-user location.
This is the seam tests use so they never touch the developer's real
``platformdirs`` config directory.
"""

import os
from pathlib import Path

from platformdirs import user_config_path

APP_NAME = "model-meta"
APP_AUTHOR = "mcnuggies"
SPECS_DIRNAME = "specs"
RESULTS_DIRNAME = "results"


def config_file() -> Path:
    """Return the config file path.

    Honors ``$MODEL_META_CONFIG`` if set; otherwise falls back to the
    platform's per-user config directory (macOS ``~/Library/Application
    Support/…``, Linux ``~/.config/…``, Windows ``%LOCALAPPDATA%\\…``).
    """
    override = os.environ.get("MODEL_META_CONFIG")
    if override:
        return Path(override).expanduser()
    return user_config_path(APP_NAME, APP_AUTHOR) / "config.toml"


def specs_dir(config_path: Path | None = None) -> Path:
    """The ``specs/`` folder beside the config file.

    Derived from the config *path*, not its contents, so it resolves even when
    the config is absent or corrupt — and ``$MODEL_META_CONFIG`` carries over
    for free, with no sibling override to set.
    """
    return (config_path or config_file()).parent / SPECS_DIRNAME


def results_dir(config_path: Path | None = None) -> Path:
    """The ``results/`` folder beside ``specs/``, resolved the same way."""
    return (config_path or config_file()).parent / RESULTS_DIRNAME
