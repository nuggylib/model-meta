"""Unit tests for parenting patterns (model_meta.specs.parenting)."""

import pytest

from model_meta.specs import parenting

CORNERS = ["front.L", "front.R", "rear.L", "rear.R"]
SUSARMS = [
    f"susarm.{c.split('.')[0]}.{h}.{c.split('.')[1]}"
    for c in CORNERS
    for h in ("top", "bottom")
]
REQUIRED = [
    "root",
    *(f"wheel.{c}" for c in CORNERS),
    *(f"axle.{c}" for c in CORNERS),
    *SUSARMS,
    *(f"shockmount.body.{c}" for c in CORNERS),
    *(f"shockmount.wheel.{c}" for c in CORNERS),
]


def _infer(parents, children, existing=None):
    return parenting.infer(parents, children, REQUIRED, existing or {})


def _corners(base):
    return [f"{base}.{c}" for c in CORNERS]


# --- match -----------------------------------------------------------------


def test_match_literal():
    assert parenting.match("root", "root") == {}
    assert parenting.match("root", "rooty") is None


def test_match_binds_one_whole_segment_per_placeholder():
    assert parenting.match("axle.{1}.{2}", "axle.front.L") == {
        "{1}": "front",
        "{2}": "L",
    }


def test_match_needs_the_same_segment_count():
    assert parenting.match("axle.{1}", "axle.front.L") is None
    assert parenting.match("axle.{1}.{2}", "axle.L") is None


def test_match_honours_bound_values():
    assert (
        parenting.match("wheel.{1}.{2}", "wheel.front.L", {"{1}": "front"}) is not None
    )
    assert parenting.match("wheel.{1}.{2}", "wheel.rear.L", {"{1}": "front"}) is None


def test_match_repeated_placeholder_must_agree():
    assert parenting.match("a.{1}.{1}", "a.x.x") == {"{1}": "x"}
    assert parenting.match("a.{1}.{1}", "a.x.y") is None


def test_match_base_is_always_literal():
    assert parenting.match("{1}.L", "arm.L") is None


def test_has_placeholder_segment():
    assert parenting.has_placeholder_segment("arm.{1}")
    assert not parenting.has_placeholder_segment("arm.L")


# --- generalize -------------------------------------------------------------


def test_generalize_keeps_identical_names_literal():
    assert parenting.generalize(["wheel.front.L"]) == "wheel.front.L"
    assert parenting.generalize(["root", "root"]) == "root"


def test_generalize_numbers_each_differing_segment_in_order():
    assert parenting.generalize(["wheel.front.L", "wheel.front.R"]) == "wheel.front.{1}"
    assert (
        parenting.generalize(["susarm.front.top.L", "susarm.rear.top.R"])
        == "susarm.{1}.top.{2}"
    )


@pytest.mark.parametrize(
    "names", [[], ["wheel.front.L", "axle.front.L"], ["wheel.front.L", "wheel.L"]]
)
def test_generalize_needs_a_shared_base_and_length(names):
    assert parenting.generalize(names) is None


# --- resolve / ancestors / is_valid / merge ---------------------------------


def test_resolve_pairs_each_mirror_with_its_own_child():
    resolved = parenting.resolve({"axle.{1}.{2}": ["wheel.{1}.{2}"]}, REQUIRED)
    assert resolved == {f"wheel.{c}": [f"axle.{c}"] for c in CORNERS}


def test_resolve_free_placeholders_match_independently():
    resolved = parenting.resolve({"root": ["susarm.{1}.{2}.{3}"]}, REQUIRED)
    assert sorted(resolved) == sorted(SUSARMS)


def test_resolve_ignores_other_syntaxes():
    assert parenting.resolve({"axle.*": ["wheel.*"]}, REQUIRED) == {}


def test_ancestors_walks_up():
    resolved = {"wheel.front.L": ["axle.front.L"], "axle.front.L": ["root"]}
    assert parenting.ancestors("wheel.front.L", resolved) == {"axle.front.L", "root"}
    assert parenting.ancestors("root", resolved) == set()


def test_is_valid_rejects_two_parents_and_cycles():
    assert parenting.is_valid({"root": ["axle.front.L"]}, REQUIRED)
    assert not parenting.is_valid(
        {"root": ["axle.front.L"], "wheel.front.L": ["axle.front.L"]}, REQUIRED
    )
    assert not parenting.is_valid(
        {"root": ["axle.front.L"], "axle.front.L": ["root"]}, REQUIRED
    )
    assert not parenting.is_valid({"root": ["root"]}, REQUIRED)


def test_merge_appends_dedupes_and_copies():
    existing = {"root": ["a"]}
    merged = parenting.merge(existing, {"root": ["a", "b", "b"], "x": ["y"]})
    assert merged == {"root": ["a", "b"], "x": ["y"]}
    assert existing == {"root": ["a"]}


# --- infer ------------------------------------------------------------------


def test_infer_pairs_each_checked_parent_with_its_corner():
    entries = _infer(_corners("wheel"), _corners("shockmount.wheel"))
    assert entries == {"wheel.{1}.{2}": ["shockmount.wheel.{1}.{2}"]}
    assert len(parenting.pairs(entries, REQUIRED)) == 4


def test_infer_two_child_families_share_one_key():
    children = [*_corners("wheel"), *_corners("shockmount.wheel")]
    entries = _infer(_corners("axle"), children)
    assert entries == {"axle.{1}.{2}": ["wheel.{1}.{2}", "shockmount.wheel.{1}.{2}"]}


