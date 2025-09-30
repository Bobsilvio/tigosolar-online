# Tigo Energy Integration for Home Assistant

This is a custom integration for [Home Assistant](https://www.home-assistant.io/) that allows you to monitor your **Tigo Energy solar system**, including each individual panel, in real-time using Tigo’s public API.

> [!IMPORTANT]
> This integration requires an active **Tigo EI Premium subscription**.

More info on the Tigo EI Premium Plan in [Italian](https://it.tigoenergy.com/ei-solution/premium) or in [English](https://www.tigoenergy.com/ei-solution/premium).

> [!CAUTION]
> This will conflict with [tigosolar-local](https://github.com/Bobsilvio/tigosolar-local), you can not use both at the same time!

> [!WARNING]
> Data is Not Real-Time
>
> Note: The data is not real-time. The web system requests and updates data at fixed intervals (every X minutes).
>
> This limitation applies to the TAP → CCA communication.

The TAP sends data to the CCA sporadically and not all at once. Sometimes it only sends data from one panel at a time, and the logic behind this timing is not clear.

Here’s an example captured using TAPTAP (this system has 20 panels). After more than 10 minutes, only some of the panels had sent data:

```lang=json
{"gateway":{"id":4609},"node":{"id":17},"timestamp":"2025-04-15T15:43:09.291106+02:00",...}
{"gateway":{"id":4609},"node":{"id":17},"timestamp":"2025-04-15T15:43:11.291106+02:00",...}
{"gateway":{"id":4609},"node":{"id":13},"timestamp":"2025-04-15T15:43:45.299594+02:00",...}
{"gateway":{"id":4609},"node":{"id":13},"timestamp":"2025-04-15T15:43:47.299594+02:00",...}
{"gateway":{"id":4609},"node":{"id":9},"timestamp":"2025-04-15T15:45:09.286432+02:00",...}
...
```

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

### 2. HACS (optional)

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

- API calls are rate-limited; the integration performs **one single API call per parameter** and shares the result across all sensors.
- This integration uses **`DataUpdateCoordinator`** to cache and refresh data every 60 seconds (panels) and 5 minutes (system summary).
- System layout is retrieved once during setup and reused.

## 🙏 Credits

Built and maintained by [Bobsilvio](https://github.com/Bobsilvio)

Inspired by the great work of [MartinStoffel's Tigo Integration](https://github.com/MartinStoffel/tigo)

## 📄 License

This project is licensed under the [Apache License](LICENSE).

---

**Not affiliated with Tigo Energy. Use at your own risk.**
