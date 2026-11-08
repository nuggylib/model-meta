from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from model_meta.core.json_document import JsonDocument

_RESULTS_KEYS = ("model_file", "spec", "armature", "mesh_roles", "modifiers")


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


@dataclass
class Results(JsonDocument):
    """A `None` check was never run and is omitted on write."""

    model_file: str
    spec: str
    armature: bool | None = None
    mesh_roles: dict[str, MeshRoleResult] | None = None
    modifiers: ModifiersResult | None = None
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
        }
        checks = {key: value for key, value in known.items() if value is not None}
        return {
            "model_file": self.model_file,
            "spec": self.spec,
            **checks,
            **self.extra,
        }
