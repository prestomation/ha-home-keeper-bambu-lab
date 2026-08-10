"""Config + options flow for the Bambu Lab glue.

A single instance is all that's needed (it watches every Bambu Lab printer), so the
config flow is a one-click confirm. Options cover the firmware task's name template and
the maintenance catalog: a master toggle, then a per-item enable and interval override.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import catalog
from .const import (
    DEFAULT_MAINTENANCE,
    DEFAULT_NAME_TEMPLATE,
    DOMAIN,
    MANAGED_DISPLAY_NAME,
    OPT_MAINTENANCE,
    OPT_NAME_TEMPLATE,
)


class BambuLabGlueConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # One glue instance watches every Bambu Lab printer — disallow a second.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=MANAGED_DISPLAY_NAME, data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BambuLabGlueOptionsFlow()


class BambuLabGlueOptionsFlow(OptionsFlow):
    """Options: the firmware task name template, then the maintenance catalog.

    Two steps rather than one long form. Someone who installed this glue for firmware
    mirroring should be able to answer the first question and press Submit; the catalog —
    eight items with an interval each — belongs behind its own screen.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data = {**self.config_entry.options, **user_input}
            if user_input.get(OPT_MAINTENANCE):
                return await self.async_step_maintenance()
            return self.async_create_entry(title="", data=self._data)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_NAME_TEMPLATE,
                    default=opts.get(OPT_NAME_TEMPLATE, DEFAULT_NAME_TEMPLATE),
                ): str,
                vol.Optional(
                    OPT_MAINTENANCE,
                    default=opts.get(OPT_MAINTENANCE, DEFAULT_MAINTENANCE),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Per-item enable + interval override for the maintenance catalog.

        Intervals are pre-filled with Bambu Lab's own published figure (or its
        duty-cycle equivalent in printer hours), so submitting the form unchanged
        ships the manufacturer's schedule. Every field is the user's to overrule.
        """
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._data, **user_input})

        opts = self.config_entry.options
        fields: dict[Any, Any] = {}
        for item in catalog.CATALOG:
            enabled_key = catalog.option_key_enabled(item.key)
            interval_key = catalog.option_key_interval(item.key)
            _, current_interval = catalog.resolve(item, dict(opts))
            fields[
                vol.Optional(
                    enabled_key,
                    default=bool(opts.get(enabled_key, item.default_enabled)),
                )
            ] = selector.BooleanSelector()
            fields[vol.Optional(interval_key, default=current_interval)] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="h" if item.is_usage else item.unit,
                    )
                )
            )
        return self.async_show_form(
            step_id="maintenance", data_schema=vol.Schema(fields)
        )
