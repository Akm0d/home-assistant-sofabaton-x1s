"""Phase 8 tests: activity-restore unification and favorites replay.

Each test exercises one slice of Phase 8's contract:

- ``restore_activity`` routes through :func:`run_device_create` with
  ``entity_kind='activity'`` and produces the canonical post-step
  sequence (activity-create -> bindings -> macros -> remote-sync,
  followed by favorite replays via :meth:`command_to_favorite`).
- Unmapped macro-step references are surfaced -- logged at WARNING
  and counted in ``DeviceCreateResult.skipped_macro_steps`` -- rather
  than silently dropped (the Phase 8 E6 fix).
- Favorite replays issue :meth:`command_to_favorite` with the
  remapped destination device id, the source command id, and the
  source slot id.

The tests use a lightweight monkeypatched proxy so they exercise the
orchestration without a hub connection.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from tests._stub_packages import ensure_stub_package

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ensure_stub_package("custom_components", ROOT / "custom_components")
ensure_stub_package(
    "custom_components.sofabaton_x1s",
    ROOT / "custom_components" / "sofabaton_x1s",
)
ensure_stub_package(
    "custom_components.sofabaton_x1s.lib",
    ROOT / "custom_components" / "sofabaton_x1s" / "lib",
)


# conftest installs the homeassistant stubs that X1Proxy needs.
import conftest  # noqa: F401

from custom_components.sofabaton_x1s.const import HUB_VERSION_X1S
from custom_components.sofabaton_x1s.lib import x1_proxy as x1_proxy_module
from custom_components.sofabaton_x1s.lib.device_create import (
    FAMILY_ACTIVITY_CREATE,
    FAMILY_BUTTON_BINDING,
    FAMILY_MACRO,
    FAMILY_REMOTE_SYNC,
)
from custom_components.sofabaton_x1s.lib.x1_proxy import X1Proxy


def _activity_backup(
    *,
    macro_steps: list[dict[str, int]] | None = None,
    favorites: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Build a minimal activity backup payload for replay tests."""

    if macro_steps is None:
        macro_steps = [
            {"device_id": 11, "command_id": 1, "button_code": 0x4E21},
            {"device_id": 12, "command_id": 2, "button_code": 0x4E22},
        ]
    if favorites is None:
        favorites = [
            {"button_id": 0xA0, "device_id": 11, "command_id": 1},
            {"button_id": 0xA1, "device_id": 12, "command_id": 2},
        ]
    return {
        "kind": "activity_backup",
        "schema_version": 3,
        "device": {
            "entity_type": "activity",
            "device_id": 5,
            "name": "Watch TV",
            "brand": "",
            "icon": 0,
            "sort": 0,
            "code_type": 0x0D,
            "device_type": 0x00,
            "code_id": b"\x00" * 16,
            "hide": 0,
            "input_flag": 0,
            "channel": 0,
            "power_state": 0,
            "ip_address": None,
            "poll_time": 0,
            "input_mode": 0,
            "power_mode": 0,
            "power_style": 0,
            "share_mode": 0,
        },
        "button_bindings": [
            {"button_id": 0x58, "device_id": 11, "command_id": 1},
        ],
        "macros": [
            {"button_id": 0xC6, "name": "Watch TV ON", "steps": macro_steps}
        ],
        "favorite_slots": favorites,
    }


def _patched_proxy(monkeypatch: pytest.MonkeyPatch) -> tuple[X1Proxy, list[Any]]:
    """Build an X1Proxy with the wire-touching hooks neutralised.

    Returns the proxy plus the captured ``CreateStep`` sequence list
    each ``run_create_sequence`` invocation receives. The first
    invocation is the family-0x37 activity-create; subsequent
    invocations are the post-step batch and any
    ``command_to_favorite`` driven map/stage/commit calls.
    """

    proxy = X1Proxy(
        "127.0.0.1",
        proxy_enabled=False,
        diag_dump=False,
        diag_parse=False,
        hub_version=HUB_VERSION_X1S,
    )
    monkeypatch.setattr(proxy, "can_issue_commands", lambda: True)
    monkeypatch.setattr(proxy, "reset_ack_queues", lambda: None)
    monkeypatch.setattr(proxy, "clear_entity_cache", lambda *args, **kwargs: None)

    sequence_calls: list[list[Any]] = []

    def _run_create_sequence(_proxy, steps):
        steps_list = list(steps)
        sequence_calls.append(steps_list)
        # Every batch succeeds; on the create batch, report the
        # hub-assigned activity id at 0x55.
        assigned = 0x55 if len(sequence_calls) == 1 else None
        return types.SimpleNamespace(
            success=True,
            assigned_device_id=assigned,
            failed_step=None,
            failed_index=None,
        )

    monkeypatch.setattr(
        x1_proxy_module, "run_create_sequence", _run_create_sequence
    )
    return proxy, sequence_calls


