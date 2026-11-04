import json

import pytest

from model_meta.core.results import Results


def test_round_trips_with_extra_keys_after_the_known_ones(tmp_path):
    path = tmp_path / "car.json"
    data = {"note": "hand-added", "spec": "vehicle", "model_file": "/m/car.blend"}
    results = Results.from_dict(data, path=path)
    assert results.model_file == "/m/car.blend"
    assert results.spec == "vehicle"
    assert list(results.to_dict()) == ["model_file", "spec", "note"]


def test_create_then_load(tmp_path):
    path = tmp_path / "results" / "car.json"
    Results(model_file="/m/car.blend", spec="vehicle", path=path).create()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "model_file": "/m/car.blend",
        "spec": "vehicle",
    }
    assert Results.load(path) == Results(
        model_file="/m/car.blend", spec="vehicle", path=path
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"spec": "vehicle"}, "`model_file` is not a string."),
        ({"model_file": 1, "spec": "vehicle"}, "`model_file` is not a string."),
        ({"model_file": "/m/car.blend"}, "`spec` is not a string."),
        ({"model_file": "/m/car.blend", "spec": None}, "`spec` is not a string."),
        (
            {"model_file": "/m/car.blend", "spec": "vehicle", "armature": None},
            "`armature` is not a boolean.",
        ),
        (
            {"model_file": "/m/car.blend", "spec": "vehicle", "armature": 1},
            "`armature` is not a boolean.",
        ),
    ],
)
def test_rejects_a_missing_or_mistyped_field(tmp_path, data, message):
    with pytest.raises(ValueError, match=message):
        Results.from_dict(data, path=tmp_path / "car.json")


def test_unchecked_armature_is_none_and_omitted(tmp_path):
    data = {"model_file": "/m/car.blend", "spec": "vehicle"}
    results = Results.from_dict(data, path=tmp_path / "car.json")
    assert results.armature is None
    assert results.to_dict() == data


@pytest.mark.parametrize("passed", [True, False])
def test_armature_result_round_trips_before_extra_keys(tmp_path, passed):
    data = {"note": "x", "armature": passed, "spec": "vehicle", "model_file": "/m"}
    results = Results.from_dict(data, path=tmp_path / "car.json")
    assert results.armature is passed
    assert list(results.to_dict()) == ["model_file", "spec", "armature", "note"]


def test_save_writes_the_armature_result(tmp_path):
    path = tmp_path / "car.json"
    Results(model_file="/m/car.blend", spec="vehicle", path=path).create()
    results = Results.load(path)
    results.armature = False
    results.save()
    assert json.loads(path.read_text(encoding="utf-8"))["armature"] is False


def test_path_for_is_stable_and_named_after_the_model(tmp_path):
    model = tmp_path / "models" / "car.blend"
    path = Results.path_for(tmp_path / "results", model)
    assert path == Results.path_for(tmp_path / "results", model)
    assert path.parent == tmp_path / "results"
    assert path.name.startswith("car-")
    assert path.suffix == ".json"


def test_path_for_keeps_same_named_models_apart(tmp_path):
    results_dir = tmp_path / "results"
    first = Results.path_for(results_dir, tmp_path / "a" / "car.blend")
    second = Results.path_for(results_dir, tmp_path / "b" / "car.blend")
    assert first != second
