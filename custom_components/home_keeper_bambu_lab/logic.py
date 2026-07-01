"""Pure decision logic for the Bambu Lab firmware glue.

Given the current Home Keeper task list and a printer's firmware-update state, decide
what to do — create/arm/clear a ``triggered`` task — without touching Home Assistant.
This mirrors the purity of ``home_keeper``'s own reconcilers: every branch is a plain
transformation over dicts, so it is exhaustively unit-testable in isolation. The
HA-facing wiring (``wiring.py``) turns these decisions into service calls.

The design rests on Home Keeper's ``triggered`` task model plus its ``completion_blocked``
ownership flag, so the task is a **read-only mirror** of the printer's update state:

* firmware update available (the ``update`` entity reads ``on``) → the task is **armed**
  (due-now). If we've never seen this printer, create the task (born armed); otherwise
  re-arm the existing dormant task with ``trigger_task``.
* firmware up to date (the ``update`` entity reads ``off``) → **clear** the task with
  ``complete_task``, returning it to dormant. The user never checks it off themselves —
  it clears only when Bambu Lab reports the printer is current.

Every decision is idempotent: arming an already-armed task or clearing an already-dormant
one is a no-op (we return ``None``), so repeated state events and startup reconciliation
never create duplicates or loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    COMPLETION_PROMPT,
    MANAGED_DISPLAY_NAME,
    MANAGED_ICON,
    SOURCE_NS,
)


# ── action descriptors (what wiring.py should do) ────────────────────────────
@dataclass(frozen=True)
class CreateTask:
    """Create a new triggered task for *device_id*, born armed (due-now)."""

    device_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ArmTask:
    """Re-arm an existing dormant task (call ``home_keeper.trigger_task``)."""

    task_id: str
    device_id: str


@dataclass(frozen=True)
class ClearTask:
    """Clear an armed task (call ``home_keeper.complete_task``)."""

    task_id: str
    device_id: str


@dataclass(frozen=True)
class DeleteTask:
    """Remove a task entirely (call ``home_keeper.delete_task`` with ``force``)."""

    task_id: str
    device_id: str


@dataclass(frozen=True)
class UpdateChips:
    """Refresh ``task_chips`` on an existing task when the firmware version changes.

    Emitted during reconcile when the armed task's chips no longer match the current
    ``latest_version`` / release URL (e.g. a newer firmware superseded the one the task
    was created for), so the card always shows the version actually available.
    """

    task_id: str
    device_id: str
    chips: list[dict[str, str]]


Action = CreateTask | ArmTask | ClearTask | DeleteTask | UpdateChips


# ── helpers over the Home Keeper task list ───────────────────────────────────
def _is_ours(task: Any) -> bool:
    """Whether *task* is a well-formed task dict we own (has an id + our source ns)."""
    if not isinstance(task, dict) or not task.get("id"):
        return False
    return isinstance((task.get("source") or {}).get(SOURCE_NS), dict)


def task_for_device(tasks: list[dict], device_id: str) -> dict | None:
    """Return our task for *device_id* (matched by our ``source`` namespace), or None."""
    for task in tasks:
        if _is_ours(task) and task["source"][SOURCE_NS].get("device_id") == device_id:
            return task
    return None


def is_armed(task: dict) -> bool:
    """A triggered task is armed (due-now) when it has a ``next_due``; dormant otherwise."""
    return bool(task.get("next_due"))


def our_tasks(tasks: list[dict]) -> list[dict]:
    """Every well-formed task we own (carries our ``source`` namespace + an id)."""
    return [t for t in tasks if _is_ours(t)]


# ── payload construction ─────────────────────────────────────────────────────
def _format_name(name_template: str, printer_name: str) -> str:
    """Render the task name from the configurable template, defensively.

    A user can mis-type the template (e.g. a stray ``{foo}``); fall back to a sensible
    default rather than raising and dropping the task.
    """
    try:
        return name_template.format(printer_name=printer_name)
    except (KeyError, IndexError, ValueError):
        return f"Update firmware: {printer_name}"


def _format_notes(latest_version: Any, installed_version: Any) -> str:
    """Compact description for the task notes (best-effort, may be empty)."""
    bits: list[str] = []
    if latest_version:
        bits.append(f"Firmware {latest_version} available")
    else:
        bits.append("A firmware update is available")
    if installed_version:
        bits.append(f"installed {installed_version}")
    return " · ".join(bits)


def build_firmware_chips(
    latest_version: Any,
    release_url: Any,
) -> list[dict[str, str]]:
    """Build Home Keeper task chips for the available firmware.

    A version chip (``{"label": "01.08.02.00", "icon": "mdi:package-up"}``) when the
    latest version is known, plus a *Release notes* link chip when the update entity
    exposes an ``http(s)`` release URL. Home Keeper only accepts ``http(s)`` chip URLs,
    so a non-web release_url is dropped rather than rejected.
    """
    chips: list[dict[str, str]] = []
    if latest_version:
        chips.append({"label": str(latest_version), "icon": "mdi:package-up"})
    if isinstance(release_url, str) and release_url.startswith(("http://", "https://")):
        chips.append({"label": "Release notes", "url": release_url})
    return chips


def build_add_task_payload(
    *,
    device_id: str,
    entity_id: str,
    printer_name: str,
    config_entry_id: str,
    name_template: str,
    latest_version: Any = None,
    installed_version: Any = None,
    release_url: Any = None,
) -> dict[str, Any]:
    """The ``home_keeper.add_task`` payload for a new firmware task (born armed).

    Carries a ``source`` namespaced to us (so we recognise it later) and a ``managed_by``
    block that marks the task Home-Keeper-managed, deletion-protected, and
    **completion-blocked** — the last hides the *Done* action so a user can't dismiss it;
    it is a read-only mirror that clears only when the printer reports up to date. No
    schedule fields — it's a ``triggered`` task.
    """
    return {
        "name": _format_name(name_template, printer_name),
        "notes": _format_notes(latest_version, installed_version),
        "recurrence_type": "triggered",
        "device_id": device_id,
        "source": {SOURCE_NS: {"device_id": device_id, "entity_id": entity_id}},
        "task_chips": build_firmware_chips(latest_version, release_url),
        "managed_by": {
            "integration": SOURCE_NS,
            "display_name": MANAGED_DISPLAY_NAME,
            "icon": MANAGED_ICON,
            "config_entry_id": config_entry_id,
            "deletion_protected": True,
            "completion_blocked": True,
            "completion_prompt": COMPLETION_PROMPT,
            "locked_fields": ["name", "recurrence_type", "device_id"],
        },
    }


# ── planners ─────────────────────────────────────────────────────────────────
def plan_update_available(
    tasks: list[dict],
    *,
    device_id: str,
    entity_id: str,
    printer_name: str,
    config_entry_id: str,
    name_template: str,
    latest_version: Any = None,
    installed_version: Any = None,
    release_url: Any = None,
) -> Action | None:
    """Decide what to do when *device_id* has a firmware update available.

    Absent → create (born armed). Dormant → arm. Already armed → nothing.
    """
    task = task_for_device(tasks, device_id)
    if task is None:
        return CreateTask(
            device_id,
            build_add_task_payload(
                device_id=device_id,
                entity_id=entity_id,
                printer_name=printer_name,
                config_entry_id=config_entry_id,
                name_template=name_template,
                latest_version=latest_version,
                installed_version=installed_version,
                release_url=release_url,
            ),
        )
    if is_armed(task):
        return None
    return ArmTask(task["id"], device_id)


def plan_update_cleared(tasks: list[dict], *, device_id: str) -> Action | None:
    """Decide what to do when *device_id*'s firmware is up to date again.

    Armed → clear (records the completion, goes dormant). Dormant/absent → nothing.
    """
    task = task_for_device(tasks, device_id)
    if task is None or not is_armed(task):
        return None
    return ClearTask(task["id"], device_id)


def plan_reconcile(
    tasks: list[dict],
    available: dict[str, dict[str, Any]],
    up_to_date: set[str],
    *,
    config_entry_id: str,
    name_template: str,
) -> list[Action]:
    """Converge the full state at startup (catch up on transitions missed while down).

    *available* maps ``device_id`` → its firmware info (name + version fields + entity_id)
    for every Bambu printer whose update entity currently reads ``on``; each gets a
    created/armed task, and an armed task whose chips no longer match the current version
    is refreshed.

    Clearing is **affirmative**: we only clear an armed task whose printer is in
    *up_to_date* — one whose update entity affirmatively reads ``off``. A printer that's
    merely offline (``unavailable``/``unknown``, so in neither set) keeps its armed task,
    so a printer that powers off mid-update-window doesn't record a phantom "installed".
    Idempotent no-ops are dropped.
    """
    actions: list[Action] = []

    for device_id, info in available.items():
        action = plan_update_available(
            tasks,
            device_id=device_id,
            entity_id=info.get("entity_id", ""),
            printer_name=info.get("name") or device_id,
            config_entry_id=config_entry_id,
            name_template=name_template,
            latest_version=info.get("latest_version"),
            installed_version=info.get("installed_version"),
            release_url=info.get("release_url"),
        )
        if action is not None:
            actions.append(action)
        # If the task already existed (arm or already-armed no-op), keep its chips in
        # step with the version currently on offer — a newer firmware may have superseded
        # the one the task was created for.
        existing = task_for_device(tasks, device_id)
        if existing is not None:
            desired = build_firmware_chips(
                info.get("latest_version"), info.get("release_url")
            )
            if (existing.get("task_chips") or []) != desired:
                actions.append(UpdateChips(existing["id"], device_id, desired))

    for task in our_tasks(tasks):
        device_id = (task["source"][SOURCE_NS]).get("device_id")
        if device_id in up_to_date and is_armed(task):
            actions.append(ClearTask(task["id"], device_id))
    return actions
