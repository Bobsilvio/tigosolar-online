"""Async client for the current Tigo v4 cloud API (mapi.tigoenergy.com).

This is the API the official Tigo mobile app uses. It exposes per-minute,
per-panel telemetry (power/voltage/current/rssi) and per-panel daily energy.

This commit only implements the client surface; the auto-fallback factory and
token-refresh lifecycle are added in the next commit, and the
interpretation/mapping of the returned payloads lives in topology.py /
coordinator.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from .errors import TigoApiError, TigoAuthError

_LOGGER = logging.getLogger(__name__)

API_HOST = "https://mapi.tigoenergy.com"

# temp= values for the per-panel summary endpoint.
METRIC_PIN = "pin"
METRIC_VIN = "vin"
METRIC_IIN = "iin"
METRIC_RSSI = "rssi"
PANEL_METRICS = (METRIC_PIN, METRIC_VIN, METRIC_IIN, METRIC_RSSI)


def _cache_buster() -> int:
    """Millisecond epoch, used as the `_` param to defeat 304 caching."""
    return int(time.time() * 1000)


class TigoV4Client:
    """Async wrapper over the Tigo v4 endpoints used by the integration.

    Token lifecycle (re-login/refresh on 401/expiry) is layered on in the
    factory commit; here ``login`` simply authenticates and stores the token,
    refresh token and expiry so later code can manage them.
    """

    def __init__(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._session = session
        self.token: str | None = token
        self.refresh_token: str | None = None
        self.expires: datetime | None = None
        self.user_id: int | None = None
        self.user_type: str | None = None

    # ------------------------------------------------------------------ #
    # low-level helpers
    # ------------------------------------------------------------------ #
    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        auth_required: bool = True,
    ) -> Any:
        hdrs = dict(headers or {})
        if auth_required:
            hdrs.setdefault("Authorization", f"Bearer {self.token}")
            hdrs.setdefault("Accept", "application/json")
        try:
            async with self._session.request(
                method, url, headers=hdrs, json=json
            ) as resp:
                body = await resp.text()
                if resp.status == 401:
                    raise TigoAuthError(f"Tigo v4 unauthorized: {method} {url}")
                if resp.status != 200:
                    # Surface status + a short body snippet; callers (coordinator)
                    # decide how to treat 403/404/422/429/5xx.
                    raise TigoApiError(
                        f"Tigo v4 error {resp.status}: {method} {url} :: {body[:200]}",
                    )
                try:
                    return await resp.json(content_type=None)
                except Exception as err:  # noqa: BLE001 - non-JSON 200
                    raise TigoApiError(
                        f"Tigo v4 non-JSON body: {method} {url}: {err}"
                    ) from err
        except aiohttp.ClientError as err:
            raise TigoApiError(
                f"Tigo v4 request failed: {method} {url}: {err}"
            ) from err

    # ------------------------------------------------------------------ #
    # auth
    # ------------------------------------------------------------------ #
    async def login(self, email: str, password: str) -> str:
        """POST /api/v3/user/login?type=8 -> store and return bearer token."""
        url = f"{API_HOST}/api/v3/user/login?type=8"
        try:
            async with self._session.post(
                url,
                json={"username": email, "password": password},
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status in (401, 403):
                    raise TigoAuthError("Tigo login failed: invalid credentials")
                if resp.status != 200:
                    raise TigoApiError(f"Tigo login error {resp.status}")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TigoApiError(f"Tigo login request failed: {err}") from err

        user = data.get("user") if isinstance(data, dict) else None
        if not user or "auth" not in user:
            raise TigoApiError(f"Tigo login response missing token: {data!r}")

        self.token = user["auth"]
        self.refresh_token = user.get("refresh_token")
        self.user_id = user.get("user_id")
        self.user_type = user.get("user_type")
        self.expires = self._parse_expires(user.get("expires"))
        return self.token

    @staticmethod
    def _parse_expires(value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        try:
            # e.g. "2026-11-10T22:48:15-08:00"
            return datetime.fromisoformat(value)
        except ValueError:
            _LOGGER.debug("Unparseable Tigo token expiry: %r", value)
            return None

    # ------------------------------------------------------------------ #
    # topology / capabilities
    # ------------------------------------------------------------------ #
    async def get_systems(self) -> list[dict]:
        """GET /api/v3/systems/query -> list of systems for this account."""
        data = await self._request_json(
            "GET",
            f"{API_HOST}/api/v3/systems/query?limit=100&page=1&sort=-id",
        )
        if isinstance(data, dict):
            return data.get("systems") or data.get("data") or []
        return data if isinstance(data, list) else []

    async def get_topology(self, system_id: int) -> dict:
        """GET /api/v3/systems/full/{id} -> sources/strings/mppts/inverters."""
        return await self._request_json(
            "GET",
            f"{API_HOST}/api/v3/systems/full/{system_id}?system_id={system_id}",
        )

    async def get_capabilities(self, system_id: int) -> dict:
        """GET /api/v4/systems/view/{id}?includes=details -> has_* flags."""
        data = await self._request_json(
            "GET",
            f"{API_HOST}/api/v4/systems/view/{system_id}?includes=details",
        )
        if isinstance(data, dict):
            return data.get("details", data) if "details" in data else data
        return {}

    async def get_system_info(self, system_id: int, date: str) -> dict:
        """GET /api/v3/tigobuild/systeminfo -> has_premium, features, units…"""
        return await self._request_json(
            "GET",
            f"{API_HOST}/api/v3/tigobuild/systeminfo"
            f"?system_id={system_id}&date={date}"
            f"&resourceId=dateinfo-{date}&_={_cache_buster()}",
        )

    async def get_equipments(self, system_id: int) -> list[dict]:
        """GET /api/v4/equipments?systemId= -> ordered equipment list.

        Returned order indexes the telemetry `d[]` arrays; callers MUST keep
        it verbatim (it is stable but not alphabetical).
        """
        data = await self._request_json(
            "GET",
            f"{API_HOST}/api/v4/equipments?systemId={system_id}",
        )
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------ #
    # telemetry
    # ------------------------------------------------------------------ #
    async def get_panel_summary(
        self, system_id: int, date: str, metric: str, cca_uid: str
    ) -> dict:
        """GET /api/v4/system/summary/summary for one metric.

        Returns the raw payload: ``{"dataType","dataset":[{"data":[{"t","d":[…]}…]}],
        "lastData": "YYYY-MM-DD HH:MM:SS"}``. Interpretation is the
        coordinator's job.
        """
        url = (
            f"{API_HOST}/api/v4/system/summary/summary"
            f"?system_id={system_id}&date={date}&temp={metric}&uid={cca_uid}"
            f"&resourceId=data-{date}-{metric}-{cca_uid}&_={_cache_buster()}"
        )
        return await self._request_json("GET", url)

    async def get_agg_energy(self, system_id: int, date: str) -> dict:
        """GET /api/v4/system/summary/aggenergy -> per-object_id daily Wh.

        Returns ``{"dataset":{object_id:Wh},"datasetLastData":{…},
        "dailyStats":{"total_agg_energy":Wh,"total_agg_reclaimed":Wh},…}``.
        """
        url = (
            f"{API_HOST}/api/v4/system/summary/aggenergy"
            f"?system_id={system_id}&date={date}&temp=energy"
            f"&resourceId=data-{date}-energy&_={_cache_buster()}"
        )
        return await self._request_json("GET", url)
