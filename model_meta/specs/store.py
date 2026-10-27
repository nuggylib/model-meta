"""Spec operations on disk; the file I/O and validation live in `core.spec`."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from model_meta.core.spec import MeshRole, Modifiers, Spec
from model_meta.specs import naming, parenting, schema

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


@dataclass(frozen=True)
class ArmaturePatch:
    """Bones append deduped, drops apply before sets, `object_name=None` keeps it."""

    add_bones: Sequence[str] = ()
    set_inverses: Mapping[str, str] = field(default_factory=dict)
    drop_inverses: Sequence[str] = ()
    object_name: str | None = None
    add_parenting: Mapping[str, Sequence[str]] = field(default_factory=dict)


def create(specs_dir: Path, model_type: str) -> Path:
    """Write a new skeleton spec. Raises `FileExistsError` / `OSError`."""
    path = Spec.path_for(specs_dir, model_type)
    Spec.from_dict(schema.skeleton(model_type), path=path).create()
    return path


def update_armature(path: Path, patch: ArmaturePatch) -> None:
    """Raises like `Spec.load`, or `OSError` on write."""
    spec = Spec.load(path)
    armature = spec.armature
    if patch.object_name is not None:
        armature.object_name = patch.object_name
    for bone in patch.add_bones:
        if bone not in armature.required_bones:
            armature.required_bones.append(bone)
    for segment in patch.drop_inverses:
        armature.bone_name_inverses.pop(segment, None)
    armature.bone_name_inverses.update(patch.set_inverses)
    if patch.add_parenting:
        armature.parenting = parenting.merge(armature.parenting, patch.add_parenting)
    spec.save()


def rename_bone(
    path: Path,
    name: str,
    new_name: str,
    *,
    set_inverses: Mapping[str, str] | None = None,
) -> None:
    """Raises `ValueError` if `name` is gone or `new_name` is another required bone,
    or like `Spec.load`, or `OSError` on write."""
    spec = Spec.load(path)
    armature = spec.armature
    if name not in armature.required_bones:
        raise ValueError(f"'{name}' is no longer a required bone.")
    if new_name != name and new_name in armature.required_bones:
        raise ValueError(f"'{new_name}' is already required.")
    armature.required_bones = [
        new_name if b == name else b for b in armature.required_bones
    ]
    armature.bone_name_inverses.update(set_inverses or {})
    spec.save()


def delete_bone(path: Path, name: str) -> None:
    """Inverses, parenting and mesh roles are kept: their patterns simply stop
    matching it. Raises `ValueError` if `name` is gone, or like `Spec.load`, or
    `OSError` on write."""
    spec = Spec.load(path)
    if name not in spec.armature.required_bones:
        raise ValueError(f"'{name}' is no longer a required bone.")
    spec.armature.required_bones.remove(name)
    spec.save()


def add_mesh_role(path: Path, name: str, role: MeshRole) -> None:
    """Raises `ValueError` if `name` is already a role, or like `Spec.load`, or
    `OSError` on write."""
    spec = Spec.load(path)
    if name in spec.mesh_roles:
        raise ValueError(f"'{name}' is already a mesh role.")
    spec.mesh_roles[name] = role
    spec.save()


def update_mesh_role(
    path: Path, name: str, new_name: str, edit: Callable[[MeshRole], MeshRole]
) -> None:
    """`edit` gets the role as just read, and the role keeps its position.

    Raises `ValueError` if `name` is gone or `new_name` is another role, or like
    `Spec.load`, or `OSError` on write.
    """
    spec = Spec.load(path)
    roles = spec.mesh_roles
    if name not in roles:
        raise ValueError(f"'{name}' is no longer a mesh role.")
    if new_name != name and new_name in roles:
        raise ValueError(f"'{new_name}' is already a mesh role.")
    updated = edit(roles[name])
    spec.mesh_roles = {
        (new_name if key == name else key): (updated if key == name else role)
        for key, role in roles.items()
    }
    spec.save()


def delete_mesh_role(path: Path, name: str) -> None:
    """Raises `ValueError` if `name` is gone, or like `Spec.load`, or `OSError`
    on write."""
    spec = Spec.load(path)
    if name not in spec.mesh_roles:
        raise ValueError(f"'{name}' is no longer a mesh role.")
    del spec.mesh_roles[name]
    spec.save()


def update_modifiers(path: Path, edit: Callable[[Modifiers], Modifiers]) -> None:
    """`edit` gets the modifiers as just read. Raises like `Spec.load`, or
    `OSError` on write."""
    spec = Spec.load(path)
    spec.modifiers = edit(spec.modifiers)
    spec.save()


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
