"""Unit tests for the maintenance catalog and its planner.

The catalog is the one place this glue holds an opinion, so these tests pin both the
*shape* of what it produces (a Home Keeper usage task with a time backstop, or a plain
floating task) and the guardrails around it: firmware tasks are never touched, an
accumulated meter baseline survives a reconcile, and turning items off removes exactly
their tasks and nothing else.

They also pin the **per-model** behaviour, which is the reason the catalog is not one
flat list: an A1 must not be told to service a chamber filter it doesn't have, an
unrecognised printer must still get the items every Bambu Lab printer shares, and a user
who corrects the detected model must see the task set change on the next reconcile.
"""

import bl_catalog as C
import bl_logic as L

CFG = "entry123"
NS = "home_keeper_bambu_lab"
USAGE = "sensor.x1c_total_usage_hours"
SERIAL = "01P00A000000001"

PRINTERS = {
    "dev1": {
        "name": "X1C",
        "serial": SERIAL,
        "model": "X1C",
        "usage_entity_id": USAGE,
    }
}


def _resolved(item_key, family=C.FAMILY_X1, serial="", options=None):
    return C.resolve(C.BY_KEY[item_key], family, serial, options)


def _enabled_keys(family=C.FAMILY_X1, serial="", options=None):
    """The item keys that apply to *family*, in catalog order."""
    return [r.item.key for r in C.resolve_all(family, serial, options) if r.enabled]


def _catalog_task(device_id, item_key, family=C.FAMILY_X1, **over):
    """A Home-Keeper-shaped catalog task owned by us, as *family* would have made it."""
    resolved = _resolved(item_key, family)
    task = {
        "id": f"task_{device_id}_{item_key}",
        "next_due": None,
        "notes": resolved.notes,
        "source": {NS: {"device_id": device_id, "entity_id": USAGE, "item": item_key}},
    }
    if resolved.is_usage:
        task["sensor"] = {
            "entity_id": USAGE,
            "mode": "usage",
            "target": float(resolved.hours),
            "unit": "h",
            "also_every": {"interval": resolved.interval, "unit": resolved.unit},
            "combinator": "any",
        }
    else:
        task["interval"] = resolved.interval
        task["unit"] = resolved.unit
    task.update(over)
    return task


def _all_tasks(device_id="dev1", family=C.FAMILY_X1):
    return [_catalog_task(device_id, key, family) for key in _enabled_keys(family)]


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


def test_every_family_override_is_addressed_to_a_real_family():
    # A typo'd family key would silently never apply, which is exactly the kind of bug
    # that reads as "the catalog is just wrong for my printer".
    for item in C.CATALOG:
        for family in item.by_family:
            assert family in C.FAMILIES, f"{item.key} -> {family}"
        for override in item.by_family.values():
            if override.source is not None:
                assert override.source.startswith("https://wiki.bambulab.com/")


def test_every_family_has_a_label():
    assert set(C.FAMILY_LABELS) == set(C.FAMILIES)
    assert set(C.MODEL_FAMILIES.values()) <= set(C.FAMILIES)


# ── detection ────────────────────────────────────────────────────────────────
def test_normalize_family_maps_every_known_model():
    assert C.normalize_family("X1C") == C.FAMILY_X1
    assert C.normalize_family("P1P") == C.FAMILY_P1P
    assert C.normalize_family("P1S") == C.FAMILY_P1S
    assert C.normalize_family("A1MINI") == C.FAMILY_A1
    assert C.normalize_family("P2S") == C.FAMILY_P2
    assert C.normalize_family("X2D") == C.FAMILY_P2
    assert C.normalize_family("H2DPRO") == C.FAMILY_H2


def test_normalize_family_is_forgiving_about_formatting():
    for spelling in ("x1c", " X1C ", "A1 mini", "a1-mini"):
        assert C.normalize_family(spelling) in (C.FAMILY_X1, C.FAMILY_A1)
    assert C.normalize_family("A1 mini") == C.FAMILY_A1


