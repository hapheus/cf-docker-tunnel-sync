"""Command-line entry point for preflight, dry-run, and the ASGI service."""

import os

import uvicorn

from tunnel_sync.bootstrap import create_services
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.runtime.logging import perform_startup_validation
from tunnel_sync.web.app import create_app


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Cloudflare Docker Tunnel Sync")
    parser.add_argument("--preflight", action="store_true", help="Run non-mutating preflight validation and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="Run sync in predictive dry-run mode (no Cloudflare mutations)"
    )
    args, unknown = parser.parse_known_args()

    perform_startup_validation(exit_on_error=True)

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    preflight_env = os.getenv("PREFLIGHT_ONLY", "false").lower() in ("true", "1", "yes")
    if args.preflight or preflight_env:
        exit_code = create_services(Settings(os.environ)).preflight.run()
        sys.exit(exit_code)

    uvicorn.run(create_app(), host="0.0.0.0", port=8090)
