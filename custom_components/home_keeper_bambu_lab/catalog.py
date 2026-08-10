"""The printer-maintenance catalog: what Bambu Lab says to do, and how often.

The firmware half of this glue is a pure mirror — it invents nothing, because the
printer already tells us whether an update is waiting. Maintenance has no such signal:
no Bambu Lab entity reports "the lead screws are dry". What the *manufacturer* does
publish is a maintenance schedule, so this module encodes that schedule and the glue
turns each item into a Home Keeper task bound to the printer's cumulative usage-hours
sensor.

**Every interval here is sourced from wiki.bambulab.com** (``source`` on each item and
on each per-family override); none is invented. Where Bambu gives a duty-cycle rule —
*"every three months if the printer is used about 8 hours a day"* — that is exactly Home
Keeper's usage-with-a-time-backstop shape, and the ``hours`` figure is that rule
arithmetic made explicit. The derivation is recorded per item so a reader can check it.

**The schedule is not the same for every printer.** An A1 is an open-frame bed-slinger
with no chamber filter and no X-axis carbon rods; a P2S has oiled X-axis shafts where an
X1 has carbon rods that must never be greased. So each item carries per-family overrides
(see :data:`MODEL_FAMILIES`), and the glue reads the printer's model from the device
registry to pick them.

Model detection only drives **defaults**. Every item is always offered in the options
flow, whatever the printer, and the user can overrule the detected model outright —
otherwise a printer Bambu ships next year would be unconfigurable. An unrecognised model
falls back to each item's own ``default_enabled``, which is true only for the items every
FDM printer has (rods, lead screws).

Where Bambu's interval is in **spools of filament** (the cutter blade, nozzle cleaning)
there is no matching sensor and no honest conversion, so those items are deliberately
**absent** rather than guessed at. See ``docs/MAINTENANCE_CATALOG_PLAN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bambu Lab wiki pages the intervals below are taken from.
WIKI_X1 = "https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance"
WIKI_P1 = "https://wiki.bambulab.com/en/p1/maintenance/p1p-maintenance"
WIKI_P2S = "https://wiki.bambulab.com/en/p2s/maintenance/period-maintenance"
WIKI_A1 = "https://wiki.bambulab.com/en/a1/maintenance/basic-maintenance"
WIKI_H2 = "https://wiki.bambulab.com/en/h2/maintenance/period-maintenance"
WIKI_FILTER = "https://wiki.bambulab.com/en/x1/maintenance/replace-carbon-filter"

# ── model families ───────────────────────────────────────────────────────────
# Bambu publishes one maintenance page per *series*, so families are the useful
# granularity — except P1P/P1S, which share a page but not a chamber: the P1S is
# enclosed and takes an activated carbon filter, the P1P is open-frame and doesn't.
FAMILY_X1 = "X1"
FAMILY_P1P = "P1P"
FAMILY_P1S = "P1S"
FAMILY_P2 = "P2"
FAMILY_A1 = "A1"
FAMILY_H2 = "H2"
FAMILY_UNKNOWN = "unknown"

FAMILIES: tuple[str, ...] = (
    FAMILY_X1,
    FAMILY_P1P,
    FAMILY_P1S,
    FAMILY_P2,
    FAMILY_A1,
    FAMILY_H2,
    FAMILY_UNKNOWN,
)

# Human labels for the options flow's model picker.
FAMILY_LABELS: dict[str, str] = {
    FAMILY_X1: "X1 series (X1, X1C, X1E)",
    FAMILY_P1P: "P1P (open frame)",
    FAMILY_P1S: "P1S (enclosed)",
    FAMILY_P2: "P2 series (P2S, X2D)",
    FAMILY_A1: "A1 series (A1, A1 mini)",
    FAMILY_H2: "H2 series (H2C, H2D, H2D Pro, H2S)",
    FAMILY_UNKNOWN: "Other / not listed",
}

# ha-bambulab's ``device_type`` (which it also sets as the device registry ``model``)
# mapped to a family. The values are ``pybambu.const.Printers``; a docker contract test
# asserts this covers every member of that enum, so a printer Bambu adds later shows up
# as a CI failure rather than silently landing in FAMILY_UNKNOWN.
#
# X1E and H2DPRO have no maintenance page of their own; they are grouped with their
# series on the strength of being the same chassis. A2L likewise has no page and no
# obvious sibling, so it stays unknown rather than being guessed into a family.
MODEL_FAMILIES: dict[str, str] = {
    "X1": FAMILY_X1,
    "X1C": FAMILY_X1,
    "X1E": FAMILY_X1,
    "P1P": FAMILY_P1P,
    "P1S": FAMILY_P1S,
    # The P2S/X2D share an air-filter replacement guide, which is the evidence for
    # grouping them: https://wiki.bambulab.com/en/p2s/maintenance/replace-air-filter
    "P2S": FAMILY_P2,
    "X2D": FAMILY_P2,
    "A1": FAMILY_A1,
    "A1MINI": FAMILY_A1,
    "H2C": FAMILY_H2,
    "H2D": FAMILY_H2,
    "H2DPRO": FAMILY_H2,
    "H2S": FAMILY_H2,
    "A2L": FAMILY_UNKNOWN,
}


def normalize_family(model: Any) -> str:
    """Map a printer's reported model to a maintenance family.

    *model* is the device registry's ``model`` field, which ha-bambulab sets to its
    ``device_type``. Anything unrecognised (including ``None``) is FAMILY_UNKNOWN, which
    is a usable state rather than an error: the user picks the items by hand.
    """
    key = str(model or "").strip().upper().replace(" ", "").replace("-", "")
    return MODEL_FAMILIES.get(key, FAMILY_UNKNOWN)


@dataclass(frozen=True)
class ModelOverride:
    """How one family differs from an item's baseline. ``None`` means "inherit"."""

    enabled: bool | None = None
    hours: int | None = None
    interval: int | None = None
    unit: str | None = None
    notes: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class CatalogItem:
    """One maintenance item.

    ``hours`` set  → a Home Keeper **usage** task bound to the printer's usage-hours
    sensor, with ``interval``/``unit`` as its *time backstop* (whichever comes first).
    ``hours`` unset → a plain **floating** task on ``interval``/``unit`` alone, for the
    items Bambu schedules purely by the calendar.

    ``default_enabled`` is the answer for a printer we don't recognise, so it is true
    only for the parts every FDM printer has. Model-specific items switch themselves on
    through ``by_family``.
    """

    key: str
    name: str
    notes: str
    interval: int
    unit: str
    source: str
    hours: int | None = None
    default_enabled: bool = False
    by_family: dict[str, ModelOverride] = field(default_factory=dict)

    @property
    def is_usage(self) -> bool:
        """Whether this item is metered against the printer's usage hours."""
        return self.hours is not None


