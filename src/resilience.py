"""Compatibility import for the historical resilience module."""

import sys

from tunnel_sync.adapters import retry as _module

sys.modules[__name__] = _module
