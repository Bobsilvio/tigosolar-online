"""Tigo API clients.

This package isolates all Tigo HTTP access behind async clients that take an
injected ``aiohttp.ClientSession`` (Home Assistant's shared session):

- ``TigoV3Client``  -> legacy api2.tigoenergy.com (fallback)
- ``TigoV4Client``  -> current mapi.tigoenergy.com (the app's API; default)

The auto-fallback factory and token lifecycle handling are added next.
"""

from .errors import TigoApiError, TigoAuthError
from .v3 import TigoV3Client
from .v4 import TigoV4Client

__all__ = ["TigoApiError", "TigoAuthError", "TigoV3Client", "TigoV4Client"]