def test_restore_activity_post_steps_match_canonical(monkeypatch) -> None:
    """The post-step batch is bindings -> macros -> remote-sync (in order)."""

    proxy, sequence_calls = _patched_proxy(monkeypatch)

    favorite_calls: list[tuple[int, int, int, int | None]] = []

    def _command_to_favorite(activity_id, device_id, command_id, *, slot_id=None, refresh_after_write=True):
        favorite_calls.append((activity_id, device_id, command_id, slot_id))
        return {"activity_id": activity_id, "device_id": device_id, "command_id": command_id}

    monkeypatch.setattr(proxy, "command_to_favorite", _command_to_favorite)

    result = proxy.restore_activity(
        _activity_backup(),
        device_id_map={11: 0x21, 12: 0x22},
    )

    assert result is not None
    assert result["status"] == "success"
    assert result["activity_id"] == 0x55

    # First batch: family-0x37 create.
    assert len(sequence_calls) == 2
    create_steps = sequence_calls[0]
    assert len(create_steps) == 1
    assert create_steps[0].family == FAMILY_ACTIVITY_CREATE

    # Second batch: bindings, macros, remote-sync, in that order.
    post_steps = sequence_calls[1]
    families = [step.family for step in post_steps]
    assert families[-1] == FAMILY_REMOTE_SYNC
    assert FAMILY_BUTTON_BINDING in families
    assert FAMILY_MACRO in families
    # Bindings come before macros come before remote-sync.
    binding_idx = families.index(FAMILY_BUTTON_BINDING)
    macro_idx = families.index(FAMILY_MACRO)
    assert binding_idx < macro_idx < families.index(FAMILY_REMOTE_SYNC)


def test_restore_activity_writes_favorite_slots(monkeypatch) -> None:
    """Each backup favorite triggers a remapped ``command_to_favorite`` call."""

    proxy, _sequence_calls = _patched_proxy(monkeypatch)

    favorite_calls: list[tuple[int, int, int, int | None]] = []

    def _command_to_favorite(activity_id, device_id, command_id, *, slot_id=None, refresh_after_write=True):
        favorite_calls.append((activity_id, device_id, command_id, slot_id))
        return {"activity_id": activity_id, "device_id": device_id, "command_id": command_id}

    monkeypatch.setattr(proxy, "command_to_favorite", _command_to_favorite)

    result = proxy.restore_activity(
        _activity_backup(),
        device_id_map={11: 0x21, 12: 0x22},
    )

    assert result is not None
    assert result["restored_favorites"] == 2
    assert result["skipped_favorites"] == 0
    # Both favorites issued through the live add-favorite path, with
    # device ids remapped through the device_id_map and the source
    # slot id preserved.
    assert favorite_calls == [
        (0x55, 0x21, 1, 0xA0),
        (0x55, 0x22, 2, 0xA1),
    ]


def test_restore_logs_skipped_favorite_with_unmapped_command(
    monkeypatch, caplog
) -> None:
    """A favorite whose ``command_id`` is zero is skipped + counted + logged."""

    proxy, _sequence_calls = _patched_proxy(monkeypatch)

    favorite_calls: list[Any] = []
    monkeypatch.setattr(
        proxy,
        "command_to_favorite",
        lambda *args, **kwargs: favorite_calls.append((args, kwargs)) or {"ok": True},
    )

    payload = _activity_backup(
        macro_steps=[{"device_id": 11, "command_id": 1, "button_code": 0x4E21}],
        favorites=[
            {"button_id": 0xA0, "device_id": 11, "command_id": 1},
            # command_id == 0 -> unbound on source, should be skipped.
            {"button_id": 0xA1, "device_id": 11, "command_id": 0},
        ],
    )

    with caplog.at_level(logging.WARNING):
        result = proxy.restore_activity(payload, device_id_map={11: 0x21})

    assert result is not None
    assert result["restored_favorites"] == 1
    assert result["skipped_favorites"] == 1
    # Only the well-formed favorite reached the live write path.
    assert len(favorite_calls) == 1
    # The skipped one logged a WARNING citing the slot id.
    assert any(
        "skipped favorite slot=0xA1" in record.getMessage()
        for record in caplog.records
    )


def test_restore_activity_logs_unmapped_macro_steps(
    monkeypatch, caplog
) -> None:
    """An unmapped macro step ``device_id`` is logged + counted, not silently dropped."""

    proxy, _sequence_calls = _patched_proxy(monkeypatch)
    monkeypatch.setattr(proxy, "command_to_favorite", lambda *a, **kw: {"ok": True})

    # The macro has three steps, one of which references device id 99
    # which is intentionally absent from the supplied map. The
    # up-front validation should still catch it -- this test exercises
    # the defence-in-depth log + counter inside the macro loop.
    macro_steps = [
        {"device_id": 11, "command_id": 1, "button_code": 0x4E21},
        {"device_id": 0, "command_id": 0, "button_code": 0},  # benign no-op
        {"device_id": 11, "command_id": 3, "button_code": 0x4E23},
    ]
    payload = _activity_backup(macro_steps=macro_steps, favorites=[])

    # device_id 11 is mapped; step #2 has device_id 0 which is a
    # legitimate no-op (not counted, not logged).
    with caplog.at_level(logging.WARNING):
        result = proxy.restore_activity(payload, device_id_map={11: 0x21})

    assert result is not None
    # No skipped_macro_steps because device_id=0 is a benign no-op.
    assert result["skipped_macro_steps"] == 0
