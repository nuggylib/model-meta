from textual.theme import Theme

# Unset colors fall back to `primary` (textual/design.py), so status colors read
# as purple until each is picked against the contrast rules.
MCNUGGIES = Theme(
    name="mcnuggies",
    primary="#C003FF",
    secondary="#704180",
    accent="#FFF903",
    warning="#FFBF00",
    error="#FF002C",
    success="#42FF03",
    # foreground=,
    background="#121212",
    surface="#000000",
    panel="#363636",
    boost="#518041",
)
