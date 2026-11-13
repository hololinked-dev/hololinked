"""Utilities common to all metadata formats."""

from __future__ import annotations

import importlib.util
import json
import os

from pathlib import Path
from typing import Any, Literal


def load_metadata_file(path: str | os.PathLike, format: Literal["json", "yaml"] | None) -> dict[str, Any]:
    """
    Load a metadata document, like a Thing Model or a Thing Description, from a JSON or a YAML file.

    YAML is loaded with `JSONCompatibleYAMLLoader` and must hold only JSON types. Ensure pyyaml is installed.

    Parameters
    ----------
    path: str | os.PathLike
        path of the file
    format: Literal["json", "yaml"] | None
        format of the file, `None` for YAML if the file ends with `.yaml` or `.yml` and JSON otherwise

    Returns
    -------
    dict[str, Any]
        the metadata document

    Raises
    ------
    ImportError
        if a YAML file is loaded without PyYAML installed
    ValueError
        if the document is empty, is not a mapping or (for YAML) holds a value that is not valid JSON
    """
    is_yaml = format == "yaml" if format is not None else Path(path).suffix.lower() in (".yaml", ".yml")
    if is_yaml and importlib.util.find_spec("yaml") is None:
        raise ImportError(
            "PyYAML is required to load YAML files, install a recent version of pyyaml "
            "or hololinked[yaml]/hololinked[all]"
        )
    with open(path, encoding="utf-8") as file:
        if not is_yaml:
            data = json.load(file)
        else:
            from hololinked.yaml_loader import JSONCompatibleYAMLLoader, assert_json_compatible

            loader = JSONCompatibleYAMLLoader(file)
            try:
                data = loader.get_single_data()
            finally:
                loader.dispose()
            assert_json_compatible(data, "$", set(), set())
    if data is None:
        raise ValueError(f"metadata file {path} is empty")
    if not isinstance(data, dict):
        raise ValueError(f"metadata file {path} must hold a mapping at the top level, not a {type(data).__name__}")
    return data
