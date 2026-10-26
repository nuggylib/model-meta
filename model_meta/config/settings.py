"""The persisted settings shape and its schema version.

``SCHEMA_VERSION`` is written from the first save; bumping it is the anchor a
migration keys off of. All paths are stored as already-normalized absolute
strings (normalization happens at capture time, not here).

Schema history:

- **v1** — ``[models] directory`` held exactly *one* source-models path.
- **v2** — ``[models] directories`` is an array of them. Real projects keep
  models in several places (vehicles, props, characters), which v1 could not
  express. ``store.load`` upgrades a v1 file transparently; see
  ``model_meta/config/CLAUDE.md``.
"""

from dataclasses import dataclass
from pathlib import Path

from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.godot_connection import GodotConnection

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Settings:
    """The anchors first-time setup captures, plus the recorded Blender version.

    ``models_directories`` is a **tuple**, not a list: this dataclass is frozen,
    and a mutable field would undercut that. Order is user-meaningful — it is the
    order they were added in the wizard, and the order the dashboard lists them.
    """

    blender_executable: str
    blender_version: str
    models_directories: tuple[str, ...]
    godot_projects_root: str

    @property
    def blender(self) -> BlenderConnection:
        return BlenderConnection(Path(self.blender_executable))

    @property
    def godot(self) -> GodotConnection:
        return GodotConnection(Path(self.godot_projects_root))

    def to_toml_dict(self) -> dict:
        """Serialize to the nested mapping ``tomli_w`` writes to disk."""
        return {
            "schema_version": SCHEMA_VERSION,
            "blender": {
                "executable": self.blender_executable,
                "version": self.blender_version,
            },
            # A TOML array — handed to `tomli_w`, never hand-serialized
            # (escaping a list of Windows backslash paths is a corruption
            # footgun).
            "models": {"directories": list(self.models_directories)},
            "godot": {"projects_root": self.godot_projects_root},
        }
