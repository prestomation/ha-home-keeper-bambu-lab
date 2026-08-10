"""Config + options flow for the Bambu Lab glue.

A single instance is all that's needed (it watches every Bambu Lab printer), so the
config flow is a one-click confirm.

Options cover the firmware task's name template and the maintenance catalog. The
catalog is configured **per printer**, because Bambu Lab's schedule is not the same for
every model: an A1 has no chamber filter and no X-axis carbon rods, while an X1C has
both. The flow is therefore:

``init`` → (``select_printer``) → ``model`` → ``items`` → (back to ``select_printer``)

``select_printer`` is skipped when there is exactly one printer. ``model`` shows what we
detected from the device registry and lets the user overrule it, and ``items`` always
lists **every** catalog item — the model only decides which ones start ticked and what
their intervals are pre-filled with, so an unrecognised printer is still configurable by
hand.

Form field names stay static (``model``, ``item_<key>_enabled``, …) so they can be
translated; they're written out to the printer's serial-keyed option keys on submit.
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

from . import catalog, wiring
from .const import (
    DEFAULT_MAINTENANCE,
    DEFAULT_NAME_TEMPLATE,
    DOMAIN,
    MANAGED_DISPLAY_NAME,
    OPT_MAINTENANCE,
    OPT_NAME_TEMPLATE,
)

# Sentinel value in the printer picker meaning "I'm done configuring printers".
FINISH = "__finish__"

# Form field names, kept static (and therefore translatable) even though the options
# they end up in are keyed on the printer's serial.
FIELD_PRINTER = "printer"
FIELD_MODEL = "model"


def _field_enabled(key: str) -> str:
    return f"item_{key}_enabled"


def _field_interval(key: str) -> str:
    return f"item_{key}_interval"


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
    """Options: the firmware task name template, then the per-printer catalog."""

    def __init__(self) -> None:
        # Accumulates across steps and becomes the entry's options when we finish.
        self._data: dict[str, Any] = {}
        # Printers as of the moment the flow opened, device_id → info (see
        # wiring.scan_printers). Snapshotted so the picker and the steps agree.
        self._printers: dict[str, dict[str, Any]] = {}
        # The printer currently being configured.
        self._serial: str = ""
        self._name: str = ""
        self._detected: str = ""
        # The family whose defaults the stored per-item answers were given under, and
        # the family the user just chose. When they differ the stored answers were about
        # a different printer, so the items step ignores them (see _prefill_from_family).
        self._previous_family: str = catalog.FAMILY_UNKNOWN
        self._family: str = catalog.FAMILY_UNKNOWN

    # ── step 1: firmware naming + the catalog master switch ──────────────────
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data = {**self.config_entry.options, **user_input}
            if not user_input.get(OPT_MAINTENANCE):
                return self.async_create_entry(title="", data=self._data)
            self._printers = wiring.scan_printers(self.hass)
            if not self._printers:
                # Maintenance is on but no printer is visible yet — save, and the
                # reconcile will apply each model's defaults when they appear.
                return self.async_create_entry(title="", data=self._data)
            if len(self._printers) == 1:
                self._select(next(iter(self._printers.values())))
                return await self.async_step_model()
            return await self.async_step_select_printer()

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

    def _select(self, info: dict[str, Any]) -> None:
        """Make *info* the printer the next two steps are about."""
        self._serial = str(info.get("serial") or "")
        self._name = str(info.get("name") or "")
        self._detected = str(info.get("model") or "")
        self._previous_family = catalog.resolved_family(
            self._serial, self._detected, self._data
        )
        self._family = self._previous_family

    # ── step 2 (multi-printer only): which printer? ──────────────────────────
    async def async_step_select_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a printer to configure, or finish.

        Shown only for a fleet. Each printer's model and item choices are its own, so
        they're answered one printer at a time and we come back here afterwards.
        """
        if user_input is not None:
            chosen = user_input.get(FIELD_PRINTER)
            if not chosen or chosen == FINISH:
                return self.async_create_entry(title="", data=self._data)
            for info in self._printers.values():
                if str(info.get("serial") or "") == chosen:
                    self._select(info)
                    return await self.async_step_model()
            return self.async_create_entry(title="", data=self._data)

        options = [
            selector.SelectOptionDict(
                value=str(info.get("serial") or ""),
                label=self._printer_label(info),
            )
            for info in self._printers.values()
        ]
        options.append(selector.SelectOptionDict(value=FINISH, label="Save and finish"))
        schema = vol.Schema(
            {
                vol.Required(FIELD_PRINTER, default=FINISH): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="select_printer", data_schema=schema)

    def _printer_label(self, info: dict[str, Any]) -> str:
        """ "<name> (<model>)" for the picker, dropping the model when we have none."""
        name = str(info.get("name") or info.get("serial") or "")
        model = str(info.get("model") or "").strip()
        return f"{name} ({model})" if model else name

    # ── step 3: which model is this, really? ─────────────────────────────────
    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm or overrule the detected model.

        Separate from the items step because a Home Assistant form can't re-render its
        defaults when one of its own fields changes: the model has to be committed
        before the item defaults can follow from it.
        """
        if user_input is not None:
            chosen = str(user_input.get(FIELD_MODEL) or catalog.FAMILY_UNKNOWN)
            self._family = chosen if chosen in catalog.FAMILIES else self._family
            return await self.async_step_items()

        schema = vol.Schema(
            {
                vol.Required(
                    FIELD_MODEL, default=self._previous_family
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=family, label=catalog.FAMILY_LABELS[family]
                            )
                            for family in catalog.FAMILIES
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="model",
            data_schema=schema,
            description_placeholders={
                "printer_name": self._name,
                "detected": self._detected or "not reported",
            },
        )

    # ── step 4: the items themselves ─────────────────────────────────────────
    async def async_step_items(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Per-item enable + interval for this printer.

        Every catalog item is listed whatever the model, so an unrecognised printer is
        still fully configurable; the model decides only which start ticked and what the
        intervals are pre-filled with. Intervals default to Bambu Lab's own published
        figure (or its duty-cycle equivalent in printer hours), so submitting the form
        unchanged ships the manufacturer's schedule.
        """
        if user_input is not None:
            self._data[catalog.option_key_model(self._serial)] = self._family
            for item in catalog.CATALOG:
                self._data[catalog.option_key_enabled(self._serial, item.key)] = bool(
                    user_input.get(_field_enabled(item.key))
                )
                raw = user_input.get(_field_interval(item.key))
                try:
                    interval = int(float(raw))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    interval = 0
                self._data[catalog.option_key_interval(self._serial, item.key)] = max(
                    interval, 0
                )
            if len(self._printers) > 1:
                return await self.async_step_select_printer()
            return self.async_create_entry(title="", data=self._data)

        # The pre-fill rule: stored answers only apply if they were given about *this*
        # model. Change the model and the previous answers are discarded, so "actually
        # it's an A1" re-defaults the whole list rather than keeping X1 answers.
        stored = self._data if self._family == self._previous_family else None
        fields: dict[Any, Any] = {}
        for item in catalog.CATALOG:
            resolved = catalog.resolve(item, self._family, self._serial, stored)
            fields[vol.Optional(_field_enabled(item.key), default=resolved.enabled)] = (
                selector.BooleanSelector()
            )
            default = resolved.hours if resolved.is_usage else resolved.interval
            fields[vol.Optional(_field_interval(item.key), default=default)] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement=(
                            "h" if resolved.is_usage else resolved.unit
                        ),
                    )
                )
            )
        return self.async_show_form(
            step_id="items",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "printer_name": self._name,
                "model": catalog.FAMILY_LABELS[self._family],
            },
        )
