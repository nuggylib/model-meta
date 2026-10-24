"""Spec operations on disk; the file I/O and validation live in `core.spec_file`."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from model_meta.core.spec_file import SpecFile
from model_meta.specs import naming, parenting

SPEC_GLOB = f"*{naming.SUFFIX}"


class SpecState(Enum):
    """What reading one spec file concluded."""

    OK = auto()
    UNREADABLE = auto()  # unparseable JSON, not an object, or an OSError
    MISMATCHED = auto()  # `model_type` disagrees with the filename stem


@dataclass(frozen=True)
class SpecEntry:
    """One spec on disk. `model_type` is the filename stem — the identity."""

    path: Path
    model_type: str
    state: SpecState


def create(specs_dir: Path, model_type: str) -> Path:
    """Write a new skeleton spec. Raises `FileExistsError` / `OSError`."""
    path = specs_dir / f"{model_type}{naming.SUFFIX}"
    SpecFile(path).create()
    return path


def read(path: Path) -> dict:
    """One spec document. Raises `OSError`, or `ValueError` for a malformed one."""
    return SpecFile(path).read()


def required_bones(document: dict) -> list[str]:
    """`armature.required_bones` of a document `read` returned."""
    return document.get("armature", {}).get("required_bones", [])


def bone_name_inverses(document: dict) -> dict[str, str]:
    """`armature.bone_name_inverses` of a document `read` returned."""
    return document.get("armature", {}).get("bone_name_inverses", {})


def parenting_map(document: dict) -> dict[str, list[str]]:
    """`armature.parenting` of a document `read` returned."""
    return document.get("armature", {}).get("parenting", {})


def armature_name(document: dict) -> str:
    """`armature.object_name` of a document `read` returned."""
    return document.get("armature", {}).get("object_name", "")


def mesh_roles(document: dict) -> dict[str, dict]:
    """`mesh_roles` of a document `read` returned."""
    return document.get("mesh_roles", {})


def update_armature(
    path: Path,
    *,
    add_bones: Iterable[str] = (),
    set_inverses: Mapping[str, str] | None = None,
    drop_inverses: Iterable[str] = (),
    object_name: str | None = None,
    add_parenting: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Re-read the spec and patch only the armature keys passed.

    Bones append in order, skipping ones already present. Drops apply before
    sets. `add_parenting` appends child patterns per key, deduped.
    `object_name` is left alone when `None`. Raises like `read`, or
    `OSError` on write.
    """
    with SpecFile(path).edit() as document:
        armature = document.setdefault("armature", {})
        if object_name is not None:
            armature["object_name"] = object_name
        bones = armature.setdefault("required_bones", [])
        for bone in add_bones:
            if bone not in bones:
                bones.append(bone)
        inverses = armature.setdefault("bone_name_inverses", {})
        for segment in drop_inverses:
            inverses.pop(segment, None)
        inverses.update(set_inverses or {})
        if add_parenting:
            armature["parenting"] = parenting.merge(
                armature.get("parenting", {}), add_parenting
            )


def rename_bone(
    path: Path,
    name: str,
    new_name: str,
    *,
    set_inverses: Mapping[str, str] | None = None,
) -> None:
    """Re-read the spec and rename one required bone in place, touching nothing else.

    `set_inverses` is applied to `bone_name_inverses`. Raises `ValueError` if
    `name` is gone or `new_name` is another required bone, or like `read`, or
    `OSError` on write.
    """
    with SpecFile(path).edit() as document:
        bones = required_bones(document)
        if name not in bones:
            raise ValueError(f"'{name}' is no longer a required bone.")
        if new_name != name and new_name in bones:
            raise ValueError(f"'{new_name}' is already required.")
        armature = document["armature"]
        armature["required_bones"] = [new_name if b == name else b for b in bones]
        armature.setdefault("bone_name_inverses", {}).update(set_inverses or {})


def delete_bone(path: Path, name: str) -> None:
    """Re-read the spec and remove one required bone, touching nothing else.

    Inverses, parenting and mesh roles are kept: their patterns simply stop
    matching it. Raises `ValueError` if `name` is gone, or like `read`, or
    `OSError` on write.
    """
    with SpecFile(path).edit() as document:
        bones = required_bones(document)
        if name not in bones:
            raise ValueError(f"'{name}' is no longer a required bone.")
        document["armature"]["required_bones"] = [b for b in bones if b != name]


