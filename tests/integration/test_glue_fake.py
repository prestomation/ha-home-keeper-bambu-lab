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
from homeassistant.helpers import device_registry as dr, entity_registry as er
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


async def test_update_available_creates_read_only_armed_task(hass: HomeAssistant) -> None:
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


async def test_duplicate_available_events_do_not_duplicate_tasks(hass: HomeAssistant) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    _, entity_id = _make_bambu_update(hass, serial="X1D", state="off")
    await _setup_glue(hass)

    hass.states.async_set(entity_id, "on", {"latest_version": "1"})
    hass.states.async_set(entity_id, "on", {"latest_version": "1", "installed_version": "0"})
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
    hk.tasks["foreign"] = {"id": "foreign", "source": {"other": {"x": 1}}, "next_due": None}

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ours_id not in hk.tasks  # our task cleaned up on removal
    assert "foreign" in hk.tasks  # someone else's task untouched


async def test_binary_sensor_firmware_available_creates_task(hass: HomeAssistant) -> None:
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
        "binary_sensor", BAMBU_DOMAIN, "weird_firmware_update",
        device_id=device.id, original_device_class="problem",
    )
    hass.states.async_set(ent.entity_id, "on", {"device_class": "problem"})
    entry = await _setup_glue(hass)
    await entry.runtime_data._reconcile()
    await hass.async_block_till_done()

    assert hk.get_task_by_source(DOMAIN, device_id=device.id) is None
