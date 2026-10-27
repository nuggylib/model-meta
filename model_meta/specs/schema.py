"""The spec document's vocabulary and its empty skeleton.

The constants here are the schema *definition* — the lists a later validator and
the skeleton both key off. **Nothing enforces them yet**: a spec written today
can hold any texture name or modifier identifier and no code objects.

The document has four top-level sections:

- `model_type` — the filename stem, repeated inside the file.
- `armature` — the expected armature object, the bones that must exist, the
  bone-name segment inverses (`.front` ↔ `.rear`), and a parent-pattern →
  child-patterns map using `{n}` placeholders (see `parenting.py`).
- `mesh_roles` — role name → `mesh_regex`, `vtx_grp`, `count`, `texture_maps`,
  `weight`, and an optional `material_slots`.
- `modifiers` — which modifier types are required on skinned meshes, allowed
  anywhere, worth warning about, and outright failures.
"""

from __future__ import annotations

# Godot's BaseMaterial3D.TextureParam, lowercased without the TEXTURE_ prefix.
# A mesh role may require none, some, or all of them.
TEXTURE_MAPS = (
    "albedo",
    "metallic",
    "roughness",
    "emission",
    "normal",
    "bent_normal",
    "rim",
    "clearcoat",
    "flowmap",
    "ambient_occlusion",
    "heightmap",
    "subsurface_scattering",
    "subsurface_transmittance",
    "backlight",
    "refraction",
    "detail_mask",
    "detail_albedo",
    "detail_normal",
    "orm",
)

# Blender modifier type identifiers, curated to what comes up in Godot-bound
# work. Not Blender's full ~55 — that list drifts every release.
MODIFIERS = (
    "ARMATURE",
    "ARRAY",
    "BEVEL",
    "BOOLEAN",
    "CAST",
    "DATA_TRANSFER",
    "DECIMATE",
    "DISPLACE",
    "EDGE_SPLIT",
    "LATTICE",
    "MIRROR",
    "MULTIRES",
    "REMESH",
    "SHRINKWRAP",
    "SMOOTH",
    "SOLIDIFY",
    "SUBSURF",
    "TRIANGULATE",
    "WELD",
    "WEIGHTED_NORMAL",
)


def skeleton(model_type: str) -> dict:
    """A complete, empty-valued spec — valid shape from the first write."""
    return {
        "model_type": model_type,
        "armature": {
            "object_name": "",
            "required_bones": [],
            "bone_name_inverses": {},
            "parenting": {},
        },
        "mesh_roles": {},
        "modifiers": {
            "required": {"skinned_meshes": ["ARMATURE"]},
            "allowed": [],
            "warn": [],
            "fail": [],
        },
    }
