"""Constants for the Home Keeper ↔ Bambu Lab glue integration.

This integration owns *no* domain logic of its own: it mirrors the Bambu Lab
integration's firmware-update state into a Home Keeper ``triggered`` task. It talks to
both sides purely over Home Assistant's entity/state registry and Home Keeper's
services — no Python imports in either direction — so it degrades gracefully if either
is absent.

Unlike the Battery Notes glue, Bambu Lab exposes no bus events for firmware: the update
is surfaced as a standard Home Assistant ``update`` **entity**. So detection here is
entity-state-driven — we watch the printer's ``update.*_firmware_update`` entity (state
``on`` = an update is available, ``off`` = up to date) rather than listening for events.
"""

from __future__ import annotations

DOMAIN = "home_keeper_bambu_lab"

# ── Home Keeper side ─────────────────────────────────────────────────────────
HK_DOMAIN = "home_keeper"
# Home Keeper fires this (at its setup and on reload) to ask companion integrations
# to (re-)announce themselves to its discovery registry. We both register at our own
# setup and respond to this ping, so discovery works regardless of startup order.
HK_EVENT_REGISTER_COMPANIONS = "home_keeper_register_companions"
HK_SERVICE_REGISTER_COMPANION = "register_companion"
# Namespace for the opaque ``source`` dict we attach to tasks we create, so we can
# recognise our own tasks later (``source[SOURCE_NS] == {"device_id": ...}``).
SOURCE_NS = DOMAIN
# Opaque ``origin`` marker we pass to complete_task so a completion we trigger is
# recognisable (loop prevention — see Home Keeper INTEGRATING.md §4). This glue never
# reacts to completion events (the task is completion-blocked), but we still stamp our
# clears so any listener can tell them apart from a user action.
ORIGIN = DOMAIN

# ── Bambu Lab side (EXTERNAL CONTRACT — verify against a pinned release) ──────
# These names are the Bambu Lab integration's surface, not ours. Asserted against the
# fetched, real integration by the docker contract test; if Bambu Lab renames them,
# update here and re-pin BAMBU_REF.
BAMBU_DOMAIN = "bambu_lab"
# The firmware update surfaces as ONE OF TWO entities, depending on the Bambu Lab
# integration's "Firmware update" option (they are mutually exclusive):
#   * option ON  → an ``update`` entity (``BambuLabUpdate``), which can also install; or
#   * option OFF (the default) → a ``binary_sensor`` with device_class ``update`` that
#     just reports availability.
# Both share the ``{serial}_firmware_update`` unique_id and both read ``on`` when an
# update is available / ``off`` when up to date, so the glue mirrors whichever exists.
UPDATE_DOMAIN = "update"
BINARY_SENSOR_DOMAIN = "binary_sensor"
FIRMWARE_DOMAINS = (UPDATE_DOMAIN, BINARY_SENSOR_DOMAIN)
# Both variants set ``unique_id = f"{serial}_firmware_update"`` — we match on this suffix
# so we only pick up the firmware entity (not any other update/binary_sensor).
UPDATE_UNIQUE_SUFFIX = "_firmware_update"
# device_class of the binary_sensor variant — an extra sanity filter for that domain.
FIRMWARE_BINARY_DEVICE_CLASS = "update"

# The printer's cumulative run-time counter, which the maintenance catalog meters
# against. ``BambuLabSensor`` composes ``unique_id = f"{serial}_{description.key}"``,
# so we match the same way we match firmware: by unique_id suffix on the bambu_lab
# platform. It is ``SensorStateClass.TOTAL_INCREASING`` hours with no per-model gate
# (only ``available_fn`` on the printer actually reporting ``info.usage_hours``).
# NOTE: it counts *printer usage* hours, not strictly print hours — close enough for a
# service interval, and it is what Bambu's own duty-cycle guidance is written against.
SENSOR_DOMAIN = "sensor"
USAGE_HOURS_UNIQUE_SUFFIX = "_total_usage_hours"
USAGE_HOURS_UNIT = "h"

# Key under our ``source`` namespace naming which thing a task mirrors: ``"firmware"``
# for the update mirror, or a ``catalog.CatalogItem.key`` for a maintenance task. Tasks
# created before this key existed carry no ``item`` and are firmware tasks, so a missing
# value reads as ITEM_FIRMWARE rather than as "unknown".
SOURCE_ITEM = "item"
ITEM_FIRMWARE = "firmware"

# Attributes a standard HA ``update`` entity exposes; we read these to enrich the task.
ATTR_INSTALLED_VERSION = "installed_version"
ATTR_LATEST_VERSION = "latest_version"
ATTR_RELEASE_URL = "release_url"
ATTR_TITLE = "title"

# After a task clears (firmware installed), ignore a re-arm for the same printer for this
# many seconds. A single install presents the update entity's ``on``→``off`` edge once,
# but the printer's reboot/reconnect (or a stale/retained MQTT message, or a staged
# version-by-version update) can briefly re-report the update as available afterwards;
# re-arming on that flap and clearing again records a phantom second completion. A real
# install takes far longer than this window, so suppressing a re-arm within it can't hide
# a genuine new update.
REARM_COOLDOWN_SECONDS = 15 * 60

# ── Options (config_flow) ────────────────────────────────────────────────────
OPT_NAME_TEMPLATE = "name_template"
# Master switch for the whole maintenance catalog (per-item toggles live under
# ``catalog.option_key_enabled``). Off by default: someone who installed this glue for
# firmware mirroring shouldn't wake up to eight new tasks per printer after an upgrade.
OPT_MAINTENANCE = "maintenance"

DEFAULT_NAME_TEMPLATE = "Update firmware: {printer_name}"
DEFAULT_MAINTENANCE = False
# Task name for a catalog item: "<item>: <printer>", matching the firmware task's shape.
MAINTENANCE_NAME_TEMPLATE = "{item_name}: {printer_name}"

# Display metadata for the "Managed by" chip Home Keeper renders on our tasks, and the
# prompt shown where a Done action would normally be (the task is completion-blocked —
# it clears itself when the printer reports up to date, so there is nothing to check off).
MANAGED_DISPLAY_NAME = "Bambu Lab"
MANAGED_ICON = "mdi:printer-3d"
COMPLETION_PROMPT = (
    "This clears automatically once the printer's firmware is up to date — install the "
    "update from the Bambu Lab app or the printer's screen."
)
