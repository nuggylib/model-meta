from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, TextIO


def read_json(path: Path) -> dict:
    """Raises `OSError`, or `ValueError` when the file isn't a JSON object."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object.")
    return data


def write_json(path: Path, data: dict) -> None:
    """Atomic: a crash leaves the old file, never a half-written one."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            _dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def create_json(path: Path, data: dict) -> None:
    """Raises `FileExistsError` rather than overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # "x" is O_EXCL: a replace would overwrite the file this exists to protect.
    with path.open("x", encoding="utf-8") as f:
        _dump(data, f)


@dataclass
class JsonDocument(ABC):
    path: Path = field(kw_only=True, compare=False)

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        """Raise `ValueError` if `data` is malformed."""

    @abstractmethod
    def to_dict(self) -> dict:
        """The JSON object `save` and `create` write."""

    @classmethod
    def load(cls, path: Path) -> Self:
        """Raises `OSError`, or `ValueError` for a malformed document."""
        return cls.from_dict(read_json(path), path=path)

    def save(self) -> None:
        """Raises `ValueError` for a malformed document, before touching disk."""
        write_json(self.path, self._checked())

    def create(self) -> None:
        """Raises `FileExistsError` rather than overwrite, or `ValueError` like `save`."""
        create_json(self.path, self._checked())

    def _checked(self) -> dict:
        # Python doesn't enforce field types, so re-parse what would be written.
        data = self.to_dict()
        type(self).from_dict(data, path=self.path)
        return data


def _dump(data: dict, f: TextIO) -> None:
    json.dump(data, f, indent=2)
    f.write("\n")
