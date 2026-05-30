from __future__ import annotations

import sys
import types
from pathlib import Path


def ensure_stub_package(name: str, path: Path) -> None:
    """Register a package stub and wire it onto its parent package.

    Some tests import narrow library modules without importing the full Home
    Assistant integration package. When we create ad-hoc package stubs, we need
    both ``sys.modules[name]`` and ``parent.child`` to point at the same module;
    otherwise later string-based monkeypatch resolution can fail depending on
    import order.
    """

    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    module.__path__ = [str(path)]  # type: ignore[attr-defined]

    parent_name, _, child_name = name.rpartition(".")
    if parent_name:
        parent = sys.modules.get(parent_name)
        if parent is None:
            ensure_stub_package(parent_name, path.parent)
            parent = sys.modules[parent_name]
        setattr(parent, child_name, module)
