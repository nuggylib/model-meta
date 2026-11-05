import asyncio
import json
import threading

import pytest
from textual.app import App
from textual.widgets import Static

from model_meta.core.blender_bridge import (
    Armatures,
    BridgeError,
    MeshReport,
    MeshTextures,
    MeshWeight,
    OpenFile,
    SceneMesh,
)
from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.results import FieldCheck, MeshRoleResult, Results
from model_meta.tui.screens import model_dashboard
from model_meta.tui.screens.model_dashboard import ModelDashboardScreen

_DROP = object()


class _Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


def _text(widget):
    return str(widget.render())


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _fake_running(monkeypatch, *answers):
    """Each check returns the next answer; an `Event` blocks until it is set."""
    calls = []

    def is_running(cls, timeout=5.0):
        answer = answers[min(len(calls), len(answers) - 1)]
        calls.append(answer)
        if isinstance(answer, threading.Event):
            answer.wait(5)
            return True
        return answer

    monkeypatch.setattr(BlenderConnection, "is_running", classmethod(is_running))
    return calls


def _fake_subscription(monkeypatch, name, wrap, *, reachable=True):
    """Each put is yielded to the screen, as `wrap(put, *args)` unless it is an `OpenFile`.

    `_DROP` closes the connection.
    """
    pushes = asyncio.Queue()

    async def subscribe(*args, port=7417, timeout=2.0):
        if not reachable:
            raise BridgeError("The Blender add-on isn't reachable.")
        while (message := await pushes.get()) is not _DROP:
            yield message if isinstance(message, OpenFile) else wrap(message, *args)
        raise BridgeError("The Blender add-on closed the connection.")

    monkeypatch.setattr(model_dashboard, name, subscribe)
    return pushes


def _passing_report(meshes, plan):
    """Every planned weight and texture passes, so only the scene meshes decide."""
    weights, textures = plan(meshes)
    return MeshReport(
        meshes,
        [MeshWeight(t.mesh, t.vertex_group, 10, 10, 10) for t in weights],
        [MeshTextures(t.mesh, dict.fromkeys(t.maps, True)) for t in textures],
    )


def _fake_bridge(monkeypatch, *, reachable=True):
    """Returns the armature pushes (a list is yielded as `Armatures`).

    The mesh subscription waits for pushes nobody sends; `_fake_meshes` replaces it.
    """
    _fake_meshes(monkeypatch, reachable=reachable)
    return _fake_subscription(
        monkeypatch, "subscribe_armatures", Armatures, reachable=reachable
    )


def _fake_meshes(monkeypatch, *, reachable=True):
    """Returns the mesh pushes: a list of `SceneMesh` is yielded as a passing report."""
    return _fake_subscription(
        monkeypatch, "subscribe_meshes", _passing_report, reachable=reachable
    )


@pytest.fixture(autouse=True)
def _no_bridge(monkeypatch):
    _fake_bridge(monkeypatch, reachable=False)


_ROLES = {
    "wheels": {
        "mesh_regex": r"wheel_hub\.(front|rear)\.[LR]",
        "vtx_grp": "wheel_hub.{1}.{2}",
        "count": 4,
        "weight": 1.0,
        "material_slots": ["rubber"],
    },
    "body": {"mesh_regex": "body", "vtx_grp": "body", "count": 1, "weight": 1.0},
}
_WHEELS = [
    SceneMesh(name, [name], ["rubber"])
    for name in (
        "wheel_hub.front.L",
        "wheel_hub.front.R",
        "wheel_hub.rear.L",
        "wheel_hub.rear.R",
    )
]
_SCENE = [SceneMesh("body", ["body"], ["paint"]), *_WHEELS]


def _screen(tmp_path, armature=None, passed=None, roles=None, role_results=None):
    """`passed` / `role_results` are the results already in the results file."""
    path = tmp_path / "vehicle.json"
    if armature is not None or roles is not None:
        spec = {"armature": {"object_name": armature or ""}, "mesh_roles": roles or {}}
        path.write_text(json.dumps(spec))
    model = tmp_path / "sedan.blend"
    model.touch()
    results_path = tmp_path / "sedan-results.json"
    Results(
        model_file=str(model),
        spec="vehicle",
        armature=passed,
        mesh_roles=role_results,
        path=results_path,
    ).create()
    return ModelDashboardScreen(model, path, results_path)


def _on_model(tmp_path):
    return OpenFile(str(tmp_path / "sedan.blend"))


def _saved(screen):
    return Results.load(screen.results_path).armature


def _status(screen):
    return _text(screen.query_one("#connection-status", Static))


def _hint(screen):
    return _text(screen.query_one("#connection-hint", Static))


def _rows(screen):
    return [_text(row) for row in screen.query(".model-item-depth-0")]


def _role_rows(screen):
    """The `Mesh Roles:` heading, then one row per role."""
    rows = [_text(row) for row in screen.query(".model-item") if row.id != "model-type"]
    start = next(i for i, row in enumerate(rows) if row.endswith(" Mesh Roles:"))
    return rows[start : start + 3]


