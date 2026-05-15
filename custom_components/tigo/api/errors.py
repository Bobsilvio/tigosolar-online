"""Exception types shared by the Tigo API clients."""

from __future__ import annotations


class TigoApiError(Exception):
    """Generic Tigo API failure (network, bad status, unparseable body)."""


class TigoAuthError(TigoApiError):
    """Authentication failed (bad credentials or expired/invalid token)."""