def test_infer_one_parent_stays_literal_and_does_not_mirror():
    entries = _infer(["axle.front.L"], ["wheel.front.L"])
    assert entries == {"axle.front.L": ["wheel.front.L"]}


def test_infer_frees_only_the_segments_that_vary():
    entries = _infer(["root"], _corners("shockmount.body"))
    assert entries == {"root": ["shockmount.body.{1}.{2}"]}


def test_infer_collapses_a_whole_family():
    assert _infer(["root"], SUSARMS) == {"root": ["susarm.{1}.{2}.{3}"]}


def test_infer_keeps_a_scattered_selection_exact():
    entries = _infer(["root"], ["susarm.front.top.L", "susarm.rear.bottom.R"])
    assert entries == {"root": ["susarm.front.top.L", "susarm.rear.bottom.R"]}


def test_infer_never_frees_a_segment_with_one_value():
    assert _infer(["root"], ["axle.front.L"]) == {"root": ["axle.front.L"]}


def test_infer_binds_by_value_not_position():
    parents = [b for b in SUSARMS if ".top." in b]
    entries = _infer(parents, _corners("shockmount.wheel"))
    assert entries == {"susarm.{1}.top.{2}": ["shockmount.wheel.{1}.{2}"]}


def test_infer_parents_that_are_not_a_whole_pattern_stay_exact():
    entries = _infer(
        ["wheel.front.L", "wheel.rear.R"],
        ["shockmount.wheel.front.L", "shockmount.wheel.rear.R"],
    )
    assert entries == {
        "wheel.front.L": ["shockmount.wheel.front.L"],
        "wheel.rear.R": ["shockmount.wheel.rear.R"],
    }


def test_infer_falls_back_to_exact_on_a_conflict():
    existing = {"root": ["shockmount.wheel.rear.R"]}
    entries = _infer(_corners("wheel"), _corners("shockmount.wheel")[:3], existing)
    assert entries == {
        "wheel.front.L": ["shockmount.wheel.front.L"],
        "wheel.front.R": ["shockmount.wheel.front.R"],
        "wheel.rear.L": ["shockmount.wheel.rear.L"],
    }


@pytest.mark.parametrize(
    ("parents", "child", "reason"),
    [
        (_corners("wheel"), "root", "no checked parent"),
        (["root", "wheel.front.L"], "axle.front.L", "no checked parent"),
        (["axle.front.L", "axle.rear.L"], "brace.front.rear", "more than one parent"),
    ],
)
def test_infer_rejects_a_child_it_cannot_pair(parents, child, reason):
    with pytest.raises(ValueError, match=reason):
        _infer(parents, [child])


@pytest.mark.parametrize("existing", [{}, {"axle.{1}.{2}": ["wheel.{1}.{2}"]}])
def test_infer_merges_into_an_existing_key(existing):
    entries = _infer(_corners("axle"), _corners("shockmount.wheel"), existing)
    merged = parenting.merge(existing, entries)
    assert list(merged) == ["axle.{1}.{2}"]
    assert merged["axle.{1}.{2}"][-1] == "shockmount.wheel.{1}.{2}"


# --- is_stale / stale_keys -------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "old", "new", "expected"),
    [
        ("arm.L", "arm.L", "upperarm.L", True),  # a literal is lost
        ("arm.{1}", "arm.L", "arm.C", False),  # the pattern still covers it
        ("arm.{1}", "arm.L", "upperarm.L", True),
        ("leg.L", "arm.L", "upperarm.L", False),  # it never matched
    ],
)
def test_is_stale(pattern, old, new, expected):
    assert parenting.is_stale(pattern, old, new) is expected


STALE = {"root": ["arm.{1}"], "arm.L": ["hand.L"], "leg.{1}": ["foot.{1}"]}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("arm.L", "upperarm.L", ["root", "arm.L"]),  # a child pattern and a key
        ("hand.L", "palm.L", ["arm.L"]),
        ("leg.L", "leg.R", []),  # the pattern still covers it
        ("root", "base", ["root"]),
        ("spine", "back", []),  # nothing names it
    ],
)
def test_stale_keys(old, new, expected):
    assert parenting.stale_keys(STALE, old, new) == expected


# --- is_unmatched / unmatched_keys -----------------------------------------


@pytest.mark.parametrize(
    ("pattern", "gone", "required", "expected"),
    [
        ("arm.L", "arm.L", ["arm.R"], True),  # a literal loses its only bone
        ("arm.{1}", "arm.L", ["arm.R"], False),  # the pattern still covers one
        ("arm.{1}", "arm.L", ["root"], True),
        ("leg.L", "arm.L", [], False),  # it never matched
    ],
)
def test_is_unmatched(pattern, gone, required, expected):
    assert parenting.is_unmatched(pattern, gone, required) is expected


@pytest.mark.parametrize(
    ("gone", "required", "expected"),
    [
        ("arm.L", ["root", "hand.L", "leg.L", "foot.L"], ["root", "arm.L"]),
        ("hand.L", ["root", "arm.L", "leg.L", "foot.L"], ["arm.L"]),  # child only
        ("leg.L", ["root", "leg.R", "foot.L"], []),  # the pattern still covers it
        ("root", ["arm.L", "hand.L"], ["root"]),  # key only
        ("spine", ["root"], []),  # nothing names it
    ],
)
def test_unmatched_keys(gone, required, expected):
    assert parenting.unmatched_keys(STALE, gone, required) == expected


def test_unmatched_keys_both_key_and_child():
    entries = {"arm.L": ["arm.L.twist"], "root": ["spine"]}
    assert parenting.unmatched_keys(entries, "arm.L", ["root", "spine"]) == ["arm.L"]
