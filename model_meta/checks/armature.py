from __future__ import annotations

from collections.abc import Sequence

from model_meta.core.blender_bridge import SceneArmature
from model_meta.core.results import ArmatureResult
from model_meta.core.spec import Armature
from model_meta.specs import parenting


def evaluate(armature: Armature, scene: Sequence[SceneArmature]) -> ArmatureResult:
    name, required = armature.object_name, armature.required_bones
    found = next((a for a in scene if a.name == name), None)
    if found is None:
        return ArmatureResult(name, False, list(required))
    parents = {bone.name: bone.parent for bone in found.bones}
    rules: dict[str, dict[str, None]] = {}
    for key, patterns in armature.parenting.items():
        for parent in required:
            bound = parenting.match(key, parent)
            if bound is None:
                continue
            for pattern in patterns:
                for child in required:
                    if (
                        child in parents
                        and parents[child] != parent
                        and parenting.match(pattern, child, bound) is not None
                    ):
                        rules.setdefault(key, {})[child] = None
    return ArmatureResult(
        name,
        True,
        [bone for bone in required if bone not in parents],
        {key: list(children) for key, children in rules.items()},
    )
