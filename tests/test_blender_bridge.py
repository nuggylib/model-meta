import asyncio
import json

import pytest

from model_meta.core.blender_bridge import BridgeError, subscribe_armatures


def _line(body):
    return (json.dumps({"protocol": 1, **body}) + "\n").encode()


def _success(*names):
    return _line({"status": "success", "result": {"armatures": list(names)}})


def _error(message):
    return _line({"status": "error", "message": message})


async def _serve(*lines):
    """Records the request, sends `lines`, then closes. Returns (server, port, requests)."""
    requests = []

    async def handle(reader, writer):
        requests.append(await reader.readline())
        for line in lines:
            writer.write(line)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], requests


async def _collect(*lines):
    server, port, requests = await _serve(*lines)
    seen = []
    async with server:
        with pytest.raises(BridgeError) as info:
            async for armatures in subscribe_armatures(port=port):
                seen.append(armatures)
    return seen, str(info.value), requests


async def test_sends_subscribe_request():
    _, _, requests = await _collect()
    assert json.loads(requests[0]) == {"protocol": 1, "type": "subscribe_armatures"}


async def test_yields_each_armature_list():
    seen, _, _ = await _collect(_success("Rig"), _success("Rig", "Rig.001"))
    assert seen == [["Rig"], ["Rig", "Rig.001"]]


async def test_empty_list_is_a_result():
    seen, _, _ = await _collect(_success())
    assert seen == [[]]


async def test_busy_yields_none():
    seen, _, _ = await _collect(_error("busy"), _success("Rig"))
    assert seen == [None, ["Rig"]]


async def test_closed_connection_raises():
    seen, message, _ = await _collect(_success("Rig"))
    assert seen == [["Rig"]]
    assert message == "The Blender add-on closed the connection."


async def test_error_raises_with_its_message():
    seen, message, _ = await _collect(_error("query failed: boom"))
    assert seen == []
    assert message == "The Blender add-on reported: query failed: boom"


@pytest.mark.parametrize("line", [b"not json\n", b"[1]\n"])
async def test_invalid_json_raises(line):
    _, message, _ = await _collect(line)
    assert message == "The Blender add-on sent invalid JSON."


@pytest.mark.parametrize("version", [2, True, None])
async def test_unsupported_protocol_raises(version):
    line = (json.dumps({"protocol": version, "status": "success"}) + "\n").encode()
    _, message, _ = await _collect(line)
    assert message == f"Unsupported add-on protocol: {json.dumps(version)}."


@pytest.mark.parametrize(
    "body",
    [
        {"status": "success"},
        {"status": "success", "result": []},
        {"status": "success", "result": {"armatures": "Rig"}},
        {"status": "success", "result": {"armatures": [1]}},
    ],
)
async def test_unexpected_message_raises(body):
    _, message, _ = await _collect(_line(body))
    assert message == "The Blender add-on sent an unexpected message."


async def test_unreachable_raises():
    server, port, _ = await _serve()
    server.close()
    await server.wait_closed()
    with pytest.raises(BridgeError, match="isn't reachable"):
        async for _ in subscribe_armatures(port=port):
            pass
