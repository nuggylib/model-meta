import asyncio
import json
from collections.abc import AsyncIterator

HOST = "127.0.0.1"
PORT = 7417
PROTOCOL = 1

_SUBSCRIBE = (
    json.dumps({"protocol": PROTOCOL, "type": "subscribe_armatures"}) + "\n"
).encode()


class BridgeError(Exception):
    pass


async def subscribe_armatures(
    port: int = PORT, timeout: float = 2.0
) -> AsyncIterator[list[str] | None]:
    """Yields each armature list, or `None` while Blender is busy.

    Never ends on its own: raises `BridgeError` when the add-on can't be reached, reports
    an error, or closes the connection.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(HOST, port), timeout
        )
    except (OSError, TimeoutError) as exc:
        raise BridgeError("The Blender add-on isn't reachable.") from exc
    try:
        writer.write(_SUBSCRIBE)
        await writer.drain()
        while True:
            line = await reader.readline()
            if not line.endswith(b"\n"):
                raise BridgeError("The Blender add-on closed the connection.")
            yield _parse(line)
    except (OSError, ValueError) as exc:  # ValueError: a line over the stream limit
        raise BridgeError("The Blender add-on connection failed.") from exc
    finally:
        writer.close()


def _parse(line: bytes) -> list[str] | None:
    try:
        message = json.loads(line)
    except ValueError:
        message = None
    if not isinstance(message, dict):
        raise BridgeError("The Blender add-on sent invalid JSON.")
    version = message.get("protocol")
    if isinstance(version, bool) or version != PROTOCOL:  # bool is an int
        raise BridgeError(f"Unsupported add-on protocol: {json.dumps(version)}.")
    if message.get("status") == "error":
        if message.get("message") == "busy":
            return None
        raise BridgeError(f"The Blender add-on reported: {message.get('message')}")
    result = message.get("result")
    armatures = result.get("armatures") if isinstance(result, dict) else None
    if not isinstance(armatures, list) or not all(
        isinstance(name, str) for name in armatures
    ):
        raise BridgeError("The Blender add-on sent an unexpected message.")
    return armatures