def test_an_unknown_or_missing_model_is_not_an_error():
    # A printer Bambu Lab ships next year has to remain configurable, so an unrecognised
    # model resolves to a usable family rather than raising or being dropped.
    for junk in (None, "", "   ", "TOTALLY_NEW", 42):
        assert C.normalize_family(junk) == C.FAMILY_UNKNOWN


def test_the_user_override_beats_the_detection():
    options = {C.option_key_model(SERIAL): C.FAMILY_A1}
    assert C.resolved_family(SERIAL, "X1C", options) == C.FAMILY_A1
    # A blank or nonsense override falls back to what we detected.
    for junk in ("", None, "NOPE"):
        assert C.resolved_family(SERIAL, "X1C", {C.option_key_model(SERIAL): junk}) == (
            C.FAMILY_X1
        )
    assert C.resolved_family(SERIAL, "X1C", None) == C.FAMILY_X1


# ── resolution ───────────────────────────────────────────────────────────────
def test_family_gating_matches_the_published_schedules():
    x1 = _enabled_keys(C.FAMILY_X1)
    a1 = _enabled_keys(C.FAMILY_A1)
    p1p = _enabled_keys(C.FAMILY_P1P)
    p1s = _enabled_keys(C.FAMILY_P1S)
    p2 = _enabled_keys(C.FAMILY_P2)

    # The A1 is an open-frame bed-slinger: no chamber filter and no X-axis carbon rods.
    assert "carbon_filter" not in a1
    assert "carbon_rods" not in a1
    # ...but it still has rods to clean and lead screws to grease.
    assert "linear_rods" in a1 and "z_lead_screws" in a1
    # The camera is off for a different reason: the A1 *has* one, but Bambu publishes
    # no cleaning cadence for it, so we ship no interval rather than invent one. It
    # must still be offered, and switching it on must work.
    assert "camera_lens" not in a1
    on = {C.option_key_enabled(SERIAL, "camera_lens"): True}
    assert _resolved("camera_lens", C.FAMILY_A1, SERIAL, on).enabled is True

    # The P1P is open-frame, the P1S is enclosed — same wiki page, different chamber.
    assert "carbon_filter" not in p1p
    assert "carbon_filter" in p1s
    assert "carbon_rods" in p1p and "carbon_rods" in p1s

    # The X1 has both; the P2 has the filter but uses oiled shafts, not carbon rods.
    assert "carbon_filter" in x1 and "carbon_rods" in x1
    assert "carbon_filter" in p2 and "carbon_rods" not in p2


def test_an_unknown_printer_gets_only_the_items_every_printer_has():
    unknown = _enabled_keys(C.FAMILY_UNKNOWN)
    assert set(unknown) == {"linear_rods", "z_lead_screws", "camera_lens"}
    # Every item is still offered — the model decides defaults, never availability.
    assert len(C.resolve_all(C.FAMILY_UNKNOWN)) == len(C.CATALOG)


def test_a_family_can_rewrite_the_notes_without_forking_the_item():
    # The X1's carbon rods must never be greased; the P2's X/Y shafts must be oiled.
    # Same axis, opposite instruction, one item.
    x1 = _resolved("linear_rods", C.FAMILY_X1)
    p2 = _resolved("linear_rods", C.FAMILY_P2)
    assert p2.notes != x1.notes
    assert "oil" in p2.notes.lower()
    # The schedule itself is shared, so only the prose diverges.
    assert (p2.hours, p2.interval, p2.unit) == (x1.hours, x1.interval, x1.unit)


def test_resolve_falls_back_to_the_default_for_junk_overrides():
    item = C.BY_KEY["z_lead_screws"]
    assert _resolved("z_lead_screws").enabled is True
    assert _resolved("z_lead_screws").hours == item.hours
    # A blanked or nonsensical override must not produce an invalid target.
    for junk in ("", None, 0, -5, "abc"):
        key = C.option_key_interval(SERIAL, item.key)
        assert _resolved("z_lead_screws", serial=SERIAL, options={key: junk}).hours == (
            item.hours
        )
    key = C.option_key_interval(SERIAL, item.key)
    assert _resolved("z_lead_screws", serial=SERIAL, options={key: "600"}).hours == 600
    off = {C.option_key_enabled(SERIAL, item.key): False}
    assert _resolved("z_lead_screws", serial=SERIAL, options=off).enabled is False


