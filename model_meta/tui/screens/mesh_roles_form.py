"""The mesh roles form — add mesh role after mesh role, or open one."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, SelectionList, Static

from model_meta.specs import mesh_roles, store
from model_meta.tui.screens.confirm_modal import ConfirmModal
from model_meta.tui.screens.mesh_role_form import MeshRoleFormScreen
from model_meta.tui.widgets.field_list import FieldList

_EMPTY = "No mesh roles yet."
_NO_BONES = "Add required bones first."


class MeshRolesFormScreen(Screen):
    """Stay-on form for a spec's mesh roles, pushed as an instance.

    Opening a role, or a confirmed delete, discards an Add in progress
    unwritten. `x` works only from a focused, non-empty role list. `escape`
    hides the bones question back to the name, clears a non-empty name, closes
    the Add editor from an empty one, and leaves when it is closed. `q` is
    shadowed: the form holds an Input and a Button.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add", "Add"),
        Binding("x", "delete_role", "Delete"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    MeshRolesFormScreen #mesh-roles-form {
        height: auto;
        padding: 1 2 0 2;
    }
    MeshRolesFormScreen #role-status, MeshRolesFormScreen #role-bones-question {
        height: auto;
    }
    MeshRolesFormScreen #role-bones {
        height: auto;
        max-height: 8;
    }
    MeshRolesFormScreen .editor {
        height: auto;
        display: none;
    }
    MeshRolesFormScreen #role-column {
        height: 1fr;
        padding: 0 2;
    }
    MeshRolesFormScreen #role-list {
        height: 1fr;
        margin-top: 1;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._adding = False
        self._name: str | None = None
        self._role_names: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="mesh-roles-form"):
            yield Static(
                f"Mesh roles — {escape(self.path.stem)}", classes="section-title"
            )
            yield Static("", id="role-status", classes="config-detail", markup=False)
        with Vertical(id="role-column"):
            with Vertical(id="role-editor", classes="editor"):
                yield Static("Role name", classes="config-detail")
                yield Input(id="role-name")
                question = Vertical(id="role-bones-question")
                question.display = False
                with question:
                    yield Static(
                        "", id="role-bones-label", classes="config-detail", markup=False
                    )
                    yield SelectionList[str](id="role-bones")
                    yield Static(
                        "", id="role-preview", classes="config-detail", markup=False
                    )
                    role_regex = Input(id="role-regex")
                    role_regex.border_title = "Mesh regex"
                    yield role_regex
                    role_count = Input(id="role-count")
                    role_count.border_title = "Count"
                    yield role_count
                    role_weight = Input(id="role-weight")
                    role_weight.border_title = "Weight"
                    yield role_weight
                    yield Button("Add", id="confirm-role", variant="primary")
            yield FieldList(
                "Mesh roles", _EMPTY, cursor=True, id="role-list", classes="field-list"
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#role-list", FieldList).focus()
        self._show_roles()

    # -- bindings ----------------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if action == "delete_role":
            focused = self.focused
            on_list = focused is not None and focused.id == "role-list"
            return on_list and bool(self._role_names)
        return True

    def action_back(self) -> None:
        self._status("")
        name = self.query_one("#role-name", Input)
        if not self._adding:
            self.app.pop_screen()
        elif self._name is not None:
            self._drop_question()
            name.focus()
        elif name.value:
            name.value = ""
        else:
            self._close()

    def action_add(self) -> None:
        self._status("")
        if not self._adding:
            if self._gate() is None:
                return
            self._open()
        target = "#role-name" if self._name is None else "#role-bones"
        self.query_one(target).focus()

    def action_delete_role(self) -> None:
        index = self.query_one("#role-list", FieldList).highlighted
        if index is not None:
            self._delete_role(self._role_names[index])

    @work(exclusive=True, group="delete-role")
    async def _delete_role(self, name: str) -> None:
        """Ask Yes/No; on Yes, discard any Add and delete `name` alone."""
        question = ConfirmModal(f"Delete mesh role '{name}'?")
        if not await self.app.push_screen_wait(question):
            return
        self._status("")
        self._close()
        try:
            store.delete_mesh_role(self.path, name)
        except (OSError, ValueError) as error:
            self._show_roles()
            self._status(f"Could not write the spec: {_reason(error)}")
        else:
            self._show_roles()
            self._status(f"Mesh role '{name}' deleted.")
        self.query_one("#role-list", FieldList).focus()

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the form."""

    # -- the list and the Add editor ---------------------------------------

    @on(FieldList.Selected, "#role-list")
    def _on_selected(self, event: FieldList.Selected) -> None:
        if event.index is None:
            self.action_add()
            return
        self._status("")
        name = self._role_names[event.index]
        document = self._read()
        if document is None:
            return
        if name not in store.mesh_roles(document):
            self._status(f"'{name}' is no longer a mesh role.")
            self._show_roles()
            return
        self._close()
        self._open_role(name)

    @work(exclusive=True, group="role-view")
    async def _open_role(self, name: str) -> None:
        """Push the role's own view; on return, follow it under its current name."""
        current = await self.app.push_screen_wait(MeshRoleFormScreen(self.path, name))
        self._show_roles()
        if current in self._role_names:
            role_list = self.query_one("#role-list", FieldList)
            role_list.highlighted = self._role_names.index(current)

    def _gate(self) -> dict | None:
        """A fresh read when the spec has bones to check, else `None` (status set)."""
        document = self._read()
        if document is not None and not store.required_bones(document):
            self._status(_NO_BONES)
            return None
        return document

    def _open(self) -> None:
        self._adding = True
        self.query_one("#role-editor").display = True

    def _close(self) -> None:
        """Hide the Add editor, dropping its in-progress state unwritten."""
        if not self._adding:
            return
        self._adding = False
        self._drop_question()
        self.query_one("#role-name", Input).value = ""
        self.query_one("#role-editor").display = False
        self.query_one("#role-list", FieldList).focus()

    # -- the form ----------------------------------------------------------

    @on(Input.Submitted, "#role-name")
    def _on_name(self, event: Input.Submitted) -> None:
        self._status("")
        name = event.value.strip()
        self._drop_question()
        document = self._check_name(name)
        if document is not None:
            self._ask(name, store.required_bones(document))

    @on(SelectionList.SelectedChanged, "#role-bones")
    def _on_bones_changed(self) -> None:
        self._preview()

    @on(Button.Pressed, "#confirm-role")
    @on(Input.Submitted, "#role-regex")
    @on(Input.Submitted, "#role-count")
    @on(Input.Submitted, "#role-weight")
    def _on_confirm(self) -> None:
        self._status("")
        name = self._name
        if name is None:
            return
        pattern = self._infer_or_report()
        if pattern is None:
            return
        role_regex = self.query_one("#role-regex", Input)
        regex = role_regex.value.strip()
        if error := mesh_roles.validate_mesh_regex(regex):
            self._status(error)
            role_regex.focus()
            return
        role_count = self.query_one("#role-count", Input)
        try:
            count = mesh_roles.parse_count(role_count.value.strip())
        except ValueError as error:
            self._status(str(error))
            role_count.focus()
            return
        role_weight = self.query_one("#role-weight", Input)
        try:
            weight = mesh_roles.parse_weight(role_weight.value.strip())
        except ValueError as error:
            self._status(str(error))
            role_weight.focus()
            return
        try:
            store.add_mesh_role(self.path, name, pattern, regex, count, weight)
        except (OSError, ValueError) as error:
            self._status(f"Could not write the spec: {_reason(error)}")
            return
        self._drop_question()
        role_name = self.query_one("#role-name", Input)
        role_name.value = ""
        role_name.focus()
        self._show_roles()
        self._status(f"Mesh role '{name}' added.")

    # -- rendering ---------------------------------------------------------

    def _check_name(self, name: str) -> dict | None:
        """A fresh read when `name` is a valid new role name."""
        document = self._read()
        if document is None:
            return None
        if error := mesh_roles.validate_name(name, store.mesh_roles(document)):
            self._status(error)
            return None
        return document

    def _ask(self, name: str, required: list[str]) -> None:
        """Show the bones question for `name`, nothing checked."""
        self._name = name
        self.query_one("#role-bones-label", Static).update(f"Bones for '{name}'")
        checklist = self.query_one("#role-bones", SelectionList)
        checklist.clear_options()
        checklist.add_options([(Text(bone), bone) for bone in required])
        if checklist.option_count:
            checklist.highlighted = 0
        self._preview()
        self.query_one("#role-bones-question").display = True
        checklist.focus()

    def _preview(self) -> None:
        preview = self.query_one("#role-preview", Static)
        if (
            self._name is None
            or not self.query_one("#role-bones", SelectionList).selected
        ):
            preview.update("")
            return
        try:
            pattern = self._infer()
        except ValueError as error:
            preview.update(str(error))
            return
        preview.update("" if pattern is None else f"vtx_grp: {pattern}")

    def _infer_or_report(self) -> str | None:
        try:
            return self._infer()
        except ValueError as error:
            self._status(str(error))
            return None

    def _infer(self) -> str | None:
        """The `vtx_grp` for the checked bones on a fresh read; raises `ValueError`."""
        document = self._read()
        if document is None:
            return None
        return mesh_roles.infer_vtx_grp(
            self.query_one("#role-bones", SelectionList).selected,
            store.required_bones(document),
        )

    def _drop_question(self) -> None:
        self._name = None
        self.query_one("#role-bones", SelectionList).clear_options()
        self.query_one("#role-preview", Static).update("")
        self.query_one("#role-regex", Input).value = ""
        self.query_one("#role-count", Input).value = ""
        self.query_one("#role-weight", Input).value = ""
        self.query_one("#role-bones-question").display = False

    def _show_roles(self) -> None:
        document = self._read()
        if document is None:
            return
        roles = store.mesh_roles(document)
        self._role_names = list(roles)
        self.refresh_bindings()
        lines: list[tuple[str, int]] = []
        marked: set[int] = set()
        for name, role in roles.items():
            lines.append((name, 0))
            if not role.get("mesh_regex"):
                marked.add(len(lines))
            lines.append((f"mesh_regex: {role.get('mesh_regex') or 'not set'}", 1))
            if "vtx_grp" in role:
                lines.append((f"vtx_grp: {role['vtx_grp']}", 1))
            if "count" not in role:
                marked.add(len(lines))
            lines.append((f"count: {role.get('count', 'not set')}", 1))
            if "weight" in role:
                weight = mesh_roles.format_weight(role["weight"])
            else:
                marked.add(len(lines))
                weight = "not set"
            lines.append((f"weight: {weight}", 1))
            maps = role.get("texture_maps")
            lines.append((f"texture_maps: {', '.join(maps) if maps else 'none'}", 1))
            if slots := role.get("material_slots"):
                slots_text = mesh_roles.format_material_slots(slots)
                lines.append((f"material_slots: {slots_text}", 1))
        role_list = self.query_one("#role-list", FieldList)
        role_list.lines = tuple(lines)
        role_list.marked = frozenset(marked)

    def _read(self) -> dict | None:
        try:
            return store.read(self.path)
        except (OSError, ValueError) as error:
            self._status(f"Could not read the spec: {_reason(error)}")
            return None

    def _status(self, text: str) -> None:
        self.query_one("#role-status", Static).update(text)


def _reason(error: Exception) -> str:
    return str(getattr(error, "strerror", None) or error)
