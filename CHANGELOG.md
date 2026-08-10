# Changelog

All notable changes to the Home Keeper — Bambu Lab glue are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [0.2.0b1]

### Added

- **Optional printer maintenance tasks, following Bambu Lab's own published schedule.**
  Turn on **Also create printer maintenance tasks** in the options and the glue creates a
  Home Keeper task per item per printer: lead-screw greasing, rod cleaning and anti-rust,
  the activated carbon filter, the camera lens, and (off by default, because weekly is a
  lot) the extruder gear and toolhead fans.

  The items Bambu measures in hours are metered against the printer's
  `total_usage_hours` sensor with the calendar figure as a backstop, so whichever lands
  first wins. That is Bambu's own guidance, not an invention: the X1 wiki rates the air
  filter at *"every three months if the printer is used for about 8 hours a day"* and
  *"every month"* for a production machine, which is 720 printer hours either way. A
  printer that runs constantly comes due on hours; one that mostly rests comes due on the
  calendar.

  Every interval is a default you can change, in the options or on the task itself, and
  every item can be switched off. The nozzle and the cutter blade are deliberately absent:
  Bambu publishes those in spools of filament, which no sensor exposes, so there is no
  honest number to ship. See the README and `docs/MAINTENANCE_CATALOG_PLAN.md`.

  Needs Home Keeper 0.12.0 for the hours-or-calendar behaviour. Against an older version
  the tasks still work as plain meters.

- **The maintenance items are enabled per printer model.** Bambu Lab's schedule is not
  the same for every printer, so the glue reads each printer's model from the Bambu Lab
  integration and turns on the items that apply to it. An A1 is open-frame with no
  X-axis carbon rods, so it no longer gets an air-filter or carbon-rod task, while an X1C
  in the same house still gets both. The X1's *"never grease the carbon rods"* note is
  likewise replaced with *"apply lubricating oil"* on the P2S and H2, whose X-axis shafts
  are meant to be oiled.

  Detection only decides the defaults. Every item is listed for every printer, and the
  detected model is a dropdown you can overrule, so a printer we do not recognise —
  including whatever Bambu ships next — is still fully configurable: pick **Other / not
  listed** and tick what your machine has. An unrecognised printer starts with the items
  every Bambu Lab printer shares and nothing model-specific. Correcting a model
  re-applies that model's defaults rather than keeping answers you gave about a
  different machine.

  Turning maintenance on now walks you through your printers one at a time: pick a
  printer (skipped if you only have one), confirm or correct its model, then tick its
  items. Options are stored per printer, keyed on the printer's serial; the flat keys
  from the `0.2.0.dev6` preview are still read as a fallback, so preview testers keep
  their answers.

### Fixed

- **A single firmware install no longer records two completions.** A printer's
  update entity can present more than one `on`→`off` edge for one install — the printer
  reboots and reconnects, and a stale/retained MQTT message (or a staged,
  version-by-version update) can briefly re-report the update as available after the task
  already cleared. The glue re-armed on that flap and cleared again, logging a phantom
  second completion. For a short window after a clear it now ignores a re-arm that merely
  re-offers the *same* firmware the printer just installed (a genuinely newer firmware
  still re-arms immediately), so one install records one completion.
- **A firmware task's note no longer stays frozen at "… available" after the update.**
  The note was written only when the task was created and never refreshed, so a task that
  had already cleared kept advertising the (now-installed) update — e.g. *"Firmware
  01.08.01.00 available · installed 01.06.00.00"*. It now reads *"Firmware up to date …"*
  once the printer reports it's current, and is kept in step (alongside the version chip)
  when a newer firmware supersedes the one the task was created for.

## [0.1.0b2] - 2026-07-01

### Fixed

- **Firmware tasks now appear even when the Bambu Lab "Firmware update" option is off.**
  The Bambu Lab integration exposes firmware availability as *either* an `update` entity
  (option on) *or* a `binary_sensor` with device_class `update` (option off — the
  default). The glue only watched the `update` entity, so on a default Bambu Lab setup no
  task was ever created. It now mirrors *either* firmware entity (both are keyed
  `{serial}_firmware_update` and read `on` when an update is available).
- **Options dialog no longer shows a translation error.** The "Task name template" field
  description embedded a literal `{printer_name}`, which Home Assistant's frontend parsed
  as a missing translation placeholder (`formatjs … MISSING_VALUE`). The description was
  reworded to describe the placeholder without literal braces.

## [0.1.0b1] - 2026-07-01

First beta. Surfaces [Bambu Lab](https://github.com/greghesp/ha-bambulab) printer firmware
updates as [Home Keeper](https://github.com/prestomation/ha-home-keeper) `triggered` tasks.

### Added

- **Firmware update → a read-only Home Keeper task.** When a Bambu Lab printer's firmware
  `update` entity reports an update is available, the glue creates a Home Keeper **"Update
  firmware: …"** task, armed (due-now), attached to the printer's device with a *"Managed
  by Bambu Lab"* chip, a version chip, and a *Release notes* link when the entity provides
  a URL. When the firmware is installed (the entity returns to up-to-date) the task records
  the completion and goes dormant (into the **Monitored** section). It's a **read-only
  mirror** — carried via `managed_by.completion_blocked`, so it can't be checked off by
  hand and clears only when the printer reports it's current. An offline printer
  (`unavailable`/`unknown`) never clears the task, so no phantom install is recorded.
  Stateless and self-healing: state is re-derived from `home_keeper.list_tasks` + Bambu
  Lab's registry entities and reconciled on Home Assistant start; every cross-integration
  call is `has_service`-guarded. Detection is entity-state-driven (Bambu Lab exposes no bus
  events for firmware). Option: task name template.
- **Announces itself to Home Keeper's companion discovery.** Registers with Home Keeper
  (via its `register_companion` service) so it appears as a **connected** companion under
  Home Keeper's **Settings → Companions**, with a *Configure* button that opens this glue's
  settings. Best-effort and re-announced on Home Keeper reload; a no-op on older Home
  Keeper versions without companion discovery.

> **Beta note.** Requires Home Keeper with the `triggered` task type and the
> `managed_by.completion_blocked` read-only-mirror flag. This beta tracks Home Keeper
> `main`; it's offered only to HACS users who enabled "Show beta versions".
