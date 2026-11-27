from textual.theme import Theme

# Unset colors fall back to `primary` (textual/design.py), so status colors read
# as purple until each is picked against the contrast rules.
MCNUGGIES = Theme(
    name="mcnuggies",
    primary="#C003FF",
    secondary="#03DAFF",
    accent="#FFF903",
    warning="#FFBF00",
    error="#FF002C",
    success="#42FF03",
    # foreground=,
    background="#121212",
    surface="#000000",
    panel="#363636",
    # Theme(boost=) is ignored when panel is set (textual/design.py), so it goes here.
    variables={
        "boost": "#03DAFF",
        "text-muted": "#888888",
        # "scrollbar": ,
        # "scrollbar-background": ,
        # "scrollbar-hover": ,
        # "scrollbar-active": ,
        # "footer-key-foreground": ,
        # "footer-background": ,
        # "block-cursor-foreground": ,
        # "block-cursor-background": ,
    },
)
