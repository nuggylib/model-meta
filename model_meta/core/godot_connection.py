from pathlib import Path

from model_meta.core.app_connection import AppConnection

PROJECT_MARKER = "project.godot"


class GodotConnection(AppConnection):
    def _accepts(self, path: Path) -> bool:
        return path.is_dir()

    def find_projects(self, max_depth: int = 4) -> list[Path]:
        """Walks the tree, so call it from a worker. Absolute paths, sorted."""
        root = self.path.expanduser().resolve()
        results: list[Path] = []
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            try:
                entries = list(directory.iterdir())
            except OSError:
                continue  # unlistable dir — skip, don't abort the whole scan
            if any(e.name == PROJECT_MARKER for e in entries):
                results.append(directory)
                continue  # a project root — don't descend into it
            if depth < max_depth:
                for e in entries:
                    try:
                        # Symlinks are skipped, so no loops. `is_dir()`/`is_symlink()`
                        # stat the child; a readable-but-not-searchable (0o444)
                        # parent makes that raise per entry.
                        if e.is_dir() and not e.is_symlink():
                            stack.append((e, depth + 1))
                    except OSError:
                        continue  # unstattable entry — skip it, keep its siblings
        return sorted(results)
