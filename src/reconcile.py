"""Compatibility import for the historical reconcile module."""

import sys

from tunnel_sync.compat import reconcile as _module

sys.modules[__name__] = _module
