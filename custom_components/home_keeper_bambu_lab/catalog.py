"""The printer-maintenance catalog: what Bambu Lab says to do, and how often.

The firmware half of this glue is a pure mirror — it invents nothing, because the
printer already tells us whether an update is waiting. Maintenance has no such signal:
no Bambu Lab entity reports "the lead screws are dry". What the *manufacturer* does
publish is a maintenance schedule, so this module encodes that schedule and the glue
turns each item into a Home Keeper task bound to the printer's cumulative usage-hours
sensor.

**Every interval here is sourced from wiki.bambulab.com** (``source`` on each item);
none is invented. Where Bambu gives a duty-cycle rule — *"every three months if the
printer is used about 8 hours a day; monthly for a production machine"* — that is
exactly Home Keeper's usage-with-a-time-backstop shape, and the ``hours`` figure is
that rule arithmetic made explicit (8 h/day × 90 days = 720 h). The derivation is
recorded per item so a reader can check it.

Where Bambu's interval is in **spools of filament** (the cutter blade, nozzle cleaning)
there is no matching sensor and no honest conversion, so those items are deliberately
**absent** rather than guessed at. See ``docs/MAINTENANCE_CATALOG_PLAN.md``.

Every item is individually enableable and every interval is user-adjustable — these are
defaults, not decrees. The glue leaves the ``sensor`` binding unlocked precisely so the
panel's edit form can retune it, and Home Keeper preserves accumulated usage when only
the target changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Bambu Lab wiki pages the intervals below are taken from.
WIKI_X1 = "https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance"
WIKI_P1 = "https://wiki.bambulab.com/en/p1/maintenance/p1p-maintenance"
WIKI_P2S = "https://wiki.bambulab.com/en/p2s/maintenance/period-maintenance"


@dataclass(frozen=True)
class CatalogItem:
    """One maintenance item.

    ``hours`` set  → a Home Keeper **usage** task bound to the printer's usage-hours
    sensor, with ``interval``/``unit`` as its *time backstop* (whichever comes first).
    ``hours`` unset → a plain **floating** task on ``interval``/``unit`` alone, for the
    items Bambu schedules purely by the calendar.
    """

    key: str
    name: str
    notes: str
    interval: int
    unit: str
    source: str
    hours: int | None = None
    default_enabled: bool = True

    @property
    def is_usage(self) -> bool:
        """Whether this item is metered against the printer's usage hours."""
        return self.hours is not None


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem(
        key="linear_rods",
        name="Clean and oil the Y/Z linear rods",
        notes=(
            "Wipe the rods down and re-oil them. Bambu Lab suggests checking monthly, "
            "or every 5 spools if you print ABS or ASA."
        ),
        # X1/P1: "checked once a month for any dust and particle buildup". P2S states
        # the same job as "once a month" at high-frequency use (≥ 5 h/day), i.e.
        # 5 h/day × 30 days = 150 h — so 150 hours *or* a month, whichever lands first.
        hours=150,
        interval=1,
        unit="months",
        source=WIKI_P2S,
    ),
    CatalogItem(
        key="z_lead_screws",
        name="Grease the Z-axis lead screws",
        notes=(
            "Clean the three lead screws and re-grease them, then cycle the bed "
            "top to bottom a few times to spread it evenly."
        ),
        # X1/P1: "checked and greased every three months". P2S puts a deep Z-axis
        # service every 3 months at ≥ 5 h/day, i.e. 5 h/day × 90 days = 450 h.
        hours=450,
        interval=3,
        unit="months",
        source=WIKI_X1,
    ),
    CatalogItem(
        key="carbon_filter",
        name="Replace the activated carbon air filter",
        notes=(
            "Bambu Lab rates the filter at about three months of eight-hour days — "
            "a printer running as a production machine gets through one far faster."
        ),
        # X1: "every three months if the printer is used for about 8 hours a day. If
        # the printer is used as a production machine, change the filter every month."
        # 8 h/day × 90 days = 720 h, which makes the production-machine case fall out
        # of the hours half automatically instead of needing its own rule.
        hours=720,
        interval=3,
        unit="months",
        source=WIKI_X1,
    ),
    CatalogItem(
        key="carbon_rods",
        name="Clean the X-axis carbon rods",
        notes=(
            "Wipe the rods with isopropyl alcohol. Never grease them — grease "
            "collects debris and causes premature wear. Every 5 spools if you print "
            "ABS or ASA."
        ),
        # X1/P1: "should be checked once a month". No usage figure is published, and
        # the rods carry no lubricant, so this stays purely calendar-based.
        interval=1,
        unit="months",
        source=WIKI_X1,
    ),
    CatalogItem(
        key="rod_antirust",
        name="Anti-rust treatment on the Y/Z rods",
        notes="Bambu Lab suggests an anti-rust pass on the linear rods quarterly.",
        # X1/P1: "Y-axis and Z-axis rods should be anti-rust every three months."
        interval=3,
        unit="months",
        source=WIKI_X1,
    ),
    CatalogItem(
        key="camera_lens",
        name="Clean the camera lens",
        notes=(
            "Particles settle on the lens and blur the remote view. Clean it far "
            "more often if you print ABS."
        ),
        # P2S: "Clean the camera every 6 months."
        interval=6,
        unit="months",
        source=WIKI_P2S,
    ),
    CatalogItem(
        key="extruder_gear",
        name="Check and clean the extruder gear",
        notes=(
            "Look for dust on the gear and for wear on its teeth. Off by default — "
            "Bambu Lab suggests weekly, which is a lot of reminders unless the "
            "printer runs most days."
        ),
        # X1: "We recommend checking and cleaning the extruder gear assembly once a
        # week." Weekly is genuinely noisy for a hobby printer, so it ships off.
        interval=1,
        unit="weeks",
        source=WIKI_X1,
        default_enabled=False,
    ),
    CatalogItem(
        key="toolhead_fans",
        name="Check and clean the toolhead fans",
        notes=(
            "Blow the dust off the part-cooling and hotend fans. Off by default for "
            "the same reason as the extruder gear check."
        ),
        # X1/P1: "We recommend checking the fans every week."
        interval=1,
        unit="weeks",
        source=WIKI_X1,
        default_enabled=False,
    ),
)

BY_KEY: dict[str, CatalogItem] = {item.key: item for item in CATALOG}


def option_key_enabled(key: str) -> str:
    """Config-entry option key for "is this catalog item on?"."""
    return f"item_{key}_enabled"


def option_key_interval(key: str) -> str:
    """Config-entry option key for the user's interval override.

    For a usage item this overrides the **hours** target; for a calendar-only item it
    overrides the number of ``unit``s. ``0`` (or absent) means "use the default".
    """
    return f"item_{key}_interval"


def resolve(item: CatalogItem, options: dict[str, Any] | None) -> tuple[bool, int]:
    """Return ``(enabled, interval)`` for *item* under the entry's *options*.

    The interval is the hours target for a usage item, or the calendar count for a
    time-only one. A non-positive or unparseable override falls back to the default so
    a blanked-out field can't produce an invalid task.
    """
    options = options or {}
    enabled = bool(options.get(option_key_enabled(item.key), item.default_enabled))
    default = item.hours if item.is_usage else item.interval
    try:
        override = int(options.get(option_key_interval(item.key)) or 0)
    except (TypeError, ValueError):
        override = 0
    return enabled, override if override > 0 else int(default)
