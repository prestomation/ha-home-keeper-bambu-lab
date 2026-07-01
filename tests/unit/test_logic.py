"""Unit tests for the pure glue decision logic."""

import bl_logic as L


CFG = "entry123"
TMPL = "Update firmware: {printer_name}"
NS = "home_keeper_bambu_lab"


def _task(
    device_id,
    *,
    next_due="2026-06-11T00:00:00-04:00",
    extra_source=None,
    chips=None,
    notes=None,
):
    """A Home-Keeper-shaped task owned by us (or by *extra_source* if given)."""
    source = {NS: {"device_id": device_id, "entity_id": f"update.{device_id}"}}
    if extra_source is not None:
        source = extra_source
    task = {"id": f"task_{device_id}", "next_due": next_due, "source": source}
    if chips is not None:
        task["task_chips"] = chips
    if notes is not None:
        task["notes"] = notes
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
def test_clear_armed_task_returns_clear_action_with_up_to_date_notes():
    tasks = [_task("x1c", next_due="2026-06-01T00:00:00-04:00")]
    action = L.plan_update_cleared(tasks, device_id="x1c", installed_version="01.08.02.00")
    assert action == L.ClearTask(
        "task_x1c",
        "x1c",
        notes="Firmware up to date · 01.08.02.00",
        cleared_version="01.08.02.00",
    )


def test_clear_without_installed_version_uses_generic_up_to_date_note():
    tasks = [_task("x1c", next_due="2026-06-01T00:00:00-04:00")]
    action = L.plan_update_cleared(tasks, device_id="x1c")
    assert action == L.ClearTask("task_x1c", "x1c", notes="Firmware up to date")


def test_clear_dormant_or_absent_is_noop():
    assert L.plan_update_cleared([_task("x1c", next_due=None)], device_id="x1c") is None
    assert L.plan_update_cleared([], device_id="x1c") is None


def test_format_up_to_date_notes():
    assert L.format_up_to_date_notes("01.08.02.00") == "Firmware up to date · 01.08.02.00"
    assert L.format_up_to_date_notes(None) == "Firmware up to date"


# ── re-arm cooldown (double-completion guard) ────────────────────────────────
def test_within_cooldown():
    # Never cleared -> never in cooldown.
    assert L.within_cooldown(None, now=1000.0, cooldown=900.0) is False
    # Within the window.
    assert L.within_cooldown(1000.0, now=1000.5, cooldown=900.0) is True
    assert L.within_cooldown(1000.0, now=1899.0, cooldown=900.0) is True
    # Past the window.
    assert L.within_cooldown(1000.0, now=1900.0, cooldown=900.0) is False
    assert L.within_cooldown(1000.0, now=5000.0, cooldown=900.0) is False


def test_is_stale_rearm_discriminates_by_version():
    # Same firmware re-offered right after installing it -> stale (a flap).
    assert L._is_stale_rearm("01.08.02.00", "01.08.02.00") is True
    # A genuinely newer firmware -> not stale, should re-arm.
    assert L._is_stale_rearm("01.09.00.00", "01.08.02.00") is False
    # Version-less (binary_sensor) -> can't tell them apart, treat as stale.
    assert L._is_stale_rearm(None, None) is True
    assert L._is_stale_rearm("01.09.00.00", None) is True
    assert L._is_stale_rearm(None, "01.08.02.00") is True


def test_stale_rearm_suppressed_but_new_version_rearms_within_cooldown():
    # A dormant task whose printer just cleared at 01.08.02.00.
    tasks = [_task("x1c", next_due=None)]
    recently = {"x1c": "01.08.02.00"}
    # Flap re-offers the same firmware -> suppressed (no re-arm).
    assert (
        L.plan_update_available(
            tasks, **_available(latest_version="01.08.02.00"), recently_cleared=recently
        )
        is None
    )
    # A genuinely newer firmware within the same window -> still re-arms.
    assert L.plan_update_available(
        tasks, **_available(latest_version="01.09.00.00"), recently_cleared=recently
    ) == L.ArmTask("task_x1c", "x1c")
    # Not in cooldown at all -> re-arms regardless of version.
    assert L.plan_update_available(
        tasks, **_available(latest_version="01.08.02.00"), recently_cleared={}
    ) == L.ArmTask("task_x1c", "x1c")


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
        _task(
            "avail_already_armed",
            next_due="2026-06-01T00:00:00-04:00",
            chips=[{"label": "01.08.02.00", "icon": "mdi:package-up"}],
            notes="Firmware 01.08.02.00 available",
        ),  # update + armed, matching chips/notes -> noop
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
    up_to_date = {"installed_still_armed": "01.09.00.00"}
    actions = L.plan_reconcile(
        tasks, available, up_to_date, config_entry_id=CFG, name_template=TMPL
    )

    kinds = {type(a) for a in actions}
    assert L.CreateTask in kinds and L.ArmTask in kinds and L.ClearTask in kinds
    assert L.ArmTask("task_avail_dormant", "avail_dormant") in actions
    assert (
        L.ClearTask(
            "task_installed_still_armed",
            "installed_still_armed",
            notes="Firmware up to date · 01.09.00.00",
            cleared_version="01.09.00.00",
        )
        in actions
    )
    creates = [a for a in actions if isinstance(a, L.CreateTask)]
    assert len(creates) == 1 and creates[0].device_id == "brand_new"
    # The already-armed device with matching chips/notes produces no arm/refresh action.
    assert not any(
        isinstance(a, L.ArmTask) and a.device_id == "avail_already_armed" for a in actions
    )
    assert not any(
        isinstance(a, L.UpdateTask) and a.device_id == "avail_already_armed"
        for a in actions
    )


