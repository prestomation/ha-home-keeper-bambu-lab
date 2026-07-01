"""Unit tests for the pure glue decision logic."""

import bl_logic as L


CFG = "entry123"
TMPL = "Update firmware: {printer_name}"
NS = "home_keeper_bambu_lab"


def _task(device_id, *, next_due="2026-06-11T00:00:00-04:00", extra_source=None, chips=None):
    """A Home-Keeper-shaped task owned by us (or by *extra_source* if given)."""
    source = {NS: {"device_id": device_id, "entity_id": f"update.{device_id}"}}
    if extra_source is not None:
        source = extra_source
    task = {"id": f"task_{device_id}", "next_due": next_due, "source": source}
    if chips is not None:
        task["task_chips"] = chips
    return task


def _available(**over):
    kwargs = dict(
        device_id="x1c",
        entity_id="update.x1c_firmware_update",
        printer_name="X1 Carbon",
        config_entry_id=CFG,
        name_template=TMPL,
        latest_version="01.08.02.00",
        installed_version="01.07.00.00",
        release_url="https://bambulab.com/release",
    )
    kwargs.update(over)
    return kwargs


# ── helpers ──────────────────────────────────────────────────────────────────
def test_task_for_device_matches_only_our_namespace():
    ours = _task("x1c")
    foreign = _task("x1c", extra_source={"other_integration": {"device_id": "x1c"}})
    assert L.task_for_device([foreign, ours], "x1c") is ours
    assert L.task_for_device([foreign], "x1c") is None


def test_is_armed():
    assert L.is_armed(_task("d", next_due="2026-01-01T00:00:00-04:00")) is True
    assert L.is_armed(_task("d", next_due=None)) is False


# ── firmware update available ────────────────────────────────────────────────
def test_available_with_no_task_creates_read_only_triggered_task():
    action = L.plan_update_available([], **_available())
    assert isinstance(action, L.CreateTask)
    p = action.payload
    assert p["recurrence_type"] == "triggered"
    assert p["name"] == "Update firmware: X1 Carbon"
    assert "01.08.02.00" in p["notes"] and "01.07.00.00" in p["notes"]
    assert p["device_id"] == "x1c"
    assert p["source"][NS]["device_id"] == "x1c"
    assert p["source"][NS]["entity_id"] == "update.x1c_firmware_update"
    mb = p["managed_by"]
    assert mb["integration"] == NS
    assert mb["config_entry_id"] == CFG
    assert mb["deletion_protected"] is True
    # The read-only mirror contract: the user cannot check this off.
    assert mb["completion_blocked"] is True
    assert "name" in mb["locked_fields"]


def test_available_with_dormant_task_arms_it():
    tasks = [_task("x1c", next_due=None)]
    action = L.plan_update_available(tasks, **_available())
    assert action == L.ArmTask("task_x1c", "x1c")


def test_available_with_already_armed_task_is_noop():
    tasks = [_task("x1c", next_due="2026-06-01T00:00:00-04:00")]
    action = L.plan_update_available(tasks, **_available())
    assert action is None


# ── firmware cleared ─────────────────────────────────────────────────────────
def test_clear_armed_task_returns_clear_action():
    tasks = [_task("x1c", next_due="2026-06-01T00:00:00-04:00")]
    assert L.plan_update_cleared(tasks, device_id="x1c") == L.ClearTask("task_x1c", "x1c")


def test_clear_dormant_or_absent_is_noop():
    assert L.plan_update_cleared([_task("x1c", next_due=None)], device_id="x1c") is None
    assert L.plan_update_cleared([], device_id="x1c") is None


# ── chips ────────────────────────────────────────────────────────────────────
def test_build_firmware_chips_version_and_release_url():
    chips = L.build_firmware_chips("01.08.02.00", "https://bambulab.com/release")
    assert chips == [
        {"label": "01.08.02.00", "icon": "mdi:package-up"},
        {"label": "Release notes", "url": "https://bambulab.com/release"},
    ]


def test_build_firmware_chips_drops_non_web_release_url():
    chips = L.build_firmware_chips("01.08.02.00", "ftp://x/y")
    assert chips == [{"label": "01.08.02.00", "icon": "mdi:package-up"}]


def test_build_firmware_chips_no_version():
    assert L.build_firmware_chips(None, None) == []


def test_create_payload_includes_version_and_release_chips():
    action = L.plan_update_available([], **_available())
    assert action.payload["task_chips"] == [
        {"label": "01.08.02.00", "icon": "mdi:package-up"},
        {"label": "Release notes", "url": "https://bambulab.com/release"},
    ]


