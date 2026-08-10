"""End-to-end: real Home Keeper + the fake Bambu Lab + this glue in a HA container.

We toggle the Bambu Lab firmware ``update`` entity (via the fake's
``bambu_lab.set_firmware_available`` service) over REST and assert that Home Keeper's
to-do list reflects the firmware task being armed and cleared. The to-do list counts
incomplete items, and a triggered task is on the list exactly while armed — so its count
is our observable for the full glue → Home Keeper loop.

The behavioural test drives a *fake* Bambu Lab entity (a real printer can't run in CI),
so it can't catch the *real* integration renaming its firmware surface. The static
contract test below guards that separately, against the fetched real ha-bambulab source.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import bl_catalog as catalog
import pytest

TODO = "todo.home_keeper_tasks"

# Where ci/fetch-upstreams.sh stages the *real* ha-bambulab for the contract assertion.
_BAMBU_SRC = Path(__file__).resolve().parent / "upstream_src" / "bambu_lab"


def _count(api) -> int:
    return int(api.state(TODO) or 0)


def test_bambu_firmware_contract_against_real_source():
    """Guard the external Bambu Lab firmware surface this glue depends on.

    The behavioural tests drive a fake entity, so they can't catch the real integration
    moving its firmware surface. Assert the real ha-bambulab source still defines a
    ``firmware_update`` update entity keyed ``{serial}_firmware_update`` and driven from
    ``upgrade.new_version`` / ``upgrade.cur_version``. If this fails, the real integration
    moved its surface — update const.py and re-pin BAMBU_REF.
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    update_py = _BAMBU_SRC / "update.py"
    assert update_py.is_file(), "ha-bambulab no longer has update.py"
    text = update_py.read_text(encoding="utf-8")
    # The firmware update entity's description key. The glue's UPDATE_UNIQUE_SUFFIX is
    # "_" + this key (the runtime unique_id is f"{serial}_{key}"), so if the key changes
    # the glue stops matching the entity.
    assert 'key="firmware_update"' in text, (
        "ha-bambulab no longer keys its firmware update entity 'firmware_update' — "
        "update const.UPDATE_UNIQUE_SUFFIX."
    )
    # The unique_id is composed as f"{serial}_{description.key}" — that's what makes the
    # entity id end with '_firmware_update'. The literal suffix never appears in source
    # (it's assembled at runtime), so assert the composition instead.
    assert "description.key" in text and "serial" in text, (
        "ha-bambulab no longer builds the firmware update unique_id from "
        "serial + description.key — re-check const.UPDATE_UNIQUE_SUFFIX."
    )
    assert "new_version" in text and "cur_version" in text, (
        "ha-bambulab no longer sources firmware from upgrade.new_version/cur_version."
    )

    # The other firmware surface: when the "Firmware update" option is off (the default),
    # the integration exposes a binary_sensor keyed 'firmware_update' with device_class
    # UPDATE instead of the update entity. The glue mirrors this variant too, so guard it.
    definitions_py = _BAMBU_SRC / "definitions.py"
    assert definitions_py.is_file(), "ha-bambulab no longer has definitions.py"
    defs = definitions_py.read_text(encoding="utf-8")
    assert 'key="firmware_update"' in defs, (
        "ha-bambulab no longer defines a 'firmware_update' binary_sensor — the glue's "
        "binary_sensor firmware path would silently stop matching."
    )
    assert "BinarySensorDeviceClass.UPDATE" in defs, (
        "ha-bambulab's firmware binary_sensor is no longer device_class UPDATE — "
        "re-check const.FIRMWARE_BINARY_DEVICE_CLASS."
    )


def test_bambu_usage_hours_contract_against_real_source():
    """Guard the cumulative counter the maintenance catalog meters against.

    Every hours-based catalog item binds to ``sensor.<printer>_total_usage_hours``. If
    ha-bambulab renames that key or drops the sensor, those tasks would silently never
    be created (the calendar-only ones would still work, which is exactly the kind of
    half-broken state a contract test exists to catch).
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    definitions_py = _BAMBU_SRC / "definitions.py"
    assert definitions_py.is_file(), "ha-bambulab no longer has definitions.py"
    defs = definitions_py.read_text(encoding="utf-8")
    assert 'key="total_usage_hours"' in defs, (
        "ha-bambulab no longer defines a 'total_usage_hours' sensor — update "
        "const.USAGE_HOURS_UNIQUE_SUFFIX."
    )
    # A meter must be monotonic for the usage-delta arithmetic to mean anything.
    assert "TOTAL_INCREASING" in defs, (
        "ha-bambulab's sensors no longer declare TOTAL_INCREASING — re-check that "
        "total_usage_hours is still a cumulative counter."
    )


def _real_printer_models() -> list[str]:
    """Every value of the real ``pybambu.const.Printers`` enum, parsed from source.

    Parsed rather than imported: the staged tree isn't an installable package, and a
    regex over one small enum block is cheaper than standing up an import path for it.
    """
    const_py = _BAMBU_SRC / "pybambu" / "const.py"
    assert const_py.is_file(), "ha-bambulab no longer ships pybambu/const.py"
    text = const_py.read_text(encoding="utf-8")
    block = re.search(r"class Printers\(StrEnum\):\n((?:\s+\w+ = .*\n)+)", text)
    assert block, "ha-bambulab no longer defines a Printers StrEnum"
    return re.findall(r'=\s*"([^"]+)"', block.group(1))


def test_every_real_printer_model_is_classified_by_the_catalog():
    """Guard the family map against Bambu Lab shipping a printer we've never heard of.

    An unclassified model is not broken — it falls back to the universal items and the
    user can pick the rest by hand — but it *is* a silent loss of the manufacturer's
    schedule for that printer. This turns that into a CI failure with a name attached,
    so a new model gets a family (or a deliberate ``FAMILY_UNKNOWN``) rather than
    drifting in unnoticed.
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    models = _real_printer_models()
    assert len(models) >= 10, f"suspiciously few models parsed: {models}"
    unclassified = [m for m in models if m not in catalog.MODEL_FAMILIES]
    assert not unclassified, (
        "ha-bambulab ships printer models the maintenance catalog has no opinion on: "
        f"{unclassified}. Add each to catalog.MODEL_FAMILIES — to its series' family if "
        "it shares that series' wiki maintenance page, or to FAMILY_UNKNOWN if it needs "
        "its own research first."
    )


