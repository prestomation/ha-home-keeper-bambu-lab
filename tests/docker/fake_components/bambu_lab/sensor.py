"""A controllable cumulative usage-hours sensor for the e2e fake Bambu Lab.

Mirrors the real integration's ``total_usage_hours`` sensor — the counter the
maintenance catalog meters against — including its ``TOTAL_INCREASING`` state class and
the ``{serial}_total_usage_hours`` unique_id the glue matches on. A
``bambu_lab.advance_usage_hours`` service winds it forward so the docker tier can watch
Home Keeper arm a usage task without waiting for real print time.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

DOMAIN = "bambu_lab"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    serial = entry.data.get("serial", "E2E0001")
    name = entry.data.get("name", "X1 Carbon")
    ent = BambuFakeUsageHours(serial, name)
    hass.data.setdefault(DOMAIN, {"entities": [], "sensors": []}).setdefault(
        "sensors", []
    ).append(ent)
    async_add_entities([ent])


class BambuFakeUsageHours(SensorEntity):
    """Mirrors the real ``{serial}_total_usage_hours`` sensor."""

    _attr_has_entity_name = True
    _attr_name = "Total usage hours"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, serial: str, name: str) -> None:
        self._attr_unique_id = f"{serial}_total_usage_hours"
        self._hours = 660.0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=name,
            manufacturer="Bambu Lab",
            model="X1 Carbon",
        )

    @property
    def native_value(self) -> float:
        return self._hours

    def advance(self, hours: float) -> None:
        self._hours += hours
        self.async_write_ha_state()

    def set_hours(self, hours: float) -> None:
        self._hours = hours
        self.async_write_ha_state()
