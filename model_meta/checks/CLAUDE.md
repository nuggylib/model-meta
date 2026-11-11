# model_meta/checks/

Compares a model's scene data, as reported by `core.blender_bridge`, against its
spec, and builds the results `core.results` stores. Pure functions: no I/O, no
Textual, no UI.

## Files
- `mesh_roles.py` — the `mesh_roles` check.
  - `plan(roles, meshes)`: the `WeightTarget`s, then one textured
    `MeshTarget` per mesh a role with `texture_maps` matches (for textures and
    UVs), then one per mesh any role matches (for modifiers), deduped. The
    screen passes `functools.partial(plan, roles)` to `subscribe_meshes`.
  - `evaluate(roles, report, overrides)`: one `MeshRoleResult` per role. It
    re-runs `plan` to line the report's items up with their targets, so the
    report must come from the same roles. `overrides` is the results file's
    `texture_map_overrides`. Each role gets its own `_Scene.stems`, mapping
    `(mesh, map)` to the override name its file must start with. When two
    overrides name the same mesh and map, the first wins.
  - A role's meshes are the scene meshes whose whole name matches
    `mesh_regex` (`re.fullmatch`).
  - Each set field becomes a `FieldCheck` holding one dict of facts per
    failure. The UI words them; nothing here writes prose. `_CHECKS` lists the
    fields in spec order, each with its "is set" test and its check, which
    returns the `FieldCheck`. An absent field, or an empty `texture_maps` /
    `material_slots`, is left out.
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
      A map is present when one of the mesh's images has a file whose name
      ends with `<stem>_<map>.png`. `<stem>` is the mesh's name, or the
      override's name when one covers that mesh and map. An image with no file
      never counts. A `texture_maps` failure also lists `expected`, the exact
      filename each missing map needs. With an add-on before 0.5.1 (`textures` `None`),
      `texture_maps` fails once with `OLD_ADDON`.
    - `texture_maps` always sets `duplicates`: the report's same-shape
      groups, reduced to the role's matched meshes, keeping groups of two or
      more. They are set whether the check passes or fails, and are empty
      when the add-on predates `get_duplicate_meshes`.
    - A `texture_maps` failure with `missing` also gets
      `"has_default_uv_map": True` when the bridge reports one for that mesh
      (a `False` is left out as noise), or its `uv_error`. It is a hint,
      not a check: the add-on's match can't tell a deliberate layout from a
      forgotten unwrap. Neither key is added when the report's `uvs` is
      `None` (an add-on before 0.2.0).
  - When nothing matched, every field but `count` fails with
    `"no meshes matched"` (`NO_MESHES`). A missing or non-compiling
    `mesh_regex` fails every set field with that reason.
- `modifiers.py` — the `modifiers` check, over the meshes the roles matched
  (a mesh no role matches is scenery, lighting or effects, and isn't checked).
  - `evaluate(mods, roles, report)` takes the spec's `Modifiers`, the
    `mesh_roles.evaluate` results (for each role's `meshes`) and the report's
    `MeshModifiers`. It returns the root `ModifiersResult` over every role's
    meshes, each listed once, and the roles with their own meshes'
    `ModifiersResult` set.
  - `required.skinned_meshes`: `{"mesh", "missing"}` for a mesh lacking any.
  - `warn` / `fail`: `{"mesh", "modifiers"}`, the listed types on the mesh,
    deduped in stack order. `warn` is a `warning` check.
  - `allowed` and unlisted modifiers check nothing.
  - A mesh the bridge reports an `error` for is `{"mesh", "error"}` in every
    check. A role with no meshes fails every check with `NO_MESHES`; the root
    with no meshes passes.

## Conventions
- A new field's check is one `_CHECKS` entry. A new root field's check is a
  module here, with its result type in `core/results.py`.