def test_the_device_model_the_catalog_detects_from_is_still_the_device_type():
    """Guard the field the model detection reads.

    ``wiring.scan_printers`` reads the device registry's ``model`` and hands it to
    ``catalog.normalize_family``, which only works because ha-bambulab sets that field
    to the raw ``device_type``. If it starts writing a marketing name there instead
    ("X1 Carbon"), every printer would silently detect as unknown.
    """
    if not _BAMBU_SRC.is_dir():
        pytest.skip("ha-bambulab not staged (run ci/fetch-upstreams.sh first)")

    coordinator_py = _BAMBU_SRC / "coordinator.py"
    assert coordinator_py.is_file(), "ha-bambulab no longer has coordinator.py"
    text = coordinator_py.read_text(encoding="utf-8")
    assert 'device_type = self.config_entry.data["device_type"]' in text, (
        "ha-bambulab no longer reads device_type from its config entry."
    )
    assert "model=device_type," in text, (
        "ha-bambulab's printer DeviceInfo no longer sets model=device_type — the "
        "maintenance catalog's model detection reads that field."
    )


def test_available_then_installed_arms_then_clears_the_task(api):
    base = _count(api)

    # Firmware update becomes available → a triggered task is created, armed (on the list).
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))

    # Firmware installed (up to date) → the task records the completion and goes dormant.
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))


def test_available_again_rearms_without_duplicating(api):
    base = _count(api)
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))

    # Available again → re-armed (count back to +1, not +2 — same task reused).
    api.call_service("bambu_lab", "set_firmware_available", {"available": True})
    api.poll_state(TODO, str(base + 1))
    # Clean up so re-runs start from the same baseline.
    api.call_service("bambu_lab", "set_firmware_available", {"available": False})
    api.poll_state(TODO, str(base))


def _maintenance_task(api) -> dict | None:
    """The seeded maintenance task (Z-axis lead screws), or ``None``."""
    tasks = api.call_service_response("home_keeper", "list_tasks", {})["tasks"]
    for task in tasks:
        if "lead screws" in (task.get("name") or "").lower():
            return task
    return None


def _poll_maintenance(api, predicate, timeout: float = 40) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = _maintenance_task(api)
        if last is not None and predicate(last):
            return last
        time.sleep(1)
    raise AssertionError(f"maintenance task never satisfied predicate; last={last}")


def test_maintenance_catalog_task_arms_once_the_meter_advances(api):
    """The catalog's headline path: printer hours advance, a maintenance task comes due.

    The container's config entry is seeded with the catalog on and exactly one item
    enabled (``z_lead_screws``, target 5 h — see ``ha_config/.storage/core.config_entries``).

    Asserted against the task itself rather than the to-do count: the firmware tests in
    this file move that count around, and this test needs to be about one task.

    Note the deliberate two-step nudge. A usage task has no meter baseline until Home
    Keeper first evaluates the bound sensor, which happens on the next state change (or
    the 5-minute coordinator tick). So the first advance anchors the meter and the
    second one is what actually crosses the target. Nothing here is this glue's code:
    Home Keeper does the arming, which is exactly the division of labour the catalog is
    built on.
    """
    task = _maintenance_task(api)
    assert task is not None, "the seeded catalog item should have created a task"
    assert task["source"]["home_keeper_bambu_lab"]["item"] == "z_lead_screws"

    # Complete it if a previous run left it armed, so this test can be re-run against a
    # live container. Completing a usage task also re-anchors its baseline.
    if task.get("next_due"):
        api.call_service("home_keeper", "complete_task", {"task_id": task["id"]})
    task = _poll_maintenance(api, lambda t: not t.get("next_due"))

    # First nudge anchors the meter (if it wasn't already) and must not arm anything.
    api.call_service("bambu_lab", "advance_usage_hours", {"hours": 1})
    _poll_maintenance(
        api, lambda t: (t.get("sensor") or {}).get("baseline") is not None
    )
    time.sleep(3)
    assert not _maintenance_task(api).get("next_due"), (
        "one hour of use must not cross a five-hour target"
    )

    # Second nudge, well past the 5-hour target -> Home Keeper arms it.
    api.call_service("bambu_lab", "advance_usage_hours", {"hours": 25})
    armed = _poll_maintenance(api, lambda t: bool(t.get("next_due")))
    assert armed["recurrence_type"] == "sensor"

    # Put the task back to dormant before leaving. Not tidiness: the to-do entity's
    # count trails the task list by a coordinator tick, so an armed task left behind
    # makes the *next* run's firmware tests read a stale baseline and then watch the
    # count move under them. Leave the container as we found it.
    api.call_service("home_keeper", "complete_task", {"task_id": armed["id"]})
    _poll_maintenance(api, lambda t: not t.get("next_due"))
    api.poll_state(TODO, "0")
