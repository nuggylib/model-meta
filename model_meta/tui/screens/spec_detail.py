"""The spec detail screen — one spec's contents, and the way to edit them.

Summarizes each root field in a `FieldSummary` (Armature: name and bone count;
Mesh roles: the role names in columns; Modifiers: each list; full details live
on the forms). `e`
(**Edit data**) opens `EditDataModal`, a picker of the spec's root fields, and
routes the choice to that field's form. The spec is one small file, read inline (like
`NewSpecModal`'s inline write) and re-read on every resume so it reflects
whatever a form wrote.
"""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from model_meta.core.spec import Spec
from model_meta.specs import modifiers
from model_meta.tui.screens.armature_form import ArmatureFormScreen
from model_meta.tui.screens.edit_data_modal import EditDataModal
from model_meta.tui.screens.mesh_roles_form import MeshRolesFormScreen
from model_meta.tui.screens.modifiers_form import ModifiersFormScreen
from model_meta.tui.widgets.field_summary import FieldSummary

_UNREADABLE = "This spec can't be read — see the fix steps on the Specs page."
_NOT_SET = "not set"
_MODIFIER_ROWS = (("Allowed", "allowed"), ("Warn", "warn"), ("Fail", "fail"))


class SpecDetailScreen(Screen):
    """Detail view for one spec, pushed as an instance (see `screens/CLAUDE.md`).

    `model_type` is the filename stem — the identity, so it titles the page even
    when the file can't be read. `path` is the file the sections are read from.
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        Binding("e", "edit_data", "Edit data"),
    ]

    def __init__(self, model_type: str, path: Path) -> None:
        super().__init__()
        self.model_type = model_type
        self.path = path
        self._readable = False

    def compose(self) -> ComposeResult:
        yield Header()
        unreadable = Static(_UNREADABLE, id="spec-unreadable", classes="config-detail")
        unreadable.display = False
        yield VerticalScroll(
            # Escaped for the same reason `SpecRow` escapes it: a spec called
            # `mech[v2]` would otherwise be read as markup.
            Static(
                f"Spec — {escape(self.model_type)}",
                id="spec-title",
                classes="section-title",
            ),
            FieldSummary("Armature", id="armature-summary", classes="field-summary"),
            FieldSummary(
                "Mesh roles",
                empty="No mesh roles yet.",
                id="mesh-roles-summary",
                classes="field-summary",
            ),
            FieldSummary("Modifiers", id="modifiers-summary", classes="field-summary"),
            unreadable,
            id="detail-panel",
            can_focus=False,
        )
        yield Footer()

    def on_screen_resume(self) -> None:
        self._show_fields()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """`e` is disabled while the spec can't be read."""
        if action == "edit_data" and not self._readable:
            return None
        return True

    # -- edit data ---------------------------------------------------------

    def action_edit_data(self) -> None:
        self._edit_data()

    @work(exclusive=True, group="edit-data")
    async def _edit_data(self) -> None:
        """Pick a root field, then open its form."""
        field = await self.app.push_screen_wait(EditDataModal())
        if field == "armature":
            self.app.push_screen(ArmatureFormScreen(self.path))
        elif field == "mesh_roles":
            self.app.push_screen(MeshRolesFormScreen(self.path))
        elif field == "modifiers":
            self.app.push_screen(ModifiersFormScreen(self.path))

    # -- sections ----------------------------------------------------------

    def _show_fields(self) -> None:
        try:
            spec = Spec.load(self.path)
        except (OSError, ValueError):
            self._readable = False
        else:
            self._readable = True
            self.query_one("#armature-summary", FieldSummary).rows = (
                ("Name", spec.armature.object_name or _NOT_SET),
                ("Bones", str(len(spec.armature.required_bones))),
            )
            self.query_one("#mesh-roles-summary", FieldSummary).items = tuple(
                spec.mesh_roles
            )
            mods = spec.modifiers
            skinned = modifiers.format_list(mods.required.skinned_meshes)
            self.query_one("#modifiers-summary", FieldSummary).rows = (
                ("Required", (("skinned_meshes", skinned),)),
                *(
                    (label, modifiers.format_list(modifiers.get(mods, key)))
                    for label, key in _MODIFIER_ROWS
                ),
            )
        for summary in self.query(FieldSummary):
            summary.display = self._readable
        self.query_one("#spec-unreadable", Static).display = not self._readable
        self.refresh_bindings()
