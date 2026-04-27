from __future__ import annotations

from importlib import import_module
from typing import Any


def import_string(dotted_path: str) -> Any:
    module_path, _, attribute = dotted_path.rpartition(".")
    if not module_path or not attribute:
        msg = f"{dotted_path!r} is not a valid dotted import path"
        raise ImportError(msg)

    module = import_module(module_path)
    return getattr(module, attribute)
