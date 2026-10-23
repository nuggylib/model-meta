"""The mesh role form — one role's name and fields, each edited on its own."""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, SelectionList, Static

from model_meta.specs import mesh_roles, schema, store
from model_meta.tui.widgets.field_list import FieldList

_NO_BONES = "Add required bones first."
_REQUIRED = ("mesh_regex", "vtx_grp", "count", "weight")
_INPUTS = {
    "mesh_regex": "#mesh-regex",
    "count": "#count",
    "weight": "#weight",
    "material_slots": "#material-slots",
}
_LISTED = (*_REQUIRED, "texture_maps")


class MeshRoleFormScreen(Screen[str]):
    """One mesh role, pushed as an instance; dismissed with its current name.

    One editor at a time (`_editing`); opening one discards the other
    unwritten. `escape` closes the open editor unsaved, else leaves. `q` is
    shadowed: the form holds an Input and a Button.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("m", "material_slots", "Material slots"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    MeshRoleFormScreen #mesh-role-form {
        height: auto;
        padding: 1 2 0 2;
    }
    MeshRoleFormScreen #role-status, MeshRoleFormScreen #role-name-view {
        height: auto;
    }
    MeshRoleFormScreen #role-bones, MeshRoleFormScreen #role-textures {
        height: auto;
        max-height: 8;
    }
    MeshRoleFormScreen .editor {
        height: auto;
        display: none;
    }
    MeshRoleFormScreen #role-column {
        height: 1fr;
        padding: 0 2;
    }
    MeshRoleFormScreen #role-fields {
        height: 1fr;
        margin-top: 1;
    }
    MeshRoleFormScreen #role-fields .field-list-child {
        color: $text-muted;
    }
    """

    def __init__(self, path: Path, name: str) -> None:
        super().__init__()
        self.path = path
        self.role = name
        self._editing: (
            Literal[
                "name",
                "vtx_grp",
                "mesh_regex",
                "count",
                "weight",
                "texture_maps",
                "material_slots",
            ]
            | None
        ) = None
        self._field_names: list[str] = []
        self._texture_choices: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="mesh-role-form"):
            yield Static(
                self._title(), id="role-title", classes="section-title", markup=False
            )
            yield FieldList("Name", "", id="role-name-view", classes="field-list")
            role_name = Input(id="role-name", classes="editor")
            role_name.border_title = "Name"
            yield role_name
            yield Static("", id="role-status", classes="config-detail", markup=False)
        with Vertical(id="role-column"):
            mesh_regex = Input(id="mesh-regex", classes="editor")
            mesh_regex.border_title = "mesh_regex"
            yield mesh_regex
            count = Input(id="count", classes="editor")
            count.border_title = "count"
            yield count
            weight = Input(id="weight", classes="editor")
            weight.border_title = "weight"
            yield weight
            material_slots = Input(id="material-slots", classes="editor")
            material_slots.border_title = "material_slots"
            yield material_slots
            with Vertical(id="vtx-grp-editor", classes="editor"):
                yield Static(
                    "", id="role-bones-label", classes="config-detail", markup=False
                )
                yield SelectionList[str](id="role-bones")
                yield Static(
                    "", id="role-preview", classes="config-detail", markup=False
                )
                yield Button("Save", id="save-vtx-grp", variant="primary")
            with Vertical(id="texture-maps-editor", classes="editor"):
                yield Static(
                    "", id="role-textures-label", classes="config-detail", markup=False
                )
                yield SelectionList[str](id="role-textures")
                yield Button("Save", id="save-texture-maps", variant="primary")
            yield FieldList(
                "Fields",
                "No fields.",
                cursor=True,
                id="role-fields",
                classes="field-list",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#role-fields", FieldList).focus()
        self._show()

    # -- bindings ----------------------------------------------------------

    def action_back(self) -> None:
        self._status("")
        if self._editing is None:
            self.dismiss(self.role)
        else:
            self._close()

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the form."""

    def action_material_slots(self) -> None:
        self._status("")
        if self._editing == "material_slots":
            self.query_one("#material-slots").focus()
            return
        self._edit_input("material_slots")

    # -- editors -----------------------------------------------------------

    @on(FieldList.Selected, "#role-name-view")
    def _edit_name(self) -> None:
        self._status("")
        self._close()
        self._editing = "name"
        self.query_one("#role-name-view").display = False
        role_name = self.query_one("#role-name", Input)
        role_name.value = self.role
        role_name.display = True
        role_name.focus()

    @on(FieldList.Selected, "#role-fields")
    def _on_field_selected(self, event: FieldList.Selected) -> None:
        self._status("")
        if event.index is None:
            return
        field = self._field_names[event.index]
        if field == "vtx_grp":
            self._edit_vtx_grp()
        elif field == "texture_maps":
            self._edit_texture_maps()
        elif field in _INPUTS:
            self._edit_input(field)
        else:
            self._status(f"'{field}' can't be edited here yet.")

    def _edit_vtx_grp(self) -> None:
        if self._editing == "vtx_grp":
            self.query_one("#role-bones").focus()
            return
        document = self._read()
        if document is None:
            return
        required = store.required_bones(document)
        if not required:
            self._status(_NO_BONES)
            return
        role = store.mesh_roles(document).get(self.role)
        if role is None:
            self._status(f"'{self.role}' is no longer a mesh role.")
            return
        self._close()
        self._editing = "vtx_grp"
        pattern = role.get("vtx_grp")
        checked = mesh_roles.matches(pattern, required) if pattern else []
        self._ask(required, checked)
        if pattern and not checked:
            self._status(f"Its vtx_grp '{pattern}' matches no required bone.")

    def _edit_texture_maps(self) -> None:
        if self._editing == "texture_maps":
            self.query_one("#role-textures").focus()
            return
        document = self._read()
        if document is None:
            return
        role = store.mesh_roles(document).get(self.role)
        if role is None:
            self._status(f"'{self.role}' is no longer a mesh role.")
            return
        self._close()
        self._editing = "texture_maps"
        current = role.get("texture_maps", [])
        self._texture_choices = mesh_roles.texture_choices(current)
        self.query_one("#role-textures-label", Static).update(
            f"Texture maps for '{self.role}'"
        )
        checklist = self.query_one("#role-textures", SelectionList)
        checklist.clear_options()
        checklist.add_options(
            [
                (Text(_texture_label(name)), name, name in current)
                for name in self._texture_choices
            ]
        )
        checklist.highlighted = 0
        self.query_one("#texture-maps-editor").display = True
        checklist.focus()

    def _edit_input(
        self, field: Literal["mesh_regex", "count", "weight", "material_slots"]
    ) -> None:
        document = self._read()
        if document is None:
            return
        role = store.mesh_roles(document).get(self.role)
        if role is None:
            self._status(f"'{self.role}' is no longer a mesh role.")
            return
        self._close()
        self._editing = field
        editor = self.query_one(_INPUTS[field], Input)
        value = role.get(field)
        if value is None:
            editor.value = ""
        elif field == "weight":
            editor.value = mesh_roles.format_weight(value)
        elif field == "material_slots":
            editor.value = mesh_roles.format_material_slots(value)
        else:
            editor.value = str(value)
        editor.display = True
        editor.focus()

    def _close(self) -> None:
        """Hide the open editor, dropping its in-progress state unwritten."""
        if self._editing == "name":
            self.query_one("#role-name", Input).display = False
            view = self.query_one("#role-name-view", FieldList)
            view.display = True
            view.focus()
        elif self._editing in _INPUTS:
            self.query_one(_INPUTS[self._editing], Input).display = False
            self.query_one("#role-fields", FieldList).focus()
        elif self._editing == "vtx_grp":
            self.query_one("#role-bones", SelectionList).clear_options()
            self.query_one("#role-preview", Static).update("")
            self.query_one("#vtx-grp-editor").display = False
            self.query_one("#role-fields", FieldList).focus()
        elif self._editing == "texture_maps":
            self.query_one("#role-textures", SelectionList).clear_options()
            self.query_one("#texture-maps-editor").display = False
            self.query_one("#role-fields", FieldList).focus()
        self._editing = None

    # -- the form ----------------------------------------------------------

    @on(Input.Submitted, "#role-name")
    def _on_name(self, event: Input.Submitted) -> None:
        self._status("")
        name = event.value.strip()
        document = self._read()
        if document is None:
            return
        others = [role for role in store.mesh_roles(document) if role != self.role]
        if error := mesh_roles.validate_name(name, others):
            self._status(error)
            return
        if not self._write(name):
            return
        self.role = name
        self.query_one("#role-title", Static).update(self._title())
        self._close()
        self._show()
        self._status(f"Mesh role '{name}' saved.")

    @on(Input.Submitted, "#mesh-regex")
    def _on_mesh_regex(self, event: Input.Submitted) -> None:
        self._status("")
        regex = event.value.strip()
        if error := mesh_roles.validate_mesh_regex(regex):
            self._status(error)
            return
        if not self._write(self.role, mesh_regex=regex):
            return
        self._saved("mesh_regex")

    @on(Input.Submitted, "#count")
    def _on_count(self, event: Input.Submitted) -> None:
        self._status("")
        try:
            count = mesh_roles.parse_count(event.value.strip())
        except ValueError as error:
            self._status(str(error))
            return
        if not self._write(self.role, count=count):
            return
        self._saved("count")

    @on(Input.Submitted, "#weight")
    def _on_weight(self, event: Input.Submitted) -> None:
        self._status("")
        try:
            weight = mesh_roles.parse_weight(event.value.strip())
        except ValueError as error:
            self._status(str(error))
            return
        if not self._write(self.role, weight=weight):
            return
        self._saved("weight")

    @on(Input.Submitted, "#material-slots")
    def _on_material_slots(self, event: Input.Submitted) -> None:
        self._status("")
        try:
            slots = mesh_roles.parse_material_slots(event.value.strip())
        except ValueError as error:
            self._status(str(error))
            return
        if not self._write(self.role, material_slots=slots):
            return
        self._saved("material_slots" if slots else "texture_maps")

    @on(Input.Changed, "#mesh-regex")
    @on(Input.Changed, "#count")
    @on(Input.Changed, "#weight")
    @on(Input.Changed, "#material-slots")
    def _on_input_changed(self) -> None:
        self._status("")

    @on(SelectionList.SelectedChanged, "#role-bones")
    def _on_bones_changed(self) -> None:
        self._preview()

    @on(Button.Pressed, "#save-vtx-grp")
    def _on_save(self) -> None:
        self._status("")
        try:
            pattern = self._infer()
        except ValueError as error:
            self._status(str(error))
            return
        if pattern is None or not self._write(self.role, pattern):
            return
        self._saved("vtx_grp")

    @on(Button.Pressed, "#save-texture-maps")
    def _on_save_texture_maps(self) -> None:
        self._status("")
        checked = self.query_one("#role-textures", SelectionList).selected
        maps = mesh_roles.order_texture_maps(checked, self._texture_choices)
        if not self._write(self.role, texture_maps=maps):
            return
        self._saved("texture_maps")

    def _saved(self, field: str) -> None:
        """Close the editor and re-render with the cursor on `field`."""
        self._close()
        self._show()
        self.query_one("#role-fields", FieldList).highlighted = self._field_names.index(
            field
        )
        self._status(f"Mesh role '{self.role}' saved.")

    def _write(
        self,
        new_name: str,
        vtx_grp: str | None = None,
        *,
        mesh_regex: str | None = None,
        count: int | None = None,
        weight: float | None = None,
        texture_maps: Sequence[str] | None = None,
        material_slots: Sequence[str] | None = None,
    ) -> bool:
        try:
            store.update_mesh_role(
                self.path,
                self.role,
                new_name,
                vtx_grp,
                mesh_regex=mesh_regex,
                count=count,
                weight=weight,
                texture_maps=texture_maps,
                material_slots=material_slots,
            )
        except (OSError, ValueError) as error:
            self._status(f"Could not write the spec: {_reason(error)}")
            return False
        return True

    # -- rendering ---------------------------------------------------------

    def _ask(self, required: list[str], checked: Collection[str]) -> None:
        """Show the bones checklist, `checked` pre-checked."""
        self.query_one("#role-bones-label", Static).update(f"Bones for '{self.role}'")
        checklist = self.query_one("#role-bones", SelectionList)
        checklist.clear_options()
        checklist.add_options(
            [(Text(bone), bone, bone in checked) for bone in required]
        )
        checklist.highlighted = 0
        self._preview()
        self.query_one("#vtx-grp-editor").display = True
        checklist.focus()

    def _preview(self) -> None:
        preview = self.query_one("#role-preview", Static)
        if not self.query_one("#role-bones", SelectionList).selected:
            preview.update("")
            return
        try:
            pattern = self._infer()
        except ValueError as error:
            preview.update(str(error))
            return
        preview.update("" if pattern is None else f"vtx_grp: {pattern}")

    def _infer(self) -> str | None:
        """The `vtx_grp` for the checked bones on a fresh read; raises `ValueError`."""
        document = self._read()
        if document is None:
            return None
        return mesh_roles.infer_vtx_grp(
            self.query_one("#role-bones", SelectionList).selected,
            store.required_bones(document),
        )

    def _show(self) -> None:
        document = self._read()
        if document is None:
            return
        role = store.mesh_roles(document).get(self.role)
        fields = self.query_one("#role-fields", FieldList)
        if role is None:
            self._field_names = []
            fields.lines = ()
            self._status(f"'{self.role}' is no longer a mesh role.")
            return
        self.query_one("#role-name-view", FieldList).lines = ((self.role, 0),)
        self._field_names, lines = _field_lines(role, store.required_bones(document))
        fields.lines = tuple(lines)
        marked: set[int] = set()
        for field in _INPUTS.keys() & _REQUIRED:
            if role.get(field) in (None, ""):
                start = lines.index((f"{field}: not set", 0))
                marked |= {start, start + 1}
        fields.marked = frozenset(marked)

    def _read(self) -> dict | None:
        try:
            return store.read(self.path)
        except (OSError, ValueError) as error:
            self._status(f"Could not read the spec: {_reason(error)}")
            return None

    def _title(self) -> str:
        return f"Mesh role — {self.role}"

    def _status(self, text: str) -> None:
        self.query_one("#role-status", Static).update(text)


def _field_lines(
    role: dict, required: Sequence[str]
) -> tuple[list[str], list[tuple[str, int]]]:
    """`key: value` per field, any description beneath; required fields first."""
    slots = ["material_slots"] if role.get("material_slots") else []
    others = (key for key in role if key not in (*_LISTED, "material_slots"))
    keys = [*_LISTED, *slots, *others]
    lines: list[tuple[str, int]] = []
    for key in keys:
        if key == "mesh_regex":
            regex = role.get("mesh_regex")
            lines.append((f"mesh_regex: {regex or 'not set'}", 0))
            if not regex:
                lines.append(("required: the meshes in this role", 1))
        elif key == "vtx_grp":
            pattern = role.get("vtx_grp")
            lines.append((f"vtx_grp: {pattern or 'not set'}", 0))
            if pattern:
                lines.append((_matches(pattern, required), 1))
        elif key == "count":
            count = role.get("count")
            lines.append((f"count: {'not set' if count is None else count}", 0))
            if count is None:
                lines.append(("required: how many meshes mesh_regex matches", 1))
        elif key == "weight":
            weight = role.get("weight")
            if weight is None:
                lines.append(("weight: not set", 0))
                lines.append(("required: the weight its meshes carry on vtx_grp", 1))
            else:
                lines.append((f"weight: {mesh_roles.format_weight(weight)}", 0))
        elif key == "texture_maps":
            maps = role.get("texture_maps")
            lines.append((f"texture_maps: {', '.join(maps) if maps else 'none'}", 0))
        elif key == "material_slots":
            slots_text = mesh_roles.format_material_slots(role["material_slots"])
            lines.append((f"material_slots: {slots_text}", 0))
        else:
            lines.append((f"{key}: {_value(role[key])}", 0))
    return keys, lines


def _matches(pattern: str, required: Sequence[str]) -> str:
    matched = mesh_roles.matches(pattern, required)
    return f"matches {', '.join(matched)}" if matched else "matches no required bone"


def _texture_label(name: str) -> str:
    return name if name in schema.TEXTURE_MAPS else f"{name} (not a Godot map)"


def _value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value) or "(empty)"
    return _text(value)


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _reason(error: Exception) -> str:
    return str(getattr(error, "strerror", None) or error)
