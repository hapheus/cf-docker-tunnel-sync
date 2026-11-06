"""Compatibility import for the historical cloudflare module."""

import sys
import warnings

from tunnel_sync.compat import cloudflare as _module

warnings.warn(
    "Use 'tunnel_sync.adapters.cloudflare' instead; historical 'cloudflare' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _module
