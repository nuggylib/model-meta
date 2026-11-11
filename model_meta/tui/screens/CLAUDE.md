# model_meta/tui/screens/

Full-page Textual `Screen` subclasses. Each screen is one landing view or page
in the app (analogous to a route in a web app).

## Contents
- `dashboard.py` — `DashboardScreen`, the landing view **and navigation hub**.
  Renders four stacked sections — **Blender → Specs → Models → Godot**. The
  three configured anchors each carry a live existence/validity marker; **Specs
  is config-free** — it reads no settings and renders a muted `#specs-value`
  line with no `✓`/`✗`, because its location is a path convention
  (`app.specs_dir`) rather than a configured anchor, so there is nothing to
  validate. That line is a live count (`No specs yet` / `N specs`) from
  `specs.store.count` — a single-directory glob with no parsing, so it runs
  inline in `compose` like the other cards' `is_dir()`. It is **also refreshed
  on `on_screen_resume`**, targeted at `#specs-value` alone: a spec created on
  the Specs page lands while the dashboard is suspended, a pop does not
  recompose, and a full `recompose` would re-trigger the Godot scan on every
  `escape`. The Models section renders **one row per configured directory**, in
  stored order, each with its own independent marker (the schema and the wizard
  both enforce at least one, so there is no empty state). It reads
  `self.app.settings` (app-level state) and never touches TOML or the filesystem
  beyond cheap stats: Blender validity via `settings.blender.state()` (three
  states — valid / present-but-not-executable / missing — platform-aware, no
  subprocess), Models existence via `is_dir` and the Godot root via
  `settings.godot.state()`, both inline. The one
  filesystem *walk* — the Godot project count — runs in a `@work` worker
  (`asyncio.to_thread(godot.find_projects)`) showing "Scanning…" until it
  returns (zero projects is a valid `0`). It `watch`es the app's `settings`
  reactive and `recompose`s on change, so editing config via `s` refreshes the
  view without a restart. When `self.app.settings is None` (absent/corrupt
  config) it shows a "run setup" prompt in place of the three config-derived
  sections — prompt first, with the Specs card below it. Its `s` binding
  (`app.open_setup`) re-opens the setup wizard in edit mode.
  **Navigation:** each section is a focusable `SectionCard` (see
  `../widgets/CLAUDE.md`); `down`/`j` → `app.focus_next` and `up`/`k` →
  `app.focus_previous` step through them (wrapping at both ends), and `enter` on
  a card posts `SectionCard.Opened`, which `on_section_card_opened` turns into a
  `push_screen(target)`. The cards are the screen's **only** focus stops — a
  test asserts the chain is exactly the four sections, because anything else
  focusable here is a widget the user has to arrow past. `_focus_section()`
  focuses the first section on mount and, critically, **re-focuses the same
  section after `recompose()`**: a config edit tears down every widget, so
  without the save-and-restore the user's highlight silently jumps to the top
  after saving. With no valid config Specs is the only card, so the navigation
  keys act on it alone and the footer still advertises `enter Open`. Future
  work adds live validation results from a Blender-polling worker.
- `models.py` — `ModelsScreen`, the Models detail view. One group per configured
  directory, in stored order, each ending in **one of four states**, and that
  distinction is the point of the page: a directory that *exists* but holds no
  models reads as a healthy `✓ found` on the dashboard, which is exactly how a
  mis-pointed directory hides. So **missing** (`is_dir()` inline), **unreadable**
  (the scan raised `OSError`), **empty** (`0 models`), and **populated** each
  render differently, and each problem state contributes a step to the
  `#fix-panel` block (a `FixPanel`, workflow step 7). That block sits **outside**
  the scroller so a long model list can't push it off screen, and shows only the
  problems the scan actually found — a healthy page shows nothing and the list
  takes the full height. The scan is delegated to the `models`
  category inside `@work(exclusive=True, group="models-scan")` via
  `asyncio.to_thread`, per directory, sequentially — few directories, ordered
  output, and `exclusive` means a recompose-driven rescan cancels the one in
  flight rather than racing it. Rows are `SelectableRow`s keyed by the model's
  `Path` and labeled with its
  path *relative to* its configured directory, so a model in a subfolder keeps
  that context; they are the screen's only focus stops, which is why the
  `VerticalScroll` wrapper passes `can_focus=False` (`ScrollableContainer` opts
  in by default and would otherwise be a stop the user arrows past). Group
  shells are keyed by **position** (`#models-state-{i}`, `#models-files-{i}`),
  not by path — a path is not a usable widget id. `enter` on a row runs
  `_open_model` (`@work(exclusive=True, group="open-model")`): it loads the
  model's `Results` from `app.results_dir`. With none, it lists the `OK` specs
  (in a thread), `push_screen_wait`s a `LinkSpecModal`, and `create`s the
  results file from the choice (`escape` writes nothing). Then it pushes
  `ModelDashboardScreen(model, spec path, results path)`. An unreadable results file,
  an invalid spec name in it, or a failed write is a notice; the file is never
  overwritten.
