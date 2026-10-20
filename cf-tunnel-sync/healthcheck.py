"""Preserve the historical container/local healthcheck.py command."""

from tunnel_sync.runtime.healthcheck import main

if __name__ == "__main__":
    raise SystemExit(main())
