import pytest
from coloraide import Color as Measured
from textual.color import Color

from model_meta.tui.theme import MCNUGGIES

# WCAG 2.2 SC 1.4.3. A terminal has no "large text", so every label needs 4.5.
TEXT = 4.5
# WCAG 2.2 SC 1.4.11: focus, selection and status borders.
NON_TEXT = 3.0

VARIABLES = MCNUGGIES.to_color_system().generate()

PAIRS = [
    ("text", "background", TEXT),
    ("text", "surface", TEXT),
    ("text-muted", "background", TEXT),
    ("text-muted", "surface", TEXT),
    ("text-error", "surface", TEXT),
    ("accent", "background", TEXT),
    ("accent", "surface", TEXT),
    ("warning", "background", TEXT),
    ("error", "background", TEXT),
    ("error", "surface", TEXT),
    ("success", "background", TEXT),
    ("block-cursor-foreground", "block-cursor-background", TEXT),
    ("text", "accent", TEXT),
    ("foreground", "panel", TEXT),
    ("footer-key-foreground", "footer-background", TEXT),
    ("primary", "background", NON_TEXT),
    ("primary", "surface", NON_TEXT),
    ("accent", "background", NON_TEXT),
    ("accent", "surface", NON_TEXT),
    ("warning", "background", NON_TEXT),
    ("scrollbar", "scrollbar-background", NON_TEXT),
]


def _resolve(name: str, backdrop: Color) -> Color:
    """Composite a variable onto ``backdrop``; ``auto N%`` is Textual's contrast text."""
    value = VARIABLES[name]
    if value.startswith("auto"):
        alpha = float(value.removeprefix("auto").strip().rstrip("%") or 100) / 100
        return backdrop + backdrop.get_contrast_text(alpha)
    return backdrop + Color.parse(value)


def _ratio(fore: str, back: str) -> float:
    backdrop = _resolve(back, Color.parse(VARIABLES["background"]))
    return Measured(_resolve(fore, backdrop).hex).contrast(backdrop.hex)


@pytest.mark.parametrize(("fore", "back", "minimum"), PAIRS)
def test_contrast(fore: str, back: str, minimum: float) -> None:
    ratio = _ratio(fore, back)
    assert ratio >= minimum, f"${fore} on ${back}: {ratio:.2f}:1, needs {minimum}:1"
