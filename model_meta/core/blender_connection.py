import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Self

from model_meta.core.app_connection import AppConnection


class ProbeOutcome(Enum):
    OK = "ok"  # ran and identified itself as Blender
    NOT_FOUND = "not-found"  # nothing at that path / not on PATH
    NOT_EXE = "not-exe"  # exists but can't be executed (perms, wrong format, a dir)
    TIMEOUT = "timeout"  # started but didn't respond in time
    UNPARSEABLE = "unparseable"  # ran, but output isn't Blender's `--version`


@dataclass(frozen=True)
class ProbeResult:
    """`version` is set only when `outcome is OK`."""

    outcome: ProbeOutcome
    version: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is ProbeOutcome.OK


class BlenderConnection(AppConnection):
    @classmethod
    def candidates(cls) -> list[Self]:
        """Existing installs at the platform's standard locations, best first."""
        if sys.platform == "darwin":
            base = ["/Applications/Blender.app/Contents/MacOS/Blender"]
        elif sys.platform == "win32":
            # The version dir varies (Blender 4.5, 4.4, …) — glob real installs.
            base = [
                str(p)
                for p in Path(r"C:\Program Files\Blender Foundation").glob(
                    "*/blender.exe"
                )
            ]
        else:
            base = ["/usr/bin/blender", "/usr/local/bin/blender"]

        found = [Path(p) for p in base if Path(p).exists()]
        which = shutil.which("blender")
        if which:
            found.append(Path(which))

        # `which` may repeat a base path; dict keys keep the first occurrence.
        return [cls(path) for path in dict.fromkeys(found)]

    def _accepts(self, path: Path) -> bool:
        if sys.platform == "win32":  # no POSIX exec bit
            return path.is_file()
        # A `.app` bundle is a directory, but it's what a macOS user picks.
        if sys.platform == "darwin" and path.suffix == ".app" and path.is_dir():
            return True
        return path.is_file() and os.access(path, os.X_OK)

    def probe(self, timeout: float = 10.0) -> ProbeResult:
        """Blocks on a subprocess, so call it from a worker. Never raises."""
        try:
            proc = subprocess.run(
                [self.path, "--version"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return ProbeResult(ProbeOutcome.NOT_FOUND, message="No file at that path.")
        except (PermissionError, OSError):
            # IsADirectoryError, exec-format errors, permission denied, etc.
            return ProbeResult(
                ProbeOutcome.NOT_EXE, message="Not an executable Blender binary."
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(
                ProbeOutcome.TIMEOUT, message="Blender did not respond (timed out)."
            )

        if proc.returncode == 0:
            # Scan for `Blender X.Y.Z` rather than trusting line 0, so a leading
            # banner can't be mistaken for the version.
            for raw_line in proc.stdout.splitlines():
                line = raw_line.strip()
                if line.startswith("Blender "):
                    return ProbeResult(
                        ProbeOutcome.OK, version=line.removeprefix("Blender").strip()
                    )

        return ProbeResult(
            ProbeOutcome.UNPARSEABLE, message="That program is not Blender."
        )

    @classmethod
    def is_running(cls, timeout: float = 5.0) -> bool:
        """Blocks on a subprocess, so call it from a worker. Never raises."""
        if sys.platform == "win32":
            cmd = ["tasklist", "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"]
        else:
            cmd = ["ps", "-A", "-o", "comm="]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

        if sys.platform == "win32":
            # With no match, tasklist prints an INFO line rather than nothing.
            return '"blender.exe"' in proc.stdout.casefold()
        # macOS lists the full path, and `blender-thumbnailer` must not match.
        return any(
            Path(line.strip()).name.casefold() == "blender"
            for line in proc.stdout.splitlines()
        )
