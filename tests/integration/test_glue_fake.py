"""Integration tests for the glue against Home Keeper's real test fake.

These exercise the full contract — a Bambu Lab firmware ``update`` entity's state → Home
Keeper service call → task state — using ``home_keeper.testing.async_setup_fake_home_keeper``
(the real model/event code). They need a real HA test environment
(pytest-homeassistant-custom-component).

Bambu Lab exposes no bus events for firmware, so we stand in a fake ``update`` entity
registered on the ``bambu_lab`` platform (unique_id ``*_firmware_update``) and drive its
state, exactly as the real integration would.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_keeper_bambu_lab.const import (
    BAMBU_DOMAIN,
    DOMAIN,
)

try:
    from home_keeper.testing import async_setup_fake_home_keeper
except ImportError:  # pragma: no cover - home-keeper not installed in this env
    async_setup_fake_home_keeper = None

pytestmark = pytest.mark.skipif(
    async_setup_fake_home_keeper is None,
    reason="home-keeper (test fake) not installed",
)


async def _setup_glue(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _make_bambu_update(
    hass: HomeAssistant,
    *,
    serial: str,
    state: str,
    name: str = "X1 Carbon",
    latest_version: str | None = "01.08.02.00",
    installed_version: str | None = "01.07.00.00",
    release_url: str | None = "https://bambulab.com/release",
) -> tuple[str, str]:
    """Register a Bambu Lab firmware update entity in *state*; return (device_id, entity_id)."""
    bambu_entry = MockConfigEntry(domain=BAMBU_DOMAIN, data={})
    bambu_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bambu_entry.entry_id,
        identifiers={(BAMBU_DOMAIN, serial)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "update",
        BAMBU_DOMAIN,
        f"{serial}_firmware_update",
        device_id=device.id,
    )
    attrs = {}
    if latest_version is not None:
        attrs["latest_version"] = latest_version
    if installed_version is not None:
        attrs["installed_version"] = installed_version
    if release_url is not None:
        attrs["release_url"] = release_url
    hass.states.async_set(ent.entity_id, state, attrs)
    return device.id, ent.entity_id


def _make_bambu_binary_firmware(
    hass: HomeAssistant, *, serial: str, state: str, name: str = "Printermation"
) -> tuple[str, str]:
    """Register the Bambu Lab firmware *binary_sensor* (device_class update) in *state*.

    This is the variant the Bambu Lab integration exposes when its "Firmware update"
    option is off (the default) — a binary_sensor keyed ``{serial}_firmware_update`` with
    device_class ``update``, rather than an ``update`` entity. Returns (device_id, entity_id).
    """
    bambu_entry = MockConfigEntry(domain=BAMBU_DOMAIN, data={})
    bambu_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bambu_entry.entry_id,
        identifiers={(BAMBU_DOMAIN, serial)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "binary_sensor",
        BAMBU_DOMAIN,
        f"{serial}_firmware_update",
        device_id=device.id,
        original_device_class="update",
    )
    hass.states.async_set(ent.entity_id, state, {"device_class": "update"})
    return device.id, ent.entity_id


async def test_update_available_creates_read_only_armed_task(
    hass: HomeAssistant,
) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1C123", state="on")
    entry = await _setup_glue(hass)
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()

    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task is not None
    assert task["recurrence_type"] == "triggered"
    assert task["next_due"]  # armed / due-now
    assert task["managed_by"]["completion_blocked"] is True
    assert task.get("task_chips") == [
        {"label": "01.08.02.00", "icon": "mdi:package-up"},
        {"label": "Release notes", "url": "https://bambulab.com/release"},
    ]


async def test_live_transition_arms_then_clears(hass: HomeAssistant) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_update(hass, serial="P1S9", state="off")
    await _setup_glue(hass)

    # Firmware update appears -> the glue's state watcher arms a task.
    hass.states.async_set(entity_id, "on", {"latest_version": "01.08.02.00"})
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task is not None and task["next_due"]  # armed

    # Firmware installed (entity returns to off) -> task clears itself (dormant), and the
    # install is recorded even though the user never checked it off.
    hass.states.async_set(entity_id, "off", {})
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task["next_due"] is None
    assert len(task["completions"]) == 1


async def test_note_refreshes_to_up_to_date_after_install(hass: HomeAssistant) -> None:
    # After the firmware installs, the note must stop advertising the (now-installed)
    # update — a dormant task shouldn't read "… available" forever.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_update(hass, serial="NOTE1", state="off")
    await _setup_glue(hass)

    hass.states.async_set(
        entity_id,
        "on",
        {"latest_version": "01.08.02.00", "installed_version": "01.06.00.00"},
    )
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert "available" in (task.get("notes") or "")

    # Installed: entity returns to off, now reporting the new version as installed.
    hass.states.async_set(entity_id, "off", {"installed_version": "01.08.02.00"})
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task["next_due"] is None
    assert task["notes"] == "Firmware up to date · 01.08.02.00"


async def test_flapping_after_install_does_not_double_complete(
    hass: HomeAssistant,
) -> None:
    # A single install can present more than one on->off edge (the printer reboots and a
    # stale/retained MQTT message briefly re-reports the update as available). The glue
    # must record exactly one completion, not one per edge.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_update(hass, serial="FLAP1", state="off")
    await _setup_glue(hass)

    # Update available -> armed.
    hass.states.async_set(
        entity_id,
        "on",
        {"latest_version": "01.08.02.00", "installed_version": "01.06.00.00"},
    )
    await hass.async_block_till_done()
    # Install completes -> off (completion #1).
    hass.states.async_set(entity_id, "off", {"installed_version": "01.08.02.00"})
    await hass.async_block_till_done()
    # Reconnect flap: a stale message briefly re-reports the update as available...
    hass.states.async_set(
        entity_id,
        "on",
        {"latest_version": "01.08.02.00", "installed_version": "01.06.00.00"},
    )
    await hass.async_block_till_done()
    # ...then it settles up to date again.
    hass.states.async_set(entity_id, "off", {"installed_version": "01.08.02.00"})
    await hass.async_block_till_done()

    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task["next_due"] is None  # dormant, not re-armed
    assert len(task["completions"]) == 1  # one install, one completion — not two


async def test_offline_printer_does_not_clear_armed_task(hass: HomeAssistant) -> None:
    # An armed task must survive the printer going offline (entity unavailable) — clearing
    # it would record a phantom firmware install.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_update(hass, serial="A1M", state="on")
    await _setup_glue(hass)
    hass.states.async_set(entity_id, "on", {"latest_version": "1"})
    await hass.async_block_till_done()
    assert hk.get_task_by_source(DOMAIN, device_id=device_id)["next_due"]

    hass.states.async_set(entity_id, "unavailable", {})
    await hass.async_block_till_done()

    assert hk.get_task_by_source(DOMAIN, device_id=device_id)["next_due"]  # still armed


async def test_reconcile_clears_when_up_to_date(hass: HomeAssistant) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_update(hass, serial="X1E", state="on")
    entry = await _setup_glue(hass)
    hass.states.async_set(entity_id, "on", {"latest_version": "1"})
    await hass.async_block_till_done()
    assert hk.get_task_by_source(DOMAIN, device_id=device_id)["next_due"]

    # Firmware got installed while we were down: entity now reads off.
    hass.states.async_set(entity_id, "off", {})
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()

    assert hk.get_task_by_source(DOMAIN, device_id=device_id)["next_due"] is None


async def test_duplicate_available_events_do_not_duplicate_tasks(
    hass: HomeAssistant,
) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    _, entity_id = _make_bambu_update(hass, serial="X1D", state="off")
    await _setup_glue(hass)

    hass.states.async_set(entity_id, "on", {"latest_version": "1"})
    hass.states.async_set(
        entity_id, "on", {"latest_version": "1", "installed_version": "0"}
    )
    await hass.async_block_till_done()

    ours = [t for t in hk.tasks.values() if (t.get("source") or {}).get(DOMAIN)]
    assert len(ours) == 1


async def test_no_home_keeper_is_a_safe_noop(hass: HomeAssistant) -> None:
    # Home Keeper absent (no fake): setup + a firmware state change must not raise.
    await async_setup_component(hass, "homeassistant", {})
    _, entity_id = _make_bambu_update(hass, serial="X1F", state="off")
    await _setup_glue(hass)
    hass.states.async_set(entity_id, "on", {"latest_version": "1"})
    await hass.async_block_till_done()


async def test_remove_entry_deletes_only_our_tasks(hass: HomeAssistant) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1G", state="on")
    entry = await _setup_glue(hass)
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()
    ours_id = hk.get_task_by_source(DOMAIN, device_id=device_id)["id"]
    hk.tasks["foreign"] = {
        "id": "foreign",
        "source": {"other": {"x": 1}},
        "next_due": None,
    }

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ours_id not in hk.tasks  # our task cleaned up on removal
    assert "foreign" in hk.tasks  # someone else's task untouched


async def test_binary_sensor_firmware_available_creates_task(
    hass: HomeAssistant,
) -> None:
    # The default Bambu Lab setup (Firmware update option off) exposes firmware as a
    # binary_sensor with device_class update, not an update entity. The glue must still
    # create the task — this is the case a real default install hits.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_binary_firmware(hass, serial="P1S1", state="on")
    entry = await _setup_glue(hass)
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()

    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task is not None
    assert task["recurrence_type"] == "triggered"
    assert task["next_due"]  # armed
    assert task["managed_by"]["completion_blocked"] is True


async def test_binary_sensor_firmware_live_transition_arms_then_clears(
    hass: HomeAssistant,
) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, entity_id = _make_bambu_binary_firmware(hass, serial="P1S2", state="off")
    await _setup_glue(hass)

    hass.states.async_set(entity_id, "on", {"device_class": "update"})
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task is not None and task["next_due"]  # armed

    hass.states.async_set(entity_id, "off", {"device_class": "update"})
    await hass.async_block_till_done()
    task = hk.get_task_by_source(DOMAIN, device_id=device_id)
    assert task["next_due"] is None
    assert len(task["completions"]) == 1


async def test_non_update_binary_sensor_is_ignored(hass: HomeAssistant) -> None:
    # A bambu_lab binary_sensor that happens to end with the suffix but is NOT device_class
    # update (defensive) must not create a task.
    hk = await async_setup_fake_home_keeper(hass)
    bambu_entry = MockConfigEntry(domain=BAMBU_DOMAIN, data={})
    bambu_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bambu_entry.entry_id,
        identifiers={(BAMBU_DOMAIN, "weird")},
        name="Weird",
    )
    ent = er.async_get(hass).async_get_or_create(
        "binary_sensor",
        BAMBU_DOMAIN,
        "weird_firmware_update",
        device_id=device.id,
        original_device_class="problem",
    )
    hass.states.async_set(ent.entity_id, "on", {"device_class": "problem"})
    entry = await _setup_glue(hass)
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()

    assert hk.get_task_by_source(DOMAIN, device_id=device.id) is None


# ── maintenance catalog ──────────────────────────────────────────────────────
def _make_usage_hours_sensor(
    hass: HomeAssistant, *, serial: str, device_id: str, hours: float = 660.0
) -> str:
    """Register the printer's cumulative usage-hours sensor on an existing device."""
    ent = er.async_get(hass).async_get_or_create(
        "sensor",
        BAMBU_DOMAIN,
        f"{serial}_total_usage_hours",
        device_id=device_id,
    )
    hass.states.async_set(ent.entity_id, str(hours), {"unit_of_measurement": "h"})
    return ent.entity_id


