"""Compatibility import for the historical security module."""

import sys

from tunnel_sync import security as _module

sys.modules[__name__] = _module
