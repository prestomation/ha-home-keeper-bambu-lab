"""Integration tests for the per-printer maintenance options flow.

The flow is where the model detection becomes a decision the user owns, so these tests
are about the seams rather than the widgets: the printer picker appears only for a
fleet, the model step arrives pre-filled with what we detected, the items step always
offers **every** item whatever the printer, and answers are written to that printer's
serial-keyed options rather than a global set.

The subtle one is :func:`test_changing_the_model_discards_the_previous_answers` — item
answers given about an X1 are answers about a different machine once the user says
"actually it's an A1", so they must not be carried over.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_keeper_bambu_lab import catalog
from custom_components.home_keeper_bambu_lab.config_flow import FINISH
from custom_components.home_keeper_bambu_lab.const import BAMBU_DOMAIN, DOMAIN


@pytest.fixture(autouse=True)
def _no_home_keeper_needed():
    """The options flow talks to the registries only, so Home Keeper can be absent."""
    yield


def _add_printer(hass: HomeAssistant, *, serial: str, name: str, model: str) -> str:
    """Register a Bambu Lab printer (firmware entity + device) and return its device_id."""
    bambu_entry = MockConfigEntry(domain=BAMBU_DOMAIN, data={})
    bambu_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bambu_entry.entry_id,
        identifiers={(BAMBU_DOMAIN, serial)},
        name=name,
        model=model,
    )
    ent = er.async_get(hass).async_get_or_create(
        "update", BAMBU_DOMAIN, f"{serial}_firmware_update", device_id=device.id
    )
    hass.states.async_set(ent.entity_id, "off", {})
    return device.id


async def _open(hass: HomeAssistant, options: dict | None = None) -> tuple[str, dict]:
    """Set up the glue and open its options flow; return (flow_id, first step result)."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return result["flow_id"], result


def _defaults(result: dict) -> dict:
    """The form's pre-filled values (voluptuous fills the defaults for an empty input)."""
    return result["data_schema"]({})


def _all_items_off() -> dict:
    return {f"item_{item.key}_enabled": False for item in catalog.CATALOG}


async def test_turning_maintenance_off_saves_without_asking_about_printers(
    hass: HomeAssistant,
) -> None:
    _add_printer(hass, serial="X1C920", name="Workshop", model="X1C")
    flow_id, result = await _open(hass)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": False}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_a_single_printer_skips_the_picker(hass: HomeAssistant) -> None:
    _add_printer(hass, serial="X1C921", name="Workshop", model="X1C")
    flow_id, _ = await _open(hass)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    # One printer, so there is nothing to pick between.
    assert result["step_id"] == "model"
    assert result["description_placeholders"] == {
        "printer_name": "Workshop",
        "detected": "X1C",
    }
    assert _defaults(result)["model"] == catalog.FAMILY_X1


async def test_the_model_step_offers_every_family_and_pre_fills_the_detection(
    hass: HomeAssistant,
) -> None:
    _add_printer(hass, serial="A1M922", name="Desk", model="A1MINI")
    flow_id, _ = await _open(hass)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    assert _defaults(result)["model"] == catalog.FAMILY_A1
    selector = result["data_schema"].schema[
        next(k for k in result["data_schema"].schema if str(k) == "model")
    ]
    offered = [o["value"] for o in selector.config["options"]]
    assert offered == list(catalog.FAMILIES)


async def test_an_unrecognised_printer_lands_on_other_but_still_lists_everything(
    hass: HomeAssistant,
) -> None:
    _add_printer(hass, serial="NEW923", name="Mystery", model="Z9ULTRA")
    flow_id, _ = await _open(hass)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    assert _defaults(result)["model"] == catalog.FAMILY_UNKNOWN
    result = await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_UNKNOWN}
    )
    assert result["step_id"] == "items"
    defaults = _defaults(result)
    # Every item is offered whatever the printer — that is what keeps an unknown model
    # configurable — but only the ones every printer has start ticked.
    for item in catalog.CATALOG:
        assert f"item_{item.key}_enabled" in defaults
        assert f"item_{item.key}_interval" in defaults
    assert defaults["item_z_lead_screws_enabled"] is True
    assert defaults["item_carbon_filter_enabled"] is False


async def test_the_items_step_pre_fills_the_family_defaults(
    hass: HomeAssistant,
) -> None:
    _add_printer(hass, serial="X1C924", name="Workshop", model="X1C")
    flow_id, _ = await _open(hass)
    await hass.config_entries.options.async_configure(flow_id, {"maintenance": True})
    result = await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_X1}
    )
    defaults = _defaults(result)
    assert defaults["item_carbon_filter_enabled"] is True
    assert defaults["item_carbon_rods_enabled"] is True
    # Usage items pre-fill with their hours target, calendar items with their interval.
    assert (
        defaults["item_carbon_filter_interval"] == catalog.BY_KEY["carbon_filter"].hours
    )
    assert (
        defaults["item_carbon_rods_interval"] == catalog.BY_KEY["carbon_rods"].interval
    )