async def test_running_blender_shows_manual_mode(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert _hint(screen) == "Press r to refresh."


async def test_no_blender_shows_inactive_and_hint(tmp_path, monkeypatch):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        assert _hint(screen) == "Start Blender, then press r to refresh."


async def test_rows_show_refreshing_emoji_until_the_check_returns(
    tmp_path, monkeypatch
):
    release = threading.Event()
    _fake_running(monkeypatch, release)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: screen.is_refreshing)
        assert all(row.startswith("🔄 ") for row in _rows(screen))
        release.set()
        assert await _wait_for(pilot, lambda: not screen.is_refreshing)
        assert all(row.startswith("🟡 ") for row in _rows(screen))
        assert _status(screen) == "Manual Mode"


async def test_r_checks_again(tmp_path, monkeypatch):
    calls = _fake_running(monkeypatch, False, True)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        await pilot.press("r")
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert len(calls) == 2
        assert _hint(screen) == "Press r to refresh."


@pytest.mark.parametrize(("passed", "emoji"), [(True, "✅"), (False, "❌")])
async def test_inactive_shows_the_saved_result(tmp_path, monkeypatch, passed, emoji):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path, "Rig", passed=passed)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        assert _rows(screen)[0] == f"{emoji} Armature: Rig"


async def test_r_rereads_the_results_file(tmp_path, monkeypatch):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        results = Results.load(screen.results_path)
        results.armature = True
        results.save()
        await pilot.press("r")
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))


async def test_unreadable_results_file_is_pending(tmp_path, monkeypatch):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path, "Rig", passed=True)
    screen.results_path.write_text("{", encoding="utf-8")
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        assert _rows(screen)[0] == "🟡 Armature: Rig"


async def test_reachable_add_on_shows_live_mode(tmp_path, monkeypatch):
    calls = _fake_running(monkeypatch, True)
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        assert (
            _hint(screen)
            == "Results update when you load a file, or save one, in Blender."
        )
        assert calls == []


async def test_armature_in_scene_passes_and_is_saved(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Other", "Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0] == "✅ Armature: Rig")
        assert _saved(screen) is True
        assert all(row.startswith("🟡 ") for row in _rows(screen)[1:])


