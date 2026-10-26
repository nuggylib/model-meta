import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import pytest

from model_meta.core.json_document import JsonDocument


@dataclass
class _Doc(JsonDocument):
    n: object = 0

    @classmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        if not isinstance(data.get("n"), int):
            raise ValueError("bad")
        return cls(path=path, n=data["n"])

    def to_dict(self) -> dict:
        return {"n": self.n}


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_abstract_base_cannot_be_instantiated(tmp_path):
    with pytest.raises(TypeError):
        JsonDocument(path=tmp_path / "doc.json")


def test_create_writes_indented_with_a_trailing_newline(tmp_path):
    path = tmp_path / "doc.json"
    _Doc(path=path).create()
    assert path.read_text(encoding="utf-8") == '{\n  "n": 0\n}\n'
    assert _Doc.load(path) == _Doc(path=path)


def test_create_makes_missing_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "doc.json"
    _Doc(path=path).create()
    assert path.is_file()


def test_create_refuses_to_overwrite(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 7})
    with pytest.raises(FileExistsError):
        _Doc(path=path).create()
    assert _read(path) == {"n": 7}


def test_create_of_an_invalid_document_writes_nothing(tmp_path):
    path = tmp_path / "nested" / "doc.json"
    with pytest.raises(ValueError, match="bad"):
        _Doc(path=path, n="x").create()
    assert not path.parent.exists()


@pytest.mark.parametrize("payload", [[], "text", 3, None])
def test_load_rejects_non_object_json(tmp_path, payload):
    path = tmp_path / "doc.json"
    _write(path, payload)
    with pytest.raises(ValueError, match="doc.json is not a JSON object"):
        _Doc.load(path)


def test_load_rejects_invalid_json(tmp_path):
    path = tmp_path / "doc.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError):
        _Doc.load(path)


def test_load_surfaces_from_dict(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": "x"})
    with pytest.raises(ValueError, match="bad"):
        _Doc.load(path)


def test_load_of_a_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        _Doc.load(tmp_path / "doc.json")


def test_load_keeps_the_path(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    assert _Doc.load(path).path == path


def test_equality_ignores_the_path(tmp_path):
    assert _Doc(path=tmp_path / "a.json") == _Doc(path=tmp_path / "b.json")


def test_save_persists_changes(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    doc = _Doc.load(path)
    doc.n = 2
    doc.save()
    assert _read(path) == {"n": 2}
    assert list(tmp_path.iterdir()) == [path]


def test_save_rejects_an_invalid_document_and_keeps_the_original(tmp_path):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})
    doc = _Doc.load(path)
    doc.n = "x"
    with pytest.raises(ValueError, match="bad"):
        doc.save()
    assert _read(path) == {"n": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_save_cleans_up_the_tmp_when_the_swap_fails(tmp_path, monkeypatch):
    path = tmp_path / "doc.json"
    _write(path, {"n": 1})

    def fail(*_):
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="locked"):
        _Doc(path=path, n=2).save()
    assert _read(path) == {"n": 1}
    assert list(tmp_path.iterdir()) == [path]
