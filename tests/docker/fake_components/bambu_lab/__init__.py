"""Minimal fake of the Bambu Lab integration for the end-to-end tiers.

The real Bambu Lab integration needs a printer (MQTT/cloud) to instantiate its firmware
``update`` entity, which can't run in CI — so, exactly as the Battery Notes glue fires
synthetic Battery Notes events, this stub stands in a single controllable firmware
``update`` entity on the real ``bambu_lab`` platform. A ``bambu_lab.set_firmware_available``
service flips whether an update is on offer, so the docker/browser tiers can drive the
glue over REST. The *real* integration's firmware surface is guarded separately by the
static contract test in ``test_end_to_end.py``.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

DOMAIN = "bambu_lab"
PLATFORMS = ["update", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"entities": [], "sensors": []})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _set_available(call: ServiceCall) -> None:
        available = bool(call.data.get("available", True))
        for ent in hass.data[DOMAIN]["entities"]:
            ent.set_available(available)

    hass.services.async_register(DOMAIN, "set_firmware_available", _set_available)

    async def _advance_usage(call: ServiceCall) -> None:
        hours = float(call.data.get("hours", 1))
        for ent in hass.data[DOMAIN].get("sensors", []):
            ent.advance(hours)

    hass.services.async_register(DOMAIN, "advance_usage_hours", _advance_usage)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