- `specs.py` — `SpecsScreen` (`specs` in `SCREENS`), the Specs page: the
  validation specs in `specs/`, one focusable `SelectableRow` each, keyed by
  its `SpecEntry`. Follows
  `models.py`'s page shape — a `VerticalScroll` of rows (`can_focus=False`, so
  the rows are the only focus stops) plus a `FixPanel` **outside** the scroller.
  The listing parses JSON per file, so it runs in
  `@work(exclusive=True, group="specs-load")` via `asyncio.to_thread`, and every
  post-load `query_one` is `NoMatches`-guarded. Two problem states contribute a
  fix step — `UNREADABLE` (not valid JSON) and `MISMATCHED` (the file's
  `model_type` disagrees with its filename; the filename wins). **Zero specs is
  not a problem**: on a fresh install it is the normal state, so it renders a
  plain `#specs-empty` note and contributes no step — the opposite call from the
  Models screen's empty directory. `enter` on a row opens `spec_detail.py` for
  that spec, pushed as an **instance** (the screen is per spec), so no `enter`
  on this page is a dead key.
  **`n` creates:** `action_new_spec` runs a `@work(exclusive=True,
  group="new-spec")` worker that `push_screen_wait`s a `NewSpecModal` and, on a
  non-`None` return, notifies, `recompose`s, reloads, and hands focus to the
  **new** row rather than row one (`_focus_after_load`). `exclusive` is what
  stops a fast double `n` stacking two modals.
  It reads `self.app.specs_dir`, a path derived from the config *path* rather
  than its contents, so the page lists and works identically in every config
  state.
- `spec_detail.py` — `SpecDetailScreen(model_type, path)`, the per-spec detail
  view opened by `enter` on a spec row. Not in `SCREENS` (see Conventions).
  Summarizes each root field in a non-focusable `FieldSummary` box — Armature
  shows `Name` (`object_name`, or `not set`) and `Bones` (a count); Mesh roles
  lists the role names (`items`, numbered, columns of 10; `No mesh roles yet.` when
  none). Modifiers mirrors the JSON: `Required:` with `skinned_meshes`
  indented beneath it, then `Allowed`, `Warn`, `Fail`, each via
  `format_list` (`[]` when empty). It never lists bones or a role's fields; those live on the forms. The spec is one small
  file, read inline via `Spec.load` and **re-read on
  `on_screen_resume`** so it reflects what a form wrote. A spec `read` rejects
  hides every summary, shows the page-level `#spec-unreadable`, and
  `check_action` disables `e`. `e` (**Edit data**) runs a
  `@work(exclusive=True, group="edit-data")` worker:
  `push_screen_wait(EditDataModal())`, then `"armature"` →
  `ArmatureFormScreen(path)`, `"mesh_roles"` → `MeshRolesFormScreen(path)` and
  `"modifiers"` → `ModifiersFormScreen(path)`.
  A new root field is one `FIELDS` entry in the picker, one route here, and one
  `FieldSummary` with its rows.