# ── name template ────────────────────────────────────────────────────────────
def test_name_template_falls_back_on_bad_template():
    action = L.plan_update_available(
        [], **_available(name_template="Firmware {nonexistent}", printer_name="P1S")
    )
    assert isinstance(action, L.CreateTask)
    assert action.payload["name"] == "Update firmware: P1S"


def test_notes_without_versions_is_generic():
    action = L.plan_update_available(
        [], **_available(latest_version=None, installed_version=None, release_url=None)
    )
    assert action.payload["notes"] == "A firmware update is available"
    assert action.payload["task_chips"] == []


# ── defensive ────────────────────────────────────────────────────────────────
def test_malformed_tasks_are_ignored():
    malformed = [
        "not-a-dict",
        {"source": {NS: {"device_id": "x1c"}}},  # no id
        {"id": "x", "source": {"other": {"device_id": "x1c"}}},  # not ours
    ]
    assert L.task_for_device(malformed, "x1c") is None
    assert L.our_tasks(malformed) == []
    # And an available event for that device creates a fresh task rather than KeyError-ing.
    action = L.plan_update_available(malformed, **_available())
    assert isinstance(action, L.CreateTask)


# ── reconcile ────────────────────────────────────────────────────────────────
def test_reconcile_creates_arms_and_clears_to_converge():
    tasks = [
        _task("avail_dormant", next_due=None),  # update now -> arm
        _task("installed_still_armed", next_due="2026-06-01T00:00:00-04:00"),  # off -> clear
        _task("avail_already_armed", next_due="2026-06-01T00:00:00-04:00", chips=[
            {"label": "01.08.02.00", "icon": "mdi:package-up"}
        ]),  # update + armed, matching chips -> noop
    ]
    available = {
        "avail_dormant": {"name": "A", "latest_version": None, "release_url": None},
        "avail_already_armed": {
            "name": "B",
            "latest_version": "01.08.02.00",
            "release_url": None,
        },
        "brand_new": {"name": "C", "latest_version": None, "release_url": None},  # create
    }
    up_to_date = {"installed_still_armed"}
    actions = L.plan_reconcile(
        tasks, available, up_to_date, config_entry_id=CFG, name_template=TMPL
    )

    kinds = {type(a) for a in actions}
    assert L.CreateTask in kinds and L.ArmTask in kinds and L.ClearTask in kinds
    assert L.ArmTask("task_avail_dormant", "avail_dormant") in actions
    assert L.ClearTask("task_installed_still_armed", "installed_still_armed") in actions
    creates = [a for a in actions if isinstance(a, L.CreateTask)]
    assert len(creates) == 1 and creates[0].device_id == "brand_new"
    # The already-armed device with matching chips produces no arm/chip action.
    assert not any(
        isinstance(a, L.ArmTask) and a.device_id == "avail_already_armed" for a in actions
    )
    assert not any(
        isinstance(a, L.UpdateChips) and a.device_id == "avail_already_armed"
        for a in actions
    )


def test_reconcile_keeps_armed_task_for_offline_printer():
    # A printer that's neither reporting-available nor affirmatively up-to-date (offline,
    # absent from both sets) must keep its armed task — clearing it would record a phantom
    # firmware install.
    tasks = [_task("offline", next_due="2026-06-01T00:00:00-04:00")]
    actions = L.plan_reconcile(
        tasks, {}, set(), config_entry_id=CFG, name_template=TMPL
    )
    assert actions == []


def test_reconcile_refreshes_chips_when_version_supersedes():
    # Task armed for an older firmware; a newer one is now on offer -> refresh chips.
    task = _task("x1c", next_due="2026-06-01T00:00:00-04:00", chips=[
        {"label": "01.07.00.00", "icon": "mdi:package-up"}
    ])
    actions = L.plan_reconcile(
        [task],
        {"x1c": {"name": "X1C", "latest_version": "01.08.02.00", "release_url": None}},
        set(),
        config_entry_id=CFG,
        name_template=TMPL,
    )
    chip_actions = [a for a in actions if isinstance(a, L.UpdateChips)]
    assert len(chip_actions) == 1
    assert chip_actions[0].task_id == "task_x1c"
    assert chip_actions[0].chips == [{"label": "01.08.02.00", "icon": "mdi:package-up"}]


def test_reconcile_ignores_foreign_tasks():
    tasks = [_task("x1c", extra_source={"pawsistant": {"x": 1}}, next_due="2026-01-01T00:00:00-04:00")]
    assert L.plan_reconcile(
        tasks, {}, set(), config_entry_id=CFG, name_template=TMPL
    ) == []