def test_the_user_option_beats_the_family_which_beats_the_item():
    # carbon_filter ships off, the X1 family turns it on, the user turns it back off.
    assert _resolved("carbon_filter", C.FAMILY_UNKNOWN).enabled is False
    assert _resolved("carbon_filter", C.FAMILY_X1).enabled is True
    off = {C.option_key_enabled(SERIAL, "carbon_filter"): False}
    assert _resolved("carbon_filter", C.FAMILY_X1, SERIAL, off).enabled is False
    # ...and can equally turn on something their family never suggested.
    on = {C.option_key_enabled(SERIAL, "carbon_rods"): True}
    assert _resolved("carbon_rods", C.FAMILY_A1, SERIAL, on).enabled is True


def test_per_printer_options_are_ignored_when_we_have_no_serial_to_key_them_on():
    off = {C.option_key_enabled(SERIAL, "carbon_filter"): False}
    assert _resolved("carbon_filter", C.FAMILY_X1, "", off).enabled is True


def test_the_legacy_flat_options_still_apply_without_a_serial():
    # The 0.2.0b1 keys were one flat set for every printer, so they carry no serial.
    # Gating them behind one would silently drop a preview tester's answers for a
    # printer whose serial we couldn't derive.
    legacy = {"item_carbon_filter_enabled": False, "item_z_lead_screws_interval": 600}
    assert _resolved("carbon_filter", C.FAMILY_X1, "", legacy).enabled is False
    assert _resolved("z_lead_screws", C.FAMILY_X1, "", legacy).hours == 600


def test_the_flat_option_keys_from_the_first_beta_still_apply():
    # 0.2.0b1 shipped one set of options for every printer. A preview tester's answers
    # must survive the move to per-printer keys.
    legacy = {"item_carbon_filter_enabled": False, "item_z_lead_screws_interval": 600}
    assert _resolved("carbon_filter", C.FAMILY_X1, SERIAL, legacy).enabled is False
    assert _resolved("z_lead_screws", C.FAMILY_X1, SERIAL, legacy).hours == 600
    # A per-printer answer wins over the legacy one for that printer, in both
    # directions — a legacy True must not resurrect an item the user has since
    # switched off for this printer, and vice versa.
    both = {**legacy, C.option_key_enabled(SERIAL, "carbon_filter"): True}
    assert _resolved("carbon_filter", C.FAMILY_X1, SERIAL, both).enabled is True
    inverted = {
        "item_carbon_rods_enabled": True,
        C.option_key_enabled(SERIAL, "carbon_rods"): False,
    }
    assert _resolved("carbon_rods", C.FAMILY_X1, SERIAL, inverted).enabled is False
    # Same for the interval: the per-printer number wins even when a legacy one exists.
    intervals = {
        "item_z_lead_screws_interval": 600,
        C.option_key_interval(SERIAL, "z_lead_screws"): 900,
    }
    assert _resolved("z_lead_screws", C.FAMILY_X1, SERIAL, intervals).hours == 900


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
    printers = {
        "dev1": {"name": "A1", "serial": "S2", "model": "A1", "usage_entity_id": None}
    }
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
    assert len(actions) == len(_enabled_keys(C.FAMILY_X1))
    assert all(isinstance(a, L.CreateTask) for a in actions)


def test_existing_tasks_are_left_alone():
    assert _plan(_all_tasks()) == []


def test_a_mixed_fleet_gets_a_different_task_set_per_printer():
    printers = {
        "dev1": PRINTERS["dev1"],
        "dev2": {
            "name": "A1 mini",
            "serial": "S2",
            "model": "A1MINI",
            "usage_entity_id": "sensor.a1_total_usage_hours",
        },
    }
    by_device: dict[str, set[str]] = {"dev1": set(), "dev2": set()}
    for action in _plan([], printers):
        by_device[action.device_id].add(action.payload["source"][NS]["item"])
    assert "carbon_filter" in by_device["dev1"]
    assert "carbon_filter" not in by_device["dev2"]
    assert by_device["dev2"] < by_device["dev1"]


