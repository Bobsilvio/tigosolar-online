"""Single shared data coordinator for the Tigo v4 cloud API.

Responsibilities:

* Incremental per-minute fetch: the summary endpoint returns the whole day's
  1440-minute array every call; we only emit values for minutes newer than the
  last processed one, and carry previous values forward otherwise (no history
  spam).
* Day rollover (local/system tz): finalize energy, reset per-minute/per-day
  baselines, refresh system info (sunrise/sunset/premium/features).
* Night / CCA-cadence skips: don't hammer the API when the sun is down or when
  ``lastData`` has not advanced.
* Resilience for Tigo's poor uptime: exponential backoff with jitter, and
  strict respect of throttling (429 / 503 + Retry-After). Surfaces health via
  ``last_update_success`` (a connectivity binary_sensor reads it) and raises a
  repair issue after a prolonged outage.

Not wired into setup yet -- the entity model (commit 8) consumes this and flips
the integration from the v3 path to v4/auto.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TigoApiError, TigoAuthError
from .api.errors import TigoThrottleError
from .const import (
    BACKOFF_BASE,
    BACKOFF_MAX,
    CONF_ENABLE_CURRENT,
    CONF_ENABLE_RSSI,
    CONF_ENABLE_VOLTAGE,
    CONF_ENERGY_POLL_INTERVAL,
    CONF_NIGHT_SKIP,
    CONF_PANEL_SCAN_INTERVAL,
    CONF_PROBE_EXTRA_HARDWARE,
    DEFAULT_ENERGY_POLL_INTERVAL,
    DEFAULT_NIGHT_SKIP,
    DEFAULT_PANEL_SCAN_INTERVAL,
    DOMAIN,
    ISSUE_API_UNREACHABLE,
    METRIC_IIN,
    METRIC_PIN,
    METRIC_RSSI,
    METRIC_VIN,
    OUTAGE_ISSUE_AFTER,
)
from .topology import Topology, build_topology

_LOGGER = logging.getLogger(__name__)


@dataclass
class _EnergyState:
    """Daily-reset Wh -> monotonic cumulative kWh accumulator."""

    cumulative_wh: float = 0.0
    d_prev: float = 0.0

    def apply(self, current_wh: float | None) -> None:
        if current_wh is None:
            return
        if current_wh >= self.d_prev:
            self.cumulative_wh += current_wh - self.d_prev
        else:  # daily/meter reset detected within the day
            self.cumulative_wh += current_wh
        self.d_prev = current_wh

    def rollover(self) -> None:
        # New local day: next reading is the day's first; keep cumulative.
        self.d_prev = 0.0

    @property
    def lifetime_kwh(self) -> float:
        return round(self.cumulative_wh / 1000.0, 3)

    @property
    def today_kwh(self) -> float:
        return round(self.d_prev / 1000.0, 3)


@dataclass
class _Backoff:
    failures: int = 0
    next_allowed: float = 0.0  # time.monotonic() gate

    def ok(self) -> bool:
        return time.monotonic() >= self.next_allowed

    def hold(self, seconds: float) -> None:
        self.next_allowed = time.monotonic() + max(seconds, 0.0)

    def on_success(self) -> None:
        self.failures = 0
        self.next_allowed = 0.0

    def on_failure(self) -> float:
        self.failures += 1
        step = min(BACKOFF_BASE * (2 ** (self.failures - 1)), BACKOFF_MAX)
        jitter = step * 0.2 * random.random()
        delay = step + jitter
        self.hold(delay)
        return delay


@dataclass
class _RuntimeMeta:
    tz: ZoneInfo | None = None
    current_date: str = ""
    sunrise_h: float = 0.0
    sunset_h: float = 24.0
    has_premium: bool = False
    features: set[str] = field(default_factory=set)
    capabilities: dict[str, Any] = field(default_factory=dict)
    last_lastdata: str | None = None


class TigoDataUpdateCoordinator(DataUpdateCoordinator):
    """One coordinator; all panels read from its data dict."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client,
        system_id: int,
    ) -> None:
        self.entry = entry
        self.client = client
        self.system_id = system_id
        self.topology: Topology | None = None

        opts = {**entry.data, **entry.options}
        self._scan = int(
            opts.get(CONF_PANEL_SCAN_INTERVAL, DEFAULT_PANEL_SCAN_INTERVAL)
        )
        self._energy_every = int(
            opts.get(CONF_ENERGY_POLL_INTERVAL, DEFAULT_ENERGY_POLL_INTERVAL)
        )
        self._night_skip = bool(opts.get(CONF_NIGHT_SKIP, DEFAULT_NIGHT_SKIP))
        self._probe_extra = bool(opts.get(CONF_PROBE_EXTRA_HARDWARE, False))
        self.extra_probe: dict[str, Any] = {}

        # Options force a metric on regardless of entity state. Optional
        # metrics are otherwise fetched on demand: as soon as the user
        # enables one of their (disabled-by-default) entities.
        self._forced_metrics = {METRIC_PIN}
        if opts.get(CONF_ENABLE_VOLTAGE):
            self._forced_metrics.add(METRIC_VIN)
        if opts.get(CONF_ENABLE_CURRENT):
            self._forced_metrics.add(METRIC_IIN)
        if opts.get(CONF_ENABLE_RSSI):
            self._forced_metrics.add(METRIC_RSSI)

        self._meta = _RuntimeMeta()
        self._backoff = _Backoff()
        self._last_minute: dict[str, int] = {}
        self._panel_vals: dict[str, dict[str, float | None]] = {}
        self._sys_energy = _EnergyState()
        self._panel_energy: dict[str, _EnergyState] = {}
        self._last_energy_fetch = 0.0
        self._disabled_metrics: set[str] = set()

        super().__init__(
            hass,
            _LOGGER,
            name="Tigo",
            update_interval=timedelta(seconds=self._scan),
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _now(self) -> datetime:
        return datetime.now(self._meta.tz) if self._meta.tz else datetime.now()

    async def _refresh_system_info(self, today: date) -> None:
        info = await self.client.get_system_info(
            self.system_id, today.isoformat()
        )
        if not isinstance(info, dict):
            return
        feats = info.get("features") or []
        self._meta.features = {str(f) for f in feats}
        self._meta.has_premium = bool(info.get("has_premium", False))
        day = info.get(today.isoformat()) or {}
        if isinstance(day, dict):
            self._meta.sunrise_h = float(day.get("sunrise", 0.0) or 0.0)
            self._meta.sunset_h = float(day.get("sunset", 24.0) or 24.0)
            tzname = day.get("timezone")
            if tzname:
                try:
                    self._meta.tz = ZoneInfo(tzname)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Unknown Tigo timezone %r", tzname)

    def _is_night(self, now: datetime) -> bool:
        if not self._night_skip:
            return False
        hour = now.hour + now.minute / 60.0
        return hour < (self._meta.sunrise_h - 0.25) or hour > (
            self._meta.sunset_h + 0.5
        )

    def _cca_uids(self) -> list[str]:
        if self.topology and self.topology.cca_uids:
            return self.topology.cca_uids
        return [str(self.system_id)]

    @staticmethod
    def _minute_index(t: str) -> int:
        try:
            hh, mm = t.split(":")[:2]
            return int(hh) * 60 + int(mm)
        except Exception:  # noqa: BLE001
            return -1

    # ------------------------------------------------------------------ #
    # main update
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Any]:
        # Backoff / throttle gate: skip the network entirely, keep last data.
        if not self._backoff.ok():
            if self.data is not None:
                return self.data
            raise UpdateFailed("Tigo API backing off (no data yet)")

        try:
            data = await self._do_update()
        except TigoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TigoThrottleError as err:
            wait = err.retry_after if err.retry_after else self._backoff.on_failure()
            if err.retry_after:
                self._backoff.hold(err.retry_after)
                self._backoff.failures += 1
            _LOGGER.warning(
                "Tigo API throttled; honoring Retry-After=%ss", round(wait)
            )
            self._maybe_raise_outage_issue()
            raise UpdateFailed(f"Tigo API throttled (retry in {round(wait)}s)") from err
        except Exception as err:  # noqa: BLE001
            delay = self._backoff.on_failure()
            _LOGGER.warning(
                "Tigo API update failed (%s); backing off %ss", err, round(delay)
            )
            self._maybe_raise_outage_issue()
            raise UpdateFailed(str(err)) from err

        self._backoff.on_success()
        self._clear_outage_issue()
        return data

    async def _do_update(self) -> dict[str, Any]:
        now = self._now()
        today = now.date()
        date_str = today.isoformat()

        # First run / topology.
        if self.topology is None:
            layout = {}
            try:
                layout = await self.client.get_system_layout(self.system_id)
            except TigoApiError as err:
                _LOGGER.info(
                    "Tigo layout unavailable (%s); telemetry-only mapping", err
                )
            equipments = await self.client.get_equipments(self.system_id)
            self.topology = build_topology(layout, equipments)
            try:
                self._meta.capabilities = await self.client.get_capabilities(
                    self.system_id
                )
            except TigoApiError:
                self._meta.capabilities = {}
            if self._probe_extra and hasattr(
                self.client, "probe_extra_hardware"
            ):
                try:
                    self.extra_probe = await self.client.probe_extra_hardware(
                        self.system_id
                    )
                except TigoApiError as err:
                    _LOGGER.debug("Extra-hardware probe failed: %s", err)
            await self._refresh_system_info(today)
            self._meta.current_date = date_str

        # Day rollover.
        if date_str != self._meta.current_date:
            _LOGGER.debug("Tigo day rollover %s -> %s", self._meta.current_date, date_str)
            self._sys_energy.rollover()
            for st in self._panel_energy.values():
                st.rollover()
            self._last_minute.clear()
            self._meta.last_lastdata = None
            await self._refresh_system_info(today)
            self._meta.current_date = date_str

        night = self._is_night(now)

        # --- per-minute telemetry ---
        if not night:
            await self._fetch_telemetry(date_str)
        else:
            _LOGGER.debug("Tigo night skip: telemetry fetch suppressed")

        # --- per-panel / system daily energy ---
        if (
            time.monotonic() - self._last_energy_fetch >= self._energy_every
            or self._last_energy_fetch == 0.0
            or night  # ensure a final capture after sunset / after midnight
        ):
            await self._fetch_energy(date_str)
            self._last_energy_fetch = time.monotonic()

        return self._build_result()

    # metric -> entity unique_id suffix (matches sensor.PANEL_METRICS)
    _METRIC_SUFFIX = {
        METRIC_PIN: "power",
        METRIC_VIN: "voltage",
        METRIC_IIN: "current",
        METRIC_RSSI: "rssi",
    }

    def _active_metrics(self) -> list[str]:
        """pin always; an optional metric is active if forced via options
        OR at least one of its entities is enabled in the registry."""
        active = set(self._forced_metrics)
        try:
            reg = er.async_get(self.hass)
            enabled_suffixes = {
                ent.unique_id.rsplit("_", 1)[-1]
                for ent in er.async_entries_for_config_entry(
                    reg, self.entry.entry_id
                )
                if ent.disabled_by is None and ent.unique_id
            }
            for metric, suffix in self._METRIC_SUFFIX.items():
                if suffix in enabled_suffixes:
                    active.add(metric)
        except Exception:  # noqa: BLE001 - registry not ready -> forced only
            pass
        # Stable order: pin, vin, iin, rssi
        return [
            m
            for m in (METRIC_PIN, METRIC_VIN, METRIC_IIN, METRIC_RSSI)
            if m in active
        ]

    async def _fetch_telemetry(self, date_str: str) -> None:
        # CCA-cadence skip: probe pin first; if lastData unchanged, the other
        # metrics produced no new minute either -> skip them this cycle.
        metrics = [
            m for m in self._active_metrics() if m not in self._disabled_metrics
        ]
        advanced = True
        for metric in metrics:
            if metric != METRIC_PIN and not advanced:
                continue
            for uid in self._cca_uids():
                try:
                    payload = await self.client.get_panel_summary(
                        self.system_id, date_str, metric, uid
                    )
                except TigoApiError as err:
                    if err.status == 403:
                        _LOGGER.warning(
                            "Tigo metric %s not entitled (403); disabling for "
                            "this session",
                            metric,
                        )
                        self._disabled_metrics.add(metric)
                        break
                    if err.status in (404, 422):
                        break  # absent for this account; ignore quietly
                    raise
                last_data = payload.get("lastData")
                if metric == METRIC_PIN:
                    advanced = last_data != self._meta.last_lastdata
                    self._meta.last_lastdata = last_data
                self._apply_summary(metric, payload)

    def _apply_summary(self, metric: str, payload: dict) -> None:
        dataset = payload.get("dataset") or []
        if not dataset:
            return
        rows = dataset[0].get("data") or []
        seen = self._last_minute.get(metric, -1)
        newest = seen
        newest_row: list | None = None
        for row in rows:
            mi = self._minute_index(row.get("t", ""))
            if mi <= seen:
                continue
            vals = row.get("d") or []
            if any(v not in ("-", "", None) for v in vals):
                if mi > newest:
                    newest = mi
                    newest_row = vals
        if newest_row is None:
            return  # no newer filled minute -> carry forward
        self._last_minute[metric] = newest
        assert self.topology is not None
        for idx, raw in enumerate(newest_row):
            meta = self.topology.by_index.get(idx)
            if meta is None:
                continue
            try:
                val = None if raw in ("-", "", None) else round(float(raw), 2)
            except (TypeError, ValueError):
                val = None
            self._panel_vals.setdefault(meta.equipment_id, {})[metric] = val

    async def _fetch_energy(self, date_str: str) -> None:
        try:
            agg = await self.client.get_agg_energy(self.system_id, date_str)
        except TigoApiError as err:
            if err.status in (403, 404, 422):
                return
            raise
        ds = agg.get("dataset") or {}
        for obj_id, wh in ds.items():
            st = self._panel_energy.setdefault(str(obj_id), _EnergyState())
            try:
                st.apply(float(wh))
            except (TypeError, ValueError):
                continue
        stats = agg.get("dailyStats") or {}
        total = stats.get("total_agg_energy")
        if total is not None:
            try:
                self._sys_energy.apply(float(total))
            except (TypeError, ValueError):
                pass

    def _build_result(self) -> dict[str, Any]:
        assert self.topology is not None
        panels: dict[str, dict[str, Any]] = {}
        sys_power = 0.0
        for meta in self.topology.panels:
            vals = dict(self._panel_vals.get(meta.equipment_id, {}))
            pin = vals.get(METRIC_PIN)
            if isinstance(pin, (int, float)):
                sys_power += pin
            est = (
                self._panel_energy.get(meta.object_id)
                if meta.object_id
                else None
            )
            if est is not None:
                vals["energy_kwh_lifetime"] = est.lifetime_kwh
                vals["energy_kwh_today"] = est.today_kwh
            panels[meta.equipment_id] = vals
        return {
            "panels": panels,
            "system": {
                "power_w": round(sys_power, 2),
                "lifetime_energy_kwh": self._sys_energy.lifetime_kwh,
                "today_energy_kwh": self._sys_energy.today_kwh,
            },
            "meta": {
                "has_premium": self._meta.has_premium,
                "features": sorted(self._meta.features),
                "capabilities": self._meta.capabilities,
                "last_data": self._meta.last_lastdata,
                "disabled_metrics": sorted(self._disabled_metrics),
            },
        }

    # ------------------------------------------------------------------ #
    # restore seeding (called by RestoreSensor entities on startup so the
    # monotonic lifetime counters survive a HA restart)
    # ------------------------------------------------------------------ #
    def seed_system_energy(self, lifetime_kwh: float) -> None:
        if lifetime_kwh and self._sys_energy.cumulative_wh == 0.0:
            self._sys_energy.cumulative_wh = float(lifetime_kwh) * 1000.0

    def seed_panel_energy(self, object_id: str, lifetime_kwh: float) -> None:
        if not object_id or not lifetime_kwh:
            return
        st = self._panel_energy.setdefault(object_id, _EnergyState())
        if st.cumulative_wh == 0.0:
            st.cumulative_wh = float(lifetime_kwh) * 1000.0

    # ------------------------------------------------------------------ #
    # outage repair issue
    # ------------------------------------------------------------------ #
    def _maybe_raise_outage_issue(self) -> None:
        if self._backoff.failures < OUTAGE_ISSUE_AFTER:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_API_UNREACHABLE,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_API_UNREACHABLE,
        )

    def _clear_outage_issue(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_API_UNREACHABLE)
