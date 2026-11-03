import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 7417
PROTOCOL = 1

# One write, so the add-on reads both in the same tick: the path it reports is the file
# the subscription is on.
_SUBSCRIBE = (
    json.dumps({"protocol": PROTOCOL, "type": "get_filepath"})
    + "\n"
    + json.dumps({"protocol": PROTOCOL, "type": "subscribe_armatures"})
    + "\n"
).encode()


class BridgeError(Exception):
    pass


@dataclass(frozen=True)
class OpenFile:
    """`path` is `None` when the open file was never saved."""

    path: str | None


@dataclass(frozen=True)
class Armatures:
    """`names` is `None` while Blender is busy."""

    names: list[str] | None


async def subscribe_armatures(
    port: int = PORT, timeout: float = 2.0
) -> AsyncIterator[OpenFile | Armatures]:
    """Yields the open file, then its armatures; a new `OpenFile` whenever another file opens.

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
        subscribed = False
        while True:
            line = await reader.readline()
            if not line.endswith(b"\n"):
                raise BridgeError("The Blender add-on closed the connection.")
            message = _parse(line)
            if isinstance(message, OpenFile):
                # A second path means another file opened and the subscription ended.
                if subscribed:
                    writer.write(_SUBSCRIBE)
                    await writer.drain()
                    subscribed = False
                    continue
                subscribed = True
            yield message
    except (OSError, ValueError) as exc:  # ValueError: a line over the stream limit
        raise BridgeError("The Blender add-on connection failed.") from exc
    finally:
        writer.close()


def _parse(line: bytes) -> OpenFile | Armatures:
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
            return Armatures(None)
        raise BridgeError(f"The Blender add-on reported: {message.get('message')}")
    result = message.get("result")
    if isinstance(result, dict):
        path = result.get("filepath")
        if "filepath" in result and (path is None or isinstance(path, str)):
            return OpenFile(path)
        armatures = result.get("armatures")
        if isinstance(armatures, list) and all(
            isinstance(name, str) for name in armatures
        ):
            return Armatures(armatures)
    raise BridgeError("The Blender add-on sent an unexpected message.")
