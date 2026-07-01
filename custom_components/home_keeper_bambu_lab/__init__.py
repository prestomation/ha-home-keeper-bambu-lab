"""Home Keeper ↔ Bambu Lab glue integration.

Mirrors a Bambu Lab printer's firmware-update state into a Home Keeper ``triggered``
task: when the printer's ``update`` entity reports an update is available, a Home Keeper
task becomes due; when the firmware is installed (the entity returns to up-to-date) the
task clears itself. The task is a **read-only mirror** — completion-blocked in Home
Keeper — so it can't be dismissed by hand; it clears only when Bambu Lab says so.

The integration is stateless: it persists no device→task mapping. Everything is
re-derived from Home Keeper's ``list_tasks`` (matched by our ``source`` namespace) plus
Bambu Lab's registry entities, so it self-heals across restarts.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import HK_DOMAIN, SOURCE_NS
from .wiring import BambuLabGlue

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the glue from its config entry."""
    glue = BambuLabGlue(hass, entry)
    await glue.async_setup()
    entry.runtime_data = glue
    # Re-run setup (re-subscribe + reconcile) when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry. Event/state listeners are removed via ``entry.async_on_unload``.

    Deliberately does NOT delete the tasks we created: a transient unload/reload (e.g. an
    options change) must not wipe task history. Permanent cleanup happens in
    ``async_remove_entry`` when the integration is truly removed; until then Home Keeper's
    orphan detection lifts deletion protection so the user can clean up if they uninstall
    us.
    """
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """On permanent removal, proactively delete the tasks we own.

    Best-effort and guarded: if Home Keeper is gone, its orphan detection already lets the
    user remove our (now unprotected) tasks. We pass ``force`` because our own tasks are
    deletion-protected while our config entry still resolves.
    """
    if not hass.services.has_service(HK_DOMAIN, "list_tasks"):
        return
    try:
        resp = await hass.services.async_call(
            HK_DOMAIN, "list_tasks", {}, blocking=True, return_response=True
        )
    except Exception:  # noqa: BLE001 - cleanup must never raise on removal
        _LOGGER.debug("Could not list Home Keeper tasks during removal", exc_info=True)
        return
    for task in (resp or {}).get("tasks", []):
        src = (task.get("source") or {}).get(SOURCE_NS)
        if isinstance(src, dict) and hass.services.has_service(HK_DOMAIN, "delete_task"):
            try:
                await hass.services.async_call(
                    HK_DOMAIN,
                    "delete_task",
                    {"task_id": task["id"], "force": True},
                    blocking=True,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Failed to delete task %s on removal", task.get("id"))
