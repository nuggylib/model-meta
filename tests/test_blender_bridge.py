import asyncio
import json
from contextlib import aclosing

import pytest

from model_meta.core.blender_bridge import (
    Armatures,
    BridgeError,
    MeshModifiers,
    MeshReport,
    MeshTarget,
    MeshTextures,
    MeshUvs,
    MeshWeight,
    OpenFile,
    SceneMesh,
    TextureTarget,
    WeightTarget,
    subscribe_armatures,
    subscribe_meshes,
)

_PAIR = [
    {"protocol": 1, "type": "get_filepath"},
    {"protocol": 1, "type": "get_version"},
    {"protocol": 1, "type": "subscribe_armatures"},
]
_OLD_ADDON = 'unknown type: "get_version"'


def _line(body):
    return (json.dumps({"protocol": 1, **body}) + "\n").encode()


def _result(result):
    return _line({"status": "success", "result": result})


def _success(*names):
    return _result({"armatures": list(names)})


def _filepath(path):
    return _result({"filepath": path})


def _error(message):
    return _line({"status": "error", "message": message})


async def _serve(respond):
    """`respond(request)` returns the lines to send back; a `None` among them closes.

    Returns (server, port, requests).
    """
    requests = []

    async def handle(reader, writer):
        while line := await reader.readline():
            request = json.loads(line)
            requests.append(request)
            for reply in respond(request):
                if reply is None:
                    writer.close()
                    return
                writer.write(reply)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], requests


def _subscriptions(*replies, version):
    """Answers each subscribe with the next reply, then closes after the last."""
    remaining = list(replies)

    def respond(request):
        if request["type"] == "get_filepath":
            return []
        if request["type"] == "get_version":
            return [version]
        return [*remaining.pop(0), *([] if remaining else [None])]

    return respond


_VERSION = _result({"version": "0.3.0"})


async def _collect(*replies, version=_VERSION):
    server, port, requests = await _serve(_subscriptions(*replies, version=version))
    seen = []
    async with server:
        with pytest.raises(BridgeError) as info:
            async for message in subscribe_armatures(port=port):
                seen.append(message)
    return seen, str(info.value), requests


async def test_sends_filepath_version_then_subscribe_requests():
    _, _, requests = await _collect([])
    assert requests == _PAIR


async def test_an_addon_without_get_version_still_yields_armatures():
    seen, _, _ = await _collect(
        [_filepath(None), _success("Rig")], version=_error(_OLD_ADDON)
    )
    assert seen == [OpenFile(None), Armatures(["Rig"])]


async def test_yields_the_open_file_then_each_armature_list():
    seen, _, _ = await _collect(
        [_filepath("/models/sedan.blend"), _success("Rig"), _success("Rig", "Rig.001")]
    )
    assert seen == [
        OpenFile("/models/sedan.blend"),
        Armatures(["Rig"]),
        Armatures(["Rig", "Rig.001"]),
    ]


async def test_never_saved_file_is_none():
    seen, _, _ = await _collect([_filepath(None)])
    assert seen == [OpenFile(None)]


async def test_empty_list_is_a_result():
    seen, _, _ = await _collect([_filepath(None), _success()])
    assert seen == [OpenFile(None), Armatures([])]


async def test_busy_yields_no_names():
    seen, _, _ = await _collect([_filepath(None), _error("busy"), _success("Rig")])
    assert seen == [OpenFile(None), Armatures(None), Armatures(["Rig"])]


async def test_another_file_opening_subscribes_again():
    seen, _, requests = await _collect(
        [_filepath("/a.blend"), _success("Rig"), _filepath("/b.blend")],
        [_filepath("/b.blend"), _success("Other")],
    )
    assert requests == [*_PAIR, *_PAIR]
    assert seen == [
        OpenFile("/a.blend"),
        Armatures(["Rig"]),
        OpenFile("/b.blend"),
        Armatures(["Other"]),
    ]


async def test_closed_connection_raises():
    seen, message, _ = await _collect([_filepath(None)])
    assert seen == [OpenFile(None)]
    assert message == "The Blender add-on closed the connection."


async def test_error_raises_with_its_message():
    seen, message, _ = await _collect([_error('unknown type: "get_filepath"')])
    assert seen == []
    assert message == 'The Blender add-on reported: unknown type: "get_filepath"'


@pytest.mark.parametrize("line", [b"not json\n", b"[1]\n"])
async def test_invalid_json_raises(line):
    _, message, _ = await _collect([line])
    assert message == "The Blender add-on sent invalid JSON."


