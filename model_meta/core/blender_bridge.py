import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from enum import Enum

HOST = "127.0.0.1"
PORT = 7417
PROTOCOL = 1
UVS_VERSION = (0, 2, 0)
MODIFIERS_VERSION = (0, 4, 0)
DUPLICATES_VERSION = (0, 5, 0)
TEXTURES_VERSION = (0, 5, 1)


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


@dataclass(frozen=True)
class SceneMesh:
    name: str
    vertex_groups: list[str]
    material_slots: list[str]


@dataclass(frozen=True)
class WeightTarget:
    mesh: str
    vertex_group: str
    weight: float


@dataclass(frozen=True)
class MeshTarget:
    mesh: str


@dataclass(frozen=True)
class MeshWeight:
    """With `error` set (`"no mesh"` / `"no vertex group"`), the counts are 0."""

    mesh: str
    vertex_group: str
    vertices: int = 0
    assigned: int = 0
    at_weight: int = 0
    error: str | None = None


@dataclass(frozen=True)
class TextureImage:
    """`filepath` is `None` for an image with no file, like an unsaved bake."""

    name: str
    filepath: str | None


@dataclass(frozen=True)
class MeshTextures:
    """With `error` set (`"no mesh"`), `images` is empty."""

    mesh: str
    images: list[TextureImage]
    error: str | None = None


@dataclass(frozen=True)
class MeshUvs:
    """With `error` set (`"no mesh"` / `"in edit mode"`), the rest is empty."""

    mesh: str
    has_default_uv_map: bool
    error: str | None = None


@dataclass(frozen=True)
class MeshModifiers:
    """Blender modifier types in stack order. With `error` set (`"no mesh"`), it's empty."""

    mesh: str
    modifiers: list[str]
    error: str | None = None


@dataclass(frozen=True)
class MeshReport:
    """`weights`, `textures` / `uvs` and `modifiers` answer the plan's targets, in order.
    `duplicates` holds every same-shape group of scene meshes, fetched only when there are
    textured targets. An optional list is `None` when the add-on predates its `_ADDED`
    version."""

    meshes: list[SceneMesh]
    weights: list[MeshWeight]
    textures: list[MeshTextures] | None
    uvs: list[MeshUvs] | None
    modifiers: list[MeshModifiers] | None
    duplicates: list[list[str]] | None


MeshPlan = Callable[
    [list[SceneMesh]],
    tuple[Sequence[WeightTarget], Sequence[MeshTarget], Sequence[MeshTarget]],
]


class _Status(Enum):
    BUSY = "busy"
    STALE = "stale"


@dataclass(frozen=True)
class _Version:
    """`version` is `None` for an add-on older than `get_version`."""

    version: str | None


@dataclass(frozen=True)
class _Revision:
    revision: int


@dataclass(frozen=True)
class _Page:
    revision: int
    key: str
    items: list
    next_cursor: int | None


async def subscribe_armatures(
    port: int = PORT, timeout: float = 2.0
) -> AsyncIterator[OpenFile | Armatures]:
    """Yields the open file, then its armatures; a new `OpenFile` whenever another file opens.

    Never ends on its own: raises `BridgeError` when the add-on can't be reached, reports
    an error, or closes the connection.
    """
    async with _subscription("subscribe_armatures", port, timeout) as bridge:
        while True:
            message = await bridge.receive()
            if message is _Status.BUSY:
                yield Armatures(None)
            elif isinstance(message, OpenFile | Armatures):
                yield message
            elif isinstance(message, _Version):
                continue
            else:
                raise _unexpected()


async def subscribe_meshes(
    plan: MeshPlan, port: int = PORT, timeout: float = 2.0
) -> AsyncIterator[OpenFile | MeshReport]:
    """Yields the open file, then a `MeshReport` after each save/load; a new `OpenFile` whenever
    another file opens.

    `plan(meshes)` picks the weight, textured (textures and UVs) and modifier targets to
    fetch. Raises like `subscribe_armatures`.
    """
    async with _subscription("subscribe_meshes", port, timeout) as bridge:
        version = None
        latest = None
        fetch = None
        while True:
            message = await bridge.receive()
            if isinstance(message, OpenFile):
                yield message
            elif message is _Status.BUSY:
                continue
            elif isinstance(message, _Version):
                version = message.version
            elif isinstance(message, _Revision):
                latest = message.revision
                # One request at a time: an in-flight one is restarted when its reply lands.
                if fetch is None:
                    fetch = _Fetch(latest, plan, version)
                    await bridge.send(fetch.request())
            elif fetch is None or not (
                message is _Status.STALE or isinstance(message, _Page)
            ):
                raise _unexpected()
            elif fetch.revision != latest:
                fetch = _Fetch(latest, plan, version)
                await bridge.send(fetch.request())
            elif message is _Status.STALE:
                # The new revision hasn't arrived yet; it starts the next fetch.
                fetch = None
            elif (report := fetch.add(message)) is not None:
                fetch = None
                yield report
            else:
                await bridge.send(fetch.request())


