"""Unit tests for the specs category (model_meta.specs).

Pure data and filesystem tests against `tmp_path` — no Textual. The vocabulary,
the name rules (including the path-traversal strings the rules exist to stop),
and create/list behavior against a real directory.
"""

import json

import pytest

from model_meta.specs import naming, schema, store

SUSARM_REGEX = r"(?i)^sus\.?arm\.(?P<pos>front|rear)\.top\.(?P<side>[LR])$"

# --- vocabulary ------------------------------------------------------------


def test_texture_maps_holds_every_godot_channel():
    """All 19 `BaseMaterial3D.TextureParam` members, lowercased and unprefixed."""
    assert len(schema.TEXTURE_MAPS) == 19
    assert len(set(schema.TEXTURE_MAPS)) == 19
    assert "albedo" in schema.TEXTURE_MAPS
    assert "subsurface_transmittance" in schema.TEXTURE_MAPS
    assert "orm" in schema.TEXTURE_MAPS
    # The prefix is stripped and nothing shouts — these are JSON values.
    assert all(name == name.lower() for name in schema.TEXTURE_MAPS)
    assert not any(name.startswith("texture_") for name in schema.TEXTURE_MAPS)


def test_modifiers_holds_the_curated_set():
    """Blender's identifiers verbatim (upper snake case), curated to 20."""
    assert len(schema.MODIFIERS) == 20
    assert len(set(schema.MODIFIERS)) == 20
    assert "ARMATURE" in schema.MODIFIERS
    assert "WEIGHTED_NORMAL" in schema.MODIFIERS
    assert all(name == name.upper() for name in schema.MODIFIERS)


# --- skeleton --------------------------------------------------------------


def test_skeleton_is_complete_and_empty():
    """Every key present with an empty value: a valid-shaped spec from the
    first write, and a document that explains the schema by existing."""
    document = schema.skeleton("vehicle")

    assert document["model_type"] == "vehicle"
    assert set(document) == {"model_type", "armature", "mesh_roles", "modifiers"}
    assert document["armature"] == {
        "object_name": "",
        "required_bones": [],
        "bone_name_inverses": {},
        "parenting": {},
    }
    assert document["mesh_roles"] == {}
    assert document["modifiers"] == {
        "required": {"skinned_meshes": []},
        "allowed": [],
        "warn": [],
        "fail": [],
    }


def test_skeleton_does_not_share_mutable_state_between_calls():
    """Built fresh each call — a shared default would leak one spec's edits into
    the next file written in the same session."""
    first = schema.skeleton("vehicle")
    first["armature"]["required_bones"].append("root")
    assert schema.skeleton("character")["armature"]["required_bones"] == []


# --- normalize -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("vehicle", "vehicle"),
        ("Vehicle", "vehicle"),
        ("  vehicle  ", "vehicle"),
        ("space ship", "space-ship"),
        ("space   ship", "space-ship"),
        ("Space\tShip", "space-ship"),
        ("rig_v2", "rig_v2"),
    ],
)
def test_normalize_lowercases_trims_and_collapses_whitespace(raw, expected):
    assert naming.normalize(raw) == expected


# --- validate --------------------------------------------------------------


@pytest.mark.parametrize("raw", ["vehicle", "space-ship", "rig_v2", "Space Ship", "a"])
def test_validate_accepts_usable_names(raw):
    assert naming.validate(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "\t\n"],
    ids=["empty", "spaces", "whitespace"],
)
def test_validate_rejects_an_empty_name(raw):
    assert naming.validate(raw) == "Enter a name for the model type."


def test_validate_rejects_an_over_length_name():
    reason = naming.validate("v" * (naming.MAX_LENGTH + 1))
    assert reason is not None
    assert str(naming.MAX_LENGTH) in reason
    # The boundary itself is fine.
    assert naming.validate("v" * naming.MAX_LENGTH) is None


@pytest.mark.parametrize(
    "raw",
    [
        "../x",
        "../../etc/passwd",
        "a/b",
        "a\\b",
        "/absolute",
        "my.spec",
        "-lead",
        "trail-",
        "_lead",
        "double--hyphen",
        "spec!",
        "spec name!",
    ],
)
def test_validate_rejects_out_of_charset_names(raw):
    """One pattern, one message — and it is what stops a name from ever being
    read as a path. Validation runs before any path is joined."""
    assert naming.validate(raw) == "Use letters, numbers, hyphens and underscores only."


