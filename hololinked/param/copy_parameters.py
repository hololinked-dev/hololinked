def copy_parameters(
    src: str = "D:/onedrive/desktop/dashboard/scada/scadapy/scadapy/param/parameters.py",
    dst: str = "D:/onedrive/desktop/dashboard/scada/scadapy/scadapy/server/remote_parameters.py",
) -> None:
    skip_classes = [
        "Infinity",
        "resolve_path",
        "normalize_path",
        "BaseConstrainedList",
        "TypeConstrainedList",
        "TypeConstrainedDict",
        "TypedKeyMappingsConstrainedDict",
        "Event",
    ]
    end_line = "def hashable"
    additional_imports = [
        "from ..param.parameters import (TypeConstrainedList, TypeConstrainedDict, abbreviate_paths,\n",
        "                       TypedKeyMappingsConstrainedDict, resolve_path, concrete_descendents, named_objs)\n"
        "from .remote_parameter import RemoteParameter\n",
        "from .constants import HTTP, PROXY, USE_OBJECT_NAME, GET, PUT",
    ]

    def fetch_line() -> typing.Generator[str]:
        with open(src, "r") as file:
            oldlines = file.readlines()
            for line in oldlines:
                yield line

    remote_init_kwargs = [
        "\t\t\tURL_path : str = USE_OBJECT_NAME, http_method : typing.Tuple[str, str] = (GET, PUT),\n",
        "\t\t\tstate : typing.Optional[typing.Union[typing.List, typing.Tuple, str, Enum]] = None,\n",
        "\t\t\tdb_persist : bool = False, db_init : bool = False, db_commit : bool = False,\n"
        "\t\t\taccess_type : str = (HTTP, PROXY),\n",
    ]

    remote_super_init = [
        "\t\t\tURL_path=URL_path, http_method=http_method, state=state, db_persist=db_persist,\n",
        "\t\t\tdb_init=db_init, db_commit=db_commit, access_type=access_type)\n",
    ]

    common_linegen = fetch_line()
    newlines = []

    def skip_to_init_doc():
        for line in common_linegen:
            if "doc : typing.Optional[str] = None" in line:
                return line
            else:
                newlines.append(line)

    def skip_to_super_init_end():
        for line in common_linegen:
            if "precedence=precedence)" in line:
                return line
            else:
                newlines.append(line)

    def is_function(line: str) -> bool:
        if "def " in line and "self" not in line and "cls" not in line and "obj" not in line:
            return True
        return False

    def next_line_after_skip_class_or_function() -> str:
        for line_ in common_linegen:
            if ("class " in line_ and ":" in line_) or is_function(line_):
                return line_

    def process_current_line(line: str):
        newline = line
        if "import " in line and "parameterized " in line:
            newlines_ = [
                line.replace("from .parameterized", "from ..param.parameterized").replace("ParamOverrides,", ""),
                next(common_linegen).replace("ParameterizedFunction, descendents,", ""),
                *additional_imports,
            ]
            newlines.extend(newlines_)
            return
        elif "from collections import OrderedDict" in line:
            newlines.append("from enum import Enum\n")
        elif "from .utils" in line or "from .exceptions" in line:
            newline = line.replace("from .", "from ..param.")
        elif "class " in line and ":" in line and line.startswith("class"):
            if "(Parameter):" in line:
                newline = line.replace("(Parameter):", "(RemoteParameter):")
                newlines.append(newline)
            else:
                classname_with_inheritance = line.split(" ", 1)[1][:-2]  # [:-2] for removing colon
                classname_without_inheritance = classname_with_inheritance.split("(", 1)[0]
                if classname_without_inheritance in skip_classes:
                    newline = next_line_after_skip_class_or_function()
                    process_current_line(newline)
                    return
                else:
                    newlines.append(line)
            newline = skip_to_init_doc()
            newlines.append(newline)
            newlines.extend(remote_init_kwargs)
            newline = skip_to_super_init_end()
            if newline:
                newline = newline.replace("precedence=precedence)", "precedence=precedence,")
                newlines.append(newline)
                newlines.extend(remote_super_init)
            return
        elif "Parameter.__init__" in line:
            newline = line.replace("Parameter.__init__", "RemoteParameter.__init__")
        elif is_function(line):
            newline = next_line_after_skip_class_or_function()
            process_current_line(newline)
            return
        newlines.append(newline)

    for line in common_linegen:
        process_current_line(line)
        if end_line in line:
            newlines.pop()
            break

    with open(dst, "w") as file:
        file.writelines(newlines)
