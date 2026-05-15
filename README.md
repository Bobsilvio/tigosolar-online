[![Sample](https://storage.ko-fi.com/cdn/generated/zfskfgqnf/2025-03-07_rest-7d81acd901abf101cbdf54443c38f6f0-dlmmonph.jpg)](https://ko-fi.com/silviosmart)

## Supportami / Support Me

Se ti piace il mio lavoro e vuoi che continui nello sviluppo delle card, puoi offrirmi un caffè.\
If you like my work and want me to continue developing the cards, you can buy me a coffee.


[![PayPal](https://img.shields.io/badge/Donate-PayPal-%2300457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=Z6KY9V6BBZ4BN)

Non dimenticare di seguirmi sui social:\
Don't forget to follow me on social media:

[![TikTok](https://img.shields.io/badge/Follow_TikTok-%23000000?style=for-the-badge&logo=tiktok&logoColor=white)](https://www.tiktok.com/@silviosmartalexa)

[![Instagram](https://img.shields.io/badge/Follow_Instagram-%23E1306C?style=for-the-badge&logo=instagram&logoColor=white)](https://www.instagram.com/silviosmartalexa)

[![YouTube](https://img.shields.io/badge/Subscribe_YouTube-%23FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/@silviosmartalexa)

# Tigo Energy Integration for Home Assistant

This is a custom integration for [Home Assistant](https://www.home-assistant.io/) that allows you to monitor your **Tigo Energy solar system**, including each individual panel, in real-time using Tigo’s public API.

---

## 🆕 v2 — Tigo **v4** cloud API (this fork)

This is a fork of [Bobsilvio/tigosolar-online](https://github.com/Bobsilvio/tigosolar-online)
upgraded to Tigo's current **v4** cloud API (`mapi.tigoenergy.com`, the API the
official Tigo mobile app uses), with the legacy **v3** API kept as an automatic
fallback. Highlights:

- **API selection**: `auto` (try v4, fall back to v3), `v4`, or `v3` — set at
  setup and changeable in **Options**.
- **Token lifecycle**: long-lived token persisted across restarts; transparent
  re-login on expiry/401, with a proper **re-authentication** flow.
- **Premium toggle**: tell the integration whether the account has a Tigo EI
  Premium subscription; non-premium degrades gracefully to system-level data
  instead of erroring.
- **Resilience for Tigo's flaky cloud**: exponential backoff with jitter,
  **strict respect of throttling** (`429` / `503` + `Retry-After`), a
  `binary_sensor` showing Tigo API connectivity, and a Repair issue raised
  during prolonged outages (auto-cleared on recovery).
- **Efficient polling**: incremental per-minute fetch (no duplicate history),
  night skip, and CCA-cadence skip so we never hammer the API.
- **Energy Dashboard**: a monotonic lifetime **Production** sensor
  (`kWh`, `total_increasing`) that survives restarts and midnight resets — add
  it under *Settings → Energy → Solar production*.
- **Diagnostics**: redacted downloadable diagnostics + optional verbose logging
  and an extra-hardware probe (see below).

### Energy Dashboard setup

Add **`sensor.tigo_system_production`** as a *Solar production* source under
**Settings → Energy**. Use that sensor (not "Production Today"): it is a
monotonic `total_increasing` kWh counter, so Home Assistant's long-term
statistics handle midnight/DST correctly. "Production Today" and per-panel
"Energy" sensors are also available for tiles/automations.

### A note on DUO modules

Tigo `TS4-R-X-DUO` optimizers have a **single** input with two panels wired in
series, so they report **one** voltage/current/power value and appear as a
single "panel" — this is expected, not a missing panel.

### Got inverters / meters / batteries? Help extend the integration

This fork was developed on a panels-only system. If your account has
**monitored inverters, net/consumption meters, or batteries**, enable
*Options → "Probe & log extra hardware"* (and optionally *Verbose debug
logging*), reproduce the data in the Tigo app, then download
**Settings → Devices & Services → Tigo → ⋯ → Download diagnostics**
(secrets are redacted) and open an issue with it attached. That payload is
what we need to add v4 support for that hardware.

> ✅ **Important**: This integration requires an active **Tigo EI Premium subscription**.

> More info: Italian [Tigo EI Premium Plan](https://it.tigoenergy.com/ei-solution/premium)

> More info: English [Tigo EI Premium Plan](https://www.tigoenergy.com/ei-solution/premium)

⚠️ Data is Not Real-Time

    🔄 Note: The data is not real-time. The web system requests and updates data at fixed intervals (every X minutes).
    This limitation applies to the TAP → CCA communication.

The TAP sends data to the CCA sporadically and not all at once. Sometimes it only sends data from one panel at a time, and the logic behind this timing is not clear.

Here’s an example captured using TAPTAP (this system has 20 panels). After more than 10 minutes, only some of the panels had sent data:

{"gateway":{"id":4609},"node":{"id":17},"timestamp":"2025-04-15T15:43:09.291106+02:00",...}
{"gateway":{"id":4609},"node":{"id":17},"timestamp":"2025-04-15T15:43:11.291106+02:00",...}
{"gateway":{"id":4609},"node":{"id":13},"timestamp":"2025-04-15T15:43:45.299594+02:00",...}
{"gateway":{"id":4609},"node":{"id":13},"timestamp":"2025-04-15T15:43:47.299594+02:00",...}
{"gateway":{"id":4609},"node":{"id":9},"timestamp":"2025-04-15T15:45:09.286432+02:00",...}
...

As you can see, each node (panel) sends data independently, and delays between updates can be significant.

## Images
<img src="image/1.png" alt="EP Cube Logo" width="450"/> <img src="image/2.png" alt="EP Cube Icon" width="450"/>
<img src="image/3.png" alt="EP Cube Icon" width="450"/> <img src="image/4.png" alt="EP Cube Icon" width="450"/>
<img src="image/5.png" alt="EP Cube Icon" width="450"/>
## 🔧 Features

- Supports both **system-level** and **panel-level** data
- Automatically discovers all **panels**, grouped by Inverter / MPPT / String
- Creates one device per panel, with multiple sensors:
  - Power (W)
  - Voltage In (V)
  - Current In (A)
  - Signal Strength (RSSI)
- Includes system summary sensors:
  - Daily Energy (kWh)
  - YTD Energy (kWh)
  - Lifetime Energy (kWh)
  - Current DC Power (W)
- Fully compatible with **Home Assistant Energy Dashboard**
- Uses **Tigo API v3** (`api2.tigoenergy.com`)
- No polling overload: optimized with a **shared data coordinator**

## 📦 Installation

### 1. Manual Installation

1. Download this repository
2. Copy the contents into your Home Assistant `custom_components/tigo/` folder
3. Restart Home Assistant

### 2. HACS (optional, if published)

To be added when available via HACS.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bobsilvio&repository=tigosolar-online&category=integration)

## ⚙️ Configuration

1. Go to **Settings > Devices & Services**
2. Click **Add Integration**
3. Search for **Tigo Energy**
4. Enter your **Tigo account email and password**
5. Done! Entities will be created automatically

## 🧪 Entities Created

### Panel Devices (One per panel)

- `sensor.panel_<name>_power`
- `sensor.panel_<name>_voltage_in`
- `sensor.panel_<name>_current_in`
- `sensor.panel_<name>_rssi`

### System Summary Sensors

- `sensor.tigo_daily_energy` *(kWh)*
- `sensor.tigo_ytd_energy` *(kWh)*
- `sensor.tigo_lifetime_energy` *(kWh)*
- `sensor.tigo_current_power` *(W)*

All energy sensors are classified with the appropriate `device_class` and `state_class` for dashboard compatibility.

## 🔐 Security Notice

This integration requires your **Tigo account email and password** to authenticate. Credentials are stored securely in Home Assistant's config entry system. All communication with Tigo servers is HTTPS encrypted.

## 🧱 Dependencies

- `aiohttp` (installed automatically by Home Assistant)

## 🛠 Development Notes

- A **single shared `DataUpdateCoordinator`** drives all entities (no per-panel polling).
- Telemetry is fetched **incrementally** (only minutes newer than the last processed one) so history is not spammed; energy is polled less often (default 5 min).
- Polling backs off on errors and **respects `Retry-After`/429/503**; it skips at night and when the CCA's `lastData` has not advanced.
- Topology (layout + equipment order) is retrieved at setup; equipment-order drift is detected and the mapping rebuilt.

## 🙏 Credits

Originally built and maintained by [Bobsilvio](https://github.com/Bobsilvio/tigosolar-online) (Apache-2.0).

v2 (Tigo v4 API upgrade, resilience, Energy Dashboard, diagnostics) by
[TerryFrench](https://github.com/TerryFrench/tigosolar-online), with the
intent to contribute back upstream.

Inspired by the great work of [MartinStoffel's Tigo Integration](https://github.com/MartinStoffel/tigo)

See `NOTICE` for full attribution.

---

**Not affiliated with Tigo Energy. Use at your own risk.**