@dataclass(frozen=True)
class ResolvedItem:
    """An item as it applies to one printer, after family and user overrides."""

    item: CatalogItem
    enabled: bool
    interval: int
    unit: str
    notes: str
    hours: int | None

    @property
    def is_usage(self) -> bool:
        """Whether this resolves to a metered task (the family may have removed hours)."""
        return self.hours is not None


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem(
        key="linear_rods",
        name="Clean and oil the linear rods",
        notes=(
            "Wipe the rods down with alcohol and re-oil them. Bambu Lab suggests "
            "checking monthly, or every 5 spools if you print ABS or ASA."
        ),
        # X1/P1: "checked once a month for any dust and particle buildup". P2S states
        # the same job as "once a month" at high-frequency use (≥ 5 h/day), i.e.
        # 5 h/day × 30 days = 150 h — so 150 hours *or* a month, whichever lands first.
        hours=150,
        interval=1,
        unit="months",
        source=WIKI_P2S,
        # Every Bambu printer moves on rods or shafts that want cleaning, so this is one
        # of the two items an unrecognised printer still gets by default.
        default_enabled=True,
        by_family={
            FAMILY_P2: ModelOverride(
                notes=(
                    "Wipe the X and Y shafts with alcohol, then apply lubricating oil "
                    "(1–2 drops every 5 cm). Never grease them."
                ),
                source=WIKI_P2S,
            ),
            FAMILY_H2: ModelOverride(source=WIKI_H2),
            FAMILY_A1: ModelOverride(source=WIKI_A1),
        },
    ),
    CatalogItem(
        key="z_lead_screws",
        name="Grease the Z-axis lead screws",
        notes=(
            "Clean the lead screws and re-grease them, then cycle the bed "
            "top to bottom a few times to spread it evenly."
        ),
        # X1/P1: "checked and greased every three months". P2S puts a deep Z-axis
        # service every 3 months at ≥ 5 h/day, i.e. 5 h/day × 90 days = 450 h.
        hours=450,
        interval=3,
        unit="months",
        source=WIKI_X1,
        default_enabled=True,
        by_family={
            # The A1 drives its Z with two lead screws rather than three, on the same
            # quarterly cadence.
            FAMILY_A1: ModelOverride(
                notes=(
                    "The A1 uses a dual lead screw structure. Clean both screws and "
                    "re-grease them."
                ),
                source=WIKI_A1,
            ),
            FAMILY_P2: ModelOverride(source=WIKI_P2S),
            FAMILY_H2: ModelOverride(source=WIKI_H2),
        },
    ),
    CatalogItem(
        key="carbon_filter",
        name="Replace the activated carbon air filter",
        notes=(
            "Bambu Lab schedules this at about three months of eight-hour days, and "
            "rates the filter itself at 1440 hours of printing. A printer running as a "
            "production machine gets through one far faster."
        ),
        # X1: "every three months if the printer is used for about 8 hours a day. If
        # the printer is used as a production machine, change the filter every month."
        # Both endpoints of that rule land on the same number: 8 × 90 = 720 h, and
        # 24 × 30 = 720 h. The dedicated filter page separately rates the filter's
        # *working life* at 1440 h of cumulative printing — twice the schedule, which is
        # normal for a maintenance recommendation. We ship the schedule and mention the
        # rated life in the notes so anyone who wants to run it to the limit can.
        hours=720,
        interval=3,
        unit="months",
        source=WIKI_X1,
        # Only enclosed printers have a chamber filter, so this is off unless the family
        # says otherwise — including for an unrecognised printer.
        by_family={
            FAMILY_X1: ModelOverride(enabled=True),
            FAMILY_P1S: ModelOverride(enabled=True),
            FAMILY_P2: ModelOverride(enabled=True, source=WIKI_FILTER),
            FAMILY_H2: ModelOverride(enabled=True, source=WIKI_H2),
        },
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
        # the rods carry no lubricant, so this stays purely calendar-based. Only the
        # X1 and P1 series use carbon rods on the X axis; the P2/H2 use oiled shafts
        # (covered by linear_rods) and the A1 is a bed-slinger with neither.
        interval=1,
        unit="months",
        source=WIKI_X1,
        by_family={
            FAMILY_X1: ModelOverride(enabled=True),
            FAMILY_P1P: ModelOverride(enabled=True, source=WIKI_P1),
            FAMILY_P1S: ModelOverride(enabled=True, source=WIKI_P1),
        },
    ),
    CatalogItem(
        key="rod_antirust",
        name="Anti-rust treatment on the Y/Z rods",
        notes="Bambu Lab suggests an anti-rust pass on the linear rods quarterly.",
        # X1/P1: "Y-axis and Z-axis rods should be anti-rust every three months."
        # Not mentioned on the A1, P2S or H2 pages, so it stays off for those.
        interval=3,
        unit="months",
        source=WIKI_X1,
        by_family={
            FAMILY_X1: ModelOverride(enabled=True),
            FAMILY_P1P: ModelOverride(enabled=True, source=WIKI_P1),
            FAMILY_P1S: ModelOverride(enabled=True, source=WIKI_P1),
        },
    ),
    CatalogItem(
        key="camera_lens",
        name="Clean the camera lens",
        notes=(
            "Particles settle on the lens and blur the remote view. Clean it far "
            "more often if you print ABS."
        ),
        # P2S: "Clean the camera every 6 months." X1/P1 say to clean it when the video
        # is blurry, and weekly when printing ABS. The A1 series ships without a camera
        # (it is an optional accessory), so it is off there.
        interval=6,
        unit="months",
        source=WIKI_P2S,
        default_enabled=True,
        by_family={FAMILY_A1: ModelOverride(enabled=False)},
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
        # week." Weekly is genuinely noisy for a hobby printer, so it ships off for
        # every family rather than being model-gated.
        interval=1,
        unit="weeks",
        source=WIKI_X1,
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
    ),
)