- `model_dashboard.py` — `ModelDashboardScreen(model, spec_path,
  results_path)`, one model (its `.blend` path) against its spec, pushed by
  `enter` on a Models row. Not in `SCREENS`. `Models - <model stem>` heading,
  an unprefixed `Model type: <spec stem>`, then emoji-prefixed rows nested by
  depth (`.model-item-depth-{n}`): `Armature:` (`object_name`, or `not
  found`), `Mesh Roles:` with one row per role, and `Modifiers` with
  `Required:` → `Skinned Meshes`, `Warnings` and `Blocked` (the results'
  `modifiers.required.skinned_meshes`, `warn` and `fail`). The
  spec is read inline in `compose`; a spec `Spec.load` rejects shows `not
  found` and no roles.
  **Roots open the detail screen:** the three depth-0 rows are `SelectableRow`s
  keyed by their results file key (`_ROOTS`: `armature`, `mesh_roles`,
  `modifiers`, each with its title). They are the only focus stops (`MOVE`
  steps through them), and the nested rows are plain `Static`s. `enter`
  pushes `CheckDetailScreen(self, (key,), (title,))`: the dashboard is the
  detail screen's `ResultsSource`. `results_changed` is a Textual `Signal`
  that `watch_results` publishes, so the detail screen follows live results
  while the worker keeps running beneath it. Nested rows are indented past
  the root rows' rail and `▸ `.
  **Overrides:** `texture_maps(role)` gives a role's spec `texture_maps`, and
  `add_texture_map_override(role, override)` appends one through `_update`,
  which loads the file right before. It then re-runs `_check_mesh_roles` on
  `_report`, the last report checked on the model's file, so the icons and
  `expected` names change without a Blender save. A fresh scene query would
  pick up unsaved edits; the report keeps every result tied to the last save.
  With no report yet, the override is only saved, and a notice says it's
  checked when Blender next saves.
  **Icons always come from the results file**, in every mode (Live, Wrong
  File, Manual, Inactive): ✅ for `True`, ❌ for `False`, ⚠️ for a failing
  `warning` check, and 🟡 for a check never run or a results file that can't
  be read. The loaded file is the
  `results` reactive. It is read in `compose` and again on `r`. Each `Row`
  carries its key path in `Results.to_dict()` (`None` for a row nothing
  checks yet). A row whose path is missing is pending. A row with rows
  beneath it shows `tui.status.most_severe` of theirs (a failure, else a
  warning, else a pending row, else a pass). Any other row shows
  `tui.status.status_of` of its value, so a role passes when every check in
  it, its `modifiers` included, passes. Every role keeps its own row.
  Failures are never shown here, only their icons; the detail screen lists
  them.
  **Connection:** on mount and on `r` (**Refresh**), the
  `@work(exclusive=True, group="blender-check")` worker runs both
  `core.blender_bridge` subscriptions in one `asyncio.TaskGroup`, each through
  `_follow(messages, check)`: `subscribe_armatures` with `_check_armature`,
  and `subscribe_meshes(partial(mesh_roles.plan, roles))` with
  `_check_mesh_roles`. Each message sets `live`. Each `OpenFile` sets
  `wrong_file` unless its path is the model (`Path.samefile`, so a symlink or
  a case difference still matches; a never-saved `None` or a missing file is
  wrong). A connection's results are checked only once that connection's
  own `OpenFile` has confirmed the model is open. The armature check passes
  when the spec's `object_name` is in the list (a blank `object_name` fails).
  The mesh check stores `checks.mesh_roles.evaluate(roles, report,
  overrides)`, with the `texture_map_overrides` of the loaded `results`, then
  `checks.modifiers.evaluate` over those roles: the root `modifiers` and each
  role's. A report with no `modifiers` (an add-on before 0.4.0) saves the
  roles alone and keeps the stored modifier results. Both go
  through `_save(**fields)`, a `replace` passed to `_update(change)`: load
  right before, apply `change`, save only when something changed (other keys
  kept), then set `results`. A failed load or save is an error notice and
  returns `False`, and the icons keep the stored results. A
  `busy` `None` armature list checks nothing. With the wrong file open,
  results are ignored and nothing is written; the icons keep showing the
  results file.
  When either subscription raises `BridgeError` (unreachable or dropped), the
  `TaskGroup` cancels the other, `live` and `wrong_file` reset (the icons keep
  the stored results), and the worker falls back to the **Manual Mode**
  check: `BlenderConnection.is_running` via `asyncio.to_thread`, which only
  asks whether Blender is running. While
  connecting or checking, the `is_refreshing` reactive swaps every row's
  prefix to 🔄. The muted `#connection-status` beside the heading reads
  `Wrong File` in Live Mode on the wrong file, `Live Mode`, else from
  `blender_running`: `Manual Mode` when running, `Inactive` when not, empty
  before the first check. The muted `#connection-hint` below it always shows:
  "Blender doesn't have <model name> open. Results are paused until it does."
  on the wrong file, "Results update when you load a file, or save one, in
  Blender." in Live Mode, "Press r to refresh.", or "Start Blender, then press
  r to refresh." when `Inactive`. Every watcher is `NoMatches`-guarded.
