import pytest

from hololinked.metadata.utils import load_metadata_file


def write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_01_unquoted_date_stays_string(tmp_path):
    path = write(tmp_path, "tm.yaml", "created: 2026-11-13\nmodified: 2026-11-13T10:00:00Z")
    assert load_metadata_file(path, None) == {"created": "2026-11-13", "modified": "2026-11-13T10:00:00Z"}


def test_02_only_true_and_false_are_booleans(tmp_path):
    path = write(tmp_path, "tm.yaml", "enum: [yes, no, on, off, true, false, True, FALSE]")
    values = load_metadata_file(path, None)["enum"]
    assert values == ["yes", "no", "on", "off", True, False, True, False]
    assert [type(value) for value in values] == [str] * 4 + [bool] * 4


@pytest.mark.parametrize(
    "name, content, error",
    [
        pytest.param(
            "tm.yaml",
            "properties: {voltage: {enum: {200: ok}}}",
            r"^\$\.properties\.voltage\.enum: key 200 of type int",
            id="int key",
        ),
        pytest.param("tm.yaml", "true: x", r"^\$: key True of type bool", id="bool key"),
        pytest.param("tm.yaml", "const: !!binary aGVsbG8=", r"^\$\.const: bytes is not valid JSON", id="binary"),
        pytest.param("tm.yaml", "tags: !!set {a, b}", r"^\$\.tags: set is not valid JSON", id="set"),
        pytest.param("tm.yaml", "enum: [1, !!float .nan]", r"^\$\.enum\[1\]: float nan", id="nan"),
        pytest.param("tm.yaml", "maximum: !!float .inf", r"^\$\.maximum: float inf", id="inf"),
        pytest.param("tm.yaml", "- title", "must hold a mapping at the top level, not a list", id="top-level list"),
        pytest.param("tm.yaml", "", "is empty", id="empty file"),
        pytest.param("tm.txt", "title: Oscilloscope", "Expecting value", id="unknown suffix read as JSON"),
    ],
)
def test_03_rejects_what_is_not_json(tmp_path, name: str, content: str, error: str):
    with pytest.raises(ValueError, match=error):
        load_metadata_file(write(tmp_path, name, content), None)


def test_04_format_overrides_suffix(tmp_path):
    path = write(tmp_path, "tm.txt", "title: Oscilloscope")
    assert load_metadata_file(path, "yaml") == {"title": "Oscilloscope"}
    path = write(tmp_path, "tm.yaml", '{\n\t"title": "Oscilloscope"\n}')  # tab indentation is not valid YAML
    assert load_metadata_file(path, "json") == {"title": "Oscilloscope"}
