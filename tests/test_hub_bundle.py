"""Bundle backup/restore tests (Phase A + Phase B of the bundle-backup plan).

The bundle is the *only* backup unit -- per the plan the standalone
``backup_device`` / ``backup_activity`` / ``restore_device`` /
``restore_activity`` services no longer exist. These tests exercise
both halves of the new surface:

- ``async_backup_hub`` builds a ``hub_bundle`` envelope, wrapping
  either a list of device payloads (when ``device_ids`` is supplied)
  or every device + every activity (when ``device_ids`` is omitted).
- ``restore_hub_bundle`` drives ``restore_device`` per bundled
  device, builds an auto ``source_device_id -> new_device_id`` map,
  then drives ``restore_activity`` per bundled activity with that
  map plus the per-device ``command_id_map`` and the bundle's
  device payloads so 0xC5 ("set input on device") macro rows can
  be re-resolved against the freshly-restored devices.
- ``async_erase_configuration`` is a ``NotImplementedError`` stub
  until per-hub-version erase opcodes are researched and
  implemented; replace-mode bundle restores fail fast on it.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
from custom_components.sofabaton_x1s.lib.x1_proxy import X1Proxy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _device_payload(
    *,
    source_device_id: int,
    name: str = "TV",
    inputs: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Build a minimal device-backup dict suitable for bundle restore.

    Only the fields the bundle orchestrator and the 0xC5 resolver
    actually read are populated. The proxy-level ``restore_device``
    is stubbed in these tests, so the rest of the device-restore
    surface doesn't need to validate.
    """

    return {
        "kind": "device_backup",
        "schema_version": 3,
        "device": {
            "device_id": source_device_id,
            "name": name,
            "device_class": "ir",
        },
        "commands": [],
        "button_bindings": [],
        "macros": [],
        "favorite_slots": [],
        "inputs": inputs or [],
    }