BY_KEY: dict[str, CatalogItem] = {item.key: item for item in CATALOG}


# ── config-entry option keys ─────────────────────────────────────────────────
# Keyed on the printer's **serial**, not its device_id: the serial survives a device
# registry entry being recreated, and it is already what ha-bambulab composes its
# unique_ids from, so the glue can derive it without another lookup.
def option_key_model(serial: str) -> str:
    """Config-entry option key for a printer's user-chosen family override."""
    return f"printer_{serial}_model"


def option_key_enabled(serial: str, key: str) -> str:
    """Config-entry option key for "is this catalog item on for this printer?"."""
    return f"printer_{serial}_item_{key}_enabled"


def option_key_interval(serial: str, key: str) -> str:
    """Config-entry option key for this printer's interval override.

    For a usage item this overrides the **hours** target; for a calendar-only item it
    overrides the number of ``unit``s. ``0`` (or absent) means "use the default".
    """
    return f"printer_{serial}_item_{key}_interval"


# The 0.2.0b1 preview shipped one flat set of options for every printer. Read those as a
# fallback so a preview tester's choices survive the move to per-printer keys.
def _legacy_key_enabled(key: str) -> str:
    return f"item_{key}_enabled"


def _legacy_key_interval(key: str) -> str:
    return f"item_{key}_interval"


