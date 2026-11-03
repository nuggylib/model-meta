import asyncio
import json

import pytest

from model_meta.core.blender_bridge import (
    Armatures,
    BridgeError,
    OpenFile,
    subscribe_armatures,
)

_PAIR = [
    {"protocol": 1, "type": "get_filepath"},
    {"protocol": 1, "type": "subscribe_armatures"},
]


def _line(body):
    return (json.dumps({"protocol": 1, **body}) + "\n").encode()


def _success(*names):
    return _line({"status": "success", "result": {"armatures": list(names)}})


def _filepath(path):
    return _line({"status": "success", "result": {"filepath": path}})


def _error(message):
    return _line({"status": "error", "message": message})


async def _serve(*replies):
    """Each reply is the lines sent after reading one request pair; closes after the last.

    Returns (server, port, requests).
    """
    requests = []

    async def handle(reader, writer):
        for lines in replies:
            requests.append([json.loads(await reader.readline()) for _ in _PAIR])
            for line in lines:
                writer.write(line)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], requests


async def _collect(*replies):
    server, port, requests = await _serve(*replies)
    seen = []
    async with server:
        with pytest.raises(BridgeError) as info:
            async for message in subscribe_armatures(port=port):
                seen.append(message)
    return seen, str(info.value), requests


async def test_sends_filepath_then_subscribe_requests():
    _, _, requests = await _collect([])
    assert requests == [_PAIR]


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
    assert requests == [_PAIR, _PAIR]
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
    ],
)
async def test_unexpected_message_raises(body):
    _, message, _ = await _collect([_line(body)])
    assert message == "The Blender add-on sent an unexpected message."


async def test_unreachable_raises():
    server, port, _ = await _serve()
    server.close()
    await server.wait_closed()
    with pytest.raises(BridgeError, match="isn't reachable"):
        async for _ in subscribe_armatures(port=port):
            pass
