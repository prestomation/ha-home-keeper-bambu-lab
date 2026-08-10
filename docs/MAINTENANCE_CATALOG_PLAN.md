# The maintenance catalog: design and sources

> Companion to `custom_components/home_keeper_bambu_lab/catalog.py`. This is where the
> intervals come from, why they take the shape they do, and what was deliberately left
> out.

## Why the glue holds an opinion here

The firmware half of this integration invents nothing. The printer publishes an
`update` entity; the glue mirrors it into a Home Keeper `triggered` task and gets out of
the way. That is the ideal shape for a glue, and the README used to say maintenance
should wait until wear data was "modeled in the Bambu Lab integration itself".

That position was wrong, for two reasons.

**No such data is coming.** No Bambu Lab entity reports that the lead screws are dry.
There is nothing to mirror, and waiting for it means waiting forever.

**Users already pick a number themselves.** [`BambamNZ/maintenance-tracker`](https://github.com/BambamNZ/maintenance-tracker)
exists precisely because someone wanted *"P2S Nozzle Clean"* metered off a printer hours
sensor and was willing to choose the interval by hand. A good default beats a blank
field; a blank field just means everyone re-derives the same number from the same wiki.

So the glue ships the manufacturer's schedule, and makes every part of it editable.

## The shape: hours *and* calendar, not one or the other

Bambu's own guidance is written as a **duty cycle**. Two examples, verbatim:

> We recommend replacing the activated carbon air filter every three months if the
> printer is used for about 8 hours a day. If the printer is used as a production
> machine, we recommend changing the filter every month.
> — [X1 Maintenance Recommendation](https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance)

> High-frequency usage (average daily printing ≥ 5 hours): Perform a full XY-axis
> cleaning and lubrication once a month; perform a deep Z-axis maintenance every 3
> months. […] Low-frequency usage (average daily printing < 1 hour): Maintain XY-axis
> every 3 months; maintain Z-axis every 5 months.
> — [P2S Regular Cleaning and Maintenance](https://wiki.bambulab.com/en/p2s/maintenance/period-maintenance)

Neither is a date, and neither is purely a counter. They are "N hours, or M months,
whichever comes first" written out longhand, with the calendar figure tightening as the
machine runs more.

Home Keeper 0.12.0 added exactly that primitive: a usage task with a `sensor.also_every`
time backstop and `combinator: "any"`. Encoding Bambu's rule in it reproduces the rule's
own endpoints for free. The filter at 720 h / 3 months comes due monthly for a machine
running 24/7 and quarterly for a hobby printer, which is what the wiki says in prose.

## The catalog

Each row's hours figure is the wiki's duty-cycle rule turned into arithmetic; the
derivation is in a comment on the item in `catalog.py`.

| Key | Item | Hours | Calendar | On for | Source |
|---|---|---|---|---|---|
| `linear_rods` | Clean and oil the linear rods | 150 | 1 month | every printer | [P2S][p2s] (5 h/day × 30 d), [X1][x1] ("checked once a month") |
| `z_lead_screws` | Grease the Z-axis lead screws | 450 | 3 months | every printer | [X1][x1] ("greased every three months"), [P2S][p2s] (5 h/day × 90 d) |
| `carbon_filter` | Replace the activated carbon air filter | 720 | 3 months | X1, P1S, P2, H2 | [X1][x1] (8 h/day × 90 d; "every month" for a production machine falls out of the hours half) |
| `carbon_rods` | Clean the X-axis carbon rods | — | 1 month | X1, P1P, P1S | [X1][x1] ("checked once a month"; no lubricant, so no hours figure) |
| `rod_antirust` | Anti-rust treatment on the Y/Z rods | — | 3 months | X1, P1P, P1S | [X1][x1] ("anti-rust every three months") |
| `camera_lens` | Clean the camera lens | — | 6 months | every printer but the A1 | [P2S][p2s] ("clean the camera every 6 months"); the A1 has a camera but no published cadence |
| `extruder_gear` | Check and clean the extruder gear | — | 1 week | **nothing** | [X1][x1] ("once a week") |
| `toolhead_fans` | Check and clean the toolhead fans | — | 1 week | **nothing** | [X1][x1] ("checking the fans every week") |

[x1]: https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance
[p2s]: https://wiki.bambulab.com/en/p2s/maintenance/period-maintenance

The two weekly items ship **off** on every model. They are real recommendations, but a
weekly reminder per printer is a lot of noise unless the machine runs most days, and a
catalog that nags is a catalog people switch off entirely.

## The schedule is not the same for every printer

The first cut of this catalog applied all eight items to every printer, which is wrong
for half the range. An A1 is an open-frame bed-slinger: no enclosure, so no activated
carbon filter, and no X-axis carbon rods either. Telling its owner to service two parts
the machine does not have is worse than telling them nothing, because it teaches people
to ignore the list.

There is a subtler error in the same direction. `carbon_rods` says *"never grease them"*,
which is right for the X1 and P1's bare carbon rods — and exactly backwards for the P2S
and H2, whose X-axis **shafts are meant to be oiled**. Same axis, opposite instruction.

So each item carries per-family overrides (`catalog.ModelOverride`), layered
**item baseline → family override → the user's stored option**. An override can flip
`enabled`, retune `hours`/`interval`/`unit`, rewrite the `notes`, or cite a different
`source` — which is what lets one item cover both the "never grease" and the "apply oil"
case without forking it in two.

### Families

Bambu publishes one maintenance page per *series*, so families are the useful
granularity. `ha-bambulab` writes its raw `device_type` (a `pybambu.const.Printers`
value) to the device registry's `model`, and `catalog.normalize_family` maps it:

| Family | Models | Evidence |
|---|---|---|
| `X1` | X1, X1C, X1E | [X1 maintenance][x1]. X1E has no page of its own; same chassis. |
| `P1P` | P1P | [P1 series page][p1]. Open frame, so no chamber filter. |
| `P1S` | P1S | Same page, but the P1S is the enclosed variant and takes a filter. |
| `P2` | P2S, X2D | [P2S maintenance][p2s]; the two share an [air-filter guide][p2filter]. |
| `A1` | A1, A1MINI | [A1 maintenance][a1]. Dual Z lead screws; no published camera cadence. |
| `H2` | H2C, H2D, H2DPRO, H2S | [H2 maintenance][h2]. Only the H2D has a page; the rest are the same chassis. |
| `unknown` | A2L, anything Bambu ships next | No page found. |

[p1]: https://wiki.bambulab.com/en/p1/maintenance/p1p-maintenance
[a1]: https://wiki.bambulab.com/en/a1/maintenance/basic-maintenance
[h2]: https://wiki.bambulab.com/en/h2/maintenance/period-maintenance
[p2filter]: https://wiki.bambulab.com/en/p2s/maintenance/replace-air-filter

The P1P/P1S split is the one place a family is finer than a wiki page. The combined P1
page never mentions the activated carbon filter, but the P1S is the enclosed variant and
has one; rather than guess which way the page's silence cuts, the enclosed model gets the
filter and the open-frame one doesn't.

`tests/docker/test_end_to_end.py` asserts that **every** member of the real
`pybambu.const.Printers` enum appears in the family map. When Bambu ships a new printer,
that is a CI failure with the model's name in it, not a silent fallback.

### Detection only drives defaults

The model is never a gate. Three rules follow from that, and they are the whole design:

1. **Every item is always offered.** The options flow lists all eight for every printer,
   including one it does not recognise. The family decides which start ticked and what
   the intervals are pre-filled with, and nothing else.
2. **The user can overrule the detection.** The `model` step is pre-filled with what we
   read from the device and is a plain dropdown of the families plus *Other / not
   listed*. A printer that reports a `device_type` we have never seen is still one pick
   away from the right schedule.
3. **An unrecognised printer still gets the universal items.** `linear_rods`,
   `z_lead_screws` and `camera_lens` exist on everything Bambu makes, so those ship on
   for `unknown` too; the model-specific items ship off, because a reminder to service a
   part you do not have is the failure mode this section opens with.

### Options are per printer

Model gating is inherently per printer: an X1C and an A1 mini in one house need
different answers, which the first beta's flat `item_<key>_enabled` could not express.
Keys are now `printer_<serial>_model`, `printer_<serial>_item_<key>_enabled` and
`printer_<serial>_item_<key>_interval`.

The serial, not the `device_id`: it survives a device registry entry being recreated,
and it is already what `ha-bambulab` composes its unique_ids from, so the glue derives it
without another lookup. The flat `0.2.0b1` keys are still read as a fallback when no
per-printer key exists, so a preview tester's answers carry over.

**Changing the model discards that printer's stored item answers.** They were answers
about a different machine, so "actually it's an A1" re-defaults the whole list rather
than keeping the X1's ticks. Keeping the model keeps the answers.

## What's deliberately missing

**The nozzle.** The obvious first item, and the one the third-party integration that
prompted this work was built for. Bambu gives no hours figure: the H2D wiki says to
clean the nozzle *"every 5 spools"* (2 with carbon fibre), and the X1/P1 pages say only
"if the nozzle surface is dirty or there is under-extrusion". A spool is not a sensor,
and hours-per-spool varies by an order of magnitude with part geometry. Any number here
would be invented, so there isn't one. The README points people at creating their own
usage task instead, which the 0.12.0 form makes a one-minute job.

**The filament cutter blade.** Same reason: *"every 3–5 rolls"* for regular filament,
*"1–2 rolls"* for abrasives.

If Bambu ever publishes an hours-based figure for either, adding a row to `CATALOG` is
the whole change.

## Implementation notes

**Discovery** keys off the *firmware* entity, not the usage sensor
(`wiring.scan_printers`, shared with the options flow so the picker and the reconcile
see the same fleet). Every supported printer has the firmware entity; a model that
doesn't report `info.usage_hours` still gets its calendar-based items, just without the
hours half. An hours item on such a printer degrades to a plain recurring task rather
than being dropped, on the grounds that a task firing a little early beats a service
nobody mentions.

**Convergence** happens in the existing reconcile (startup, entity-registry change,
options change), because unlike firmware there is no state to mirror: nothing else can
create, retune, or remove these tasks. Home Keeper's own watcher does the arming from
then on, which is the whole point of pushing a `sensor` task rather than a `triggered`
one — the glue never has to know when the printer crossed a threshold.

**Ownership.** `managed_by` marks the tasks ours and deletion-protected, with
`locked_fields: ["name", "recurrence_type", "device_id"]`. Two deliberate omissions:

- **`sensor` is not locked**, so the panel's edit form can retune the interval. (A
  reconcile will pull it back to the configured value, so the options flow is the
  durable place for an override; the unlocked field is for a quick experiment.)
- **`completion_blocked` is not set.** The firmware mirror uses it because the task
  clears itself. Here a human does the work, so the **Done** button must be live and the
  completion recorded.

**Namespacing.** Both planners key off `source[<domain>].item`. A firmware task created
before the catalog existed has no `item`, and `logic.task_item()` reads a missing key as
`"firmware"`, so upgrading doesn't orphan or duplicate anything.

**Baseline safety.** `logic.catalog_task_drift` compares the sensor binding *excluding*
`baseline`. That value is Home Keeper's accumulated usage, and a reconcile must never
reset it.

**Forward/backward compatibility.** `also_every` / `unit` / `combinator` need Home
Keeper 0.12.0. An older install's `normalize_sensor` builds its result from known keys
only, so it silently drops them and the task still works as a plain meter. That's why
the glue sends them unconditionally instead of version-gating.