def _catalog_tasks(hk) -> list[dict]:
    return [
        t
        for t in hk.tasks.values()
        if (t.get("source") or {}).get(DOMAIN, {}).get("item", "firmware") != "firmware"
    ]


async def _setup_glue_with_options(
    hass: HomeAssistant, options: dict
) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_catalog_off_by_default_creates_no_maintenance_tasks(
    hass: HomeAssistant,
) -> None:
    # Someone who installed this glue for firmware mirroring must not wake up to eight
    # new tasks per printer after an upgrade.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1C900", state="off")
    _make_usage_hours_sensor(hass, serial="X1C900", device_id=device_id)
    await _setup_glue(hass)
    assert _catalog_tasks(hk) == []


async def test_catalog_pushes_a_usage_task_with_a_time_backstop(
    hass: HomeAssistant,
) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1C901", state="off")
    usage_entity = _make_usage_hours_sensor(hass, serial="X1C901", device_id=device_id)
    await _setup_glue_with_options(
        hass,
        {
            "maintenance": True,
            "item_z_lead_screws_enabled": True,
            # Everything else off, so the assertion is about one task.
            "item_linear_rods_enabled": False,
            "item_carbon_filter_enabled": False,
            "item_carbon_rods_enabled": False,
            "item_rod_antirust_enabled": False,
            "item_camera_lens_enabled": False,
        },
    )
    tasks = _catalog_tasks(hk)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["recurrence_type"] == "sensor"
    assert task["sensor"]["entity_id"] == usage_entity
    assert task["sensor"]["mode"] == "usage"
    assert task["sensor"]["also_every"] == {"interval": 3, "unit": "months"}
    assert task["sensor"]["combinator"] == "any"
    assert task["device_id"] == device_id
    # A human does this work, so it must stay completable and editable.
    managed = task["managed_by"]
    assert not managed.get("completion_blocked")
    assert "sensor" not in managed["locked_fields"]


