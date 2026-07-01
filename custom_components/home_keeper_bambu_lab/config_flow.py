"""Config + options flow for the Bambu Lab firmware glue.

A single instance is all that's needed (it watches every Bambu Lab printer), so the
config flow is a one-click confirm. The only behaviour to tune is the task name template.
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

from .const import (
    DEFAULT_NAME_TEMPLATE,
    DOMAIN,
    MANAGED_DISPLAY_NAME,
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
    """Options: the task name template."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_NAME_TEMPLATE,
                    default=opts.get(OPT_NAME_TEMPLATE, DEFAULT_NAME_TEMPLATE),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
