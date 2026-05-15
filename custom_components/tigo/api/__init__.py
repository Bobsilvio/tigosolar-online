"""Tigo API clients.

This package isolates all Tigo HTTP access behind async clients that take an
injected ``aiohttp.ClientSession`` (Home Assistant's shared session). Commit 2
extracts the existing v3 behaviour unchanged; later commits add the v4 client,
the auto-fallback factory and token lifecycle handling.
"""

from .errors import TigoApiError, TigoAuthError
from .v3 import TigoV3Client

__all__ = ["TigoApiError", "TigoAuthError", "TigoV3Client"]
