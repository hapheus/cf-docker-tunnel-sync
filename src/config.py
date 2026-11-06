"""Compatibility import for the historical config module."""

import sys
import warnings

from tunnel_sync.configuration import validation as _module

warnings.warn(
    "Use 'tunnel_sync.configuration.validation' instead; historical 'config' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _module
