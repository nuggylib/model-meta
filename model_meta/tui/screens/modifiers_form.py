"""The Modifiers form — the spec's four modifier lists, each edited on its own."""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, SelectionList, Static

from model_meta.core.spec import Modifiers, Spec
from model_meta.specs import modifiers, schema, store
from model_meta.tui.widgets.field_list import FieldList

_KEYS = {
    "skinned_meshes": "required.skinned_meshes",
    "allowed": "allowed",
    "warn": "warn",
    "fail": "fail",
}
_DESCRIPTIONS = {
    "skinned_meshes": "must be on every skinned mesh",
    "allowed": "allowed anywhere: safe in Godot or harmless",
    "warn": "warns on export: apply it to reach Godot",
    "fail": "fails validation: breaks geometry when applied",
}


class ModifiersFormScreen(Screen):
    """The spec's `modifiers`, pushed as an instance.

    One checklist at a time (`_editing`); opening another list's discards the
    open one unwritten. `escape` closes it unsaved, else leaves. `q` is
    shadowed: the form holds a Button.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    ModifiersFormScreen #modifiers-form {
        height: auto;
        padding: 1 2 0 2;
    }
    ModifiersFormScreen #modifiers-status {
        height: auto;
    }
    ModifiersFormScreen #modifier-choices {
        height: auto;
        max-height: 8;
    }
    ModifiersFormScreen .editor {
        height: auto;
        display: none;
    }
    ModifiersFormScreen #modifiers-column {
        height: 1fr;
        padding: 0 2;
    }
    ModifiersFormScreen #modifier-fields {
        height: 1fr;
        margin-top: 1;
    }
    ModifiersFormScreen #modifier-fields .field-list-child {
        color: $text-muted;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._editing: str | None = None
        self._field_names: list[str] = []
        self._choices: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="modifiers-form"):
            yield Static("Modifiers", id="modifiers-title", classes="section-title")
            yield Static(
                "", id="modifiers-status", classes="config-detail", markup=False
            )
        with Vertical(id="modifiers-column"):
            with Vertical(id="modifiers-editor", classes="editor"):
                yield Static(
                    "", id="modifiers-label", classes="config-detail", markup=False
                )
                yield SelectionList[str](id="modifier-choices")
                yield Button("Save", id="save-modifiers", variant="primary")
            yield FieldList(
                "Fields",
                "No fields.",
                cursor=True,
                id="modifier-fields",
                classes="field-list",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#modifier-fields", FieldList).focus()
        self._show()

    # -- bindings ----------------------------------------------------------

    def action_back(self) -> None:
        self._status("")
        if self._editing is None:
            self.dismiss()
        else:
            self._close()

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the form."""

    # -- the editor --------------------------------------------------------

    @on(FieldList.Selected, "#modifier-fields")
    def _on_field_selected(self, event: FieldList.Selected) -> None:
        self._status("")
        if event.index is None:
            return
        field = self._field_names[event.index]
        if field in modifiers.LISTS:
            self._edit(field)
        else:
            self._status(f"'{field}' can't be edited here yet.")

    def _edit(self, field: str) -> None:
        if self._editing == field:
            self.query_one("#modifier-choices").focus()
            return
        spec = self._read()
        if spec is None:
            return
        self._close()
        self._editing = field
        mods = spec.modifiers
        current = modifiers.get(mods, field)
        clashes = modifiers.conflicts(mods, field)
        self._choices = modifiers.choices(mods)
        self.query_one("#modifiers-label", Static).update(f"{_KEYS[field]} modifiers")
        checklist = self.query_one("#modifier-choices", SelectionList)
        checklist.clear_options()
        checklist.add_options(
            [
                (Text(_label(name, clashes.get(name, []))), name, name in current)
                for name in self._choices
            ]
        )
        checklist.highlighted = 0
        self.query_one("#modifiers-editor").display = True
        checklist.focus()

    def _close(self) -> None:
        """Hide the open checklist, dropping its checks unwritten."""
        if self._editing is not None:
            self.query_one("#modifier-choices", SelectionList).clear_options()
            self.query_one("#modifiers-editor").display = False
            self.query_one("#modifier-fields", FieldList).focus()
        self._editing = None

    @on(Button.Pressed, "#save-modifiers")
    def _on_save(self) -> None:
        self._status("")
        field = self._editing
        if field is None:
            return
        checked = set(self.query_one("#modifier-choices", SelectionList).selected)
        moved: dict[str, list[str]] = {}

        def edit(mods: Modifiers) -> Modifiers:
            moved.clear()
            moved.update(_moves(mods, field, checked))
            return modifiers.assign(mods, field, checked)

        try:
            store.update_modifiers(self.path, edit)
        except (OSError, ValueError) as error:
            self._status(f"Could not write the spec: {_reason(error)}")
            return
        self._close()
        self._show()
        fields = self.query_one("#modifier-fields", FieldList)
        fields.highlighted = self._field_names.index(field)
        self._status(" ".join(["Modifiers saved.", *_moved_text(moved)]))

    # -- rendering ---------------------------------------------------------

    def _show(self) -> None:
        spec = self._read()
        if spec is None:
            return
        self._field_names, lines = _field_lines(spec.modifiers)
        self.query_one("#modifier-fields", FieldList).lines = tuple(lines)

    def _read(self) -> Spec | None:
        try:
            return Spec.load(self.path)
        except (OSError, ValueError) as error:
            self._status(f"Could not read the spec: {_reason(error)}")
            return None

    def _status(self, text: str) -> None:
        self.query_one("#modifiers-status", Static).update(text)


def _field_lines(mods: Modifiers) -> tuple[list[str], list[tuple[str, int]]]:
    """Each list with its description beneath, then the extras as written."""
    names: list[str] = []
    lines: list[tuple[str, int]] = []
    for field in modifiers.LISTS:
        names.append(field)
        value = modifiers.format_list(modifiers.get(mods, field))
        lines.append((f"{_KEYS[field]}: {value}", 0))
        lines.append((_DESCRIPTIONS[field], 1))
    extras = [
        *((f"required.{key}", value) for key, value in mods.required.extra.items()),
        *mods.extra.items(),
    ]
    for key, value in extras:
        names.append(key)
        lines.append((f"{key}: {_value(value)}", 0))
    return names, lines


def _label(name: str, clashes: list[str]) -> str:
    tags = [] if name in schema.MODIFIERS else ["(not a listed modifier)"]
    if "skinned_meshes" in clashes:
        tags.append("(required)")
    if others := [other for other in clashes if other != "skinned_meshes"]:
        tags.append(f"(in {', '.join(others)})")
    return " ".join([name, *tags])


def _moves(
    mods: Modifiers, field: str, checked: Collection[str]
) -> dict[str, list[str]]:
    """The checked names each conflicting list loses, by list."""
    moved: dict[str, list[str]] = {}
    for name, lists in modifiers.conflicts(mods, field).items():
        if name in checked:
            for other in lists:
                moved.setdefault(other, []).append(name)
    return moved


def _moved_text(moved: dict[str, list[str]]) -> list[str]:
    parts = [
        f"{', '.join(moved[key])} out of {_KEYS[key]}"
        for key in modifiers.LISTS
        if key in moved
    ]
    return [f"Moved {'; '.join(parts)}."] if parts else []


def _value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value) or "(empty)"
    return _text(value)


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _reason(error: Exception) -> str:
    return str(getattr(error, "strerror", None) or error)
