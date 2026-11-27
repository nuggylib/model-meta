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
    are warnings."""

    failures: list[dict[str, object]]
    warning: bool = False

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
        return cls(failures, warning)

    def to_dict(self) -> dict:
        warning = {"warning": True} if self.warning else {}
        return {"passed": self.passed, "failures": self.failures, **warning}


@dataclass(frozen=True)
class TextureMapsCheck(FieldCheck):
    """`duplicates` groups same-shape meshes and doesn't affect `passed`."""

    duplicates: list[list[str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where` for a malformed check."""
        check = FieldCheck.from_dict(data, where=where)
        duplicates = data.get("duplicates", [])
        if not isinstance(duplicates, list) or not all(
            _is_str_list(group) for group in duplicates
        ):
            raise ValueError(f"`{where}.duplicates` is not a list of name lists.")
        return cls(check.failures, check.warning, duplicates)

    def to_dict(self) -> dict:
        duplicates = {"duplicates": self.duplicates} if self.duplicates else {}
        return {**super().to_dict(), **duplicates}


@dataclass(frozen=True)
class UvUnwrapCheck(FieldCheck):
    """`warnings` holds a dict of facts per mesh still on a default UV map, and doesn't
    affect `passed`."""

    warnings: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where` for a malformed check."""
        check = FieldCheck.from_dict(data, where=where)
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list) or not all(
            isinstance(warning, dict) for warning in warnings
        ):
            raise ValueError(f"`{where}.warnings` is not a list of objects.")
        return cls(check.failures, check.warning, warnings)

    def to_dict(self) -> dict:
        return {**super().to_dict(), "warnings": self.warnings}


@dataclass(frozen=True)
class ArmatureResult:
    """In an armature that exists, a missing bone is only in `missing_bones`:
    the add-on can't report a parent for it. A missing armature fails every
    parenting rule, so each child is in both."""

    object_name: str
    exists: bool
    missing_bones: list[str] = field(default_factory=list)
    missing_parenting_rules: dict[str, list[str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            self.exists and not self.missing_bones and not self.missing_parenting_rules
        )

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where`."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        object_name, exists = data.get("object_name"), data.get("exists")
        bones, rules = data.get("missing_bones"), data.get("missing_parenting_rules")
        if not isinstance(object_name, str):
            raise ValueError(f"`{where}.object_name` is not a string.")
        if not isinstance(exists, bool):
            raise ValueError(f"`{where}.exists` is not a boolean.")
        if not _is_str_list(bones):
            raise ValueError(f"`{where}.missing_bones` is not a list of strings.")
        if not isinstance(rules, dict) or not all(
            _is_str_list(children) for children in rules.values()
        ):
            raise ValueError(
                f"`{where}.missing_parenting_rules` is not a map of string lists."
            )
        return cls(object_name, exists, bones, rules)

    def to_dict(self) -> dict:
        return {
            "object_name": self.object_name,
            "exists": self.exists,
            "missing_bones": self.missing_bones,
            "missing_parenting_rules": self.missing_parenting_rules,
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
    """`meshes` are the names `mesh_regex` matched. A `None` check's field isn't set in
    the role's spec, and `uv_unwrap` is `None` when `texture_maps` isn't; `modifiers`
    is `None` until it has run."""

    meshes: list[str]
    count: FieldCheck | None = None
    vtx_grp: FieldCheck | None = None
    weight: FieldCheck | None = None
    texture_maps: TextureMapsCheck | None = None
    uv_unwrap: UvUnwrapCheck | None = None
    material_slots: FieldCheck | None = None
    modifiers: ModifiersResult | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def checks(self) -> dict[str, FieldCheck]:
        """The set fields' checks, in spec order."""
        return {
            key: check
            for key in _ROLE_CHECKS
            if (check := getattr(self, key)) is not None
        }

    @classmethod
    def from_dict(cls, data: object, *, where: str) -> Self:
        """Raises `ValueError` naming `where`."""
        if not isinstance(data, dict):
            raise ValueError(f"`{where}` is not an object.")
        meshes = data.get("meshes")
        if not _is_str_list(meshes):
            raise ValueError(f"`{where}.meshes` is not a list of strings.")
        checks = {
            key: check_type.from_dict(data[key], where=f"{where}.{key}")
            for key, check_type in _ROLE_CHECKS.items()
            if key in data
        }
        modifiers = None
        if "modifiers" in data:
            modifiers = ModifiersResult.from_dict(
                data["modifiers"], where=f"{where}.modifiers"
            )
        extra = {key: value for key, value in data.items() if key not in _ROLE_KEYS}
        return cls(meshes, **checks, modifiers=modifiers, extra=extra)

    def to_dict(self) -> dict:
        checks = {key: check.to_dict() for key, check in self.checks.items()}
        modifiers = (
            {} if self.modifiers is None else {"modifiers": self.modifiers.to_dict()}
        )
        return {"meshes": self.meshes, **checks, **modifiers, **self.extra}


_ROLE_CHECKS: dict[str, type[FieldCheck]] = {
    "count": FieldCheck,
    "vtx_grp": FieldCheck,
    "weight": FieldCheck,
    "texture_maps": TextureMapsCheck,
    "uv_unwrap": UvUnwrapCheck,
    "material_slots": FieldCheck,
}
_ROLE_KEYS = ("meshes", *_ROLE_CHECKS, "modifiers")

MeshRolesResult = dict[str, MeshRoleResult]


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
    model_file: str
    spec: str | None
    armature: ArmatureResult | None = None
    mesh_roles: MeshRolesResult | None = None
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

    def unlinked(self) -> Self:
        return type(self)(
            model_file=self.model_file,
            spec=None,
            texture_map_overrides=self.texture_map_overrides,
            path=self.path,
        )

    @classmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        model_file = data.get("model_file")
        if not isinstance(model_file, str):
            raise ValueError("`model_file` is not a string.")
        spec = data.get("spec")
        if "spec" in data and not isinstance(spec, str):
            raise ValueError("`spec` is not a string.")
        armature = None
        if "armature" in data:
            armature = ArmatureResult.from_dict(data["armature"], where="armature")
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
            "spec": self.spec,
            "armature": None if self.armature is None else self.armature.to_dict(),
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
        present = {key: value for key, value in known.items() if value is not None}
        return {
            "model_file": self.model_file,
            **present,
            **self.extra,
        }


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


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
