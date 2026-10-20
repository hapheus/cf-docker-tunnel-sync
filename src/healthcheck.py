"""Compatibility entry point for the HTTP health probe."""

from tunnel_sync.runtime.healthcheck import main

if __name__ == "__main__":
    raise SystemExit(main())