@pytest.mark.parametrize("version", [2, True, None])
async def test_unsupported_protocol_raises(version):
    line = (json.dumps({"protocol": version, "status": "success"}) + "\n").encode()
    _, message, _ = await _collect([line])
    assert message == f"Unsupported add-on protocol: {json.dumps(version)}."


@pytest.mark.parametrize(
    "body",
    [
        {"status": "success"},
        {"status": "success", "result": []},
        {"status": "success", "result": {"armatures": "Rig"}},
        {"status": "success", "result": {"armatures": [1]}},
        {"status": "success", "result": {"filepath": 1}},
        {"status": "success", "result": {"meshes_revision": 1}},
        {"status": "success", "result": {"version": 1}},
        {"status": "error", "message": "stale"},
    ],
)
async def test_unexpected_message_raises(body):
    _, message, _ = await _collect([_line(body)])
    assert message == "The Blender add-on sent an unexpected message."


async def test_unreachable_raises():
    server, port, _ = await _serve(lambda _request: [None])
    server.close()
    await server.wait_closed()
    with pytest.raises(BridgeError, match="isn't reachable"):
        async for _ in subscribe_armatures(port=port):
            pass


_WHEEL = {
    "name": "wheel_hub.front.L",
    "vertex_groups": ["wheel_hub.front.L", "paint"],
    "material_slots": ["rubber"],
}
_BODY = {
    "name": "body",
    "vertex_groups": ["body"],
    "material_slots": ["paint", "glass"],
}
_SCENE_BODY = SceneMesh("body", ["body"], ["paint", "glass"])


class _FakeAddon:
    """Answers mesh requests one item per page, so every list takes several pages.

    `reports` maps a targeted request type to each target's item fields, keyed by the
    target's `(mesh,)` or `(mesh, vertex_group)`. `saves` maps a request's index to
    `"before"` or `"after"`: a save/load bumps the revision and pushes it before or
    after that request's answer. `answers` maps a request type to `f(lines)`, which
    returns what to send in place of `lines`. A `None` `version` answers `get_version`
    like an add-on that predates it.
    """

    def __init__(self, meshes, reports=None, saves=None, answers=None, version="0.4.0"):
        self.revision = 1
        self.meshes = meshes
        self.reports = reports or {}
        self.version = version
        self.saves = saves or {}
        self.answers = answers or {}
        self._index = 0

    def respond(self, request):
        save = self.saves.get(self._index)
        self._index += 1
        before = self._save() if save == "before" else []
        lines = self._answer(request)
        after = self._save() if save == "after" else []
        change = self.answers.get(request["type"], lambda lines: lines)
        return [*before, *change(lines), *after]

    def _save(self):
        self.revision += 1
        return [_result({"meshes_revision": self.revision})]

    def _answer(self, request):
        kind = request["type"]
        if kind == "get_filepath":
            return [_filepath("/models/sedan.blend")]
        if kind == "get_version":
            if self.version is None:
                return [_error(_OLD_ADDON)]
            return [_result({"version": self.version})]
        if kind == "subscribe_meshes":
            return [_result({"meshes_revision": self.revision})]
        if request["revision"] != self.revision:
            return [_error("stale")]
        key = kind.removeprefix("get_")
        items = self.meshes if kind == "get_meshes" else self._items(request)
        cursor = request["cursor"]
        more = cursor + 1 < len(items)
        return [
            _result(
                {
                    "revision": self.revision,
                    key: items[cursor : cursor + 1],
                    "has_more": more,
                    "next_cursor": cursor + 1 if more else None,
                }
            )
        ]

    def _items(self, request):
        reports = self.reports[request["type"]]
        items = []
        for target in request["meshes"]:
            named = {k: target[k] for k in ("mesh", "vertex_group") if k in target}
            items.append({**named, **reports[tuple(named.values())]})
        return items


def _no_targets(_meshes):
    return [], [], [], []


async def _collect_meshes(addon, plan=_no_targets, count=2):
    server, port, requests = await _serve(addon.respond)
    seen = []
    async with server:
        async with aclosing(subscribe_meshes(plan, port=port)) as messages:
            async for message in messages:
                seen.append(message)
                if len(seen) == count:
                    break
    return seen, requests


def _paged(requests):
    return [
        (request["type"], request["revision"], request["cursor"])
        for request in requests
        if request["type"].startswith("get_mesh")
    ]


