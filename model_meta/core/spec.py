from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from model_meta.core.json_document import JsonDocument
from model_meta.specs import naming

_SPEC_KEYS = ("model_type", "armature", "mesh_roles", "modifiers")
_ARMATURE_KEYS = ("object_name", "required_bones", "bone_name_inverses", "parenting")
_MODIFIERS_KEYS = ("required", "allowed", "warn", "fail")
_REQUIRED_KEYS = ("skinned_meshes",)
_ROLE_KEYS = (
    "mesh_regex",
    "vtx_grp",
    "count",
    "weight",
    "texture_maps",
    "material_slots",
)


@dataclass
class MeshRole:
    vtx_grp: str | None = None
    mesh_regex: str | None = None
    count: int | None = None
    weight: float | None = None
    texture_maps: list[str] | None = None
    material_slots: list[str] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Raises `ValueError` for a malformed role. `None` fields were absent."""
        if not isinstance(data, dict):
            raise ValueError("`mesh_roles` is not a map of objects.")
        return cls(
            vtx_grp=_role_str(data, "vtx_grp"),
            mesh_regex=_role_str(data, "mesh_regex"),
            count=_role_count(data),
            weight=_role_weight(data),
            texture_maps=_role_str_list(data, "texture_maps"),
            material_slots=_role_str_list(data, "material_slots") or [],
            extra=_extra(data, _ROLE_KEYS),
        )

    def to_dict(self) -> dict:
        known = {
            "mesh_regex": self.mesh_regex,
            "vtx_grp": self.vtx_grp,
            "count": self.count,
            "weight": self.weight,
            "texture_maps": self.texture_maps,
            "material_slots": self.material_slots or None,
        }
        present = {key: value for key, value in known.items() if value is not None}
        return {**present, **self.extra}


@dataclass
class Armature:
    object_name: str = ""
    required_bones: list[str] = field(default_factory=list)
    bone_name_inverses: dict[str, str] = field(default_factory=dict)
    parenting: dict[str, list[str]] = field(default_factory=dict)
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Raises `ValueError` for a malformed armature. Absent keys get defaults."""
        if not isinstance(data, dict):
            raise ValueError("`armature` is not an object.")
        object_name = data.get("object_name", "")
        if not isinstance(object_name, str):
            raise ValueError("`armature.object_name` is not a string.")
        required_bones = data.get("required_bones", [])
        if not _is_str_list(required_bones):
            raise ValueError("`armature.required_bones` is not a list of strings.")
        inverses = data.get("bone_name_inverses", {})
        if not (
            isinstance(inverses, dict)
            and all(isinstance(v, str) for v in inverses.values())
        ):
            raise ValueError("`armature.bone_name_inverses` is not a string map.")
        parenting = data.get("parenting", {})
        if not (
            isinstance(parenting, dict)
            and all(_is_str_list(v) for v in parenting.values())
        ):
            raise ValueError("`armature.parenting` is not a map of string lists.")
        return cls(
            object_name=object_name,
            required_bones=required_bones,
            bone_name_inverses=inverses,
            parenting=parenting,
            extra=_extra(data, _ARMATURE_KEYS),
        )

    def to_dict(self) -> dict:
        return {
            "object_name": self.object_name,
            "required_bones": self.required_bones,
            "bone_name_inverses": self.bone_name_inverses,
            "parenting": self.parenting,
            **self.extra,
        }


def _default_skinned_meshes() -> list[str]:
    return ["ARMATURE"]


