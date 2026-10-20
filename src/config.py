"""Compatibility import for the historical config module."""

import sys

from tunnel_sync.configuration import validation as _module

sys.modules[__name__] = _module