@pytest.mark.parametrize("raw", ["con", "CON", "nul", "LPT1", "com9", "aux", "prn"])
def test_validate_rejects_windows_reserved_names(raw):
    reason = naming.validate(raw)
    assert reason is not None
    assert "reserved" in reason
    assert raw.lower() in reason  # quotes the normalized name


# --- create ----------------------------------------------------------------


def test_create_writes_a_parseable_skeleton(tmp_path):
    specs = tmp_path / "specs"
    specs.mkdir()

    path = store.create(specs, "vehicle")

    assert path == specs / "vehicle.json"
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == schema.skeleton("vehicle")
    assert text.endswith("}\n")  # trailing newline, so it diffs cleanly
    assert "\n  " in text  # indent=2, not one dense line


def test_create_makes_the_specs_dir_when_absent(tmp_path):
    """`create` is the only thing that creates the directory, lazily."""
    specs = tmp_path / "nested" / "specs"
    assert not specs.exists()

    store.create(specs, "vehicle")
    assert (specs / "vehicle.json").is_file()


def test_create_refuses_to_overwrite_an_existing_spec(tmp_path):
    """O_EXCL, not a replace: the existing file must be byte-identical after."""
    specs = tmp_path / "specs"
    path = store.create(specs, "vehicle")
    before = path.read_bytes()

    with pytest.raises(FileExistsError):
        store.create(specs, "vehicle")

    assert path.read_bytes() == before


# --- list_specs ------------------------------------------------------------


def _write(specs_dir, name, payload):
    """Hand-write a spec file; `payload` is raw text or a JSON-able object."""
    specs_dir.mkdir(parents=True, exist_ok=True)
    path = specs_dir / f"{name}.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_list_specs_returns_entries_sorted_by_name(tmp_path):
    specs = tmp_path / "specs"
    for name in ("vehicle", "character", "prop"):
        store.create(specs, name)

    entries = store.list_specs(specs)
    assert [entry.model_type for entry in entries] == ["character", "prop", "vehicle"]
    assert {entry.state for entry in entries} == {store.SpecState.OK}
    assert entries[0].path == specs / "character.json"


def test_list_specs_flags_a_model_type_filename_disagreement(tmp_path):
    """The stem is the identity, so the file's own `model_type` losing to it is
    reported rather than silently preferred."""
    specs = tmp_path / "specs"
    _write(specs, "vehicle", schema.skeleton("spaceship"))

    (entry,) = store.list_specs(specs)
    assert entry.state is store.SpecState.MISMATCHED
    assert entry.model_type == "vehicle"


def test_list_specs_flags_a_missing_model_type_key(tmp_path):
    specs = tmp_path / "specs"
    _write(specs, "vehicle", {"mesh_roles": {}})

    (entry,) = store.list_specs(specs)
    assert entry.state is store.SpecState.MISMATCHED


@pytest.mark.parametrize(
    "payload",
    ["{not json at all", "[]", '"a string"', "null", ""],
    ids=["malformed", "array", "string", "null", "empty"],
)
def test_list_specs_flags_unreadable_files(tmp_path, payload):
    """Unparseable *and* valid-JSON-wrong-type both land as UNREADABLE — the
    fix is the same (open it or delete it) either way."""
    specs = tmp_path / "specs"
    _write(specs, "vehicle", payload)

    (entry,) = store.list_specs(specs)
    assert entry.state is store.SpecState.UNREADABLE


def test_list_specs_keeps_the_good_entries_beside_a_bad_one(tmp_path):
    """One malformed file must never blank the list — the catch is per file."""
    specs = tmp_path / "specs"
    store.create(specs, "vehicle")
    store.create(specs, "character")
    _write(specs, "broken", "{nope")

    entries = store.list_specs(specs)
    assert [entry.model_type for entry in entries] == [
        "broken",
        "character",
        "vehicle",
    ]
    assert [entry.state for entry in entries] == [
        store.SpecState.UNREADABLE,
        store.SpecState.OK,
        store.SpecState.OK,
    ]