- `check_detail.py` — `CheckDetailScreen(source, path, headings)`, one
  model's results at a key path in `Results.to_dict()`. `source` is a
  `ResultsSource` (the model dashboard): `model`, `results`,
  `results_changed`, `texture_maps(role)` and
  `add_texture_map_override(role, override)`. The screen never writes the
  results file itself. It reads the value with `tui.status.lookup`, and is
  pushed by `enter` on a model dashboard root row and
  by `enter` on its own rows. Not in `SCREENS`. The title is `Models - <model
  stem>` then each of `headings`. One class serves every path: it reads
  nothing per field and lays the value out by its shape, mirroring the JSON.
  - **A container of containers** (`mesh_roles`): one `SelectableRow` per
    key, `<icon> <key>`, the icon the most severe status beneath it. They are
    the focus stops (`MOVE`; `#check-lines` gets `can_focus=False`), and the
    first is focused. `enter` pushes another `CheckDetailScreen` at
    `(*path, key)`, sharing `source`. A publish with the same keys relabels
    the rows in place, so focus stays put; other keys remount them.
  - **Any other container** (a role, `modifiers`): one bordered
    `.check-section` per key, the key as its `border_title`. A nested
    container (`modifiers`, `required`) gives each of its keys a section
    instead, titled by the path from here (`required > skinned_meshes`, or
    `modifiers > warn` on a role). A bool or a check shows `✅ passing`,
    `⚠️ warning` (a failing `warning` check) or `❌ failing`. A warning or a
    failure lists every failure's facts as `key: value` lines (the first
    marked `- `), minus the facts its fixes restate (`_RESTATED`:
    `texture_maps` hides `expected`). A check with `duplicates`
    lists them after its failures, passing or not, as `duplicates:` and one
    `SelectableRow` per group, keyed by the group as a tuple, then
    `_DUPLICATES_HELP`. On a role's page, the `texture_maps` section then
    lists that role's `texture_map_overrides` as `key: value` lines. `enter`
    on a group runs `_link`, a `@work(exclusive=True,
    group="texture-map-override")` worker that `push_screen_wait`s a
    `TextureMapOverrideModal` and passes a non-`None` result to
    `source.add_texture_map_override`. A remount refocuses the group row that
    had focus. A `_WARNINGS` entry, keyed by a failure fact, shows once
    as `Warning: ...` (`.check-warning`) when any failure has that fact
    `True`; `texture_maps`' `has_default_uv_map` is the only one.
    A list (`meshes`) shows `format_list`. Only set fields
    have a check, so only they get a section.
  - **A bool or a check** (`armature`): that one section, titled by its key.
  - **Needs Fixes:** every fix on the page sits in one `Needs Fixes` section
    (`.check-fixes`) above the others. It shows only when a failing or
    warning check has fixes. `_fixes` walks the value: each such check gets
    a bold label (its section's title, e.g. `modifiers > warn`), then its
    `_FIXES` entry's items as a numbered list. A `_FIXES` entry maps the
    check's failures to items: one fixed text (`_once`), or `texture_maps`'
    "Bake a texture map named <expected> for <mesh>", one per `expected`
    file, so an override's name shows. A check with no items (a failure
    that is only an `error`) gets no label.
  A missing value, an empty container or an unreadable file shows `No results
  yet.` A new field's fix text is a `_FIXES` entry, never a new screen.
  It subscribes to `source.results_changed` on mount and redraws on each
  publish. Only `escape` and `MOVE` are bound; outside the row list,
  `#check-lines` keeps its focus so long pages scroll.
- `texture_map_override_modal.py` — `TextureMapOverrideModal(role, meshes,
  maps)`, a `ModalScreen[TextureMapOverride | None]`. It shows a
  `#override-meshes` checklist of one duplicate group (all checked), a
  `#override-maps` checklist of the role's maps (none checked; focused), and
  a `#override-name` Input. A live `#override-preview` lists the `Expected:`
  filenames. Enter in the Input or **Save** checks, in order: at least two
  meshes, at least one map, a non-blank name (trimmed), and no `/` or `\`.
  The first problem shows in `#override-status`, and the modal stays open.
  Otherwise it returns the override, with meshes and maps in their listed
  order. `escape` returns `None`. Writes nothing. Its body is a
  `VerticalScroll`, so Save stays reachable in a short terminal. Own
  `Footer`, `q` shadowed. Never name a method `_name` here: `DOMNode` keeps
  the widget's name there.
