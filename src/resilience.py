"""Compatibility import for the historical resilience module."""

import sys
import warnings

from tunnel_sync.adapters import retry as _module

warnings.warn(
    "Use 'tunnel_sync.adapters.retry' instead; historical 'resilience' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _module