def test_list_specs_on_a_missing_dir_returns_empty_and_creates_nothing(tmp_path):
    """Read-only: a fresh install gets no empty folder in its config dir."""
    specs = tmp_path / "specs"

    assert store.list_specs(specs) == []
    assert not specs.exists()


def test_list_specs_ignores_non_json_files(tmp_path):
    specs = tmp_path / "specs"
    store.create(specs, "vehicle")
    (specs / "notes.txt").write_text("scratch", encoding="utf-8")
    (specs / "backup.json.bak").write_text("{}", encoding="utf-8")
    (specs / "nested.json").mkdir()  # a directory named like a spec

    assert [entry.model_type for entry in store.list_specs(specs)] == ["vehicle"]


# --- count -----------------------------------------------------------------


def test_count_counts_without_parsing(tmp_path):
    specs = tmp_path / "specs"
    store.create(specs, "vehicle")
    _write(specs, "broken", "{nope")  # unparseable still counts as a spec file

    assert store.count(specs) == 2


def test_count_of_a_missing_dir_is_zero(tmp_path):
    specs = tmp_path / "specs"
    assert store.count(specs) == 0
    assert not specs.exists()


# --- read ------------------------------------------------------------------


def test_read_returns_the_document(tmp_path):
    path = store.create(tmp_path, "vehicle")
    document = store.read(path)

    assert document == schema.skeleton("vehicle")
    assert store.required_bones(document) == []
    assert store.bone_name_inverses(document) == {}
    assert store.armature_name(document) == ""
    assert store.parenting_map(document) == {}
    assert store.mesh_roles(document) == {}


def test_mesh_roles_defaults_when_the_key_is_missing(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {}})
    assert store.mesh_roles(store.read(path)) == {}


def test_parenting_map_defaults_when_the_key_is_missing(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {}})
    assert store.parenting_map(store.read(path)) == {}


def test_armature_name_returns_the_stored_object_name(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {"object_name": "rig[L]"}})
    assert store.armature_name(store.read(path)) == "rig[L]"


def test_armature_name_defaults_when_the_key_is_missing(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {}})
    assert store.armature_name(store.read(path)) == ""


def test_read_tolerates_a_spec_older_than_bone_name_inverses(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {"required_bones": ["body"]}})
    document = store.read(path)

    assert store.required_bones(document) == ["body"]
    assert store.bone_name_inverses(document) == {}


@pytest.mark.parametrize(
    "payload",
    [
        "{nope",
        "[]",
        {"armature": []},
        {"armature": {"required_bones": "body"}},
        {"armature": {"required_bones": ["body", 3]}},
        {"armature": {"bone_name_inverses": []}},
        {"armature": {"bone_name_inverses": {".front": 1}}},
        {"armature": {"object_name": 3}},
        {"armature": {"parenting": []}},
        {"armature": {"parenting": {"root": "axle"}}},
        {"armature": {"parenting": {"root": [3]}}},
        {"mesh_roles": []},
        {"mesh_roles": {"body": "body"}},
        {"mesh_roles": {"body": {"vtx_grp": 3}}},
    ],
    ids=[
        "malformed",
        "array",
        "armature-not-object",
        "bones-not-list",
        "bones-not-strings",
        "inverses-not-object",
        "inverses-not-strings",
        "object-name-not-string",
        "parenting-not-object",
        "parenting-not-lists",
        "parenting-not-strings",
        "mesh-roles-not-object",
        "mesh-role-not-object",
        "vtx-grp-not-string",
    ],
)
def test_read_rejects_a_malformed_spec(tmp_path, payload):
    path = _write(tmp_path, "vehicle", payload)
    with pytest.raises(ValueError):
        store.read(path)


def test_read_raises_oserror_for_a_missing_file(tmp_path):
    with pytest.raises(OSError):
        store.read(tmp_path / "vehicle.json")


def test_read_rejects_a_non_string_mesh_regex(tmp_path):
    document = schema.skeleton("vehicle")
    document["mesh_roles"] = {"body": {"vtx_grp": "body", "mesh_regex": 5}}
    path = _write(tmp_path, "vehicle", document)

    with pytest.raises(ValueError, match="`mesh_regex` is not a string"):
        store.read(path)