- `edit_data_modal.py` — `EditDataModal(ModalScreen[str | None])`: an
  `OptionList` of spec root fields from `FIELDS` (keys are `schema.skeleton`
  root keys: Armature, Mesh roles, Modifiers). Returns the key, or `None` on
  `escape`.
  Writes nothing. Own `Footer`, `q` shadowed — `NewSpecModal`'s shape.
- `link_spec_modal.py` — `LinkSpecModal(model_name, specs)`, a
  `ModalScreen[str | None]`: an `OptionList` of the given spec names. Returns
  the chosen name, or `None` on `escape`. The caller loads and filters
  `specs`, so the modal does no I/O. With no specs it shows `#no-specs` and
  only `escape` works. Writes nothing. Own `Footer`, `q` shadowed.
- `confirm_modal.py` — `ConfirmModal(question)`, a generic
  `ModalScreen[bool]`: the question (`markup=False`), **No** (focused) and
  **Yes** buttons, `left`/`right` between them. Yes → `True`; No or `escape`
  → `False`. Writes nothing. Own `Footer`, `q` shadowed.
- `armature_form.py` — `ArmatureFormScreen(path)`, a full `Screen` the user
  stays on to name the armature and add bone after bone. **Read-only until
  selected:** each field (`#armature-name-view`, `#bone-list`,
  `#parenting-list`) is a `FieldList`; Enter or a click opens that field's
  editor (`.editor`, hidden by CSS) and closes any other, discarding its
  in-progress state unwritten. One editor at a time (`_editing`). Focus opens
  on `#bone-list`; the name view is one shift-tab away. Parenting with no
  parentable bones opens nothing and says why in `#bone-status`.
  **Name:** the `#armature-name` Input replaces its view, prefilled from
  `object_name`. Enter saves (blank clears, over 63 bytes is rejected) and
  closes; `escape` closes unsaved.
  **Bones:** `#bone-editor` sits above the list. Enter in `#bone-name`
  validates, then asks
  one `#bone-inverse` question per segment `specs.bones.next_missing` returns
  (relabeled each time; blank = no inverse). **Full chain first:** answers
  stay pending until the last one, then one `update_armature` writes them all
  (dropping pairs this bone wrote before, so a Back re-answer replaces them)
  and only then are `variants` computed into a pre-checked `#bone-variants`
  checklist with focus on **Add**. The checklist is skipped when there is
  nothing to choose. **Write-on-confirm** — no separate Save. `escape` steps
  back one question mid-bone, clears an idle name field with text, and closes
  the editor from an empty one. Failures keep the field's text, show
  `#bone-status`, and write nothing. User-typed names render with
  `markup=False` (`rich.markup.escape` misses uppercase tags like `[L]`).
  **Cursor, `a` and rename:** `#bone-list` has a `FieldList` cursor. `a`
  (`check_action`: only while `#bone-list` has focus) opens Add; Enter on an
  empty list does too. Enter or a click on a bone opens the same editor as a
  rename (`_original`; `#bone-name-label` reads `Rename '<name>'`): the add
  rules minus its own name, inverse questions for new segments, **no variant
  checklist**, then one `store.rename_bone` write, close, cursor on the bone.
  `#bone-status` then names parenting keys and mesh roles that matched the old
  name but not the new one (`stale_keys` / `stale_roles`) — never rewritten.
  The `#parenting-list` rows whose pattern `is_stale` are marked red
  (`FieldList.marked`) while that warning shows: `_status` clears the marks.
  `escape` in a rename steps back a question, then closes unsaved.
  **Delete:** `x` (`check_action`: `#bone-list` focused and non-empty) runs a
  `@work(exclusive=True, group="delete-bone")` worker that
  `push_screen_wait`s a `ConfirmModal`. Yes closes any open editor unwritten,
  then `store.delete_bone` removes only that bone; the cursor keeps its index
  (clamped). `#bone-status` then names parenting keys and mesh roles that
  matched the bone and now match no bone (`unmatched_keys` /
  `unmatched_roles`, never rewritten), and those `#parenting-list` rows are
  marked red until `_status` clears them — the rename warning's shape, sharing
  `_references`. No or `escape` changes nothing.
  **Two columns** under the name/status: bones on the left, parenting on the
  right. **Parenting:** `#parenting-editor` sits above the list.
  `#parent-bones` is a checklist of `required_bones`; **Choose children**
  hides `#parent-picker` and mounts an unchecked `#child-bones` of eligible
  bones (not a checked parent, not already parented, not an ancestor), a
  `#parenting-preview`, and **Add**. Preview and Add both call
  `specs.parenting.infer` on a fresh read, so the preview is what gets written;
  an unpairable child shows its reason in both. `escape` steps back: children →
  parents (checks kept) → clears checks → closes. With no editor open,
  `escape` leaves. `#parenting-list` and the preview are nested: each key,
  then its child patterns indented beneath it.
  Never name an attribute `_parent` here — it shadows Textual's `DOMNode._parent`.
