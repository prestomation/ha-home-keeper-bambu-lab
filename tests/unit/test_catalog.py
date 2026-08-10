"""Unit tests for the maintenance catalog and its planner.

The catalog is the one place this glue holds an opinion, so these tests pin both the
*shape* of what it produces (a Home Keeper usage task with a time backstop, or a plain
floating task) and the guardrails around it: firmware tasks are never touched, an
accumulated meter baseline survives a reconcile, and turning items off removes exactly
their tasks and nothing else.
"""

import bl_catalog as C
import bl_logic as L

CFG = "entry123"
NS = "home_keeper_bambu_lab"
USAGE = "sensor.x1c_total_usage_hours"

PRINTERS = {"dev1": {"name": "X1C", "usage_entity_id": USAGE}}


def _catalog_task(device_id, item_key, **over):
    """A Home-Keeper-shaped catalog task owned by us."""
    item = C.BY_KEY[item_key]
    task = {
        "id": f"task_{device_id}_{item_key}",
        "next_due": None,
        "notes": item.notes,
        "source": {NS: {"device_id": device_id, "entity_id": USAGE, "item": item_key}},
    }
    if item.is_usage:
        task["sensor"] = {
            "entity_id": USAGE,
            "mode": "usage",
            "target": float(item.hours),
            "unit": "h",
            "also_every": {"interval": item.interval, "unit": item.unit},
            "combinator": "any",
        }
    else:
        task["interval"] = item.interval
        task["unit"] = item.unit
    task.update(over)
    return task


def _firmware_task(device_id):
    return {
        "id": f"task_{device_id}",
        "next_due": "2026-06-11T00:00:00-04:00",
        "source": {NS: {"device_id": device_id, "entity_id": f"update.{device_id}"}},
    }


def _plan(tasks, printers=None, *, enabled=True, options=None):
    return L.plan_catalog(
        tasks,
        printers if printers is not None else PRINTERS,
        config_entry_id=CFG,
        enabled=enabled,
        options=options,
    )


# ── the catalog itself ───────────────────────────────────────────────────────
def test_every_item_cites_a_source_and_has_a_sane_interval():
    assert C.CATALOG, "the catalog must not be empty"
    for item in C.CATALOG:
        assert item.source.startswith("https://wiki.bambulab.com/"), item.key
        assert item.interval >= 1, item.key
        assert item.unit in ("days", "weeks", "months"), item.key
        if item.is_usage:
            assert item.hours and item.hours > 0, item.key


def test_item_keys_are_unique():
    keys = [item.key for item in C.CATALOG]
    assert len(keys) == len(set(keys))
    assert set(C.BY_KEY) == set(keys)


def test_resolve_falls_back_to_the_default_for_junk_overrides():
    item = C.BY_KEY["z_lead_screws"]
    assert C.resolve(item, None) == (True, item.hours)
    assert C.resolve(item, {}) == (True, item.hours)
    # A blanked or nonsensical override must not produce an invalid target.
    for junk in ("", None, 0, -5, "abc"):
        assert C.resolve(item, {C.option_key_interval(item.key): junk})[1] == item.hours
    assert C.resolve(item, {C.option_key_interval(item.key): "600"})[1] == 600
    assert C.resolve(item, {C.option_key_enabled(item.key): False})[0] is False


# ── payload shape ────────────────────────────────────────────────────────────
def test_usage_item_becomes_a_metered_task_with_a_time_backstop():
    actions = _plan([])
    payloads = {a.payload["source"][NS]["item"]: a.payload for a in actions}
    payload = payloads["z_lead_screws"]
    item = C.BY_KEY["z_lead_screws"]
    assert payload["recurrence_type"] == "sensor"
    assert payload["sensor"] == {
        "entity_id": USAGE,
        "mode": "usage",
        "target": item.hours,
        "unit": "h",
        "also_every": {"interval": item.interval, "unit": item.unit},
        "combinator": "any",
    }
    assert payload["device_id"] == "dev1"
    assert payload["name"].endswith("X1C")


def test_calendar_only_item_becomes_a_floating_task():
    payloads = {a.payload["source"][NS]["item"]: a.payload for a in _plan([])}
    payload = payloads["carbon_rods"]
    item = C.BY_KEY["carbon_rods"]
    assert payload["recurrence_type"] == "floating"
    assert payload["interval"] == item.interval
    assert payload["unit"] == item.unit
    assert "sensor" not in payload


def test_catalog_tasks_are_completable_unlike_the_firmware_mirror():
    # A human does this work, so nothing may block the Done action. (The firmware
    # mirror is the opposite: it clears itself and is completion_blocked.)
    for action in _plan([]):
        managed = action.payload["managed_by"]
        assert "completion_blocked" not in managed
        assert managed["deletion_protected"] is True
        # The interval must stay editable on the task itself.
        assert "sensor" not in managed["locked_fields"]
        assert "interval" not in managed["locked_fields"]