def test_reconcile_suppresses_stale_rearm_but_not_a_new_version():
    # A dormant task whose printer cleared at 01.08.02.00 moments ago.
    tasks = [_task("x1c", next_due=None)]
    # Reconcile sees it "available" again at the SAME version (a flap) -> no re-arm.
    stale = L.plan_reconcile(
        tasks,
        {"x1c": {"name": "X1C", "latest_version": "01.08.02.00", "release_url": None}},
        {},
        config_entry_id=CFG,
        name_template=TMPL,
        recently_cleared={"x1c": "01.08.02.00"},
    )
    assert not any(isinstance(a, L.ArmTask) for a in stale)
    # A genuinely newer version -> re-arms even within the window.
    fresh = L.plan_reconcile(
        tasks,
        {"x1c": {"name": "X1C", "latest_version": "01.09.00.00", "release_url": None}},
        {},
        config_entry_id=CFG,
        name_template=TMPL,
        recently_cleared={"x1c": "01.08.02.00"},
    )
    assert L.ArmTask("task_x1c", "x1c") in fresh


def test_reconcile_keeps_armed_task_for_offline_printer():
    # A printer that's neither reporting-available nor affirmatively up-to-date (offline,
    # absent from both sets) must keep its armed task — clearing it would record a phantom
    # firmware install.
    tasks = [_task("offline", next_due="2026-06-01T00:00:00-04:00")]
    actions = L.plan_reconcile(
        tasks, {}, {}, config_entry_id=CFG, name_template=TMPL
    )
    assert actions == []


def test_reconcile_refreshes_chips_and_notes_when_version_supersedes():
    # Task armed for an older firmware; a newer one is now on offer -> refresh chips + notes.
    task = _task(
        "x1c",
        next_due="2026-06-01T00:00:00-04:00",
        chips=[{"label": "01.07.00.00", "icon": "mdi:package-up"}],
        notes="Firmware 01.07.00.00 available · installed 01.06.00.00",
    )
    actions = L.plan_reconcile(
        [task],
        {
            "x1c": {
                "name": "X1C",
                "latest_version": "01.08.02.00",
                "installed_version": "01.06.00.00",
                "release_url": None,
            }
        },
        {},
        config_entry_id=CFG,
        name_template=TMPL,
    )
    refreshes = [a for a in actions if isinstance(a, L.UpdateTask)]
    assert len(refreshes) == 1
    assert refreshes[0].task_id == "task_x1c"
    assert refreshes[0].chips == [{"label": "01.08.02.00", "icon": "mdi:package-up"}]
    assert refreshes[0].notes == "Firmware 01.08.02.00 available · installed 01.06.00.00"


def test_reconcile_refreshes_only_drifted_field():
    # Chips already current but notes stale -> refresh notes only (chips stays None).
    task = _task(
        "x1c",
        next_due="2026-06-01T00:00:00-04:00",
        chips=[{"label": "01.08.02.00", "icon": "mdi:package-up"}],
        notes="stale",
    )
    actions = L.plan_reconcile(
        [task],
        {"x1c": {"name": "X1C", "latest_version": "01.08.02.00", "release_url": None}},
        {},
        config_entry_id=CFG,
        name_template=TMPL,
    )
    refreshes = [a for a in actions if isinstance(a, L.UpdateTask)]
    assert len(refreshes) == 1
    assert refreshes[0].chips is None
    assert refreshes[0].notes == "Firmware 01.08.02.00 available"


def test_reconcile_ignores_foreign_tasks():
    tasks = [_task("x1c", extra_source={"pawsistant": {"x": 1}}, next_due="2026-01-01T00:00:00-04:00")]
    assert L.plan_reconcile(
        tasks, {}, {}, config_entry_id=CFG, name_template=TMPL
    ) == []