def test_correcting_the_model_adds_and_removes_the_right_tasks():
    # Detected as an X1C, actually an A1: the filter, the carbon rods and the anti-rust
    # pass go away, and nothing the A1 does need is dropped.
    tasks = _all_tasks(family=C.FAMILY_X1)
    actions = _plan(tasks, options={C.option_key_model(SERIAL): C.FAMILY_A1})
    deleted = {a.task_id for a in actions if isinstance(a, L.DeleteTask)}
    assert deleted == {
        "task_dev1_carbon_filter",
        "task_dev1_carbon_rods",
        "task_dev1_rod_antirust",
        "task_dev1_camera_lens",
    }
    # The A1's lead-screw note differs from the X1's, so that task is retuned in place.
    updated = {a.task_id for a in actions if isinstance(a, L.UpdateTask)}
    assert "task_dev1_z_lead_screws" in updated
    assert not any(isinstance(a, L.CreateTask) for a in actions)


def test_correcting_the_model_back_restores_the_tasks():
    options = {C.option_key_model(SERIAL): C.FAMILY_A1}
    tasks = _all_tasks(family=C.FAMILY_A1)
    assert _plan(tasks, options=options) == []
    restored = _plan(tasks, options={C.option_key_model(SERIAL): C.FAMILY_X1})
    created = {
        a.payload["source"][NS]["item"] for a in restored if isinstance(a, L.CreateTask)
    }
    assert created == {"carbon_filter", "carbon_rods", "rod_antirust", "camera_lens"}


def test_interval_override_updates_the_existing_task():
    item = C.BY_KEY["z_lead_screws"]
    actions = _plan(
        _all_tasks(), options={C.option_key_interval(SERIAL, item.key): 600}
    )
    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, L.UpdateTask)
    assert action.fields["sensor"]["target"] == 600.0
    assert action.fields["sensor"]["also_every"] == {
        "interval": item.interval,
        "unit": item.unit,
    }


def test_reconcile_never_clobbers_the_accumulated_meter_baseline():
    tasks = _all_tasks()
    for task in tasks:
        if "sensor" in task:
            task["sensor"]["baseline"] = 660.0
    # Nothing drifted, so nothing is sent — the baseline is not part of the comparison.
    assert _plan(tasks) == []


def test_disabling_an_item_deletes_only_its_task():
    item = C.BY_KEY["carbon_filter"]
    options = {C.option_key_enabled(SERIAL, item.key): False}
    actions = _plan(_all_tasks(), options=options)
    assert len(actions) == 1
    assert isinstance(actions[0], L.DeleteTask)
    assert actions[0].task_id == f"task_dev1_{item.key}"


def test_master_switch_off_removes_every_catalog_task():
    tasks = _all_tasks()
    actions = _plan(tasks, enabled=False)
    assert len(actions) == len(tasks)
    assert all(isinstance(a, L.DeleteTask) for a in actions)


def test_a_printer_that_disappeared_has_its_catalog_tasks_removed():
    tasks = [_catalog_task("gone", key) for key in _enabled_keys()]
    actions = _plan(tasks, {})
    assert all(isinstance(a, L.DeleteTask) for a in actions)
    assert len(actions) == len(tasks)


def test_default_off_items_are_not_created_but_can_be_turned_on():
    off = [key for key in C.BY_KEY if key not in _enabled_keys()]
    assert off, "the fixture assumes at least one item is off for the X1"
    created = {a.payload["source"][NS]["item"] for a in _plan([])}
    assert created.isdisjoint(set(off))
    options = {C.option_key_enabled(SERIAL, off[0]): True}
    turned_on = _plan([], options=options)
    assert off[0] in {a.payload["source"][NS]["item"] for a in turned_on}


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