async def test_meshes_subscribes_then_follows_every_page():
    seen, requests = await _collect_meshes(_FakeAddon([_BODY, _WHEEL]))
    assert requests[:3] == [
        {"protocol": 1, "type": "get_filepath"},
        {"protocol": 1, "type": "get_version"},
        {"protocol": 1, "type": "subscribe_meshes"},
    ]
    assert _paged(requests) == [("get_meshes", 1, 0), ("get_meshes", 1, 1)]
    assert seen == [
        OpenFile("/models/sedan.blend"),
        MeshReport(
            [
                _SCENE_BODY,
                SceneMesh(
                    "wheel_hub.front.L", ["wheel_hub.front.L", "paint"], ["rubber"]
                ),
            ],
            [],
            [],
            [],
            [],
        ),
    ]


async def test_no_meshes_is_a_report():
    seen, _ = await _collect_meshes(_FakeAddon([]))
    assert seen[1] == MeshReport([], [], [], [], [])


async def test_plan_targets_are_fetched_in_order():
    planned = []

    def plan(meshes):
        planned.append(meshes)
        return (
            [
                WeightTarget("wheel_hub.front.L", "wheel_hub.front.L", 1.0),
                WeightTarget("body", "body", 0.5),
            ],
            [TextureTarget("wheel_hub.front.L", ["albedo", "orm"])],
            [MeshTarget("wheel_hub.front.L")],
            [MeshTarget("wheel_hub.front.L"), MeshTarget("body")],
        )

    addon = _FakeAddon(
        [_BODY, _WHEEL],
        reports={
            "get_mesh_weights": {
                ("wheel_hub.front.L", "wheel_hub.front.L"): {
                    "vertices": 340,
                    "assigned": 328,
                    "at_weight": 300,
                },
                ("body", "body"): {"error": "no vertex group"},
            },
            "get_mesh_textures": {
                ("wheel_hub.front.L",): {"maps": {"albedo": True, "orm": False}}
            },
            "get_mesh_uvs": {
                ("wheel_hub.front.L",): {
                    "faces": 6,
                    "has_default_uv_map": True,
                    "uv_maps": [{"name": "UVMap", "zero_area": 0}],
                }
            },
            "get_mesh_modifiers": {
                ("wheel_hub.front.L",): {"modifiers": ["ARMATURE", "MIRROR"]},
                ("body",): {"modifiers": []},
            },
        },
    )
    seen, requests = await _collect_meshes(addon, plan)
    assert [mesh.name for mesh in planned[0]] == ["body", "wheel_hub.front.L"]
    weight_requests = [r for r in requests if r["type"] == "get_mesh_weights"]
    assert weight_requests[0]["meshes"] == [
        {
            "mesh": "wheel_hub.front.L",
            "vertex_group": "wheel_hub.front.L",
            "weight": 1.0,
        },
        {"mesh": "body", "vertex_group": "body", "weight": 0.5},
    ]
    assert _paged(requests)[2:] == [
        ("get_mesh_weights", 1, 0),
        ("get_mesh_weights", 1, 1),
        ("get_mesh_textures", 1, 0),
        ("get_mesh_uvs", 1, 0),
        ("get_mesh_modifiers", 1, 0),
        ("get_mesh_modifiers", 1, 1),
    ]
    assert seen[1].weights == [
        MeshWeight("wheel_hub.front.L", "wheel_hub.front.L", 340, 328, 300),
        MeshWeight("body", "body", error="no vertex group"),
    ]
    assert seen[1].textures == [
        MeshTextures("wheel_hub.front.L", {"albedo": True, "orm": False})
    ]
    assert seen[1].uvs == [MeshUvs("wheel_hub.front.L", True)]
    assert seen[1].modifiers == [
        MeshModifiers("wheel_hub.front.L", ["ARMATURE", "MIRROR"]),
        MeshModifiers("body", []),
    ]


async def test_a_mesh_gone_from_the_textures_is_an_error():
    def plan(_meshes):
        return [], [TextureTarget("body", ["albedo"])], [], []

    addon = _FakeAddon(
        [_BODY], reports={"get_mesh_textures": {("body",): {"error": "no mesh"}}}
    )
    seen, _ = await _collect_meshes(addon, plan)
    assert seen[1].textures == [MeshTextures("body", {}, "no mesh")]


