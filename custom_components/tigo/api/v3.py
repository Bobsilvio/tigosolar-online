"""Async client for the legacy Tigo v3 cloud API (api2.tigoenergy.com).

This is a faithful async port of the original synchronous ``tigo_api.py`` plus
the per-panel CSV fetch/parse that previously lived in ``__init__.py``. No
endpoint, parameter or data shape has changed in this commit -- it only moves
the logic behind a client that uses Home Assistant's shared aiohttp session
instead of ``requests`` in an executor / a per-call ``aiohttp.ClientSession``.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .errors import TigoApiError, TigoAuthError

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://api2.tigoenergy.com/api/v3"

# Per-panel parameters fetched from /data/aggregate (param -> unit, unit unused
# here but kept to document the contract the sensors rely on).
PARAMS = {
    "Pin": "W",
    "Vin": "V",
    "Iin": "A",
    "RSSI": "dBm",
}


def parse_param_csv(csv_text: str, param: str, latest_only: bool = False) -> dict[str, float]:
    """Parse a /data/aggregate CSV body into ``{panel_id: value}``.

    Unchanged behaviour from the original ``__init__.parse_param_csv``.
    """
    result: dict[str, float] = {}
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if len(rows) < 2:
        return {}

    headers = rows[0][1:]  # skip the Datetime column
    values_rows = rows[1:]

    if latest_only:
        # Find the last row that has at least one valid value.
        for row in reversed(values_rows):
            values = row[1:]
            if any(v.strip() not in ("", "NaN") for v in values):
                break
        else:
            return {}
    else:
        values = values_rows[0][1:]

    for panel_id, value in zip(headers, values):
        try:
            result[str(panel_id)] = float(value)
        except Exception:
            continue

    return result


class TigoV3Client:
    """Minimal async wrapper over the Tigo v3 endpoints used by the integration."""

    def __init__(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._session = session
        self.token = token

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def _get_json(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    raise TigoAuthError(f"Tigo API unauthorized: GET {url}")
                if resp.status != 200:
                    raise TigoApiError(f"Tigo API error {resp.status}: GET {url}")
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TigoApiError(f"Tigo API request failed: GET {url}: {err}") from err

    async def login(self, email: str, password: str) -> str:
        """HTTP Basic-auth login; stores and returns the bearer token."""
        url = f"{API_BASE_URL}/users/login"
        try:
            async with self._session.get(
                url, auth=aiohttp.BasicAuth(email, password)
            ) as resp:
                if resp.status in (401, 403):
                    raise TigoAuthError("Tigo login failed: invalid credentials")
                if resp.status != 200:
                    raise TigoApiError(f"Tigo login error {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TigoApiError(f"Tigo login request failed: {err}") from err

        try:
            self.token = data["user"]["auth"]
        except (KeyError, TypeError) as err:
            raise TigoApiError(f"Tigo login response missing token: {data!r}") from err
        return self.token

    async def get_system_id(self) -> int:
        data = await self._get_json(f"{API_BASE_URL}/systems", headers=self._auth_headers)
        systems = data.get("systems", []) if isinstance(data, dict) else []
        if not systems:
            raise TigoApiError("No systems found for this account")
        return systems[0]["system_id"]

    async def get_system_layout(self, system_id: int) -> dict:
        return await self._get_json(
            f"{API_BASE_URL}/systems/layout?id={system_id}",
            headers=self._auth_headers,
        )

    async def get_system_info(self, system_id: int) -> dict:
        data = await self._get_json(
            f"{API_BASE_URL}/systems/view?id={system_id}",
            headers=self._auth_headers,
        )
        return data.get("system", {}) if isinstance(data, dict) else {}

    async def get_system_summary(self, system_id: int) -> dict[str, float]:
        data = await self._get_json(
            f"{API_BASE_URL}/data/summary?system_id={system_id}",
            headers=self._auth_headers,
        )
        raw = data.get("summary", {}) if isinstance(data, dict) else {}
        clean: dict[str, float] = {}
        for key, val in raw.items():
            try:
                if isinstance(val, (int, float)):
                    if "energy" in key.lower():
                        clean[key] = round(val / 1000, 2)  # Wh -> kWh
                    else:
                        clean[key] = round(val, 2)
            except Exception as err:  # pragma: no cover - defensive, matches original
                _LOGGER.warning("Error parsing summary key %s=%s: %s", key, val, err)
                continue
        return clean

    async def fetch_panel_data(self, system_id: int) -> dict[str, dict[str, float]]:
        """Return ``{panel_id: {param: value}}`` for the current UTC day.

        Behaviour preserved from the original ``__init__.fetch_tigo_data``
        (including the UTC day window -- timezone handling is addressed later
        in the coordinator commit).
        """
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(
            today, datetime.min.time(), tzinfo=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S")
        end = datetime.combine(
            today, datetime.max.time(), tzinfo=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S")

        combined: dict[str, dict[str, float]] = {}
        for param in PARAMS:
            url = (
                f"{API_BASE_URL}/data/aggregate"
                f"?system_id={system_id}&start={start}&end={end}&level=min"
                f"&param={param}&header=id&sensors=true"
            )
            _LOGGER.debug("Fetching v3 param %s: %s", param, url)
            try:
                async with self._session.get(
                    url, headers={"Authorization": f"Bearer {self.token}"}
                ) as resp:
                    if resp.status == 401:
                        raise TigoAuthError(f"Tigo API unauthorized [{param}]")
                    if resp.status != 200:
                        raise TigoApiError(
                            f"Tigo API error [{param}]: {resp.status}"
                        )
                    text = await resp.text()
            except aiohttp.ClientError as err:
                raise TigoApiError(f"Tigo API request failed [{param}]: {err}") from err

            for panel_id, value in parse_param_csv(
                text, param, latest_only=True
            ).items():
                combined.setdefault(panel_id, {})[param] = value

        return combined
