from __future__ import annotations

from model_meta.core.json_file import JsonFile
from model_meta.specs import schema


class SpecFile(JsonFile):
    def default(self) -> dict:
        return schema.skeleton(self.path.stem)

    def validate(self, document: dict) -> None:
        _check_armature(document.get("armature", {}))
        _check_mesh_roles(document.get("mesh_roles", {}))


def _check_armature(armature: object) -> None:
    """Raise `ValueError` unless `armature` has this shape. Every key may be absent.

    {
      "object_name": "rig",
      "required_bones": ["body", "wheel.front.L"],
      "bone_name_inverses": {"front": "rear"},
      "parenting": {"body": ["wheel.{n}.L"]}
    }
    """
    if not isinstance(armature, dict):
        raise ValueError("`armature` is not an object.")
    _check_object_name(armature.get("object_name", ""))
    _check_required_bones(armature.get("required_bones", []))
    _check_bone_name_inverses(armature.get("bone_name_inverses", {}))
    _check_parenting(armature.get("parenting", {}))


def _check_object_name(value: object) -> None:
    """`"object_name": "rig"`"""
    if not isinstance(value, str):
        raise ValueError("`armature.object_name` is not a string.")


def _check_required_bones(value: object) -> None:
    """`"required_bones": ["body", "wheel.front.L"]`"""
    if not _is_str_list(value):
        raise ValueError("`armature.required_bones` is not a list of strings.")


def _check_bone_name_inverses(value: object) -> None:
    """`"bone_name_inverses": {"front": "rear"}`"""
    if not (
        isinstance(value, dict) and all(isinstance(v, str) for v in value.values())
    ):
        raise ValueError("`armature.bone_name_inverses` is not a string map.")


def _check_parenting(value: object) -> None:
    """`"parenting": {"body": ["wheel.{n}.L"]}`"""
    if not (isinstance(value, dict) and all(_is_str_list(v) for v in value.values())):
        raise ValueError("`armature.parenting` is not a map of string lists.")


def _check_mesh_roles(roles: object) -> None:
    """Raise `ValueError` unless `roles` maps names to role objects.

    {"wheel": {...}, "body": {...}}
    """
    if not (
        isinstance(roles, dict) and all(isinstance(r, dict) for r in roles.values())
    ):
        raise ValueError("`mesh_roles` is not a map of objects.")
    for role in roles.values():
        _check_mesh_role(role)


def _check_mesh_role(role: dict) -> None:
    """Raise `ValueError` unless `role` has this shape. Every key may be absent.

    {
      "mesh_regex": "^wheel_.*$",
      "vtx_grp": "wheel.{n}.L",
      "count": 4,
      "weight": 1.0,
      "texture_maps": ["albedo", "normal"],
      "material_slots": ["paint"]
    }
    """
    for key in ("vtx_grp", "mesh_regex"):
        if not isinstance(role.get(key, ""), str):
            raise ValueError(f"A mesh role's `{key}` is not a string.")
    _check_count(role.get("count", 1))
    _check_weight(role.get("weight", 0.0))
    for key in ("texture_maps", "material_slots"):
        if not _is_str_list(role.get(key, [])):
            raise ValueError(f"A mesh role's `{key}` is not a list of strings.")


def _check_count(value: object) -> None:
    """`"count": 4`"""
    if not isinstance(value, int) or isinstance(value, bool):  # bool is an int
        raise ValueError("A mesh role's `count` is not a whole number.")


def _check_weight(value: object) -> None:
    """`"weight": 1.0`"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("A mesh role's `weight` is not a number.")


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)
