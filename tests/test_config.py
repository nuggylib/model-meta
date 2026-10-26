"""Unit tests for the config persistence layer (model_meta.config).

These are pure I/O tests against a temp dir — no Textual, no subprocess. They
cover the three load outcomes, the v1→v2 schema migration, the write-once-atomic
round-trip, lossless Windows-path storage, and the $MODEL_META_CONFIG
override seam.
"""

import tomllib

import pytest

from model_meta.config import paths, store
from model_meta.config.settings import SCHEMA_VERSION, Settings
from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.godot_connection import GodotConnection


def _settings(tmp_path, *directories) -> Settings:
    return Settings(
        blender_executable=str(tmp_path / "blender"),
        blender_version="4.5.0",
        models_directories=directories or (str(tmp_path / "models"),),
        godot_projects_root=str(tmp_path / "godot"),
    )


def _write_v1(path, models_directory='"/y"') -> None:
    """Hand-write a schema v1 config — the shape that shipped before v2.

    `models_directory` is injected raw so tests can supply a non-string value
    (the invalid-v1 cases) without reaching for a second helper.
    """
    path.write_text(
        "schema_version = 1\n"
        '[blender]\nexecutable = "/x"\nversion = "4.5.0"\n'
        f"[models]\ndirectory = {models_directory}\n"
        '[godot]\nprojects_root = "/z"\n'
    )


def _read(path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


# --- load() outcomes -------------------------------------------------------


def test_load_absent_when_file_missing(tmp_path):
    state, settings = store.load(tmp_path / "nope.toml")
    assert state == store.ABSENT
    assert settings is None


def test_load_valid_round_trips_settings(tmp_path):
    cfg = tmp_path / "config.toml"
    original = _settings(tmp_path)
    store.save(cfg, original)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings == original


def test_load_valid_round_trips_multiple_directories(tmp_path):
    """The whole point of v2: N directories survive save→load in stored order."""
    cfg = tmp_path / "config.toml"
    original = _settings(tmp_path, "/vehicles", "/props", "/characters")
    store.save(cfg, original)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.models_directories == ("/vehicles", "/props", "/characters")


def test_load_corrupt_on_garbage_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not : valid = toml ===")
    state, settings = store.load(cfg)
    assert state == store.CORRUPT
    assert settings is None


def test_load_corrupt_on_missing_required_key(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"schema_version = {SCHEMA_VERSION}\n"
        '[blender]\nexecutable = "/x"\n'
        '[models]\ndirectories = ["/y"]\n'
        # godot table omitted → missing required key
    )
    state, _ = store.load(cfg)
    assert state == store.CORRUPT


def test_load_corrupt_when_table_is_not_a_table(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'schema_version = {SCHEMA_VERSION}\nblender = "oops"\n')
    state, _ = store.load(cfg)
    assert state == store.CORRUPT


@pytest.mark.parametrize("version", [0, 3, 99, "1"])
def test_load_corrupt_on_unknown_schema_version(tmp_path, version):
    """Unknown/future versions stay CORRUPT and are never auto-overwritten."""
    cfg = tmp_path / "config.toml"
    store.save(cfg, _settings(tmp_path))
    before = cfg.read_text()
    cfg.write_text(
        before.replace(
            f"schema_version = {SCHEMA_VERSION}", f"schema_version = {version!r}"
        )
    )
    after = cfg.read_text()

    state, _ = store.load(cfg)
    assert state == store.CORRUPT
    assert cfg.read_text() == after  # not rewritten


# --- v2 models.directories validation --------------------------------------


@pytest.mark.parametrize(
    "directories",
    [
        "[]",  # empty — a config with zero model dirs is meaningless
        '"/y"',  # not a list
        "[1, 2]",  # non-string entries
        '["/y", 7]',  # one bad entry poisons the list
    ],
    ids=["empty", "not-a-list", "non-strings", "mixed"],
)
def test_load_corrupt_on_bad_v2_directories(tmp_path, directories):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"schema_version = {SCHEMA_VERSION}\n"
        '[blender]\nexecutable = "/x"\nversion = "4.5.0"\n'
        f"[models]\ndirectories = {directories}\n"
        '[godot]\nprojects_root = "/z"\n'
    )
    state, settings = store.load(cfg)
    assert state == store.CORRUPT
    assert settings is None


# --- v1 → v2 migration -----------------------------------------------------


def test_load_migrates_v1_in_memory(tmp_path):
    """A valid v1 config loads as VALID v2 with the single dir wrapped in a tuple."""
    cfg = tmp_path / "config.toml"
    _write_v1(cfg)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.models_directories == ("/y",)
    assert settings.blender_executable == "/x"
    assert settings.blender_version == "4.5.0"
    assert settings.godot_projects_root == "/z"


def test_load_rewrites_v1_file_as_v2_on_disk(tmp_path):
    """The migration is persisted, so the upgrade happens once — not every launch."""
    cfg = tmp_path / "config.toml"
    _write_v1(cfg)

    store.load(cfg)

    raw = _read(cfg)
    assert raw["schema_version"] == 2
    assert raw["models"] == {"directories": ["/y"]}
    assert "directory" not in raw["models"]
    assert list(tmp_path.glob("*.tmp")) == []  # atomic write left nothing behind


def test_second_load_of_upgraded_config_does_not_remigrate(tmp_path, monkeypatch):
    """Once upgraded, a load sees v2 and performs no migration write at all."""
    cfg = tmp_path / "config.toml"
    _write_v1(cfg)
    store.load(cfg)  # upgrades on disk

    def _fail(path, settings):
        raise AssertionError("re-migrated an already-v2 config")

    monkeypatch.setattr(store, "save", _fail)
    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.models_directories == ("/y",)


