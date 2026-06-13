# Changelog

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
