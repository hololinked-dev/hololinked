"""YAML loader restricted to the JSON data model to load Thing Models/Description in YAML."""

import math
import re

from typing import Any

import yaml


class JSONCompatibleYAMLLoader(yaml.SafeLoader):
    """
    Safe YAML loader that resolves unquoted scalars to the same types JSON would.

    The YAML 1.1 resolvers of `yaml.SafeLoader` are replaced:

    - only `true` and `false` (in any of `true`, `True`, `TRUE` casings) are booleans, `yes`, `no`, `on`, `off`
      remain strings
    - integers and floats follow the JSON number grammar, so `1e5` is a float and `1_000`, `0x1F`, `017`, `1:30`
      or `.inf` remain strings
    - timestamps remain strings, for example `created: 2026-11-13`

    Nulls, merge keys (`<<`), anchors and aliases are resolved as usual. Explicit tags like `!!binary`, `!!set` or
    `!!timestamp` still construct non JSON types.
    """


_kept_resolver_tags = ("tag:yaml.org,2002:null", "tag:yaml.org,2002:merge", "tag:yaml.org,2002:yaml")

JSONCompatibleYAMLLoader.yaml_implicit_resolvers = {
    first_char: [(tag, regexp) for tag, regexp in resolvers if tag in _kept_resolver_tags]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
JSONCompatibleYAMLLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
JSONCompatibleYAMLLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^-?(?:0|[1-9][0-9]*)$"),
    list("-0123456789"),
)
JSONCompatibleYAMLLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][-+]?[0-9]+)?|[eE][-+]?[0-9]+)$"),
    list("-0123456789"),
)


def assert_json_compatible(data: Any, path: str, checked: set[int], ancestors: set[int]) -> None:
    """
    Raise if `data` holds a value outside the JSON data model.

    Only `dict` with `str` keys, `list`, `str`, `int`, finite `float`, `bool` and `None` are allowed. Containers
    shared through YAML aliases are checked once, and a container that contains itself is rejected.

    Parameters
    ----------
    data: Any
        the loaded YAML document or a value within it
    path: str
        JSON path of `data` used in the error message, `$` for the document root
    checked: set[int]
        ids of the containers already found valid, empty for the document root
    ancestors: set[int]
        ids of the containers enclosing `data`, empty for the document root

    Raises
    ------
    ValueError
        naming the path of the first value that is not valid JSON
    """
    if data is None or isinstance(data, (str, int)):  # bool is an int
        return
    if isinstance(data, float):
        if not math.isfinite(data):
            raise ValueError(f"{path}: float {data} is not valid JSON")
        return
    if not isinstance(data, (dict, list)):
        raise ValueError(f"{path}: {type(data).__name__} is not valid JSON")
    if id(data) in ancestors:
        raise ValueError(f"{path}: {type(data).__name__} contains itself, a recursive structure is not valid JSON")
    if id(data) in checked:
        return
    is_dict = isinstance(data, dict)
    ancestors.add(id(data))
    for key, value in data.items() if is_dict else enumerate(data):
        if is_dict and not isinstance(key, str):
            raise ValueError(f"{path}: key {key!r} of type {type(key).__name__} is not valid JSON, keys must be strings")
        assert_json_compatible(value, f"{path}.{key}" if is_dict else f"{path}[{key}]", checked, ancestors)
    ancestors.remove(id(data))
    checked.add(id(data))
