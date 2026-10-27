# model_meta/tui/

The Textual UI layer: everything the user sees and interacts with.

## Contents
- `screens/` — full-page views (`Screen` subclasses). The app navigates by
  pushing/popping screens on the stack.
- `widgets/` — reusable widgets screens are assembled from (`SectionCard`, the
  focusable dashboard section; `ModelRow`, the focusable model row; `SpecRow`,
  the focusable spec row; `FixPanel`, the "how to fix issues" block;
  `FieldSummary`, the per-root-field box on the spec detail screen;
  `FieldList`, the selectable read-only field on the armature, mesh-roles,
  mesh-role and modifiers forms).

## Conventions
- Screens go in `screens/`; reusable widgets go in `widgets/`. A widget belongs
  there once a second screen needs it, or once it carries behavior (focus,
  bindings, messages) rather than just layout — otherwise it stays inline in
  its screen.
- Keep presentation here; validation logic and Blender I/O live in their own
  categories and are surfaced to screens via app-level state.
- Styling lives in `app.tcss` (loaded via `App.CSS_PATH`). Classes shared across
  screens — `.section-title`, `.config-value`, `.config-detail` — are styled
  once at the top level there rather than copied per screen.