_PAGED = {
    "get_meshes": "meshes",
    "get_mesh_weights": "mesh_weights",
    "get_mesh_textures": "mesh_textures",
    "get_mesh_uvs": "mesh_uvs",
    "get_mesh_modifiers": "mesh_modifiers",
    "get_duplicate_meshes": "duplicate_meshes",
}

# The add-on version that added each request's current shape; an older one leaves its
# list `None`.
_ADDED = {
    "get_mesh_textures": TEXTURES_VERSION,
    "get_mesh_uvs": UVS_VERSION,
    "get_mesh_modifiers": MODIFIERS_VERSION,
    "get_duplicate_meshes": DUPLICATES_VERSION,
}


class _Fetch:
    """One revision's pages: the meshes, then the planned weights, textures, UVs,
    modifiers and duplicates."""

    def __init__(self, revision: int, plan: MeshPlan, version: str | None) -> None:
        self.revision = revision
        self._plan = plan
        self._unsupported = {
            kind for kind, added in _ADDED.items() if not _at_least(version, added)
        }
        self._queue: list[tuple[str, dict]] = [("get_meshes", {})]
        self._cursor = 0
        self._items: dict[str, list] = {key: [] for key in _PAGED.values()}

    def request(self) -> dict:
        kind, params = self._queue[0]
        return {
            "type": kind,
            "revision": self.revision,
            "cursor": self._cursor,
            **params,
        }

    def add(self, page: _Page) -> MeshReport | None:
        """The report once the last page is in, else `None`; send `request()` next."""
        kind, _ = self._queue[0]
        if page.key != _PAGED[kind] or page.revision != self.revision:
            raise _unexpected()
        self._items[page.key].extend(page.items)
        if page.next_cursor is not None:
            self._cursor = page.next_cursor
            return None
        self._queue.pop(0)
        self._cursor = 0
        if kind == "get_meshes":
            weights, textured, modifiers = self._plan(self._items["meshes"])
            self._queue += [
                (request_type, params)
                for request_type, targets, params in (
                    ("get_mesh_weights", weights, _targets(weights)),
                    ("get_mesh_textures", textured, _targets(textured)),
                    ("get_mesh_uvs", textured, _targets(textured)),
                    ("get_mesh_modifiers", modifiers, _targets(modifiers)),
                    ("get_duplicate_meshes", textured, {}),
                )
                if targets and request_type not in self._unsupported
            ]
        if self._queue:
            return None
        return MeshReport(
            self._items["meshes"],
            self._items["mesh_weights"],
            self._optional("get_mesh_textures"),
            self._optional("get_mesh_uvs"),
            self._optional("get_mesh_modifiers"),
            self._optional("get_duplicate_meshes"),
        )

    def _optional(self, kind: str) -> list | None:
        return None if kind in self._unsupported else self._items[_PAGED[kind]]


def _targets(targets: Sequence[WeightTarget | MeshTarget]) -> dict:
    return {"meshes": [asdict(target) for target in targets]}


@asynccontextmanager
async def _subscription(kind: str, port: int, timeout: float):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(HOST, port), timeout
        )
    except (OSError, TimeoutError) as exc:
        raise BridgeError("The Blender add-on isn't reachable.") from exc
    bridge = _Bridge(reader, writer, kind)
    try:
        await bridge.subscribe()
        yield bridge
    finally:
        writer.close()


class _Bridge:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, kind: str
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._kind = kind
        self._subscribed = False

    async def subscribe(self) -> None:
        # One write, so the add-on reads them in the same tick: the path it reports is the
        # file the subscription is on, and the version arrives before any result.
        await self.send(
            {"type": "get_filepath"}, {"type": "get_version"}, {"type": self._kind}
        )
        self._subscribed = False

    async def send(self, *requests: dict) -> None:
        lines = "".join(
            json.dumps({"protocol": PROTOCOL, **request}) + "\n" for request in requests
        )
        try:
            self._writer.write(lines.encode())
            await self._writer.drain()
        except OSError as exc:
            raise BridgeError("The Blender add-on connection failed.") from exc

    async def receive(self):
        """The next message. Another file's path re-subscribes, and only the reply is returned."""
        while True:
            try:
                line = await self._reader.readline()
            # ValueError: a line over the stream limit
            except (OSError, ValueError) as exc:
                raise BridgeError("The Blender add-on connection failed.") from exc
            if not line.endswith(b"\n"):
                raise BridgeError("The Blender add-on closed the connection.")
            message = _parse(line)
            if isinstance(message, OpenFile):
                # A second path means another file opened and the subscription ended.
                if self._subscribed:
                    await self.subscribe()
                    continue
                self._subscribed = True
            return message


