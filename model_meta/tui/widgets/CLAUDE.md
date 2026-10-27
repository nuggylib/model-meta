# model_meta/tui/widgets/

Reusable Textual widgets — the parts screens are assembled from. A widget earns
a place here once a *second* screen needs it, or once it carries behavior
(focus, bindings, messages) rather than just layout. One-off layout stays inline
in the screen that owns it.

## Contents
- `section_card.py` — `SectionCard(Vertical, can_focus=True,
  can_focus_children=False)`, one focusable section of a hub screen. Holds
  arbitrary children (the dashboard passes `Static` rows), binds `enter` to an
  action that posts `SectionCard.Opened(target)`, and takes `target` — a name
  registered in `ModelMetaApp.SCREENS`, not a screen instance.
  `can_focus_children=False` is load-bearing: it keeps the hub's focus chain at
  exactly **one stop per section**, so a `Button` added inside a card later
  cannot become a stop of its own and break the "arrow keys step through
  sections" contract.
- `model_row.py` — `ModelRow(Static, can_focus=True)`, one `.blend` file on the
  Models screen. Same shape as `SectionCard` — focusable, `enter` posts
  `ModelRow.Selected` — but it carries a `Path` rather than a screen name,
  because what happens to a selected model is not a navigation decision.
  `label` (the screen passes the model's path *relative to* its configured
  directory) is escaped inside the widget: it is always a filename, and a model
  called `sedan[wip].blend` would otherwise be read as markup and render with a
  chunk missing.
- `spec_row.py` — `SpecRow(Static, can_focus=True)`, one validation spec on the
  Specs screen. `ModelRow`'s shape — focusable, `enter` posts
  `SpecRow.Selected` — with two differences: it is labeled with the spec's
  **`model_type`** (the filename stem, the spec's identity) rather than a path,
  and it takes an optional `marker` rendered beside the name for the
  unreadable/mismatched states. The message carries both the name and the path.
  The name is escaped inside the widget for the same reason `ModelRow` escapes
  its label: a spec called `mech[v2]` would otherwise be read as markup.
- `fix_panel.py` — `FixPanel(Vertical)`, the "How to fix issues" block on a
  page whose content scrolls. Assign `steps` (rendered strings); an empty tuple
  hides it. Two constraints worth keeping:
  - Children come from `compose` via a `recompose=True` reactive, **not**
    `mount_all`. Children mounted into an already-laid-out `height: auto`
    container don't re-measure it.
  - It is **not** `dock: bottom`. A docked container with `height: auto`
    renders at one row, clipping all but its heading. It sits as a plain
    sibling of the `1fr` scroller instead, which gets the same result with the
    variable height on the side that can report it.

- `field_summary.py` — `FieldSummary(Vertical)`, one spec root field on the
  spec detail screen: `title` becomes the `border_title`, `rows` (a tuple
  of `(label, value)`) render as `label: value` lines, a value of
  `(key, value)` pairs renders as `label:` with each pair indented beneath it
  (`.field-row-child`, for a nested JSON object), and `items` (a tuple of
  strings) are numbered `1). ` (right-aligned) and fill side-by-side
  `.field-column`s of `COLUMN_LENGTH` (10), top to bottom; `empty` shows when
  both are empty. Display-only — no
  focus, bindings, or messages. It earns its place by repeating once per root
  field on the same screen. `rows` is a `recompose=True` reactive for
  `FixPanel`'s reason, and rows use `markup=False` because values come from
  the spec file (`rich.markup.escape` misses uppercase tags like `[L]`).
- `field_list.py` — `FieldList(VerticalScroll, can_focus=True)`, one spec
  field's contents shown read-only on the armature, mesh-roles, mesh-role and
  modifiers forms.
  `title` becomes the `border_title`; `lines` (a tuple of `(text, depth)`)
  render as `.field-list-row`, depth 1 also `.field-list-child`; `empty` shows
  as `.field-list-empty` when there are none. `enter` or a click posts
  `FieldList.Selected` (`control` is the list), so the screen opens the
  editor. Arrow keys scroll. `lines` is a `recompose=True` reactive and rows
  use `markup=False`, both for `FieldSummary`'s reasons.
  **Opt-in cursor** (`cursor=True`): up/down move `highlighted` over the
  items (depth-0 lines; a depth-1 line belongs to the item above), clamped
  when `lines` change and kept in view; that row gets
  `.field-list-highlighted`, and a click highlights the clicked row's item.
  `Selected.index` is the highlighted item, `None` without a cursor or items.
  On: `#role-list`, `#bone-list`, `#role-fields` and `#modifier-fields`.
  **`marked`** (a frozenset of *line* indices, so a child line can be marked
  alone) adds `.field-list-marked` to those rows. Assigning `lines` clears it,
  so set it after them. On: `#parenting-list`, `#role-list` and
  `#role-fields`.

## Conventions
- **A widget never navigates.** It names where it leads (`target`) and posts a
  message; the hub screen handling that message owns `push_screen`. This is what
  keeps a card reusable by any future hub screen and keeps the pushes in one
  place.
- Messages are nested classes on the widget, so Textual derives the handler name
  from the qualname (`SectionCard.Opened` → `on_section_card_opened`).
- Styling lives in `app.tcss` keyed off the classes the screen assigns, not in
  `DEFAULT_CSS` here — a reusable widget shouldn't dictate how each screen
  wants it to look. (`SetupWizard`'s `DEFAULT_CSS` is screen-local layout, a
  different case.)
