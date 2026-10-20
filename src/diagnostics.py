"""Compatibility import for the historical diagnostics module."""

import sys

from tunnel_sync.domain import diagnostics as _module

sys.modules[__name__] = _module
