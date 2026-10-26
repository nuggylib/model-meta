from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from model_meta.core.app_connection import AppConnection, PathState


class _Dir(AppConnection):
    def _accepts(self, path: Path) -> bool:
        return path.is_dir()


class _Unreachable(AppConnection):
    def _accepts(self, path: Path) -> bool:
        raise AssertionError("_accepts ran for a missing path")


def test_the_abstract_base_cannot_be_instantiated(tmp_path):
    with pytest.raises(TypeError):
        AppConnection(tmp_path)


def test_a_missing_path_is_missing_without_asking_the_hook(tmp_path):
    assert _Unreachable(tmp_path / "nope").state() is PathState.MISSING


def test_an_accepted_path_is_ok(tmp_path):
    assert _Dir(tmp_path).state() is PathState.OK


def test_a_rejected_path_is_invalid(tmp_path):
    file = tmp_path / "file"
    file.write_text("", encoding="utf-8")
    assert _Dir(file).state() is PathState.INVALID


def test_a_home_relative_path_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "apps").mkdir()
    assert _Dir(Path("~/apps")).state() is PathState.OK


def test_a_connection_is_frozen(tmp_path):
    connection = _Dir(tmp_path)
    with pytest.raises(FrozenInstanceError):
        connection.path = tmp_path / "other"


def test_connections_with_equal_paths_are_equal(tmp_path):
    assert _Dir(tmp_path) == _Dir(tmp_path)
    assert _Dir(tmp_path) != _Dir(tmp_path / "other")