def test_printer_without_a_usage_sensor_still_gets_calendar_tasks():
    printers = {"dev1": {"name": "A1", "usage_entity_id": None}}
    payloads = {a.payload["source"][NS]["item"]: a.payload for a in _plan([], printers)}
    item = C.BY_KEY["z_lead_screws"]
    degraded = payloads["z_lead_screws"]
    # No meter to bind to -> fall back to the calendar half rather than dropping it.
    assert degraded["recurrence_type"] == "floating"
    assert degraded["interval"] == item.interval
    assert degraded["unit"] == item.unit


# ── convergence ──────────────────────────────────────────────────────────────
def test_creates_one_task_per_enabled_item_per_printer():
    actions = _plan([])
    enabled = [i for i in C.CATALOG if i.default_enabled]
    assert len(actions) == len(enabled)
    assert all(isinstance(a, L.CreateTask) for a in actions)


def test_existing_tasks_are_left_alone():
    tasks = [_catalog_task("dev1", i.key) for i in C.CATALOG if i.default_enabled]
    assert _plan(tasks) == []


def test_interval_override_updates_the_existing_task():
    item = C.BY_KEY["z_lead_screws"]
    tasks = [_catalog_task("dev1", i.key) for i in C.CATALOG if i.default_enabled]
    actions = _plan(tasks, options={C.option_key_interval(item.key): 600})
    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, L.UpdateTask)
    assert action.fields["sensor"]["target"] == 600.0
    assert action.fields["sensor"]["also_every"] == {
        "interval": item.interval,
        "unit": item.unit,
    }


def test_reconcile_never_clobbers_the_accumulated_meter_baseline():
    item = C.BY_KEY["z_lead_screws"]
    task = _catalog_task("dev1", item.key)
    task["sensor"]["baseline"] = 660.0
    tasks = [task] + [
        _catalog_task("dev1", i.key)
        for i in C.CATALOG
        if i.default_enabled and i.key != item.key
    ]
    # Nothing drifted, so nothing is sent — the baseline is not part of the comparison.
    assert _plan(tasks) == []


def test_disabling_an_item_deletes_only_its_task():
    item = C.BY_KEY["carbon_filter"]
    tasks = [_catalog_task("dev1", i.key) for i in C.CATALOG if i.default_enabled]
    actions = _plan(tasks, options={C.option_key_enabled(item.key): False})
    assert len(actions) == 1
    assert isinstance(actions[0], L.DeleteTask)
    assert actions[0].task_id == f"task_dev1_{item.key}"


def test_master_switch_off_removes_every_catalog_task():
    tasks = [_catalog_task("dev1", i.key) for i in C.CATALOG if i.default_enabled]
    actions = _plan(tasks, enabled=False)
    assert len(actions) == len(tasks)
    assert all(isinstance(a, L.DeleteTask) for a in actions)


def test_a_printer_that_disappeared_has_its_catalog_tasks_removed():
    tasks = [_catalog_task("gone", i.key) for i in C.CATALOG if i.default_enabled]
    actions = _plan(tasks, {})
    assert all(isinstance(a, L.DeleteTask) for a in actions)
    assert len(actions) == len(tasks)


def test_default_off_items_are_not_created_but_can_be_turned_on():
    off = [i for i in C.CATALOG if not i.default_enabled]
    assert off, "the fixture assumes at least one item ships off"
    created = {a.payload["source"][NS]["item"] for a in _plan([])}
    assert created.isdisjoint({i.key for i in off})
    turned_on = _plan([], options={C.option_key_enabled(off[0].key): True})
    assert off[0].key in {a.payload["source"][NS]["item"] for a in turned_on}


# ── isolation from the firmware mirror ───────────────────────────────────────
def test_firmware_tasks_are_invisible_to_the_catalog_planner():
    # A legacy firmware task carries no ``item`` key at all; it must not be mistaken
    # for an unknown catalog item and deleted.
    tasks = [_firmware_task("dev1")]
    actions = _plan(tasks, enabled=False)
    assert actions == []


def test_catalog_tasks_are_invisible_to_the_firmware_planner():
    tasks = [_catalog_task("dev1", "z_lead_screws")]
    action = L.plan_update_available(
        tasks,
        device_id="dev1",
        entity_id="update.dev1",
        printer_name="X1C",
        config_entry_id=CFG,
        name_template="Update firmware: {printer_name}",
    )
    # No firmware task exists for this printer, so it must create one rather than
    # arming the maintenance task that happens to share the device.
    assert isinstance(action, L.CreateTask)
    assert action.payload["recurrence_type"] == "triggered"


def test_legacy_firmware_task_without_an_item_key_still_matches():
    tasks = [_firmware_task("dev1")]
    assert L.task_for_device(tasks, "dev1") is tasks[0]
    assert L.task_item(tasks[0]) == "firmware"
