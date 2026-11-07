# model_meta/checks/

Compares a model's scene data, as reported by `core.blender_bridge`, against its
spec, and builds the results `core.results` stores. Pure functions: no I/O, no
Textual, no UI.

## Files
- `mesh_roles.py` — the `mesh_roles` check.
  - `plan(roles, meshes)`: the `WeightTarget`s, `TextureTarget`s and
    `UvTarget`s to fetch, deduped, with one texture target per mesh that holds
    every role's maps and one UV target per textured mesh. The screen passes
    `functools.partial(plan, roles)` to `subscribe_meshes`.
  - `evaluate(roles, report)`: one `MeshRoleResult` per role. It re-runs `plan`
    to line the report's items up with their targets, so the report must come
    from the same roles.
  - A role's meshes are the scene meshes whose whole name matches
    `mesh_regex` (`re.fullmatch`).
  - Each set field becomes a `FieldCheck` holding one dict of facts per
    failure. The UI words them; nothing here writes prose. `_CHECKS` lists the
    fields in spec order, each with its "is set" test and its check. An
    absent field, or an empty `texture_maps` / `material_slots`, is left out.
    - `count`: `{"expected", "matched"}` when the matched total is wrong.
    - `vtx_grp`: `{"mesh"}` for a mesh with no vertex group matching the
      pattern (`parenting.match`). Other groups, like recoloring ones, are
      ignored.
    - `weight`: every matching group on every mesh must have
      `vertices == assigned == at_weight`. A failure is those counts, the
      bridge's `error`, or `"no vertex group"`. With no `vtx_grp` it fails
      with `"vtx_grp not set"`.
    - `texture_maps` / `material_slots`: `{"mesh", "missing"}`, or the
      bridge's `error` for textures. Extra slots and their order don't matter.
    - A `texture_maps` failure with `missing` also gets the mesh's UVs:
      `may_need_unwrap` (`True` when the mesh has no UV map or one still
      matches a primitive's default layout), or the bridge's `uv_error`. It is
      a hint, not a check: the add-on's match can't tell a deliberate layout
      from a forgotten unwrap. Neither key is added when the report's `uvs`
      is `None` (an add-on before 0.2.0).
  - When nothing matched, every field but `count` fails with
    `"no meshes matched"`. A missing or non-compiling `mesh_regex` fails every
    set field with that reason.

## Conventions
- A new field's check is one `_CHECKS` entry. A new root field's check is a
  module here, with its result type in `core/results.py`.
