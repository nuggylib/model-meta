"""Covers the non-interactive CLI surface the release pipeline depends on:
``model-meta --version`` and ``model-meta --check``, plus the ``--setup``
flag's routing into the app (without spinning up a real TTY).
"""

import pytest

import model_meta
import model_meta.app
from model_meta.app import ModelMetaApp, main
from model_meta.diagnostics import run_headless_check


def test_version_flag_echoes_version(capsys):
    # argparse's action="version" prints then exits 0.
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert model_meta.__version__ in capsys.readouterr().out


async def test_check_mounts_headlessly_and_succeeds():
    # Awaited directly (not via main()'s asyncio.run) so it composes with the
    # loop pytest-asyncio already provides. Regression guard for the app.tcss
    # bundling fix: a stylesheet or hidden-import failure raises here.
    await run_headless_check(ModelMetaApp())


@pytest.fixture(autouse=True)
def _no_legacy_migration(monkeypatch):
    """Keep main() off the developer's real config dir."""
    calls = []
    monkeypatch.setattr(model_meta.app.legacy_dir, "migrate", lambda: calls.append(1))
    return calls


class _FakeApp:
    """Stand-in for ModelMetaApp so we can assert wiring without a TTY."""

    def __init__(self, force_setup: bool = False) -> None:
        self.force_setup = force_setup
        self.ran = False

    def run(self) -> None:
        self.ran = True


def test_setup_flag_launches_app_in_setup_mode(monkeypatch):
    created = {}
    monkeypatch.setattr(
        model_meta.app,
        "ModelMetaApp",
        lambda **kwargs: created.setdefault("app", _FakeApp(**kwargs)),
    )
    main(["--setup"])
    assert created["app"].force_setup is True
    assert created["app"].ran is True


def test_bare_invocation_does_not_force_setup(monkeypatch):
    created = {}
    monkeypatch.setattr(
        model_meta.app,
        "ModelMetaApp",
        lambda **kwargs: created.setdefault("app", _FakeApp(**kwargs)),
    )
    main([])
    assert created["app"].force_setup is False
    assert created["app"].ran is True


def test_launch_migrates_legacy_config_dir_first(monkeypatch, _no_legacy_migration):
    monkeypatch.setattr(model_meta.app, "ModelMetaApp", lambda **kwargs: _FakeApp())
    main([])
    assert _no_legacy_migration == [1]


def test_check_skips_legacy_migration(monkeypatch, _no_legacy_migration):
    async def _noop(app):
        return None

    monkeypatch.setattr("model_meta.app.run_headless_check", _noop)
    main(["--check"])
    assert _no_legacy_migration == []
