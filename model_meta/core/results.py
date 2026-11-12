from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from model_meta.core.json_document import JsonDocument

_RESULTS_KEYS = (
    "model_file",
    "spec",
    "armature",
    "mesh_roles",
    "modifiers",
    "texture_map_overrides",
)


@dataclass(frozen=True)
class FieldCheck:
    """One spec field's check: a dict of facts per failure. A `warning` check's failures
    are warnings. `duplicates` groups same-shape meshes, for `texture_maps`."""

    failures: list[dict[str, object]]
    warning: bool = False
    duplicates: list[list[str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where` for a malformed check."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        passed, failures = data.get("passed"), data.get("failures")
        warning = data.get("warning", False)
        duplicates = data.get("duplicates", [])
        if not isinstance(passed, bool):
            raise ValueError(f"`{where}.passed` is not a boolean.")
        if not isinstance(failures, list) or not all(
            isinstance(failure, dict) for failure in failures
        ):
            raise ValueError(f"`{where}.failures` is not a list of objects.")
        if passed is bool(failures):
            raise ValueError(f"`{where}.passed` disagrees with its failures.")
        if not isinstance(warning, bool):
            raise ValueError(f"`{where}.warning` is not a boolean.")
        if not isinstance(duplicates, list) or not all(
            isinstance(group, list) and all(isinstance(name, str) for name in group)
            for group in duplicates
        ):
            raise ValueError(f"`{where}.duplicates` is not a list of name lists.")
        return cls(failures, warning, duplicates)

    def to_dict(self) -> dict:
        warning = {"warning": True} if self.warning else {}
        duplicates = {"duplicates": self.duplicates} if self.duplicates else {}
        return {
            "passed": self.passed,
            "failures": self.failures,
            **warning,
            **duplicates,
        }


@dataclass(frozen=True)
class ModifiersResult:
    """`required` holds one check per `modifiers.required` list, like `skinned_meshes`."""

    required: dict[str, FieldCheck]
    warn: FieldCheck
    fail: FieldCheck

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where`."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        required = data.get("required")
        if not isinstance(required, dict):
            raise ValueError(f"`{where}.required` is not an object.")
        return cls(
            {
                key: FieldCheck.from_dict(check, where=f"{where}.required.{key}")
                for key, check in required.items()
            },
            FieldCheck.from_dict(data.get("warn"), where=f"{where}.warn"),
            FieldCheck.from_dict(data.get("fail"), where=f"{where}.fail"),
        )

    def to_dict(self) -> dict:
        return {
            "required": {key: check.to_dict() for key, check in self.required.items()},
            "warn": self.warn.to_dict(),
            "fail": self.fail.to_dict(),
        }


@dataclass(frozen=True)
class MeshRoleResult:
    """`meshes` are the names `mesh_regex` matched; `checks` holds only the role's set
    fields. `modifiers` checks just those meshes, and is `None` until it has run."""

    meshes: list[str]
    checks: dict[str, FieldCheck]
    modifiers: ModifiersResult | None = None

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Every key but `meshes` and `modifiers` is a field's check. Raises `ValueError`
        naming `where`."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        meshes = data.get("meshes")
        if not isinstance(meshes, list) or not all(
            isinstance(name, str) for name in meshes
        ):
            raise ValueError(f"`{where}.meshes` is not a list of strings.")
        checks = {
            field: FieldCheck.from_dict(check, where=f"{where}.{field}")
            for field, check in data.items()
            if field not in ("meshes", "modifiers")
        }
        modifiers = None
        if "modifiers" in data:
            modifiers = ModifiersResult.from_dict(
                data["modifiers"], where=f"{where}.modifiers"
            )
        return cls(meshes, checks, modifiers)

    def to_dict(self) -> dict:
        checks = {field: check.to_dict() for field, check in self.checks.items()}
        modifiers = (
            {} if self.modifiers is None else {"modifiers": self.modifiers.to_dict()}
        )
        return {"meshes": self.meshes, **checks, **modifiers}


@dataclass(frozen=True)
class TextureMapOverride:
    """`meshes` share `name` in place of their own name for `maps`."""

    name: str
    maps: list[str]
    meshes: list[str]

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where`."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"`{where}.name` is not a non-empty string.")
        lists = {key: data.get(key) for key in ("maps", "meshes")}
        for key, value in lists.items():
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"`{where}.{key}` is not a list of strings.")
        return cls(name, lists["maps"], lists["meshes"])

    def to_dict(self) -> dict:
        return {"name": self.name, "maps": self.maps, "meshes": self.meshes}


@dataclass
class Results(JsonDocument):
    """A `None` check was never run and is omitted on write. `texture_map_overrides`
    is the user's, by role name, and is omitted while empty."""

    model_file: str
    spec: str
    armature: bool | None = None
    mesh_roles: dict[str, MeshRoleResult] | None = None
    modifiers: ModifiersResult | None = None
    texture_map_overrides: dict[str, list[TextureMapOverride]] = field(
        default_factory=dict
    )
    extra: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def path_for(results_dir: Path, model_file: Path) -> Path:
        """Pass `model_file` absolute."""
        # The hash keeps same-named models in different directories apart.
        digest = hashlib.sha1(str(model_file).encode("utf-8")).hexdigest()[:8]
        return results_dir / f"{model_file.stem}-{digest}.json"

    @classmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        model_file = data.get("model_file")
        if not isinstance(model_file, str):
            raise ValueError("`model_file` is not a string.")
        spec = data.get("spec")
        if not isinstance(spec, str):
            raise ValueError("`spec` is not a string.")
        armature = data.get("armature")
        if "armature" in data and not isinstance(armature, bool):
            raise ValueError("`armature` is not a boolean.")
        roles = data.get("mesh_roles")
        if "mesh_roles" in data and not isinstance(roles, dict):
            raise ValueError("`mesh_roles` is not an object.")
        mesh_roles = None
        if roles is not None:
            mesh_roles = {
                name: MeshRoleResult.from_dict(role, where=f"mesh_roles.{name}")
                for name, role in roles.items()
            }
        modifiers = None
        if "modifiers" in data:
            modifiers = ModifiersResult.from_dict(data["modifiers"], where="modifiers")
        extra = {key: value for key, value in data.items() if key not in _RESULTS_KEYS}
        return cls(
            model_file=model_file,
            spec=spec,
            armature=armature,
            mesh_roles=mesh_roles,
            modifiers=modifiers,
            texture_map_overrides=_overrides(data.get("texture_map_overrides", {})),
            extra=extra,
            path=path,
        )

    def to_dict(self) -> dict:
        known = {
            "armature": self.armature,
            "mesh_roles": None
            if self.mesh_roles is None
            else {name: role.to_dict() for name, role in self.mesh_roles.items()},
            "modifiers": None if self.modifiers is None else self.modifiers.to_dict(),
            "texture_map_overrides": {
                role: [override.to_dict() for override in overrides]
                for role, overrides in self.texture_map_overrides.items()
            }
            or None,
        }
        checks = {key: value for key, value in known.items() if value is not None}
        return {
            "model_file": self.model_file,
            "spec": self.spec,
            **checks,
            **self.extra,
        }


def _overrides(data: object) -> dict[str, list[TextureMapOverride]]:
    where = "texture_map_overrides"
    if not isinstance(data, dict):
        raise ValueError(f"`{where}` is not an object.")
    overrides = {}
    for role, items in data.items():
        if not isinstance(items, list):
            raise ValueError(f"`{where}.{role}` is not a list.")
        overrides[role] = [
            TextureMapOverride.from_dict(item, where=f"{where}.{role}[{index}]")
            for index, item in enumerate(items)
        ]
    return overrides
