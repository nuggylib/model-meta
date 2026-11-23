"""Bounded, permission-tolerant scan for `.blend` files under a directory.

Pure filesystem logic — **no Textual, no UI**. Call `find_blend_files()` from a
Textual worker: on a large tree it can take a while, though the depth cap and
per-directory error tolerance keep it from running away or crashing.
"""

from pathlib import Path

BLEND_SUFFIX = ".blend"

# Exported so the UI can say where the scan stopped looking.
DEFAULT_MAX_DEPTH = 4


def find_blend_files(directory: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> list[Path]:
    """List every `.blend` file under `directory`, sorted; zero results is valid.

    Bounded by `max_depth`, permission-tolerant below the root, and never
    descends symlinked directories. Save backups (`.blend1`, `.blend2`) are
    excluded — the suffix match is exact and case-insensitive. A symlink to a
    `.blend` is kept.

    An unreadable `directory` **raises** rather than returning `[]`, so callers
    can tell "could not read" from "nothing here". A missing directory is the
    caller's to check with `is_dir()` first.
    """
    directory = directory.expanduser().resolve()
    results: list[Path] = []
    stack: list[tuple[Path, int]] = [(directory, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            if current == directory:
                raise  # the root itself — the caller must be able to say so
            continue  # unlistable descendant — skip, don't abort the whole scan
        for entry in entries:
            try:
                # `is_dir()`/`is_file()`/`is_symlink()` stat the child; a
                # readable-but-not-searchable (0o444) parent makes that raise
                # per entry.
                if entry.is_dir():
                    if depth < max_depth and not entry.is_symlink():
                        stack.append((entry, depth + 1))  # symlinks → no loops
                elif entry.is_file() and entry.suffix.lower() == BLEND_SUFFIX:
                    results.append(entry)
            except OSError:
                continue  # unstattable entry — skip it, keep its siblings
    return sorted(results)


def relative_label(model: Path, root: Path) -> str:
    """The model's path relative to its configured directory."""
    try:
        return str(model.relative_to(root.resolve()))
    except ValueError:
        # The scan resolves its root, so a symlinked dir yields outside paths.
        return model.name