async def test_calendar_only_item_pushes_a_floating_task(hass: HomeAssistant) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1C902", state="off")
    _make_usage_hours_sensor(hass, serial="X1C902", device_id=device_id)
    await _setup_glue_with_options(
        hass,
        {
            "maintenance": True,
            "item_carbon_rods_enabled": True,
            "item_linear_rods_enabled": False,
            "item_z_lead_screws_enabled": False,
            "item_carbon_filter_enabled": False,
            "item_rod_antirust_enabled": False,
            "item_camera_lens_enabled": False,
        },
    )
    tasks = _catalog_tasks(hk)
    assert len(tasks) == 1
    assert tasks[0]["recurrence_type"] == "floating"
    assert tasks[0]["unit"] == "months"
    assert "sensor" not in tasks[0]


async def test_catalog_and_firmware_tasks_coexist(hass: HomeAssistant) -> None:
    # The firmware mirror and the maintenance tasks share a device and a source
    # namespace; each planner must only see its own.
    hk = await async_setup_fake_home_keeper(hass)
    device_id, _ = _make_bambu_update(hass, serial="X1C903", state="on")
    _make_usage_hours_sensor(hass, serial="X1C903", device_id=device_id)
    await _setup_glue_with_options(
        hass,
        {
            "maintenance": True,
            "item_z_lead_screws_enabled": True,
            "item_linear_rods_enabled": False,
            "item_carbon_filter_enabled": False,
            "item_carbon_rods_enabled": False,
            "item_rod_antirust_enabled": False,
            "item_camera_lens_enabled": False,
        },
    )
    all_tasks = list(hk.tasks.values())
    firmware = [t for t in all_tasks if t["recurrence_type"] == "triggered"]
    assert len(firmware) == 1
    assert firmware[0]["next_due"]  # still armed by the update entity
    assert len(_catalog_tasks(hk)) == 1
