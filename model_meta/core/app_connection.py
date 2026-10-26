from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PathState(Enum):
    OK = "ok"
    INVALID = "invalid"
    MISSING = "missing"


@dataclass(frozen=True)
class AppConnection(ABC):
    """`path` is the app's executable, or the root it works under (Godot's projects root)."""

    path: Path

    def state(self) -> PathState:
        """Stat only: never runs or walks `path`, so it's safe on the event loop."""
        path = self.path.expanduser()
        if not path.exists():
            return PathState.MISSING
        return PathState.OK if self._accepts(path) else PathState.INVALID

    @abstractmethod
    def _accepts(self, path: Path) -> bool:
        """Whether an existing, expanded `path` is usable. Stat only."""
