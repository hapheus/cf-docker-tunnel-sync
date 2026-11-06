"""Compatibility import for the historical reconcile module."""

import sys
import warnings

from tunnel_sync.compat import reconcile as _module

warnings.warn(
    "Use 'tunnel_sync.domain.planner' / 'tunnel_sync.compat.reconcile' instead; historical 'reconcile' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _module
