"""Compatibility import for the historical models module."""

import sys
import warnings

from tunnel_sync.web import models as _module

warnings.warn(
    "Use 'tunnel_sync.web.models' instead; historical 'models' module is frozen.", DeprecationWarning, stacklevel=2
)

sys.modules[__name__] = _module
