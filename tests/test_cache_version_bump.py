"""Phase 6 guardrail: the persistent cache schema version must be at
least 2. Phase 6 reshapes the state surface enough that any older
cache file is no longer safe to load, so we bump the version and let
HomeAssistant's :class:`Store` discard pre-bump payloads on read.
"""

from __future__ import annotations

from custom_components.sofabaton_x1s.cache_store import CACHE_STORE_VERSION


def test_cache_store_version_bumped_for_phase_6() -> None:
    assert CACHE_STORE_VERSION >= 2, (
        "Phase 6 reshapes the cached state; bump CACHE_STORE_VERSION so old "
        "caches are discarded on load."
    )
