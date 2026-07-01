# Changelog

All notable changes to the Home Keeper — Bambu Lab glue are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

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
