from textual.theme import Theme

# Unset colors fall back to `primary` (textual/design.py), so status colors read
# as purple until each is picked against the contrast rules.
MCNUGGIES = Theme(
    name="mcnuggies",
    primary="#C003FF",
    # secondary=,
    # accent=,
    # warning=,
    # error=,
    # success=,
    # foreground=,
    # background=,
    # surface=,
    # panel=,
    # boost=,
)
