"""Compatibility import for the historical security module."""

import sys
import warnings

from tunnel_sync import security as _module

warnings.warn(
    "Use 'tunnel_sync.security' instead; historical 'security' module is frozen.", DeprecationWarning, stacklevel=2
)

sys.modules[__name__] = _module
