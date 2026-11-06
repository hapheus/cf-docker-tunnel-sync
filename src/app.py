"""Preserve historical app imports and ASGI/CLI invocation."""

import sys
import warnings

warnings.warn(
    "Use 'tunnel_sync.runtime.cli' / 'tunnel_sync.compat.app' instead; historical 'app' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)


if __name__ == "__main__":
    from tunnel_sync.runtime.cli import main

    main()
else:
    from tunnel_sync.compat import app as _module

    sys.modules[__name__] = _module
