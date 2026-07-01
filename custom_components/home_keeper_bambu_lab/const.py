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
# These names are the Bambu Lab integration's surface, not ours. The firmware update
# is a Home Assistant ``update`` entity whose registry ``platform`` is this domain and
# whose ``unique_id`` ends with the suffix below (``{serial}_firmware_update``). Asserted
# against the fetched, real integration by the docker contract test; if Bambu Lab renames
# them, update here and re-pin BAMBU_REF.
BAMBU_DOMAIN = "bambu_lab"
# HA entity domain the firmware update surfaces as.
UPDATE_DOMAIN = "update"
# ``BambuLabUpdate`` sets ``unique_id = f"{serial}_firmware_update"`` — we match on this
# suffix so we only pick up the firmware update entity (not any future update entity).
UPDATE_UNIQUE_SUFFIX = "_firmware_update"

# Attributes a standard HA ``update`` entity exposes; we read these to enrich the task.
ATTR_INSTALLED_VERSION = "installed_version"
ATTR_LATEST_VERSION = "latest_version"
ATTR_RELEASE_URL = "release_url"
ATTR_TITLE = "title"

# ── Options (config_flow) ────────────────────────────────────────────────────
OPT_NAME_TEMPLATE = "name_template"

DEFAULT_NAME_TEMPLATE = "Update firmware: {printer_name}"

# Display metadata for the "Managed by" chip Home Keeper renders on our tasks, and the
# prompt shown where a Done action would normally be (the task is completion-blocked —
# it clears itself when the printer reports up to date, so there is nothing to check off).
MANAGED_DISPLAY_NAME = "Bambu Lab"
MANAGED_ICON = "mdi:printer-3d"
COMPLETION_PROMPT = (
    "This clears automatically once the printer's firmware is up to date — install the "
    "update from the Bambu Lab app or the printer's screen."
)