- `mesh_roles_form.py` — `MeshRolesFormScreen(path)`, the form for adding
  mesh roles and opening one. Read-only `#role-list` (a `FieldList` with
  `cursor=True`: each role, its `mesh_regex`, `vtx_grp`, `count`, `weight`
  and `texture_maps` indented, then `material_slots` only when non-empty;
  `texture_maps: none` and `material_slots` are never marked). With no `required_bones`
  Add doesn't open, and `#role-status` says why.
  **Add** (`a`, or Enter on an empty list): Enter in `#role-name` validates
  the name and reveals `#role-bones-question` — a `#role-bones` checklist
  refilled from a fresh read, a live `#role-preview` of
  `mesh_roles.infer_vtx_grp` (or why none fits), a required `#role-regex`
  Input (`validate_mesh_regex`, trimmed), a required `#role-count` Input
  (`parse_count`), a required `#role-weight` Input (`parse_weight`; blank is
  an error, never `0`), and `#confirm-role` (**Add**, or Enter in any of the
  three Inputs), which writes all four via `add_mesh_role` and returns to an
  empty `#role-name`. Checks run bones → regex → count → weight; the first
  failure gets the status and focus. A missing `mesh_regex`, `count` or
  `weight` line is `marked`; `weight: 0.0` is set, never marked.
  `escape`: hide the question → clear the name → close → leave.
  **Open** (Enter or a click on a role): a fresh read (a role gone by hand is
  reported, nothing pushed), any Add is discarded unwritten, then
  `_open_role`, a `@work(exclusive=True, group="role-view")` worker,
  `push_screen_wait`s `MeshRoleFormScreen` and puts the cursor on the name it
  returns. Failures keep text and checks and write nothing. No typed pattern.
  **Delete:** `x` (`check_action`: `#role-list` focused and non-empty; the
  only gated key here) runs a `@work(exclusive=True, group="delete-role")`
  worker that `push_screen_wait`s a `ConfirmModal`. Yes discards any Add
  unwritten, then `store.delete_mesh_role` removes only that role; the cursor
  keeps its index (clamped). One-and-done: nothing else names a role, so
  there is no warning — unlike the bone delete. No or `escape` changes nothing.
  `q` shadowed.
- `mesh_role_form.py` — `MeshRoleFormScreen(path, name)`, one mesh role,
  dismissed with its **current** name. The name is the attribute `role`:
  `DOMNode` already owns `name`. **Read-only until selected**, the armature
  form's shape: `#role-name-view` (a `FieldList`) swaps for a prefilled
  `#role-name` Input whose Enter renames alone (`update_mesh_role` with no
  field changes; the add rules minus its own name). `#role-fields` (cursor) lists
  every field the role holds as one `key: value` line, with a muted
  description line beneath where one helps (`_field_lines`; the depth-1
  `.field-list-child` row, `$text-muted`). The required `mesh_regex`,
  `vtx_grp`, `count` and `weight` are always listed first (`not set` when
  absent); `vtx_grp` is described by the bones it `matches`, and a missing
  `mesh_regex`, `count` or `weight` is `marked` red with a `required` line.
  `weight` `0.0` is set, not missing: test `is None`, never truthiness.
  Enter on `mesh_regex`, `count` or `weight` opens its prefilled Input
  (`#mesh-regex` / `#count` / `#weight`, one `_edit_input` keyed by
  `_INPUTS`; weight is shown and prefilled via `format_weight`) whose Enter
  writes it alone (`validate_mesh_regex` / `parse_count` / `parse_weight`,
  trimmed). Enter on `vtx_grp` opens
  `#vtx-grp-editor`: required bones pre-checked with its matches, live
  preview, **Save** writes the pattern alone. `texture_maps` is always listed
  after them (`none` when absent or `[]`, never marked). Enter opens
  `#texture-maps-editor`, a checklist of `schema.TEXTURE_MAPS` plus any
  unknown names the role holds (pre-checked, labelled `(not a Godot map)`).
  **Save** writes the checked names alone, in `order_texture_maps` order.
  `material_slots` is **optional and hidden until set**: listed after
  `texture_maps` only when non-empty (absent and `[]` both hide it, and it is
  never an "other" field), never marked. `m` (footer **Material slots**)
  opens `#material-slots` from any focus but an Input, which takes `m` as
  text; Enter on its row does too once set. It's a comma-separated Input
  (`format_material_slots` prefill, `parse_material_slots` on Enter); saving
  blank removes the key and drops the cursor to `texture_maps`. `_show` marks
  only the required `_INPUTS`.
  Other fields say they can't be edited yet. One editor at a time;
  `escape` closes it unsaved, else leaves. Failures keep text and checks and
  write nothing. `q` shadowed.
