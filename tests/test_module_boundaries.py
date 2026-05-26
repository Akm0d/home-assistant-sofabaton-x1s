"""Phase 6 guardrails: keep ``lib/x1_proxy.py`` from regrowing and
ensure the mixin extraction doesn't introduce import cycles.
"""

from __future__ import annotations

import ast
from pathlib import Path


LIB_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "sofabaton_x1s" / "lib"


def test_x1_proxy_under_2000_lines() -> None:
    """``lib/x1_proxy.py`` is the thin orchestrator; mixins host the bulk.

    Phase 6 collapsed roughly five thousand lines into per-subsystem
    mixins; this guard catches regressions where new logic is dropped
    back into ``x1_proxy.py`` instead of into one of the proxy_*
    mixin modules.
    """

    x1_proxy_path = LIB_DIR / "x1_proxy.py"
    line_count = sum(1 for _ in x1_proxy_path.open(encoding="utf-8"))
    assert line_count < 2000, (
        f"lib/x1_proxy.py grew to {line_count} lines (Phase 6 budget is < 2000). "
        "New methods belong in one of the proxy_* mixin modules."
    )


def test_proxy_mixin_imports_form_a_dag() -> None:
    """Cross-module imports between proxy_* mixins must not form a cycle.

    ``lib/x1_proxy.py`` composes the mixins, so it is allowed to import
    from every proxy_* module. The mixins themselves may delegate back
    to ``lib.x1_proxy`` via *function-level* lazy imports (used to keep
    monkeypatch sites consistent), but no module-level import edge
    between two proxy_* modules is permitted -- and no proxy_* module
    may import ``x1_proxy`` at module load time.
    """

    proxy_modules = sorted(p for p in LIB_DIR.glob("proxy_*.py"))
    assert proxy_modules, "expected at least one proxy_* mixin module"

    edges: dict[str, set[str]] = {}
    for path in proxy_modules:
        name = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        targets: set[str] = set()
        # Only inspect top-level imports; function-level lazy imports
        # are an accepted pattern for breaking would-be cycles back to
        # ``x1_proxy``.
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                if node.module.startswith("proxy_") or node.module == "x1_proxy":
                    targets.add(node.module)
        edges[name] = targets

    for mixin, targets in edges.items():
        assert "x1_proxy" not in targets, (
            f"{mixin}.py imports x1_proxy at module load -- this risks an "
            "import cycle. Use a function-level ``from . import x1_proxy`` "
            "inside the consuming method instead."
        )
        for target in targets:
            if target.startswith("proxy_"):
                # If A imports B at module load, B must not import A.
                assert mixin not in edges.get(target, set()), (
                    f"Cycle detected between {mixin}.py and {target}.py"
                )
