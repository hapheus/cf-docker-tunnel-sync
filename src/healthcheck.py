"""Compatibility entry point for the HTTP health probe."""

import warnings

from tunnel_sync.runtime.healthcheck import main

warnings.warn(
    "Use 'tunnel_sync.runtime.healthcheck' instead; historical 'healthcheck' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)


if __name__ == "__main__":
    raise SystemExit(main())
