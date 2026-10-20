"""Compatibility import for the historical models module."""

import sys

from tunnel_sync.web import models as _module

sys.modules[__name__] = _module
