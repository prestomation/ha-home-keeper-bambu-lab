"""End-to-end: real Home Keeper + the fake Bambu Lab + this glue in a HA container.

We toggle the Bambu Lab firmware ``update`` entity (via the fake's
``bambu_lab.set_firmware_available`` service) over REST and assert that Home Keeper's
to-do list reflects the firmware task being armed and cleared. The to-do list counts
incomplete items, and a triggered task is on the list exactly while armed — so its count
is our observable for the full glue → Home Keeper loop.

The behavioural test drives a *fake* Bambu Lab entity (a real printer can't run in CI),
so it can't catch the *real* integration renaming its firmware surface. The static
contract test below guards that separately, against the fetched real ha-bambulab source.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

TODO = "todo.home_keeper_tasks"

# Where ci/fetch-upstreams.sh stages the *real* ha-bambulab for the contract assertion.
_BAMBU_SRC = Path(__file__).resolve().parent / "upstream_src" / "bambu_lab"


def _count(api) -> int:
    return int(api.state(TODO) or 0)


def test_bambu_firmware_contract_against_real_source():
    """Guard the external Bambu Lab firmware surface this glue depends on.

    The behavioural tests drive a fake entity, so they can't catch the real integration
    moving its firmware surface. Assert the real ha-bambulab source still defines a
    ``firmware_update`` update entity keyed ``{serial}_firmware_update`` and driven from
    ``upgrade.new_version`` / ``upgrade.cur_version``. If this fails, the real integration
    moved its surface — update const.py and re-pin BAMBU_REF.
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    update_py = _BAMBU_SRC / "update.py"
    assert update_py.is_file(), "ha-bambulab no longer has update.py"
    text = update_py.read_text(encoding="utf-8")
    # The firmware update entity's description key. The glue's UPDATE_UNIQUE_SUFFIX is
    # "_" + this key (the runtime unique_id is f"{serial}_{key}"), so if the key changes
    # the glue stops matching the entity.
    assert 'key="firmware_update"' in text, (
        "ha-bambulab no longer keys its firmware update entity 'firmware_update' — "
        "update const.UPDATE_UNIQUE_SUFFIX."
    )
    # The unique_id is composed as f"{serial}_{description.key}" — that's what makes the
    # entity id end with '_firmware_update'. The literal suffix never appears in source
    # (it's assembled at runtime), so assert the composition instead.
    assert "description.key" in text and "serial" in text, (
        "ha-bambulab no longer builds the firmware update unique_id from "
        "serial + description.key — re-check const.UPDATE_UNIQUE_SUFFIX."
    )
    assert "new_version" in text and "cur_version" in text, (
        "ha-bambulab no longer sources firmware from upgrade.new_version/cur_version."
    )

    # The other firmware surface: when the "Firmware update" option is off (the default),
    # the integration exposes a binary_sensor keyed 'firmware_update' with device_class
    # UPDATE instead of the update entity. The glue mirrors this variant too, so guard it.
    definitions_py = _BAMBU_SRC / "definitions.py"
    assert definitions_py.is_file(), "ha-bambulab no longer has definitions.py"
    defs = definitions_py.read_text(encoding="utf-8")
    assert 'key="firmware_update"' in defs, (
        "ha-bambulab no longer defines a 'firmware_update' binary_sensor — the glue's "
        "binary_sensor firmware path would silently stop matching."
    )
    assert "BinarySensorDeviceClass.UPDATE" in defs, (
        "ha-bambulab's firmware binary_sensor is no longer device_class UPDATE — "
        "re-check const.FIRMWARE_BINARY_DEVICE_CLASS."
    )


def test_bambu_usage_hours_contract_against_real_source():
    """Guard the cumulative counter the maintenance catalog meters against.

    Every hours-based catalog item binds to ``sensor.<printer>_total_usage_hours``. If
    ha-bambulab renames that key or drops the sensor, those tasks would silently never
    be created (the calendar-only ones would still work, which is exactly the kind of
    half-broken state a contract test exists to catch).
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    definitions_py = _BAMBU_SRC / "definitions.py"
    assert definitions_py.is_file(), "ha-bambulab no longer has definitions.py"
    defs = definitions_py.read_text(encoding="utf-8")
    assert 'key="total_usage_hours"' in defs, (
        "ha-bambulab no longer defines a 'total_usage_hours' sensor — update "
        "const.USAGE_HOURS_UNIQUE_SUFFIX."
    )
    # A meter must be monotonic for the usage-delta arithmetic to mean anything.
    assert "TOTAL_INCREASING" in defs, (
        "ha-bambulab's sensors no longer declare TOTAL_INCREASING — re-check that "
        "total_usage_hours is still a cumulative counter."
    )


def test_available_then_installed_arms_then_clears_the_task(api):
    base = _count(api)

    # Firmware update becomes available → a triggered task is created, armed (on the list).
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))

    # Firmware installed (up to date) → the task records the completion and goes dormant.
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))


def test_available_again_rearms_without_duplicating(api):
    base = _count(api)
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))

    # Available again → re-armed (count back to +1, not +2 — same task reused).
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))
    # Clean up so re-runs start from the same baseline.
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))


def test_maintenance_catalog_task_arms_once_the_meter_advances(api):
    """The catalog's headline path: printer hours advance, a maintenance task comes due.

    The container's config entry is seeded with the catalog on and exactly one item
    enabled (``z_lead_screws``, target 5 h — see ``ha_config/.storage/core.config_entries``),
    so the to-do count moves by one and only for a reason we control.

    Note the deliberate two-step nudge. A usage task created *after* Home Keeper has
    started has no meter baseline yet: Home Keeper stamps it on its first evaluation of
    the bound sensor, which is the next state change (or the 5-minute coordinator tick).
    So the first advance anchors the meter and the second one is what actually crosses
    the target. Nothing here is this glue's code — Home Keeper does the arming, which is
    exactly the division of labour the catalog is built on.
    """
    base = _count(api)

    # First nudge: Home Keeper anchors the meter at the current reading. Dormant, so the
    # to-do list must not move.
    api.call_service("bambu_lab", "advance_usage_hours", {"hours": 1})
    time.sleep(5)
    assert _count(api) == base, "a freshly baselined usage task must stay dormant"

    # Second nudge, well past the 5-hour target -> Home Keeper arms it.
    api.call_service("bambu_lab", "advance_usage_hours", {"hours": 25})
    api.poll_state(TODO, str(base + 1))
