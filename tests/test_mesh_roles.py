"""Unit tests for mesh-role logic (model_meta.specs.mesh_roles)."""

import pytest

from model_meta.specs import bones, mesh_roles, schema

REQUIRED = [
    "root",
    "susarm.front.top.L",
    "susarm.front.top.R",
    "susarm.rear.top.L",
    "susarm.rear.bottom.L",
]


SUSARM_REGEX = r"(?i)^sus\.?arm\.(?P<pos>front|rear)\.top\.(?P<side>[LR])$"


# --- validate_mesh_regex ---------------------------------------------------


def test_validate_mesh_regex_accepts_the_susarm_example():
    assert mesh_roles.validate_mesh_regex(SUSARM_REGEX) is None


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("", "Enter a mesh regex."),
        (
            "(?i)^sus(",
            "Not a valid regex: missing ), unterminated subpattern at position 8.",
        ),
        (
            "^a(?i)b",
            "Not a valid regex: global flags not at the start of the expression"
            " at position 2.",
        ),
    ],
    ids=["blank", "unbalanced", "mid-pattern-flag"],
)
def test_validate_mesh_regex_rejects(pattern, message):
    assert mesh_roles.validate_mesh_regex(pattern) == message


# --- parse_count -----------------------------------------------------------


@pytest.mark.parametrize(("text", "count"), [("4", 4), ("004", 4), ("1", 1)])
def test_parse_count_accepts_whole_numbers(text, count):
    assert mesh_roles.parse_count(text) == count


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "Enter a count."),
        ("0", "The count must be at least 1."),
        ("-1", "The count must be a whole number."),
        ("+4", "The count must be a whole number."),
        ("4.0", "The count must be a whole number."),
        ("1e2", "The count must be a whole number."),
        ("1_000", "The count must be a whole number."),
        ("４", "The count must be a whole number."),
        ("four", "The count must be a whole number."),
    ],
)
def test_parse_count_rejects(text, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        mesh_roles.parse_count(text)


# --- texture_choices / order_texture_maps --------------------------------


def test_texture_choices_without_extras_is_the_schema():
    assert mesh_roles.texture_choices(["normal", "albedo"]) == list(schema.TEXTURE_MAPS)


def test_texture_choices_appends_unknown_names_once_in_order():
    current = ["albedo_tex", "albedo", "Albedo", "albedo_tex"]
    assert mesh_roles.texture_choices(current) == [
        *schema.TEXTURE_MAPS,
        "albedo_tex",
        "Albedo",
    ]


def test_order_texture_maps_follows_the_schema_then_extras():
    current = ["zzz", "normal"]
    checked = ["orm", "zzz", "albedo", "normal"]
    assert mesh_roles.order_texture_maps(checked, current) == [
        "albedo",
        "normal",
        "orm",
        "zzz",
    ]


def test_order_texture_maps_of_nothing_is_empty():
    assert mesh_roles.order_texture_maps([], ["albedo"]) == []


# --- validate_name ---------------------------------------------------------


def test_validate_name_accepts_a_new_name():
    assert mesh_roles.validate_name("susarm_upper", ["body"]) is None


def test_validate_name_rejects_blank():
    assert mesh_roles.validate_name("", []) == "Enter a role name."


def test_validate_name_rejects_a_duplicate():
    assert (
        mesh_roles.validate_name("body", ["body"]) == "'body' is already a mesh role."
    )


def test_validate_name_compares_exactly():
    assert mesh_roles.validate_name("Body", ["body"]) is None


# --- matches ---------------------------------------------------------------


def test_matches_an_exact_name():
    assert mesh_roles.matches("root", REQUIRED) == ["root"]


def test_matches_placeholders_across_segments_in_order():
    assert mesh_roles.matches("susarm.{1}.top.{2}", REQUIRED) == [
        "susarm.front.top.L",
        "susarm.front.top.R",
        "susarm.rear.top.L",
    ]


def test_matches_needs_the_same_segment_count():
    assert mesh_roles.matches("susarm.{1}", REQUIRED) == []


def test_matches_keeps_the_base_literal():
    assert mesh_roles.matches("{1}.front.top.L", REQUIRED) == []


# --- infer_vtx_grp ---------------------------------------------------------


def _reason(checked, required=REQUIRED):
    with pytest.raises(ValueError) as error:
        mesh_roles.infer_vtx_grp(checked, required)
    return str(error.value)


def test_infer_vtx_grp_one_bone_is_its_exact_name():
    assert mesh_roles.infer_vtx_grp(["susarm.rear.top.L"], REQUIRED) == (
        "susarm.rear.top.L"
    )


def test_infer_vtx_grp_frees_the_segments_that_differ():
    checked = ["susarm.front.top.R", "susarm.front.top.L"]
    assert mesh_roles.infer_vtx_grp(checked, REQUIRED) == "susarm.front.top.{1}"


def test_infer_vtx_grp_follows_required_order():
    checked = ["susarm.rear.top.L", "susarm.front.top.L"]
    assert mesh_roles.infer_vtx_grp(checked, REQUIRED) == "susarm.{1}.top.L"


def test_infer_vtx_grp_needs_a_checked_bone():
    assert _reason([]) == "Check at least one bone."


def test_infer_vtx_grp_rejects_a_mixed_base_or_length():
    assert _reason(["root", "susarm.front.top.L"]) == (
        "'root' and 'susarm.front.top.L' can't share one pattern."
    )


def test_infer_vtx_grp_rejects_over_the_byte_limit():
    required = ["a" + ".x" * 31, "a" + ".y" * 31]
    assert _reason(required, required) == (
        f"Vertex group names are limited to {bones.MAX_BYTES} bytes."
    )


def test_infer_vtx_grp_names_the_bones_it_would_also_match():
    assert _reason(["susarm.front.top.R", "susarm.rear.top.L"]) == (
        "'susarm.{1}.top.{2}' would also match susarm.front.top.L."
    )


# --- stale_roles -----------------------------------------------------------

ROLES = {
    "body": {"vtx_grp": "body"},
    "arm": {"vtx_grp": "arm.{1}"},
    "glass": {},
}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("body", "hull", ["body"]),
        ("arm.L", "upperarm.L", ["arm"]),
        ("arm.L", "arm.R", []),  # the pattern still covers it
        ("glass", "window", []),  # no vtx_grp
    ],
)
def test_stale_roles(old, new, expected):
    assert mesh_roles.stale_roles(ROLES, old, new) == expected


# --- unmatched_roles -------------------------------------------------------


@pytest.mark.parametrize(
    ("gone", "required", "expected"),
    [
        ("body", ["arm.L"], ["body"]),  # a literal
        ("arm.L", ["arm.R"], []),  # the pattern still covers one
        ("arm.L", ["body"], ["arm"]),  # the pattern loses its last bone
        ("glass", [], []),  # no vtx_grp
    ],
)
def test_unmatched_roles(gone, required, expected):
    assert mesh_roles.unmatched_roles(ROLES, gone, required) == expected
