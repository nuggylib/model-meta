"""`JsonFile` through a test-only subclass, against `tmp_path` — no Textual."""

import json
import os

import pytest

from model_meta.core.json_file import JsonFile


class _Doc(JsonFile):
    def default(self) -> dict:
        return {"n": 0}

    def validate(self, document: dict) -> None:
        if "bad" in document:
            raise ValueError("bad")


class _BadDefault(_Doc):
    def default(self) -> dict:
        return {"bad": 1}


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_the_abstract_base_cannot_be_instantiated(tmp_path):
    with pytest.raises(TypeError):
        JsonFile(tmp_path / "doc.json")


def test_create_writes_the_default_indented_with_a_trailing_newline(tmp_path):
    path = tmp_path / "doc.json"
    _Doc(path).create()
    assert path.read_text(encoding="utf-8") == '{\n  "n": 0\n}\n'
    assert _Doc(path).read() == {"n": 0}


def test_create_makes_missing_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "doc.json"
    _Doc(path).create()
    assert path.is_file()


def test_create_refuses_to_overwrite(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 7})
    with pytest.raises(FileExistsError):
        _Doc(path).create()
    assert json.loads(path.read_text(encoding="utf-8")) == {"n": 7}


def test_create_with_an_invalid_default_writes_nothing(tmp_path):
    path = tmp_path / "nested" / "doc.json"
    with pytest.raises(ValueError, match="bad"):
        _BadDefault(path).create()
    assert not path.parent.exists()


@pytest.mark.parametrize("payload", [[], "text", 3, None])
def test_read_rejects_non_object_json(tmp_path, payload):
    path = tmp_path / "doc.json"
    _write(path, payload)
    with pytest.raises(ValueError, match="doc.json is not a JSON object"):
        _Doc(path).read()


def test_read_surfaces_validate(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"bad": 1})
    with pytest.raises(ValueError, match="bad"):
        _Doc(path).read()


def test_read_of_a_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        _Doc(tmp_path / "doc.json").read()


def test_replace_rejects_an_invalid_document_and_keeps_the_original(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    with pytest.raises(ValueError, match="bad"):
        _Doc(path).replace({"bad": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"n": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_replace_cleans_up_the_tmp_when_the_swap_fails(tmp_path, monkeypatch):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})

    def fail(*_):
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="locked"):
        _Doc(path).replace({"n": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"n": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_edit_persists_in_place_changes(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    with _Doc(path).edit() as document:
        document["n"] = 2
    assert _Doc(path).read() == {"n": 2}


def test_edit_discards_changes_when_the_body_raises(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    with pytest.raises(RuntimeError), _Doc(path).edit() as document:
        document["n"] = 2
        raise RuntimeError
    assert _Doc(path).read() == {"n": 1}


def test_edit_discards_changes_that_fail_validation(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    with pytest.raises(ValueError, match="bad"), _Doc(path).edit() as document:
        document["bad"] = 1
    assert _Doc(path).read() == {"n": 1}
