# model_meta/tui/templates/

Base `Screen` classes that page screens subclass for a shared frame.

## Contents
- `layout.py` — `Layout(page_title)`: `Header`, a fixed `#heading`, a
  scrolling `#body`, then `AppFooter`. `#heading` holds the optional
  `description` and whatever `compose_heading()` yields; it sits outside the
  scroller, so it stays on screen while `#body` scrolls. `#body` holds what
  `compose_body()` yields. Both hooks default to nothing. `escape` pops the
  screen, except onto Textual's default screen.

## Conventions
- Styles live in `app.tcss`: `.layout-heading-content` (the heading, with a
  margin under each child and a `$panel` bottom border) and `.body`, which
  starts right under the border. An empty heading drops its border but keeps
  its top margin, so the gap under the `Header` stays.
- Put a page's identifying info (what it's about, its connection status) in
  `compose_heading()`; put anything that can grow past one screen in
  `compose_body()`.