def _activity_payload(
    *,
    source_activity_id: int,
    macro_steps: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Build a minimal activity-backup dict suitable for bundle restore."""

    return {
        "kind": "activity_backup",
        "schema_version": 3,
        "device": {
            "entity_type": "activity",
            "device_id": source_activity_id,
            "name": f"Activity {source_activity_id}",
        },
        "button_bindings": [],
        "favorite_slots": [],
        "macros": [
            {
                "button_id": 0xC6,
                "name": "POWER_ON",
                "steps": macro_steps or [],
            }
        ],
        "referenced_source_device_ids": sorted(
            {int(step.get("device_id", 0)) & 0xFF for step in (macro_steps or [])}
            - {0}
        ),
    }


def _proxy(monkeypatch: pytest.MonkeyPatch) -> X1Proxy:
    """Build an X1Proxy with the wire path neutralised."""

    proxy = X1Proxy(
        "127.0.0.1",
        proxy_enabled=False,
        diag_dump=False,
        diag_parse=False,
        hub_version=HUB_VERSION_X1S,
    )
    monkeypatch.setattr(proxy, "can_issue_commands", lambda: True)
    monkeypatch.setattr(proxy, "reset_ack_queues", lambda: None)
    monkeypatch.setattr(proxy, "clear_entity_cache", lambda *a, **kw: None)
    return proxy


# ---------------------------------------------------------------------------
# Phase A: backup_bundle
# ---------------------------------------------------------------------------


def _run(coro):
    """Drive an async function on a fresh event loop (Python 3.13-safe)."""

    return asyncio.run(coro)


def test_backup_hub_wraps_single_device_in_bundle(monkeypatch) -> None:
    """``device_ids=[N]`` produces a hub_bundle with one device, no activities."""

    from custom_components.sofabaton_x1s.hub import SofabatonHub

    hub = SofabatonHub.__new__(SofabatonHub)
    hub.entry_id = "entry-1"
    hub.name = "Sofabaton"
    hub.version = HUB_VERSION_X1S

    backed_up: list[int] = []

    async def _async_backup_device(*, device_id: int, wait_timeout: float = 10.0):
        backed_up.append(device_id)
        return {
            "kind": "device_backup",
            "complete": True,
            "device": {"device_id": device_id, "name": f"Device {device_id}"},
        }

    async def _async_backup_activity(*, activity_id: int, wait_timeout: float = 10.0):
        raise AssertionError("activities must not be backed up in subset mode")

    hub.async_backup_device = _async_backup_device  # type: ignore[assignment]
    hub.async_backup_activity = _async_backup_activity  # type: ignore[assignment]

    result = _run(hub.async_backup_hub(device_ids=[7]))

    assert result["kind"] == "hub_bundle"
    assert result["schema_version"] == 4
    assert len(result["devices"]) == 1
    assert result["activities"] == []
    assert backed_up == [7]


def test_backup_hub_rejects_empty_after_validation(monkeypatch) -> None:
    """Empty ``device_ids`` list raises (caller should pass ``None`` for whole-hub)."""

    from custom_components.sofabaton_x1s.hub import SofabatonHub

    hub = SofabatonHub.__new__(SofabatonHub)
    hub.entry_id = "entry-1"
    hub.name = "Sofabaton"
    hub.version = HUB_VERSION_X1S

    with pytest.raises(ValueError, match="must contain at least one device id"):
        _run(hub.async_backup_hub(device_ids=[]))


def test_backup_hub_rejects_out_of_range_device_id() -> None:
    """Each entry must be in 1..255."""

    from custom_components.sofabaton_x1s.hub import SofabatonHub

    hub = SofabatonHub.__new__(SofabatonHub)
    hub.entry_id = "entry-1"
    hub.name = "Sofabaton"
    hub.version = HUB_VERSION_X1S

    with pytest.raises(ValueError, match="must be in 1..255"):
        _run(hub.async_backup_hub(device_ids=[0]))
    with pytest.raises(ValueError, match="must be in 1..255"):
        _run(hub.async_backup_hub(device_ids=[300]))


# ---------------------------------------------------------------------------
# Phase B: restore_hub_bundle orchestration
# ---------------------------------------------------------------------------


def test_restore_bundle_schema_version_rejects_older() -> None:
    """schema_version != 4 is rejected with no side effects."""

    proxy = X1Proxy(
        "127.0.0.1",
        proxy_enabled=False,
        diag_dump=False,
        diag_parse=False,
        hub_version=HUB_VERSION_X1S,
    )
    with pytest.raises(ValueError, match="schema_version must be 4"):
        proxy.restore_hub_bundle({"kind": "hub_bundle", "schema_version": 3})


def test_restore_bundle_rejects_non_bundle_kind() -> None:
    """``kind != 'hub_bundle'`` is rejected."""

    proxy = X1Proxy(
        "127.0.0.1",
        proxy_enabled=False,
        diag_dump=False,
        diag_parse=False,
        hub_version=HUB_VERSION_X1S,
    )
    with pytest.raises(ValueError, match="kind == 'hub_bundle'"):
        proxy.restore_hub_bundle({"kind": "device_backup", "schema_version": 4})


def test_restore_bundle_devices_only_succeeds_and_returns_map(monkeypatch) -> None:
    """Append-mode bundle (no activities) drives restore_device per bundled device."""

    proxy = _proxy(monkeypatch)

    restored_devices: list[dict[str, Any]] = []

    def _restore_device(*, payload, wifi_commands_request_port=8060):
        restored_devices.append(payload)
        src_id = payload["device"]["device_id"]
        return {
            "status": "success",
            "device_id": src_id + 0x10,  # destination assigns +0x10
            "restored_commands": 3,
            "command_id_map": {"1": 11, "2": 12},
        }

    monkeypatch.setattr(proxy, "restore_device", _restore_device)

    bundle = {
        "kind": "hub_bundle",
        "schema_version": 4,
        "devices": [
            _device_payload(source_device_id=7),
            _device_payload(source_device_id=8, name="AVR"),
        ],
        "activities": [],
    }

    result = proxy.restore_hub_bundle(bundle)

    assert result["status"] == "success"
    assert result["device_id_map"] == {"7": 0x17, "8": 0x18}
    assert len(result["restored_devices"]) == 2
    assert result["restored_activities"] == []
    assert [d["device"]["device_id"] for d in restored_devices] == [7, 8]


def test_restore_bundle_partial_device_failure_returns_failed_at(monkeypatch) -> None:
    """Mid-bundle device failure leaves earlier devices in place and skips the rest."""

    proxy = _proxy(monkeypatch)

    seen: list[int] = []

    def _restore_device(*, payload, wifi_commands_request_port=8060):
        src_id = payload["device"]["device_id"]
        seen.append(src_id)
        if src_id == 8:
            return {"status": "failed"}
        return {
            "status": "success",
            "device_id": src_id + 0x10,
            "command_id_map": {},
        }

    monkeypatch.setattr(proxy, "restore_device", _restore_device)
    # restore_activity must never be reached when devices phase fails.
    monkeypatch.setattr(
        proxy,
        "restore_activity",
        lambda *a, **kw: pytest.fail("activities phase reached despite device failure"),
    )

    bundle = {
        "kind": "hub_bundle",
        "schema_version": 4,
        "devices": [
            _device_payload(source_device_id=7),
            _device_payload(source_device_id=8),
            _device_payload(source_device_id=9),
        ],
        "activities": [_activity_payload(source_activity_id=0x55)],
    }

    result = proxy.restore_hub_bundle(bundle)

    assert result["status"] == "failed"
    assert result["failed_at"] == ["device", 8]
    assert seen == [7, 8]  # device 9 not attempted (no rollback either)
    assert result["device_id_map"] == {"7": 0x17}


def test_restore_bundle_resolves_input_ordinals(monkeypatch) -> None:
    """A 0xC5 macro row is re-resolved through bundle input tables.

    Source layout:
      - device 7 has inputs [{ord=1,cmd=5}, {ord=2,cmd=6}, {ord=3,cmd=7}]
      - macro step references device 7 with duration=2 (source ordinal 2,
        source command_id 6).

    Destination layout:
      - device 7's restore returns command_id_map {6 -> 0x46}.
      - query_device_input_index(new_dev=0x17, new_cmd=0x46) returns 9.

    Expected: the macro step that lands in build_macro_step_record has
    duration=9, not 2.
    """

    proxy = _proxy(monkeypatch)

    def _restore_device(*, payload, wifi_commands_request_port=8060):
        src_id = payload["device"]["device_id"]
        return {
            "status": "success",
            "device_id": src_id + 0x10,
            # The source's input row cmd=6 maps to dest cmd=0x46.
            "command_id_map": {"5": 0x45, "6": 0x46, "7": 0x47},
        }

    monkeypatch.setattr(proxy, "restore_device", _restore_device)

    # The 0xC5 resolver calls query_device_input_index on the proxy
    # for the freshly-restored device with the mapped command id.
    query_calls: list[tuple[int, int]] = []

    def _query(new_dev: int, new_cmd: int, *, timeout: float = 5.0) -> int | None:
        query_calls.append((new_dev, new_cmd))
        if (new_dev, new_cmd) == (0x17, 0x46):
            return 9
        return None

    monkeypatch.setattr(proxy, "query_device_input_index", _query)

    # Capture the duration byte the macro step record builder receives.
    build_records: list[dict[str, int]] = []

    def _build_macro_step_record(*, device_id, command_id, fid, duration, delay):
        build_records.append(
            {
                "device_id": device_id,
                "command_id": command_id,
                "duration": duration,
                "delay": delay,
            }
        )
        return b""

    import custom_components.sofabaton_x1s.lib.proxy_restore as proxy_restore_module

    monkeypatch.setattr(
        proxy_restore_module,
        "build_macro_step_record",
        _build_macro_step_record,
    )

    # Stub out the entire restore_activity-internal create sequence so
    # we exercise the macro builder path without doing wire writes.
    monkeypatch.setattr(
        x1_proxy_module,
        "run_create_sequence",
        lambda _proxy, steps: types.SimpleNamespace(
            success=True,
            assigned_device_id=0x55,
            failed_step=None,
            failed_index=None,
        ),
    )

    bundle = {
        "kind": "hub_bundle",
        "schema_version": 4,
        "devices": [
            _device_payload(
                source_device_id=7,
                inputs=[
                    {"command_id": 5, "input_index": 1, "name": "HDMI1"},
                    {"command_id": 6, "input_index": 2, "name": "HDMI2"},
                    {"command_id": 7, "input_index": 3, "name": "HDMI3"},
                ],
            )
        ],
        "activities": [
            _activity_payload(
                source_activity_id=0x55,
                macro_steps=[
                    # POWER_ON button row (0xC6) -- duration is opaque timing.
                    {
                        "device_id": 7,
                        "command_id": 0xC6,
                        "button_code": 0,
                        "duration": 1,
                        "delay": 0xFF,
                    },
                    # 0xC5 input-switch row -- duration=2 is source ordinal 2
                    # which should be re-resolved to destination ordinal 9.
                    {
                        "device_id": 7,
                        "command_id": 0xC5,
                        "button_code": 0,
                        "duration": 2,
                        "delay": 0xFF,
                    },
                ],
            )
        ],
    }

    result = proxy.restore_hub_bundle(bundle)

    assert result["status"] == "success"
    # 0xC5 step should land with duration=9 after resolution; 0xC6 stays 1.
    durations_by_cmd = {
        rec["command_id"]: rec["duration"]
        for rec in build_records
        if rec["command_id"] in (0xC5, 0xC6)
    }
    assert durations_by_cmd == {0xC6: 1, 0xC5: 9}
    # Resolver actually called the live query with the mapped command id.
    assert query_calls == [(0x17, 0x46)]


def test_restore_bundle_logs_skipped_input_ordinal(monkeypatch, caplog) -> None:
    """An unresolvable 0xC5 ordinal preserves the raw byte and logs a warning."""

    proxy = _proxy(monkeypatch)

    def _restore_device(*, payload, wifi_commands_request_port=8060):
        src_id = payload["device"]["device_id"]
        return {
            "status": "success",
            "device_id": src_id + 0x10,
            "command_id_map": {"5": 0x45},  # no entry for cmd 6
        }

    monkeypatch.setattr(proxy, "restore_device", _restore_device)
    monkeypatch.setattr(proxy, "query_device_input_index", lambda *a, **kw: None)

    build_records: list[dict[str, int]] = []

    def _build_macro_step_record(*, device_id, command_id, fid, duration, delay):
        build_records.append({"command_id": command_id, "duration": duration})
        return b""

    import custom_components.sofabaton_x1s.lib.proxy_restore as proxy_restore_module

    monkeypatch.setattr(
        proxy_restore_module,
        "build_macro_step_record",
        _build_macro_step_record,
    )
    monkeypatch.setattr(
        x1_proxy_module,
        "run_create_sequence",
        lambda _proxy, steps: types.SimpleNamespace(
            success=True,
            assigned_device_id=0x55,
            failed_step=None,
            failed_index=None,
        ),
    )

    bundle = {
        "kind": "hub_bundle",
        "schema_version": 4,
        "devices": [
            _device_payload(
                source_device_id=7,
                inputs=[
                    {"command_id": 6, "input_index": 2, "name": "HDMI2"},
                ],
            )
        ],
        "activities": [
            _activity_payload(
                source_activity_id=0x55,
                macro_steps=[
                    {
                        "device_id": 7,
                        "command_id": 0xC5,
                        "button_code": 0,
                        "duration": 2,
                        "delay": 0xFF,
                    },
                ],
            )
        ],
    }

    with caplog.at_level(logging.WARNING):
        result = proxy.restore_hub_bundle(bundle)

    assert result["status"] == "success"
    # No mapping for source cmd 6 -> raw duration preserved.
    assert build_records[0]["duration"] == 2
    assert any(
        "has no destination command_id" in record.getMessage()
        or "no input row with that ordinal" in record.getMessage()
        or "preserving raw duration" in record.getMessage()
        for record in caplog.records
    )
    assert result["restored_activities"][0]["skipped_input_ordinals"] == 1


def test_restore_activity_without_bundle_context_preserves_raw_duration(
    monkeypatch,
) -> None:
    """Calling restore_activity directly (no bundle context) keeps 0xC5 duration as-is.

    This is the legitimate "same hub round-trip" path: when nothing
    has changed on the source hub, the raw ordinal is still correct.
    The resolver only kicks in when bundle context is supplied.
    """

    proxy = _proxy(monkeypatch)

    build_records: list[dict[str, int]] = []

    def _build_macro_step_record(*, device_id, command_id, fid, duration, delay):
        build_records.append({"command_id": command_id, "duration": duration})
        return b""

    import custom_components.sofabaton_x1s.lib.proxy_restore as proxy_restore_module

    monkeypatch.setattr(
        proxy_restore_module,
        "build_macro_step_record",
        _build_macro_step_record,
    )
    monkeypatch.setattr(
        x1_proxy_module,
        "run_create_sequence",
        lambda _proxy, steps: types.SimpleNamespace(
            success=True,
            assigned_device_id=0x55,
            failed_step=None,
            failed_index=None,
        ),
    )
    # Resolver must NOT be called without bundle context.
    monkeypatch.setattr(
        proxy,
        "query_device_input_index",
        lambda *a, **kw: pytest.fail("resolver should not run outside bundle context"),
    )

    activity = _activity_payload(
        source_activity_id=0x55,
        macro_steps=[
            {
                "device_id": 7,
                "command_id": 0xC5,
                "button_code": 0,
                "duration": 5,
                "delay": 0xFF,
            },
        ],
    )

    result = proxy.restore_activity(activity, device_id_map={7: 0x17})

    assert result is not None and result["status"] == "success"
    # Raw duration preserved verbatim (5 -> 5).
    c5 = [rec for rec in build_records if rec["command_id"] == 0xC5]
    assert c5 and c5[0]["duration"] == 5
    assert result["skipped_input_ordinals"] == 0


def test_async_erase_configuration_raises_not_implemented() -> None:
    """Replace-mode gate: erase raises with hub_version in message."""

    from custom_components.sofabaton_x1s.hub import SofabatonHub

    hub = SofabatonHub.__new__(SofabatonHub)
    hub.entry_id = "entry-1"
    hub.name = "Sofabaton"
    hub.version = HUB_VERSION_X1S

    with pytest.raises(NotImplementedError, match=HUB_VERSION_X1S):
        _run(hub.async_erase_configuration())


def test_async_restore_backup_replace_mode_fails_fast_on_erase_stub() -> None:
    """A bundle with activities triggers the erase stub before any wire writes."""

    from custom_components.sofabaton_x1s.hub import SofabatonHub

    hub = SofabatonHub.__new__(SofabatonHub)
    hub.entry_id = "entry-1"
    hub.name = "Sofabaton"
    hub.version = HUB_VERSION_X1S
    hub._proxy = MagicMock()
    hub._proxy.restore_hub_bundle = MagicMock(
        side_effect=AssertionError(
            "restore_hub_bundle must not be reached in replace mode"
        )
    )

    bundle = {
        "kind": "hub_bundle",
        "schema_version": 4,
        "devices": [],
        "activities": [{"kind": "activity_backup"}],
    }

    with pytest.raises(NotImplementedError, match="not implemented for hub_version"):
        _run(hub.async_restore_backup(bundle))

    hub._proxy.restore_hub_bundle.assert_not_called()