def test_read_accepts_a_role_without_a_mesh_regex(tmp_path):
    document = schema.skeleton("vehicle")
    document["mesh_roles"] = {"body": {"vtx_grp": "body"}}
    path = _write(tmp_path, "vehicle", document)

    assert store.mesh_roles(store.read(path)) == {"body": {"vtx_grp": "body"}}


# --- update_armature -------------------------------------------------------


def test_update_armature_preserves_every_other_key(tmp_path):
    document = schema.skeleton("vehicle")
    document["armature"]["object_name"] = "Rig"
    document["mesh_roles"] = {"body": {"mesh_regex": "^body$"}}
    document["hand_added"] = True
    path = _write(tmp_path, "vehicle", document)

    store.update_armature(path, add_bones=["body"], set_inverses={".a": ".b"})

    after = json.loads(path.read_text(encoding="utf-8"))
    document["armature"]["required_bones"] = ["body"]
    document["armature"]["bone_name_inverses"] = {".a": ".b"}
    assert after == document


def test_update_armature_appends_in_order_and_dedups(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.update_armature(path, add_bones=["body", "arm.L"])
    store.update_armature(path, add_bones=["arm.L", "arm.R", "arm.R"])

    assert store.required_bones(store.read(path)) == ["body", "arm.L", "arm.R"]


def test_update_armature_drops_then_sets(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.update_armature(path, set_inverses={".front": ".rear", ".rear": ".front"})
    store.update_armature(
        path,
        drop_inverses=[".front", ".rear"],
        set_inverses={".front": ".back", ".back": ".front"},
    )

    assert store.bone_name_inverses(store.read(path)) == {
        ".front": ".back",
        ".back": ".front",
    }


def test_update_armature_sets_and_clears_the_object_name(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.update_armature(path, add_bones=["body"], object_name="Rig")
    store.update_armature(path, add_bones=["head"])
    assert store.armature_name(store.read(path)) == "Rig"

    store.update_armature(path, object_name="")
    document = store.read(path)
    assert store.armature_name(document) == ""
    assert store.required_bones(document) == ["body", "head"]


def test_update_armature_appends_parenting_and_preserves_other_keys(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.update_armature(path, add_bones=["root"], object_name="Rig")
    store.update_armature(path, add_parenting={"root": ["axle.{1}.{2}"]})
    store.update_armature(
        path, add_parenting={"root": ["axle.{1}.{2}", "susarm.{1}.{2}.{3}"]}
    )

    document = store.read(path)
    assert store.parenting_map(document) == {
        "root": ["axle.{1}.{2}", "susarm.{1}.{2}.{3}"]
    }
    assert store.required_bones(document) == ["root"]
    assert store.armature_name(document) == "Rig"


def test_update_armature_adds_the_key_to_an_older_spec(tmp_path):
    path = _write(tmp_path, "vehicle", {"model_type": "vehicle"})
    store.update_armature(path, add_bones=["body"])

    assert json.loads(path.read_text(encoding="utf-8"))["armature"] == {
        "required_bones": ["body"],
        "bone_name_inverses": {},
    }


def test_update_armature_leaves_no_tmp_behind(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.update_armature(path, add_bones=["body"])

    assert sorted(p.name for p in tmp_path.iterdir()) == ["vehicle.json"]


def test_update_armature_refuses_a_malformed_spec_and_writes_nothing(tmp_path):
    path = _write(tmp_path, "vehicle", {"armature": {"required_bones": "body"}})
    before = path.read_bytes()

    with pytest.raises(ValueError):
        store.update_armature(path, add_bones=["arm.L"])

    assert path.read_bytes() == before


# --- add_mesh_role ---------------------------------------------------------


def test_add_mesh_role_writes_the_role(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.add_mesh_role(path, "susarm_upper", "susarm.{1}.top.{2}", SUSARM_REGEX)
    store.add_mesh_role(path, "body", "body", "^body$")

    after = json.loads(path.read_text(encoding="utf-8"))["mesh_roles"]
    assert after == {
        "susarm_upper": {"mesh_regex": SUSARM_REGEX, "vtx_grp": "susarm.{1}.top.{2}"},
        "body": {"mesh_regex": "^body$", "vtx_grp": "body"},
    }
    assert list(after["body"]) == ["mesh_regex", "vtx_grp"]


def test_add_mesh_role_preserves_every_other_key(tmp_path):
    document = schema.skeleton("vehicle")
    document["armature"]["required_bones"] = ["body"]
    document["mesh_roles"] = {"wheel": {"vtx_grp": "wheel", "weight": 1.0}}
    document["hand_added"] = True
    path = _write(tmp_path, "vehicle", document)

    store.add_mesh_role(path, "body", "body", "^body$")

    after = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["body"] = {"mesh_regex": "^body$", "vtx_grp": "body"}
    assert after == document


def test_add_mesh_role_rejects_a_duplicate_and_writes_nothing(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.add_mesh_role(path, "body", "body", "^body$")
    before = path.read_bytes()

    with pytest.raises(ValueError):
        store.add_mesh_role(path, "body", "root", "^root$")

    assert path.read_bytes() == before


def test_add_mesh_role_adds_the_key_to_an_older_spec(tmp_path):
    path = _write(tmp_path, "vehicle", {"model_type": "vehicle"})
    store.add_mesh_role(path, "body", "body", "^body$")

    assert json.loads(path.read_text(encoding="utf-8"))["mesh_roles"] == {
        "body": {"mesh_regex": "^body$", "vtx_grp": "body"}
    }


def test_add_mesh_role_leaves_no_tmp_behind(tmp_path):
    path = store.create(tmp_path, "vehicle")
    store.add_mesh_role(path, "body", "body", "^body$")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["vehicle.json"]


# --- update_mesh_role ------------------------------------------------------


def _three_roles(tmp_path):
    document = schema.skeleton("vehicle")
    document["mesh_roles"] = {
        "body": {"vtx_grp": "body"},
        "wheel": {"vtx_grp": "wheel.{1}", "weight": 1.0},
        "glass": {},
    }
    document["hand_added"] = True
    return _write(tmp_path, "vehicle", document), document


def test_update_mesh_role_replaces_the_vtx_grp_in_place(tmp_path):
    path, document = _three_roles(tmp_path)
    store.update_mesh_role(path, "wheel", "wheel", "wheel.front")

    after = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["wheel"]["vtx_grp"] = "wheel.front"
    assert after == document


def test_update_mesh_role_renames_keeping_position_and_fields(tmp_path):
    path, document = _three_roles(tmp_path)
    store.update_mesh_role(path, "wheel", "tyre", "wheel.{1}")

    after = json.loads(path.read_text(encoding="utf-8"))
    assert list(after["mesh_roles"]) == ["body", "tyre", "glass"]
    assert after["mesh_roles"]["tyre"] == {"vtx_grp": "wheel.{1}", "weight": 1.0}
    assert after["hand_added"] is True


def test_update_mesh_role_adds_a_vtx_grp_to_a_role_without_one(tmp_path):
    path, _ = _three_roles(tmp_path)
    store.update_mesh_role(path, "glass", "glass", "body")

    assert store.mesh_roles(store.read(path))["glass"] == {"vtx_grp": "body"}


def test_update_mesh_role_without_a_vtx_grp_only_renames(tmp_path):
    path, document = _three_roles(tmp_path)
    store.update_mesh_role(path, "wheel", "tyre")
    store.update_mesh_role(path, "glass", "window")

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["mesh_roles"] == {
        "body": {"vtx_grp": "body"},
        "tyre": {"vtx_grp": "wheel.{1}", "weight": 1.0},
        "window": {},
    }
    assert after["hand_added"] is True


def test_update_mesh_role_writes_the_mesh_regex_alone(tmp_path):
    path, document = _three_roles(tmp_path)
    store.update_mesh_role(path, "wheel", "wheel", mesh_regex="^wheel")
    store.update_mesh_role(path, "glass", "glass", mesh_regex="^glass$")

    after = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["wheel"]["mesh_regex"] = "^wheel"
    document["mesh_roles"]["glass"] = {"mesh_regex": "^glass$"}
    assert after == document
    assert list(after["mesh_roles"]) == ["body", "wheel", "glass"]


def test_update_mesh_role_rename_and_re_pattern_keep_the_mesh_regex(tmp_path):
    path, _ = _three_roles(tmp_path)
    store.update_mesh_role(path, "wheel", "wheel", mesh_regex="^wheel")
    store.update_mesh_role(path, "wheel", "tyre")
    store.update_mesh_role(path, "tyre", "tyre", "wheel.front")

    assert store.mesh_roles(store.read(path))["tyre"] == {
        "vtx_grp": "wheel.front",
        "weight": 1.0,
        "mesh_regex": "^wheel",
    }


@pytest.mark.parametrize(
    ("name", "new_name", "message"),
    [
        ("door", "door", "'door' is no longer a mesh role."),
        ("wheel", "body", "'body' is already a mesh role."),
    ],
)
def test_update_mesh_role_rejects_and_writes_nothing(tmp_path, name, new_name, message):
    path, _ = _three_roles(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match=message):
        store.update_mesh_role(path, name, new_name, "body")

    assert path.read_bytes() == before


def test_update_mesh_role_leaves_no_tmp_behind(tmp_path):
    path, _ = _three_roles(tmp_path)
    store.update_mesh_role(path, "body", "hull", "body")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["vehicle.json"]


# --- rename_bone -----------------------------------------------------------


def _rigged(tmp_path):
    document = schema.skeleton("vehicle")
    document["armature"]["object_name"] = "Rig"
    document["armature"]["required_bones"] = ["root", "arm.L", "arm.R"]
    document["armature"]["bone_name_inverses"] = {".front": ".rear"}
    document["armature"]["parenting"] = {"root": ["arm.{1}"]}
    document["mesh_roles"] = {"arm": {"vtx_grp": "arm.{1}"}}
    return _write(tmp_path, "vehicle", document), document


def test_rename_bone_keeps_position_and_every_other_key(tmp_path):
    path, document = _rigged(tmp_path)
    store.rename_bone(path, "arm.L", "upperarm.L")

    after = json.loads(path.read_text(encoding="utf-8"))
    document["armature"]["required_bones"] = ["root", "upperarm.L", "arm.R"]
    assert after == document


def test_rename_bone_applies_set_inverses(tmp_path):
    path, _ = _rigged(tmp_path)
    store.rename_bone(
        path,
        "arm.L",
        "arm.upper.L",
        set_inverses={".upper": ".lower", ".lower": ".upper"},
    )

    assert store.bone_name_inverses(store.read(path)) == {
        ".front": ".rear",
        ".upper": ".lower",
        ".lower": ".upper",
    }


def test_rename_bone_to_its_own_name_is_accepted(tmp_path):
    path, document = _rigged(tmp_path)
    store.rename_bone(path, "arm.L", "arm.L")

    assert json.loads(path.read_text(encoding="utf-8")) == document


@pytest.mark.parametrize(
    ("name", "new_name", "message"),
    [
        ("leg.L", "leg.R", "'leg.L' is no longer a required bone."),
        ("arm.L", "arm.R", "'arm.R' is already required."),
    ],
)
def test_rename_bone_rejects_and_writes_nothing(tmp_path, name, new_name, message):
    path, _ = _rigged(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match=message):
        store.rename_bone(path, name, new_name)

    assert path.read_bytes() == before


def test_rename_bone_leaves_no_tmp_behind(tmp_path):
    path, _ = _rigged(tmp_path)
    store.rename_bone(path, "root", "base")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["vehicle.json"]


# --- delete_bone -----------------------------------------------------------


def test_delete_bone_keeps_the_order_and_every_other_key(tmp_path):
    path, document = _rigged(tmp_path)
    store.delete_bone(path, "arm.L")

    after = json.loads(path.read_text(encoding="utf-8"))
    document["armature"]["required_bones"] = ["root", "arm.R"]
    assert after == document


def test_delete_bone_rejects_a_missing_bone_and_writes_nothing(tmp_path):
    path, _ = _rigged(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="'leg.L' is no longer a required bone."):
        store.delete_bone(path, "leg.L")

    assert path.read_bytes() == before


def test_delete_bone_leaves_no_tmp_behind(tmp_path):
    path, _ = _rigged(tmp_path)
    store.delete_bone(path, "root")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["vehicle.json"]