- `modifiers_form.py` — `ModifiersFormScreen(path)`, the spec's `modifiers`.
  `MeshRoleFormScreen`'s shape minus the name editor and the return value.
  `#modifier-fields` (cursor) lists `required.skinned_meshes`, `allowed`,
  `warn` and `fail` as `key: format_list(...)`, each with a muted description
  beneath, then hand-written `required.<key>` and `modifiers` extras as
  `key: value` lines that can't be edited yet. Nothing is marked.
  Enter on a list opens `#modifiers-editor`, one shared `#modifier-choices`
  checklist relabeled `<key> modifiers`, read fresh: `modifiers.choices`, the
  list pre-checked, each name tagged `(not a listed modifier)` and/or by its
  `conflicts` (`(required)` when editing `fail`, else `(in warn, fail)`).
  Enter on the open list refocuses it; another list discards it unwritten.
  **Save** writes through `store.update_modifiers` with `modifiers.assign`,
  closes, keeps the cursor, and reports `Modifiers saved.` plus any moves
  (`Moved X, Y out of warn; Z out of fail.`), computed against the fresh read.
  Failures keep the checks and write nothing. `escape` closes the checklist
  unsaved, else leaves. `q` shadowed.
- `blender_detail.py`, `godot_detail.py` — the other two detail screens
  (`blender-detail`, `godot-detail` in `SCREENS`). Still **placeholders**: they
  render the configured value they own plus a `#placeholder-note`. They exist so
  navigation is uniform and no `enter` is a dead key; `models.py` is the pattern
  each should follow when it grows real content.
