import pytest

from model_meta.app import ModelMetaApp


@pytest.fixture(autouse=True)
def _no_blender(monkeypatch):
    """Booting the app would otherwise run the developer's real Blender."""
    monkeypatch.setattr(ModelMetaApp, "_find_blender", lambda self, settings: None)
