---
name: code-conventions
description: Code conventions for Model Meta. Use whenever writing, editing, or reviewing Python in this repo, and before adding or changing any comment or docstring. Sets a no-comment default — a comment or docstring is written only when it gives a senior developer who knows this codebase context they would otherwise lack.
---

# Model Meta code conventions

## Comments and docstrings

Default: **none**. The assumed reader knows Python, Textual, and this codebase,
including every directory's `CLAUDE.md`. Write one only when that reader would
still be stuck.

This applies equally to `#` comments, function and class docstrings, and module
docstrings. In this repo it takes precedence over any global comment skill.

### Keep

A reason that isn't visible in the code: an outside constraint, an order that
matters, a library quirk, a deliberate deviation.

```python
# "x" is O_EXCL: a replace would overwrite the file this exists to protect.
with path.open("x", encoding="utf-8") as f:
```

```python
if not isinstance(count, int) or isinstance(count, bool):  # bool is an int
```

A one-line docstring for a contract the signature can't show: what it raises,
what the caller must do first ("Pass it trimmed."), what `None` means.

### Cut

- What a line does, or a name restated in prose.
- Narration of UI flow or behavior the directory's `CLAUDE.md` already covers.
- Multi-paragraph module docstrings. Use one line, or nothing.
- `Args:`/`Returns:` sections that repeat type hints.
- Provenance: PR or issue numbers, plan files, "per review", dates, authors.
- New section banners. The existing `# -- name ---` dividers in `tui/screens/`
  can stay, but don't add banners of any other kind.

### Existing code

Older comments and docstrings were written before these rules, so don't copy
their length. Trim one only when you're already editing that code. Don't do
standalone cleanups.

### Check

Ask two questions of each comment or docstring:

1. Would a senior dev who knows this repo be stuck without it? If not, delete it.
2. Does it only make sense with context from outside the repo? If so, rewrite it
   or delete it.
