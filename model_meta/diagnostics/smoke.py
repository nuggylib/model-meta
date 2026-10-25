"""Headless launch smoke test — the packaging gate.

Booting the app through Textual's headless pilot forces the stylesheet to parse
and the full import graph to resolve, so a missing ``app.tcss`` or hidden import
fails here instead of in a user's terminal. The release pipeline runs this
against each freshly built binary (via ``model-meta --check``) before
uploading anything.
"""

import asyncio

from textual.app import App

# The smoke test's own budget. A mount-and-teardown is near-instant; this only
# guards against a wedged event loop in a frozen binary, so it belongs to the
# check rather than to the app.
_CHECK_TIMEOUT_SECONDS = 30


async def run_headless_check(
    app: App, timeout_seconds: float = _CHECK_TIMEOUT_SECONDS
) -> None:
    """Mount `app` headlessly and tear it down, raising if it fails to launch.

    Kept as an importable coroutine (not reachable only via ``main()``) so tests
    can await it directly under ``asyncio_mode = "auto"`` without nesting
    ``asyncio.run()``.
    """
    async with asyncio.timeout(timeout_seconds):
        async with app.run_test(size=(80, 24)):
            pass
    if app.return_code not in (0, None):
        raise SystemExit(f"headless check failed (return code {app.return_code})")
