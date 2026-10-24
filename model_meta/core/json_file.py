from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


class JsonFile(ABC):
    """One JSON object on disk, validated on every read and write."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @abstractmethod
    def default(self) -> dict:
        """The document `create` writes."""

    @abstractmethod
    def validate(self, document: dict) -> None:
        """Raise `ValueError` if `document` is malformed."""

    def read(self) -> dict:
        """Raises `OSError`, or `ValueError` for a malformed document."""
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self._check(document)
        return document

    def create(self) -> None:
        """Write `default()`. Raises `FileExistsError` rather than overwrite."""
        document = self.default()
        self._check(document)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # "x" is O_EXCL: a replace would overwrite the file this exists to protect.
        with self.path.open("x", encoding="utf-8") as f:
            _dump(document, f)

    def replace(self, document: dict) -> None:
        """Raises `ValueError` for a malformed document, before touching disk."""
        self._check(document)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                _dump(document, f)
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @contextmanager
    def edit(self) -> Iterator[dict]:
        """Read, yield for in-place changes, then replace. A raise skips the write."""
        document = self.read()
        yield document
        self.replace(document)

    def _check(self, document: object) -> None:
        if not isinstance(document, dict):
            raise ValueError(f"{self.path.name} is not a JSON object.")
        self.validate(document)


def _dump(document: dict, f: TextIO) -> None:
    json.dump(document, f, indent=2)
    f.write("\n")