async def test_a_mesh_in_edit_mode_is_a_uv_error():
    def plan(_meshes):
        return [], [], [MeshTarget("body")], []

    addon = _FakeAddon(
        [_BODY], reports={"get_mesh_uvs": {("body",): {"error": "in edit mode"}}}
    )
    seen, _ = await _collect_meshes(addon, plan)
    assert seen[1].uvs == [MeshUvs("body", False, "in edit mode")]


async def test_a_mesh_gone_from_the_modifiers_is_an_error():
    def plan(_meshes):
        return [], [], [], [MeshTarget("body")]

    addon = _FakeAddon(
        [_BODY], reports={"get_mesh_modifiers": {("body",): {"error": "no mesh"}}}
    )
    seen, _ = await _collect_meshes(addon, plan)
    assert seen[1].modifiers == [MeshModifiers("body", [], "no mesh")]


def _uvs_and_modifiers(_meshes):
    return [], [], [MeshTarget("body")], [MeshTarget("body")]


@pytest.mark.parametrize("version", [None, "0.1.0", "dev"])
async def test_an_addon_before_uvs_skips_uvs_and_modifiers(version):
    addon = _FakeAddon([_BODY], version=version)
    seen, requests = await _collect_meshes(addon, _uvs_and_modifiers)
    assert _paged(requests) == [("get_meshes", 1, 0)]
    assert seen[1] == MeshReport([_SCENE_BODY], [], [], None, None)


async def test_an_addon_before_modifiers_skips_them():
    addon = _FakeAddon(
        [_BODY],
        reports={"get_mesh_uvs": {("body",): {"has_default_uv_map": False}}},
        version="0.3.0",
    )
    seen, requests = await _collect_meshes(addon, _uvs_and_modifiers)
    assert _paged(requests) == [("get_meshes", 1, 0), ("get_mesh_uvs", 1, 0)]
    assert seen[1] == MeshReport([_SCENE_BODY], [], [], [MeshUvs("body", False)], None)


async def test_each_save_sends_a_new_report():
    # Request 3 is the only page; the save lands after it is answered.
    addon = _FakeAddon([_BODY], saves={3: "after"})
    seen, requests = await _collect_meshes(addon, count=3)
    assert _paged(requests) == [("get_meshes", 1, 0), ("get_meshes", 2, 0)]
    assert seen[1:] == [MeshReport([_SCENE_BODY], [], [], [], [])] * 2


@pytest.mark.parametrize("when", ["before", "after"])
async def test_a_save_mid_fetch_starts_again_at_the_new_revision(when):
    # Request 3 is the first of two pages.
    addon = _FakeAddon([_BODY, _WHEEL], saves={3: when})
    seen, requests = await _collect_meshes(addon)
    # Saved after: page 1 was answered, so page 2 is asked for and comes back stale.
    first = [("get_meshes", 1, 0), *([("get_meshes", 1, 1)] if when == "after" else [])]
    assert _paged(requests) == [*first, ("get_meshes", 2, 0), ("get_meshes", 2, 1)]
    assert [mesh.name for mesh in seen[1].meshes] == ["body", "wheel_hub.front.L"]


async def test_busy_waits_for_the_answer():
    addon = _FakeAddon(
        [_BODY], answers={"get_meshes": lambda lines: [_error("busy"), *lines]}
    )
    seen, _ = await _collect_meshes(addon)
    assert seen[1].meshes == [_SCENE_BODY]


_LAST = {"has_more": False, "next_cursor": None}


async def _meshes_error(meshes_answer):
    addon = _FakeAddon([], answers={"get_meshes": lambda _lines: [meshes_answer]})
    server, port, _ = await _serve(addon.respond)
    async with server:
        with pytest.raises(BridgeError) as info:
            async for _ in subscribe_meshes(_no_targets, port=port):
                pass
    return str(info.value)


@pytest.mark.parametrize(
    "result",
    [
        {"revision": 1, "meshes": [{"name": "body"}], **_LAST},
        {"revision": 1, "meshes": [], "has_more": True, "next_cursor": None},
        {"revision": 1, "meshes": "body", **_LAST},
        {"revision": 1, "mesh_weights": [], **_LAST},
        {"revision": 1, "mesh_uvs": [], **_LAST},
        {"revision": 1, "mesh_modifiers": [], **_LAST},
    ],
)
async def test_an_unexpected_page_raises(result):
    message = await _meshes_error(_result(result))
    assert message == "The Blender add-on sent an unexpected message."


async def test_a_failed_query_raises_with_its_message():
    message = await _meshes_error(_error("query failed: boom"))
    assert message == "The Blender add-on reported: query failed: boom"