def add_mesh_role(
    path: Path, name: str, vtx_grp: str, mesh_regex: str, count: int, weight: float
) -> None:
    """Re-read the spec and add one mesh role, touching nothing else.

    Raises `ValueError` if `name` is already a role, or like `read`, or
    `OSError` on write.
    """
    with SpecFile(path).edit() as document:
        roles = document.setdefault("mesh_roles", {})
        if name in roles:
            raise ValueError(f"'{name}' is already a mesh role.")
        roles[name] = {
            "mesh_regex": mesh_regex,
            "vtx_grp": vtx_grp,
            "count": count,
            "weight": weight,
        }


def update_mesh_role(
    path: Path,
    name: str,
    new_name: str,
    vtx_grp: str | None = None,
    *,
    mesh_regex: str | None = None,
    count: int | None = None,
    weight: float | None = None,
    texture_maps: Sequence[str] | None = None,
    material_slots: Sequence[str] | None = None,
) -> None:
    """Re-read the spec and rename and re-pattern one role, touching nothing else.

    The role keeps its position and its other fields; a field passed as `None`
    keeps its value, or its lack of one. An empty `material_slots` removes the
    key. Raises
    `ValueError` if `name` is gone or `new_name` is another role, or like
    `read`, or `OSError` on write.
    """
    with SpecFile(path).edit() as document:
        roles = mesh_roles(document)
        if name not in roles:
            raise ValueError(f"'{name}' is no longer a mesh role.")
        if new_name != name and new_name in roles:
            raise ValueError(f"'{new_name}' is already a mesh role.")
        changes = {
            key: value
            for key, value in (
                ("vtx_grp", vtx_grp),
                ("mesh_regex", mesh_regex),
                ("count", count),
                ("weight", weight),
                ("texture_maps", None if texture_maps is None else list(texture_maps)),
                ("material_slots", list(material_slots) if material_slots else None),
            )
            if value is not None
        }
        updated = {**roles[name], **changes}
        if material_slots is not None and not material_slots:
            updated.pop("material_slots", None)
        document["mesh_roles"] = {
            (new_name if key == name else key): (updated if key == name else role)
            for key, role in roles.items()
        }


def delete_mesh_role(path: Path, name: str) -> None:
    """Re-read the spec and remove one mesh role, touching nothing else.

    Raises `ValueError` if `name` is gone, or like `read`, or `OSError` on
    write.
    """
    with SpecFile(path).edit() as document:
        roles = mesh_roles(document)
        if name not in roles:
            raise ValueError(f"'{name}' is no longer a mesh role.")
        document["mesh_roles"] = {
            key: role for key, role in roles.items() if key != name
        }


def list_specs(specs_dir: Path) -> list[SpecEntry]:
    """Every spec in `specs_dir`, sorted by name. A missing dir is `[]`.

    Read-only: the directory is never created. Failures are caught **per file**
    so one malformed spec can never blank the list.
    """
    return [_read(path) for path in _spec_paths(specs_dir)]


def count(specs_dir: Path) -> int:
    """How many spec files there are, without parsing any of them.

    A single-directory glob — cheap enough for a dashboard card to call inline.
    """
    return len(_spec_paths(specs_dir))


# --- internals -------------------------------------------------------------


def _spec_paths(specs_dir: Path) -> list[Path]:
    """The spec files in `specs_dir`, sorted by stem. A missing dir is `[]`."""
    try:
        paths = [path for path in specs_dir.glob(SPEC_GLOB) if path.is_file()]
    except OSError:
        return []
    return sorted(paths, key=lambda path: path.stem)


def _read(path: Path) -> SpecEntry:
    """Classify one spec file. The stem is the identity either way."""
    model_type = path.stem
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return SpecEntry(path, model_type, SpecState.UNREADABLE)
    if not isinstance(raw, dict):
        # Valid JSON, wrong type — an array or a bare string is not a spec.
        return SpecEntry(path, model_type, SpecState.UNREADABLE)
    if raw.get("model_type") != model_type:
        return SpecEntry(path, model_type, SpecState.MISMATCHED)
    return SpecEntry(path, model_type, SpecState.OK)