async def test_armature_missing_from_scene_fails_and_is_saved(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig", passed=True)
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Other"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0] == "❌ Armature: Rig")
        assert _saved(screen) is False


async def test_unnamed_armature_fails(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(
            pilot, lambda: _rows(screen)[0] == "❌ Armature: not found"
        )


async def test_pushed_change_updates_the_armature_row(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Other"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("❌ "))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        assert _saved(screen) is True


async def test_save_keeps_other_keys_in_the_results_file(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    data = json.loads(screen.results_path.read_text(encoding="utf-8"))
    screen.results_path.write_text(json.dumps({**data, "note": "hand-added"}))
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        assert Results.load(screen.results_path).extra == {"note": "hand-added"}


async def test_armatures_before_the_open_file_are_not_saved(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, pushes.empty)
        await pilot.pause()
        assert _rows(screen)[0] == "🟡 Armature: Rig"
        assert _saved(screen) is None


async def test_busy_keeps_the_last_result(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        pushes.put_nowait(None)
        await pilot.pause()
        assert _rows(screen)[0].startswith("✅ ")
        assert _status(screen) == "Live Mode"


async def test_busy_before_a_result_is_pending(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(None)
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        assert _rows(screen)[0] == "🟡 Armature: Rig"


async def test_dropped_connection_keeps_the_saved_result(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        pushes.put_nowait(_DROP)
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert _rows(screen)[0] == "✅ Armature: Rig"
        assert _hint(screen) == "Press r to refresh."


async def _wrong_file_after(tmp_path, monkeypatch, *messages):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        for message in messages:
            pushes.put_nowait(message)
        assert await _wait_for(pilot, pushes.empty)
        await pilot.pause()
        return screen.wrong_file


async def test_model_file_open_is_the_right_file(tmp_path, monkeypatch):
    assert not await _wrong_file_after(tmp_path, monkeypatch, _on_model(tmp_path))


async def test_another_file_open_is_the_wrong_file(tmp_path, monkeypatch):
    other = tmp_path / "coupe.blend"
    other.touch()
    assert await _wrong_file_after(tmp_path, monkeypatch, OpenFile(str(other)))


async def test_unsaved_file_open_is_the_wrong_file(tmp_path, monkeypatch):
    assert await _wrong_file_after(tmp_path, monkeypatch, OpenFile(None))


async def test_symlink_to_the_model_is_the_right_file(tmp_path, monkeypatch):
    link = tmp_path / "link.blend"
    link.symlink_to(tmp_path / "sedan.blend")
    assert not await _wrong_file_after(tmp_path, monkeypatch, OpenFile(str(link)))


async def test_wrong_file_says_so_and_saves_nothing(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(OpenFile(None))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _status(screen) == "Wrong File")
        assert await _wait_for(pilot, pushes.empty)
        await pilot.pause()
        assert (
            _hint(screen)
            == "Blender doesn't have sedan.blend open. Results are paused until it does."
        )
        assert all(row.startswith("🟡 ") for row in _rows(screen))
        assert _saved(screen) is None


@pytest.mark.parametrize(("passed", "emoji"), [(True, "✅"), (False, "❌")])
async def test_wrong_file_shows_the_saved_result(tmp_path, monkeypatch, passed, emoji):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig", passed=passed)
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(OpenFile(None))
        pushes.put_nowait(["Rig"] if not passed else ["Other"])
        assert await _wait_for(pilot, pushes.empty)
        await pilot.pause()
        assert _status(screen) == "Wrong File"
        assert _rows(screen)[0] == f"{emoji} Armature: Rig"
        assert _saved(screen) is passed


async def test_leaving_the_model_file_keeps_its_saved_result(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        pushes.put_nowait(OpenFile(None))
        pushes.put_nowait(["Other"])
        assert await _wait_for(pilot, pushes.empty)
        await pilot.pause()
        assert _status(screen) == "Wrong File"
        assert _rows(screen)[0] == "✅ Armature: Rig"
        assert _saved(screen) is True


async def test_opening_the_model_file_resumes_live_mode(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig", passed=False)
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(OpenFile(None))
        assert await _wait_for(pilot, lambda: _status(screen) == "Wrong File")
        pushes.put_nowait(_on_model(tmp_path))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        assert _status(screen) == "Live Mode"
        assert _saved(screen) is True


async def test_opening_the_model_file_clears_the_wrong_file(tmp_path, monkeypatch):
    assert not await _wrong_file_after(
        tmp_path, monkeypatch, OpenFile(None), _on_model(tmp_path)
    )


async def _push_scene(tmp_path, monkeypatch, scene, expected, open_file=None):
    """Pushes `scene` on the mesh connection and waits for the role rows to read `expected`."""
    _fake_bridge(monkeypatch)
    meshes = _fake_meshes(monkeypatch)
    screen = _screen(tmp_path, "Rig", roles=_ROLES)
    async with _Host(screen).run_test() as pilot:
        meshes.put_nowait(open_file or _on_model(tmp_path))
        meshes.put_nowait(scene)
        assert await _wait_for(pilot, meshes.empty)
        assert await _wait_for(pilot, lambda: _role_rows(screen) == expected)
    return Results.load(screen.results_path).mesh_roles


async def test_matching_scene_passes_every_role_and_is_saved(tmp_path, monkeypatch):
    saved = await _push_scene(
        tmp_path, monkeypatch, _SCENE, ["✅ Mesh Roles:", "✅ wheels", "✅ body"]
    )
    assert list(saved) == ["wheels", "body"]
    assert saved["wheels"].meshes == [mesh.name for mesh in _WHEELS]
    assert all(check.passed for check in saved["wheels"].checks.values())


async def test_failing_role_fails_its_row_and_the_heading(tmp_path, monkeypatch):
    bare = SceneMesh("wheel_hub.rear.R", ["wheel_hub.rear.R"], [])
    saved = await _push_scene(
        tmp_path,
        monkeypatch,
        [*_SCENE[:-1], bare],
        ["❌ Mesh Roles:", "❌ wheels", "✅ body"],
    )
    assert saved["wheels"].checks["material_slots"] == FieldCheck(
        [{"mesh": "wheel_hub.rear.R", "missing": ["rubber"]}]
    )


async def test_mesh_report_on_the_wrong_file_is_not_saved(tmp_path, monkeypatch):
    saved = await _push_scene(
        tmp_path,
        monkeypatch,
        _SCENE,
        ["🟡 Mesh Roles:", "🟡 wheels", "🟡 body"],
        open_file=OpenFile(None),
    )
    assert saved is None


@pytest.mark.parametrize(
    ("wheels", "expected"),
    [
        (
            [{"expected": 4, "matched": 3}],
            ["❌ Mesh Roles:", "❌ wheels", "🟡 body"],
        ),
        ([], ["🟡 Mesh Roles:", "✅ wheels", "🟡 body"]),
    ],
)
async def test_inactive_shows_the_saved_role_results(
    tmp_path, monkeypatch, wheels, expected
):
    _fake_running(monkeypatch, False)
    role_results = {"wheels": MeshRoleResult([], {"count": FieldCheck(wheels)})}
    screen = _screen(tmp_path, "Rig", roles=_ROLES, role_results=role_results)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        assert _role_rows(screen) == expected


async def test_dropped_mesh_connection_falls_back_to_manual_mode(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    _fake_bridge(monkeypatch)
    meshes = _fake_meshes(monkeypatch)
    screen = _screen(tmp_path, "Rig", roles=_ROLES)
    async with _Host(screen).run_test() as pilot:
        meshes.put_nowait(_on_model(tmp_path))
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        meshes.put_nowait(_DROP)
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
