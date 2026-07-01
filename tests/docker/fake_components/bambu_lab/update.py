"""A single controllable firmware ``update`` entity for the e2e fake Bambu Lab."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

DOMAIN = "bambu_lab"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    serial = entry.data.get("serial", "E2E0001")
    name = entry.data.get("name", "X1 Carbon")
    ent = BambuFakeUpdate(serial, name)
    hass.data.setdefault(DOMAIN, {"entities": []})["entities"].append(ent)
    async_add_entities([ent])


class BambuFakeUpdate(UpdateEntity):
    """Mirrors the real integration's ``{serial}_firmware_update`` update entity."""

    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_has_entity_name = True
    _attr_name = "Firmware update"

    def __init__(self, serial: str, name: str) -> None:
        self._serial = serial
        self._attr_unique_id = f"{serial}_firmware_update"
        self._available = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=name,
            manufacturer="Bambu Lab",
            model="X1 Carbon",
        )

    @property
    def installed_version(self) -> str:
        return "01.07.00.00"

    @property
    def latest_version(self) -> str:
        # HA core derives the entity state: on when latest != installed, else off.
        return "01.08.02.00" if self._available else "01.07.00.00"

    @property
    def release_url(self) -> str:
        return "https://bambulab.com/en/support/firmware-download"

    def set_available(self, available: bool) -> None:
        self._available = available
        self.async_write_ha_state()

    def install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        self._available = False
        self.async_write_ha_state()
