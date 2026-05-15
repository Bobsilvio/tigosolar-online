"""Shared token-lifecycle behaviour for the Tigo API clients.

Both clients store the credentials used at login so the integration can
transparently re-authenticate when the token expires (~6 months for v4) or a
request comes back 401. ``auth_retry`` performs at most one re-login + retry,
then surfaces ``TigoAuthError`` for the caller to map to a reauth flow.
"""

from __future__ import annotations

import email.utils
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .errors import TigoAuthError

_LOGGER = logging.getLogger(__name__)

# Re-login this long before the stated token expiry.
_EXPIRY_MARGIN = timedelta(days=1)


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) to seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return max(delta, 0.0)


class BaseTigoClient:
    """Common credential storage + token lifecycle."""

    api_version = "base"

    def __init__(
        self, session: aiohttp.ClientSession, token: str | None = None
    ) -> None:
        self._session = session
        self.token: str | None = token
        self.refresh_token: str | None = None
        self.expires: datetime | None = None
        self._email: str | None = None
        self._password: str | None = None

    async def _do_login(self, email: str, password: str) -> str:
        """Subclass hook: perform the actual login, set self.token, return it."""
        raise NotImplementedError

    async def login(self, email: str, password: str) -> str:
        """Authenticate and remember credentials for later re-login."""
        token = await self._do_login(email, password)
        self._email = email
        self._password = password
        return token

    async def relogin(self) -> str:
        if self._email is None or self._password is None:
            raise TigoAuthError("Cannot re-login: no stored credentials")
        _LOGGER.debug("Re-authenticating Tigo %s client", self.api_version)
        return await self._do_login(self._email, self._password)

    def _token_expired(self) -> bool:
        if self.expires is None:
            return False  # v3 tokens have no stated expiry
        now = datetime.now(self.expires.tzinfo or timezone.utc)
        return now >= self.expires - _EXPIRY_MARGIN

    async def ensure_fresh(self) -> None:
        """Proactively re-login if the token is missing or near expiry."""
        if self.token is None or self._token_expired():
            await self.relogin()

    async def auth_retry(self, call: Callable[[], Awaitable[Any]]) -> Any:
        """Run ``call``; on TigoAuthError re-login once and retry once."""
        await self.ensure_fresh()
        try:
            return await call()
        except TigoAuthError:
            _LOGGER.info(
                "Tigo %s token rejected; re-logging in and retrying once",
                self.api_version,
            )
            await self.relogin()
            return await call()

    def token_state(self) -> dict[str, Any]:
        """Serializable token state for persisting into the config entry."""
        return {
            "token": self.token,
            "refresh_token": self.refresh_token,
            "expires": self.expires.isoformat() if self.expires else None,
        }