def resolved_family(serial: str, detected: Any, options: dict[str, Any] | None) -> str:
    """The family in force for a printer: the user's override, else the detection."""
    chosen = str((options or {}).get(option_key_model(serial)) or "").strip()
    if chosen in FAMILIES:
        return chosen
    return normalize_family(detected)


def resolve(
    item: CatalogItem,
    family: str,
    serial: str = "",
    options: dict[str, Any] | None = None,
) -> ResolvedItem:
    """Apply the family override then the user's stored options to *item*.

    Layered lowest to highest: the item's own baseline, the family's override, the
    user's per-printer option. A non-positive or unparseable interval override falls
    back to the resolved default so a blanked-out field can't produce an invalid task.
    """
    options = options or {}
    override = item.by_family.get(family) or ModelOverride()

    enabled = item.default_enabled if override.enabled is None else override.enabled
    hours = item.hours if override.hours is None else override.hours
    interval = item.interval if override.interval is None else override.interval
    unit = item.unit if override.unit is None else override.unit
    notes = item.notes if override.notes is None else override.notes

    if serial:
        enabled_key = option_key_enabled(serial, item.key)
        if enabled_key in options:
            enabled = bool(options[enabled_key])
        elif _legacy_key_enabled(item.key) in options:
            enabled = bool(options[_legacy_key_enabled(item.key)])

        raw = options.get(option_key_interval(serial, item.key))
        if raw is None:
            raw = options.get(_legacy_key_interval(item.key))
        try:
            override_interval = int(raw or 0)
        except (TypeError, ValueError):
            override_interval = 0
        if override_interval > 0:
            if hours is not None:
                hours = override_interval
            else:
                interval = override_interval

    return ResolvedItem(
        item=item,
        enabled=enabled,
        interval=interval,
        unit=unit,
        notes=notes,
        hours=hours,
    )


def resolve_all(
    family: str, serial: str = "", options: dict[str, Any] | None = None
) -> list[ResolvedItem]:
    """Every catalog item resolved for one printer, in catalog order."""
    return [resolve(item, family, serial, options) for item in CATALOG]
