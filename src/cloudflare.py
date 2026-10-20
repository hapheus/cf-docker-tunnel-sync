"""Compatibility import for the historical cloudflare module."""

import sys

from tunnel_sync.compat import cloudflare as _module

sys.modules[__name__] = _module
