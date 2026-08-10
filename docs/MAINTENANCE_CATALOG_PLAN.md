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

| Key | Item | Hours | Calendar | Default | Source |
|---|---|---|---|---|---|
| `linear_rods` | Clean and oil the Y/Z linear rods | 150 | 1 month | on | [P2S][p2s] (5 h/day × 30 d), [X1][x1] ("checked once a month") |
| `z_lead_screws` | Grease the Z-axis lead screws | 450 | 3 months | on | [X1][x1] ("greased every three months"), [P2S][p2s] (5 h/day × 90 d) |
| `carbon_filter` | Replace the activated carbon air filter | 720 | 3 months | on | [X1][x1] (8 h/day × 90 d; "every month" for a production machine falls out of the hours half) |
| `carbon_rods` | Clean the X-axis carbon rods | — | 1 month | on | [X1][x1] ("checked once a month"; no lubricant, so no hours figure) |
| `rod_antirust` | Anti-rust treatment on the Y/Z rods | — | 3 months | on | [X1][x1] ("anti-rust every three months") |
| `camera_lens` | Clean the camera lens | — | 6 months | on | [P2S][p2s] ("clean the camera every 6 months") |
| `extruder_gear` | Check and clean the extruder gear | — | 1 week | **off** | [X1][x1] ("once a week") |
| `toolhead_fans` | Check and clean the toolhead fans | — | 1 week | **off** | [X1][x1] ("checking the fans every week") |

[x1]: https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance
[p2s]: https://wiki.bambulab.com/en/p2s/maintenance/period-maintenance

The two weekly items ship **off**. They are real recommendations, but a weekly reminder
per printer is a lot of noise unless the machine runs most days, and a catalog that
nags is a catalog people switch off entirely.

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
(`wiring._scan_printers`). Every supported printer has the firmware entity; a model that
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
