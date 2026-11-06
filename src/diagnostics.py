"""Compatibility import for the historical diagnostics module."""

import sys
import warnings

from tunnel_sync.domain import diagnostics as _module

warnings.warn(
    "Use 'tunnel_sync.domain.diagnostics' instead; historical 'diagnostics' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _module