@dataclass
class RequiredModifiers:
    skinned_meshes: list[str] = field(default_factory=_default_skinned_meshes)
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Raises `ValueError` for malformed requirements. Absent keys get defaults."""
        if not isinstance(data, dict):
            raise ValueError("`modifiers.required` is not an object.")
        return cls(
            skinned_meshes=_modifier_list(
                data, "modifiers.required", "skinned_meshes", _default_skinned_meshes()
            ),
            extra=_extra(data, _REQUIRED_KEYS),
        )

    def to_dict(self) -> dict:
        return {"skinned_meshes": self.skinned_meshes, **self.extra}


@dataclass
class Modifiers:
    required: RequiredModifiers = field(default_factory=RequiredModifiers)
    allowed: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Raises `ValueError` for malformed modifiers. Absent keys get defaults."""
        if not isinstance(data, dict):
            raise ValueError("`modifiers` is not an object.")
        return cls(
            required=RequiredModifiers.from_dict(data.get("required", {})),
            allowed=_modifier_list(data, "modifiers", "allowed", []),
            warn=_modifier_list(data, "modifiers", "warn", []),
            fail=_modifier_list(data, "modifiers", "fail", []),
            extra=_extra(data, _MODIFIERS_KEYS),
        )

    def to_dict(self) -> dict:
        return {
            "required": self.required.to_dict(),
            "allowed": self.allowed,
            "warn": self.warn,
            "fail": self.fail,
            **self.extra,
        }


@dataclass
class Spec(JsonDocument):
    model_type: str | None = None
    armature: Armature = field(default_factory=Armature)
    mesh_roles: dict[str, MeshRole] = field(default_factory=dict)
    modifiers: Modifiers = field(default_factory=Modifiers)
    extra: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def path_for(specs_dir: Path, model_type: str) -> Path:
        """Raises `ValueError` for a name `naming.validate` rejects. Pass it normalized."""
        reason = naming.validate(model_type)
        if reason is None and model_type != naming.normalize(model_type):
            reason = f"'{model_type}' is not normalized."
        if reason is not None:
            raise ValueError(reason)
        return specs_dir / f"{model_type}{naming.SUFFIX}"

    @classmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        model_type = data.get("model_type")
        if model_type is not None and not isinstance(model_type, str):
            raise ValueError("`model_type` is not a string.")
        roles = data.get("mesh_roles", {})
        if not isinstance(roles, dict):
            raise ValueError("`mesh_roles` is not a map of objects.")
        return cls(
            path=path,
            model_type=model_type,
            armature=Armature.from_dict(data.get("armature", {})),
            mesh_roles={name: MeshRole.from_dict(role) for name, role in roles.items()},
            modifiers=Modifiers.from_dict(data.get("modifiers", {})),
            extra=_extra(data, _SPEC_KEYS),
        )

    def to_dict(self) -> dict:
        model_type = {} if self.model_type is None else {"model_type": self.model_type}
        return {
            **model_type,
            "armature": self.armature.to_dict(),
            "mesh_roles": {
                name: role.to_dict() for name, role in self.mesh_roles.items()
            },
            "modifiers": self.modifiers.to_dict(),
            **self.extra,
        }


def _role_str(data: dict, key: str) -> str | None:
    if key not in data:
        return None
    if not isinstance(data[key], str):
        raise ValueError(f"A mesh role's `{key}` is not a string.")
    return data[key]


def _role_count(data: dict) -> int | None:
    if "count" not in data:
        return None
    count = data["count"]
    if not isinstance(count, int) or isinstance(count, bool):  # bool is an int
        raise ValueError("A mesh role's `count` is not a whole number.")
    return count


def _role_weight(data: dict) -> float | None:
    if "weight" not in data:
        return None
    weight = data["weight"]
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        raise ValueError("A mesh role's `weight` is not a number.")
    return weight


def _role_str_list(data: dict, key: str) -> list[str] | None:
    if key not in data:
        return None
    if not _is_str_list(data[key]):
        raise ValueError(f"A mesh role's `{key}` is not a list of strings.")
    return data[key]


def _modifier_list(data: dict, where: str, key: str, default: list[str]) -> list[str]:
    value = data.get(key, default)
    if not _is_str_list(value):
        raise ValueError(f"`{where}.{key}` is not a list of strings.")
    return value


def _extra(data: dict, known: tuple[str, ...]) -> dict[str, object]:
    return {key: value for key, value in data.items() if key not in known}


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)