def _parse(line: bytes):
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
        return _error(message.get("message"))
    result = message.get("result")
    if isinstance(result, dict):
        path = result.get("filepath")
        if "filepath" in result and (path is None or isinstance(path, str)):
            return OpenFile(path)
        version = result.get("version")
        if isinstance(version, str):
            return _Version(version)
        armatures = result.get("armatures")
        if _is_str_list(armatures):
            return Armatures(armatures)
        revision = result.get("meshes_revision")
        if _is_whole(revision):
            return _Revision(revision)
        if (page := _page(result)) is not None:
            return page
    raise _unexpected()


def _error(text: object) -> _Status | _Version:
    if text in ("busy", "stale"):
        return _Status(text)
    if text == 'unknown type: "get_version"':
        return _Version(None)
    raise BridgeError(f"The Blender add-on reported: {text}")


def _page(result: dict) -> _Page | None:
    key = next((key for key in _ITEMS if key in result), None)
    revision, next_cursor = result.get("revision"), result.get("next_cursor")
    raw = result.get(key)
    if (
        key is None
        or not _is_whole(revision)
        or not (next_cursor is None or _is_whole(next_cursor))
        or result.get("has_more") is not (next_cursor is not None)
        or not isinstance(raw, list)
        or not all(isinstance(item, dict) for item in raw)
    ):
        return None
    items = [_ITEMS[key](item) for item in raw]
    if None in items:
        return None
    return _Page(revision, key, items, next_cursor)


def _scene_mesh(item: dict) -> SceneMesh | None:
    name = item.get("name")
    groups, slots = item.get("vertex_groups"), item.get("material_slots")
    if isinstance(name, str) and _is_str_list(groups) and _is_str_list(slots):
        return SceneMesh(name, groups, slots)
    return None


def _mesh_weight(item: dict) -> MeshWeight | None:
    mesh, group, error = item.get("mesh"), item.get("vertex_group"), item.get("error")
    if not isinstance(mesh, str) or not isinstance(group, str):
        return None
    if "error" in item:
        return MeshWeight(mesh, group, error=error) if isinstance(error, str) else None
    counts = [item.get(key) for key in ("vertices", "assigned", "at_weight")]
    return MeshWeight(mesh, group, *counts) if all(map(_is_whole, counts)) else None


def _mesh_textures(item: dict) -> MeshTextures | None:
    mesh, images, error = item.get("mesh"), item.get("images"), item.get("error")
    if not isinstance(mesh, str):
        return None
    if "error" in item:
        return MeshTextures(mesh, [], error) if isinstance(error, str) else None
    if not isinstance(images, list) or not all(isinstance(i, dict) for i in images):
        return None
    parsed = [_texture_image(image) for image in images]
    return None if None in parsed else MeshTextures(mesh, parsed)


def _texture_image(item: dict) -> TextureImage | None:
    name, filepath = item.get("name"), item.get("filepath")
    if isinstance(name, str) and (filepath is None or isinstance(filepath, str)):
        return TextureImage(name, filepath)
    return None


def _mesh_uvs(item: dict) -> MeshUvs | None:
    mesh, error = item.get("mesh"), item.get("error")
    default = item.get("has_default_uv_map")
    if not isinstance(mesh, str):
        return None
    if "error" in item:
        return MeshUvs(mesh, False, error) if isinstance(error, str) else None
    return MeshUvs(mesh, default) if isinstance(default, bool) else None


def _mesh_modifiers(item: dict) -> MeshModifiers | None:
    mesh, modifiers, error = item.get("mesh"), item.get("modifiers"), item.get("error")
    if not isinstance(mesh, str):
        return None
    if "error" in item:
        return MeshModifiers(mesh, [], error) if isinstance(error, str) else None
    return MeshModifiers(mesh, modifiers) if _is_str_list(modifiers) else None


def _duplicates(item: dict) -> list[str] | None:
    names = item.get("duplicates")
    return names if _is_str_list(names) else None


_ITEMS = {
    "meshes": _scene_mesh,
    "mesh_weights": _mesh_weight,
    "mesh_textures": _mesh_textures,
    "mesh_uvs": _mesh_uvs,
    "mesh_modifiers": _mesh_modifiers,
    "duplicate_meshes": _duplicates,
}


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _at_least(version: str | None, minimum: tuple[int, ...]) -> bool:
    """`False` for a missing or unparseable version."""
    if version is None:
        return False
    try:
        return tuple(int(part) for part in version.split(".")) >= minimum
    except ValueError:
        return False


def _unexpected() -> BridgeError:
    return BridgeError("The Blender add-on sent an unexpected message.")
