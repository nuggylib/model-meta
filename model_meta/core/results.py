from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from model_meta.core.json_document import JsonDocument

_RESULTS_KEYS = ("model_file", "spec")


@dataclass
class Results(JsonDocument):
    model_file: str
    spec: str
    extra: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def path_for(results_dir: Path, model_file: Path) -> Path:
        """Pass `model_file` absolute."""
        # The hash keeps same-named models in different directories apart.
        digest = hashlib.sha1(str(model_file).encode("utf-8")).hexdigest()[:8]
        return results_dir / f"{model_file.stem}-{digest}.json"

    @classmethod
    def from_dict(cls, data: dict, *, path: Path) -> Self:
        model_file = data.get("model_file")
        if not isinstance(model_file, str):
            raise ValueError("`model_file` is not a string.")
        spec = data.get("spec")
        if not isinstance(spec, str):
            raise ValueError("`spec` is not a string.")
        extra = {key: value for key, value in data.items() if key not in _RESULTS_KEYS}
        return cls(model_file=model_file, spec=spec, extra=extra, path=path)

    def to_dict(self) -> dict:
        return {"model_file": self.model_file, "spec": self.spec, **self.extra}
