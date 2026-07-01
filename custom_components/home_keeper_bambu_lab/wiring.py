"""Home Assistant wiring for the Bambu Lab firmware glue.

Turns the pure decisions in :mod:`logic` into Home Keeper service calls, driven by the
Bambu Lab firmware ``update`` entity's state. Everything that crosses to Home Keeper is
guarded with ``has_service`` so we degrade gracefully when Home Keeper isn't present.

Bambu Lab exposes firmware as a standard HA ``update`` entity (no bus events), so we:

* track the state of every ``update`` entity whose registry ``platform`` is ``bambu_lab``
  and whose ``unique_id`` ends ``_firmware_update`` — ``on`` arms the task, ``off`` clears
  it, ``unavailable``/``unknown`` leaves it as-is;
* re-derive the tracked set whenever the entity registry changes (a printer added/removed);
* reconcile the full state on startup so we catch transitions missed while we were down.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from . import logic
from .const import (
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_URL,
    BAMBU_DOMAIN,
    BINARY_SENSOR_DOMAIN,
    DEFAULT_NAME_TEMPLATE,
    DOMAIN,
    FIRMWARE_BINARY_DEVICE_CLASS,
    FIRMWARE_DOMAINS,
    HK_DOMAIN,
    HK_EVENT_REGISTER_COMPANIONS,
    HK_SERVICE_REGISTER_COMPANION,
    OPT_NAME_TEMPLATE,
    ORIGIN,
    UPDATE_UNIQUE_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)


class BambuLabGlue:
    """Watches Bambu Lab firmware update entities and drives Home Keeper tasks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        # Serialize the list-tasks → decide → execute span so two rapid state changes
        # can't both read an empty task list and each create a task. The glue is
        # stateless, so this lock is the only thing preventing a create/create interleave.
        self._lock = asyncio.Lock()
        self._tracked: frozenset[str] = frozenset()
        self._unsub_state: Any = None

    # ── options ──────────────────────────────────────────────────────────────
    @property
    def _name_template(self) -> str:
        return self.entry.options.get(OPT_NAME_TEMPLATE, DEFAULT_NAME_TEMPLATE)

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_setup(self) -> None:
        """Subscribe to registry/state changes and schedule the startup reconcile."""
        bus = self.hass.bus
        # Re-announce to Home Keeper's companion discovery whenever it asks (covers Home
        # Keeper starting after us), and once now.
        self.entry.async_on_unload(
            bus.async_listen(HK_EVENT_REGISTER_COMPANIONS, self._on_register_request)
        )
        await self._register_companion()

        # Refresh the tracked-entity subscription whenever the entity registry changes
        # (a printer added/removed re-homes its update entity).
        self.entry.async_on_unload(
            bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated
            )
        )
        # Ensure our state subscription is torn down on unload.
        self.entry.async_on_unload(self._unsubscribe_state)

        self._refresh_tracking()

        # Reconcile once everything is up. after_dependencies only orders setup; it
        # doesn't guarantee Bambu Lab's entities or Home Keeper's services exist yet, so
        # wait for HA-started (or run now if we're already past start-up).
        if self.hass.is_running:
            await self._reconcile()
        else:
            self.entry.async_on_unload(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._on_started
                )
            )

    async def _on_started(self, _event: Event) -> None:
        self._refresh_tracking()
        await self._reconcile()

    async def _on_register_request(self, _event: Event) -> None:
        await self._register_companion()

    async def _on_registry_updated(self, _event: Event) -> None:
        # A printer's update entity may have appeared/disappeared; re-track and reconcile
        # so its current firmware state is reflected.
        before = self._tracked
        self._refresh_tracking()
        if self._tracked != before:
            await self._reconcile()

    async def _register_companion(self) -> None:
        """Announce this glue to Home Keeper's companion registry (best-effort)."""
        if not self._hk_ready(HK_SERVICE_REGISTER_COMPANION):
            return
        try:
            await self.hass.services.async_call(
                HK_DOMAIN,
                HK_SERVICE_REGISTER_COMPANION,
                {
                    "domain": DOMAIN,
                    "name": "Bambu Lab",
                    "icon": "mdi:printer-3d",
                    "description": (
                        "Surfaces Bambu Lab printer firmware updates as Home Keeper "
                        "tasks so a pending update shows up in your to-do list."
                    ),
                    "config_entry_id": self.entry.entry_id,
                    "docs_url": (
                        "https://github.com/prestomation/ha-home-keeper-bambu-lab"
                    ),
                    "capabilities": ["firmware_updates"],
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001 — discovery is best-effort; never break setup
            _LOGGER.debug("Home Keeper companion registration failed", exc_info=True)

    # ── entity tracking ──────────────────────────────────────────────────────
    @staticmethod
    def _is_firmware_entity(entity: er.RegistryEntry) -> bool:
        """Whether *entity* is a Bambu Lab firmware entity (``update`` or ``binary_sensor``).

        The Bambu Lab integration exposes firmware as an ``update`` entity or, when its
        "Firmware update" option is off (the default), a ``binary_sensor`` with
        device_class ``update`` — both keyed ``{serial}_firmware_update``. We accept
        either; for the binary_sensor we also require the ``update`` device_class so we
        don't pick up an unrelated binary_sensor that happens to share the suffix.
        """
        if entity.platform != BAMBU_DOMAIN:
            return False
        if entity.domain not in FIRMWARE_DOMAINS:
            return False
        if not (entity.unique_id or "").endswith(UPDATE_UNIQUE_SUFFIX):
            return False
        if entity.domain == BINARY_SENSOR_DOMAIN:
            device_class = entity.device_class or entity.original_device_class
            return device_class == FIRMWARE_BINARY_DEVICE_CLASS
        return True

    def _bambu_update_entity_ids(self) -> frozenset[str]:
        """Every Bambu Lab firmware entity id, from the entity registry."""
        ent_reg = er.async_get(self.hass)
        return frozenset(
            entity.entity_id
            for entity in ent_reg.entities.values()
            if self._is_firmware_entity(entity)
        )

    @callback
    def _unsubscribe_state(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _refresh_tracking(self) -> None:
        """(Re)subscribe to state changes of the current Bambu update entities."""
        ids = self._bambu_update_entity_ids()
        if ids == self._tracked:
            return
        self._unsubscribe_state()
        self._tracked = ids
        if ids:
            self._unsub_state = async_track_state_change_event(
                self.hass, list(ids), self._on_update_state
            )

    # ── Home Keeper helpers ──────────────────────────────────────────────────
    def _hk_ready(self, service: str) -> bool:
        return self.hass.services.has_service(HK_DOMAIN, service)

    async def _list_tasks(self) -> list[dict[str, Any]]:
        if not self._hk_ready("list_tasks"):
            return []
        resp = await self.hass.services.async_call(
            HK_DOMAIN, "list_tasks", {}, blocking=True, return_response=True
        )
        return list((resp or {}).get("tasks", []))

    async def _execute(self, action: logic.Action) -> None:
        if isinstance(action, logic.CreateTask):
            if self._hk_ready("add_task"):
                await self.hass.services.async_call(
                    HK_DOMAIN, "add_task", action.payload, blocking=True
                )
                _LOGGER.debug("Created firmware task for device %s", action.device_id)
        elif isinstance(action, logic.ArmTask):
            if self._hk_ready("trigger_task"):
                await self.hass.services.async_call(
                    HK_DOMAIN, "trigger_task", {"task_id": action.task_id}, blocking=True
                )
                _LOGGER.debug("Armed firmware task %s", action.task_id)
        elif isinstance(action, logic.ClearTask):
            if self._hk_ready("complete_task"):
                await self.hass.services.async_call(
                    HK_DOMAIN,
                    "complete_task",
                    {"task_id": action.task_id, "origin": ORIGIN},
                    blocking=True,
                )
                _LOGGER.debug("Cleared firmware task %s", action.task_id)
        elif isinstance(action, logic.DeleteTask):
            if self._hk_ready("delete_task"):
                await self.hass.services.async_call(
                    HK_DOMAIN,
                    "delete_task",
                    {"task_id": action.task_id, "force": True},
                    blocking=True,
                )
                _LOGGER.debug("Deleted firmware task %s", action.task_id)
        elif isinstance(action, logic.UpdateChips):
            if self._hk_ready("update_task"):
                await self.hass.services.async_call(
                    HK_DOMAIN,
                    "update_task",
                    {"task_id": action.task_id, "task_chips": action.chips},
                    blocking=True,
                )
                _LOGGER.debug("Refreshed chips on firmware task %s", action.task_id)

    # ── firmware update state handler ────────────────────────────────────────
    async def _on_update_state(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state: State | None = event.data.get("new_state")
        if not entity_id:
            return
        ent_reg = er.async_get(self.hass)
        entry = ent_reg.async_get(entity_id)
        if entry is None or not entry.device_id:
            return
        async with self._lock:
            tasks = await self._list_tasks()
            if new_state is not None and new_state.state == "on":
                info = self._info_from_state(entry.device_id, entity_id, new_state)
                action = logic.plan_update_available(
                    tasks,
                    device_id=entry.device_id,
                    entity_id=entity_id,
                    printer_name=info["name"],
                    config_entry_id=self.entry.entry_id,
                    name_template=self._name_template,
                    latest_version=info["latest_version"],
                    installed_version=info["installed_version"],
                    release_url=info["release_url"],
                )
            elif new_state is not None and new_state.state == "off":
                action = logic.plan_update_cleared(tasks, device_id=entry.device_id)
            else:
                # unavailable/unknown (printer offline) — leave the task as it is.
                action = None
            if action is not None:
                await self._execute(action)

    def _info_from_state(
        self, device_id: str, entity_id: str, state: State
    ) -> dict[str, Any]:
        """Firmware info for a printer from its update entity state + device registry."""
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        name = (device.name_by_user or device.name) if device else None
        attrs = state.attributes
        return {
            "name": name or entity_id,
            "entity_id": entity_id,
            "installed_version": attrs.get(ATTR_INSTALLED_VERSION),
            "latest_version": attrs.get(ATTR_LATEST_VERSION),
            "release_url": attrs.get(ATTR_RELEASE_URL),
        }

    # ── startup reconcile ────────────────────────────────────────────────────
    async def _reconcile(self) -> None:
        """Catch up on transitions missed while we were down.

        Enumerate Bambu Lab's firmware update entities from the entity registry and
        converge tasks to match: arm/create for printers with an update available, clear
        tasks whose printer is affirmatively up to date.
        """
        if not self._hk_ready("list_tasks"):
            return
        async with self._lock:
            # Fetch tasks first (the only await), then snapshot entity states with no
            # await between the scan and the decision — so the reconcile can't act on an
            # entity state that drifted while awaiting the task list.
            tasks = await self._list_tasks()
            available, up_to_date = self._scan_updates()
            actions = logic.plan_reconcile(
                tasks,
                available,
                up_to_date,
                config_entry_id=self.entry.entry_id,
                name_template=self._name_template,
            )
            for action in actions:
                await self._execute(action)
            if actions:
                _LOGGER.debug("Reconcile applied %d action(s)", len(actions))

    def _scan_updates(self) -> tuple[dict[str, dict[str, Any]], set[str]]:
        """Snapshot Bambu Lab's firmware update entities for a reconcile.

        Returns ``(available, up_to_date)``: *available* maps ``device_id`` → firmware
        info for entities reading ``on`` (arm/create), *up_to_date* is the set of devices
        whose entity affirmatively reads ``off`` (clear). An entity that's
        ``unavailable``/``unknown`` (printer offline) lands in neither — we neither arm
        nor clear from it, so an offline printer keeps whatever task state it had.
        """
        ent_reg = er.async_get(self.hass)
        available: dict[str, dict[str, Any]] = {}
        up_to_date: set[str] = set()
        for entity in ent_reg.entities.values():
            if not self._is_firmware_entity(entity) or not entity.device_id:
                continue
            state = self.hass.states.get(entity.entity_id)
            if state is None:
                continue
            if state.state == "on":
                available[entity.device_id] = self._info_from_state(
                    entity.device_id, entity.entity_id, state
                )
            elif state.state == "off":
                up_to_date.add(entity.device_id)
        return available, up_to_date