async def test_answers_are_written_to_that_printers_serial_keyed_options(
    hass: HomeAssistant,
) -> None:
    serial = "X1C925"
    _add_printer(hass, serial=serial, name="Workshop", model="X1C")
    flow_id, _ = await _open(hass)
    await hass.config_entries.options.async_configure(flow_id, {"maintenance": True})
    await hass.config_entries.options.async_configure(flow_id, {"model": "A1"})
    result = await hass.config_entries.options.async_configure(
        flow_id,
        {
            **_all_items_off(),
            "item_z_lead_screws_enabled": True,
            "item_z_lead_screws_interval": 600,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[catalog.option_key_model(serial)] == catalog.FAMILY_A1
    assert data[catalog.option_key_enabled(serial, "z_lead_screws")] is True
    assert data[catalog.option_key_interval(serial, "z_lead_screws")] == 600
    assert data[catalog.option_key_enabled(serial, "carbon_filter")] is False
    # The firmware half is untouched by the maintenance steps.
    assert data["maintenance"] is True


async def test_changing_the_model_discards_the_previous_answers(
    hass: HomeAssistant,
) -> None:
    # The user said "it's an X1" and turned the filter off; then corrected the model to
    # A1. Those answers were about a different printer, so the A1's defaults win rather
    # than the stale per-item values.
    serial = "X1C926"
    _add_printer(hass, serial=serial, name="Workshop", model="X1C")
    stored = {
        "maintenance": True,
        catalog.option_key_model(serial): catalog.FAMILY_X1,
        catalog.option_key_enabled(serial, "carbon_rods"): False,
        catalog.option_key_interval(serial, "z_lead_screws"): 600,
    }
    flow_id, _ = await _open(hass, stored)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    # The stored override is what the model step arrives pre-filled with.
    assert _defaults(result)["model"] == catalog.FAMILY_X1

    result = await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_A1}
    )
    defaults = _defaults(result)
    assert defaults["item_z_lead_screws_interval"] == (
        catalog.BY_KEY["z_lead_screws"].hours
    )
    assert defaults["item_carbon_rods_enabled"] is False  # the A1 has no carbon rods
    assert defaults["item_camera_lens_enabled"] is False  # nor a camera


async def test_keeping_the_model_keeps_the_previous_answers(
    hass: HomeAssistant,
) -> None:
    serial = "X1C927"
    _add_printer(hass, serial=serial, name="Workshop", model="X1C")
    stored = {
        "maintenance": True,
        catalog.option_key_interval(serial, "z_lead_screws"): 600,
        catalog.option_key_enabled(serial, "carbon_filter"): False,
    }
    flow_id, _ = await _open(hass, stored)
    await hass.config_entries.options.async_configure(flow_id, {"maintenance": True})
    result = await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_X1}
    )
    defaults = _defaults(result)
    assert defaults["item_z_lead_screws_interval"] == 600
    assert defaults["item_carbon_filter_enabled"] is False


async def test_a_fleet_is_configured_one_printer_at_a_time(
    hass: HomeAssistant,
) -> None:
    _add_printer(hass, serial="X1C928", name="Workshop", model="X1C")
    _add_printer(hass, serial="A1M928", name="Desk", model="A1MINI")
    flow_id, _ = await _open(hass)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    assert result["step_id"] == "select_printer"

    result = await hass.config_entries.options.async_configure(
        flow_id, {"printer": "X1C928"}
    )
    assert result["description_placeholders"]["printer_name"] == "Workshop"
    await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_X1}
    )
    result = await hass.config_entries.options.async_configure(
        flow_id, {**_all_items_off(), "item_carbon_filter_enabled": True}
    )
    # Back to the picker for the next printer rather than saving after the first.
    assert result["step_id"] == "select_printer"

    result = await hass.config_entries.options.async_configure(
        flow_id, {"printer": "A1M928"}
    )
    assert result["description_placeholders"] == {
        "printer_name": "Desk",
        "detected": "A1MINI",
    }
    await hass.config_entries.options.async_configure(
        flow_id, {"model": catalog.FAMILY_A1}
    )
    result = await hass.config_entries.options.async_configure(
        flow_id, {**_all_items_off(), "item_linear_rods_enabled": True}
    )
    assert result["step_id"] == "select_printer"

    result = await hass.config_entries.options.async_configure(
        flow_id, {"printer": FINISH}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    # Each printer kept its own answers.
    assert data[catalog.option_key_enabled("X1C928", "carbon_filter")] is True
    assert data[catalog.option_key_enabled("A1M928", "carbon_filter")] is False
    assert data[catalog.option_key_enabled("A1M928", "linear_rods")] is True
    assert data[catalog.option_key_enabled("X1C928", "linear_rods")] is False


async def test_maintenance_on_with_no_printers_visible_just_saves(
    hass: HomeAssistant,
) -> None:
    # Nothing to configure yet; the reconcile applies each model's defaults once the
    # printers appear, so the flow must not dead-end here.
    flow_id, _ = await _open(hass)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"maintenance": True}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["maintenance"] is True
