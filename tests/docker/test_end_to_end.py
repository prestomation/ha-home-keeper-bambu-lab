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

from pathlib import Path

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