- `new_spec_modal.py` — `NewSpecModal(ModalScreen[Path | None])`, the one
  question a new spec needs: a model-type name. Returns the created file's path
  via `dismiss()`, or `None` on cancel. The codebase's **first `ModalScreen`**
  (the wizard is a plain `Screen[…]`), so it owns its overlay layout in
  `DEFAULT_CSS` — `align: center middle` plus a bordered panel — the way the
  wizard does.
  It takes **no constructor arguments**: it reads `self.app.specs_dir`, which is
  the whole point — a second entry point to the create flow is one
  `push_screen_wait` inside a worker, not a reimplementation.
  Key contract: **Enter in the Input creates** — the opposite call from the
  wizard's models box, where Enter Adds and never advances, because there the
  field feeds a list and here it *is* the whole form. `Input.Changed` previews
  the resulting filename (`→ specs/space-ship.json`) and clears a stale error,
  so the normalization is visible before the user commits to it. `q` is shadowed
  with a no-op for the usual reason (a focused `Button` would bubble it to the
  app's quit). Every failure — invalid name, duplicate, unwritable directory —
  keeps the modal up with a message in `#spec-status` and the Input's text
  intact, and writes nothing. The write itself is one small file done inline,
  like `app._save`: no worker needed.
  It composes its **own `Footer`**, which a `ModalScreen` needs and a plain
  pushed screen does not: a modal is transparent, so the page underneath keeps
  painting *its* bindings — the Specs page's `n New spec` and `q Quit`, neither
  of which does anything while the modal is up.
- `setup_wizard.py` — `SetupWizard(Screen[Settings | None])`, the first-time
  setup flow. A 3-step Back/Next `ContentSwitcher` (Blender executable → models
  directories → Godot root) that returns a `Settings` via `dismiss()`, or `None`
  on cancel. Pass `existing=Settings` to open pre-populated in *edit mode*.
  **Step 2 is an add/remove list** (the codebase's only `ListView`): an `Input` +
  **Add** feeds a `ListView`, and **Remove** deletes the highlighted row. Per-Add
  validation reuses the single-directory rules — normalize, accept a directory,
  reject a file, offer **Create directory** for a missing one — and dedups,
  scoped to the path in the box at Add time so a rejected Add never disturbs the
  rows already added. Key contract: **Enter in the models box Adds**, it does not
  advance; **Next gates on the list being non-empty**, not on the box; and text
  typed but never Added blocks Next with a hint rather than being silently
  dropped or silently auto-added. Edit mode fills the list from
  `existing.models_directories` and leaves the box **blank** (prefilling it would
  invite a duplicate and trip the unadded-text guard on a no-op edit).

## Conventions
- One screen per file, named `<Name>Screen`. The value-returning screens are the
  deliberate exceptions — `SetupWizard`, `NewSpecModal` and `ConfirmModal` are
  flows that return a result, not landing views, and are named for what they are.
- Register landing screens in `ModelMetaApp.SCREENS` and navigate with
  `push_screen` / `pop_screen`; push value-returning screens with
  `push_screen_wait` from inside a `@work` worker.
- **Keep slow/blocking work out of the event loop and out of the screen.** No
  screen owns a `subprocess`, a filesystem *walk*, or TOML: they call the
  `core` (`BlenderConnection.probe`, `GodotConnection.find_projects`), and
  `models` (`discovery.find_blend_files`) categories inside Textual `@work`
  workers (via `asyncio.to_thread`) so the UI never freezes; the app, not the
  screen, persists results. Cheap inline stats (`is_dir`, `mkdir`) and the fast
  `BlenderConnection.candidates()` prefill are fine.
- **A worker that writes to widgets must tolerate them being gone.** A
  recompose or a `pop_screen` can land while the scan is in flight, so every
  post-scan `query_one` is guarded against `NoMatches` (see `dashboard.py`'s
  `_scan_godot` and `models.py`'s `_update`). Pair that with
  `@work(exclusive=True, group=…)` so a rescan cancels its predecessor rather
  than racing it.
- **A detail screen reads app-level state, it does not take constructor args.**
  That is what keeps every screen pushable by name from `SCREENS`. Detail
  screens assume `self.app.settings` is valid: the dashboard only links to the
  config-derived pages when it is, so they carry no `None` fallback. `specs.py`
  reads no settings at all — only `self.app.specs_dir` — so it works in every
  config state.
  `spec_detail.py`, `armature_form.py`, `mesh_roles_form.py`,
  `mesh_role_form.py`, `modifiers_form.py`, `model_dashboard.py` and
  `check_detail.py` are the
  named exemptions: they are *per spec* (or per model), with no app-level "current spec" to read, so they take
  the spec as a constructor argument and are **not** registered in `SCREENS` — the
  `SetupWizard` / `NewSpecModal` shape, minus the return value. Adding a
  `current_spec` to app state would be persisting a selected spec, which nothing
  asks for. The rule's purpose holds because nothing in `SCREENS` names them.
- **Setup (`s` → `app.open_setup`) is bound on the dashboard only.** No other
  screen offers it, nor tells the user to press `s`.
- **Spec screens read with `Spec.load(self.path)` and write through
  `specs.store`.** They load fresh for each read and never hold a `Spec` to
  save later, so a hand edit made while the screen is open is never
  overwritten.
- **Screens read `self.app.specs_dir`, never `config.paths` directly** — the
  same rule that keeps them off `self.app._config_path`. It also means
  `$MODEL_META_CONFIG` needs no sibling `$MODEL_META_SPECS`: point the
  config somewhere and the specs follow.
- **Bind one key per `Binding`, not comma-joined keys, whenever the footer
  matters.** Textual expands `Binding("down,j", …)` into a separate binding per
  key, each carrying the same `description` and `key_display` — so a shown pair
  draws its footer entry twice. Bind the aliases separately with `show=False`
  and let one entry speak for the action. The list-navigation set is
  `tui.bindings.MOVE`; spread it (`*MOVE`) rather than copying it.
- A screen that must not honor the app's global `q`-quit binding shadows it with
  its own `q` binding (a hidden no-op action). A focused `Input` already swallows
  a typed `q` as text, but a focused `Button` would let `q` bubble to the app —
  the screen-level binding closes that gap regardless of what holds focus.
