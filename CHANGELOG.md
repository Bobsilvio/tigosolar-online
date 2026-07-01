# Changelog

## [2.0.2] - 2026-07-01

### Fixed
- Per-panel `Pin`/`Vin`/`Iin` (and `system.power_w`) stuck `unavailable` on the
  v4 API for Premium / `sensors=true` accounts, while per-panel energy worked
  ([#7](https://github.com/Bobsilvio/tigosolar-online/issues/7)).
  Root cause: `_apply_summary` selected a single "newest row where *any* column
  is non-dash", but the trailing CCA/aggregate columns are non-dash in every
  minute of the day, so selection always walked to the empty end-of-day row and
  every panel collapsed to `null`. This is the same class of bug the 2.0.1 fix
  addressed for the v3 CSV path, left unfixed on v4. Fixed by scanning per
  panel column for its latest non-dash value, ignoring the aggregate columns.

### Added
- Verbose-gated diagnostics for the summary telemetry layout (`SUMMARY-SHAPE`,
  `EQUIPMENT-ORDER`) to correlate `d[]` columns with the equipment topology.

## [2.0.1] - 2026-06-13

### Fixed
- Panel sensors (`Pin`, `Vin`, `Iin`, `RSSI`) permanently `unknown` even with active production ([#6](https://github.com/Bobsilvio/tigosolar-online/issues/6)).  
  Root cause: `parse_param_csv` selected the last row containing *any* valid value. With `sensors=true` the CCA sensor column always carries fresher data than panels (~15 min cloud delay), so that row contained only the sensor value — no panels. Fix collects the latest valid value **per column** by scanning rows in reverse.

## [2.0.0] - 2026-05-16

### Added
- Tigo v4 API client (`api/v4.py`) with automatic fallback to v3.
- `TigoDataUpdateCoordinator` — resilient coordinator with retry logic and connectivity tracking.
- `topology.py` — full equipment topology (inverter → string → panel) with drift guard.
- `binary_sensor.py` — cloud connectivity sensor.
- `diagnostics.py` — HA diagnostics support.
- `strings.json` — UI translations.
- Config flow: validation, options UI, re-auth flow.
- Capability discovery and verbose logging option.
- Automatic migration of v1 config entries to v2.
- V/I/RSSI panel sensors (opt-in via options, disabled by default).

### Changed
- Integration rewritten around a shared aiohttp session (no per-call `ClientSession`).
- Panel energy sensors use `RestoreSensor` — Energy Dashboard history survives restarts.
- Device tree: System → Inverter → String → Panel (via-device chain).
- `manifest.json`: added `integration_type: hub`, `@TerryFrench` codeowner.

### Removed
- `tigo_api.py` (synchronous `requests`-based client replaced by `api/`).
- Dead `parse_csv` function from `__init__.py`.

## [1.0.2] - 2024

### Added
- Initial release: panel sensors (`Pin`, `Vin`, `Iin`, `RSSI`) and system summary sensors (`tigo_current_power`, `tigo_daily_energy`, `tigo_ytd_energy`, `tigo_lifetime_energy`).
- Config flow (email + password).
- HACS support.