def test_migration_write_failure_still_returns_valid(tmp_path, monkeypatch):
    """`load` must never raise and must never refuse to boot over an unwritable
    config: the upgrade is returned in memory (unpersisted) and retried next
    launch, which is safe because the in-memory upgrade is idempotent."""
    cfg = tmp_path / "config.toml"
    _write_v1(cfg)

    def _boom(path, settings):
        raise OSError("read-only file system")

    monkeypatch.setattr(store, "save", _boom)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.models_directories == ("/y",)
    assert _read(cfg)["schema_version"] == 1  # still v1 on disk


@pytest.mark.parametrize(
    "directory",
    ["7", "[]", '["/y"]', "true"],
    ids=["int", "empty-list", "list", "bool"],
)
def test_load_corrupt_on_v1_with_non_string_directory(tmp_path, directory):
    """An invalid v1 file is CORRUPT — never a garbage migration."""
    cfg = tmp_path / "config.toml"
    _write_v1(cfg, models_directory=directory)
    state, settings = store.load(cfg)
    assert state == store.CORRUPT
    assert settings is None


def test_load_corrupt_on_v1_missing_directory(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "schema_version = 1\n"
        '[blender]\nexecutable = "/x"\n'
        "[models]\n"  # directory key omitted
        '[godot]\nprojects_root = "/z"\n'
    )
    state, settings = store.load(cfg)
    assert state == store.CORRUPT
    assert settings is None


def test_load_corrupt_on_v1_missing_godot_table(tmp_path):
    """v1's shared tables are validated too — not just its models key."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'schema_version = 1\n[blender]\nexecutable = "/x"\n[models]\ndirectory = "/y"\n'
    )
    state, _ = store.load(cfg)
    assert state == store.CORRUPT


# --- save() atomicity & format --------------------------------------------


def test_save_creates_parent_dirs_and_writes_schema_version(tmp_path):
    cfg = tmp_path / "nested" / "deeper" / "config.toml"
    store.save(cfg, _settings(tmp_path))

    assert cfg.exists()
    assert _read(cfg)["schema_version"] == SCHEMA_VERSION


def test_save_writes_directories_as_a_toml_array(tmp_path):
    cfg = tmp_path / "config.toml"
    store.save(cfg, _settings(tmp_path, "/a", "/b"))
    assert _read(cfg)["models"]["directories"] == ["/a", "/b"]


def test_save_leaves_no_temp_file_behind(tmp_path):
    cfg = tmp_path / "config.toml"
    store.save(cfg, _settings(tmp_path))
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_overwrites_existing_config(tmp_path):
    cfg = tmp_path / "config.toml"
    store.save(cfg, _settings(tmp_path))
    updated = Settings("/new/blender", "5.0.0", ("/new/models",), "/new/godot")
    store.save(cfg, updated)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings == updated


def test_windows_path_round_trips_losslessly(tmp_path):
    """Backslash paths must survive save→load unchanged (serialization footgun).

    Covers the array case too: hand-serializing a TOML list of Windows paths is
    exactly where escaping goes wrong, so `tomli_w` owns it.
    """
    cfg = tmp_path / "config.toml"
    win = Settings(
        blender_executable=r"C:\Program Files\Blender Foundation\Blender\blender.exe",
        blender_version="4.5.0",
        models_directories=(
            r"C:\Users\mando\BlenderModels",
            r"C:\Users\mando\Vehicles",
        ),
        godot_projects_root=r"C:\Users\mando\GodotProjects",
    )
    store.save(cfg, win)

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings == win
    assert settings.models_directories == win.models_directories


# --- config path resolution seam ------------------------------------------


def test_config_file_honors_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom" / "config.toml"
    monkeypatch.setenv("MODEL_META_CONFIG", str(override))
    assert paths.config_file() == override


def test_config_file_expands_user_in_override(monkeypatch):
    monkeypatch.setenv("MODEL_META_CONFIG", "~/bb.toml")
    resolved = paths.config_file()
    assert "~" not in str(resolved)
    assert resolved.name == "bb.toml"


def test_config_file_falls_back_to_platformdirs(monkeypatch):
    monkeypatch.delenv("MODEL_META_CONFIG", raising=False)
    resolved = paths.config_file()
    assert resolved.name == "config.toml"
    assert paths.APP_NAME in str(resolved)


# --- specs directory resolution -------------------------------------------


def test_specs_dir_sits_beside_the_config_file(tmp_path):
    cfg = tmp_path / "nested" / "config.toml"
    assert paths.specs_dir(cfg) == tmp_path / "nested" / paths.SPECS_DIRNAME


def test_specs_dir_follows_the_config_env_override(tmp_path, monkeypatch):
    """Point the config somewhere and the specs follow — no sibling override to
    set, which is why there is no `$MODEL_META_SPECS`."""
    override = tmp_path / "custom" / "config.toml"
    monkeypatch.setenv("MODEL_META_CONFIG", str(override))
    assert paths.specs_dir() == tmp_path / "custom" / paths.SPECS_DIRNAME


def test_specs_dir_resolves_without_reading_the_config(tmp_path):
    """Derived from the *path*, not its contents: it resolves for a config that
    does not exist at all."""
    cfg = tmp_path / "nope.toml"
    assert not cfg.exists()
    assert paths.specs_dir(cfg) == tmp_path / paths.SPECS_DIRNAME


# --- app connections --------------------------------------------------------


def test_blender_is_a_connection_to_the_stored_executable(tmp_path):
    assert _settings(tmp_path).blender == BlenderConnection(tmp_path / "blender")


def test_godot_is_a_connection_to_the_stored_projects_root(tmp_path):
    assert _settings(tmp_path).godot == GodotConnection(tmp_path / "godot")
