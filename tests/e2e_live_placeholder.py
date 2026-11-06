"""Opt-in live E2E placeholder (ISS-15). Skipped by default; requires sandbox secrets."""

import os
import sys


def main() -> int:
    token = os.environ.get("E2E_CLOUDFLARE_API_TOKEN", "")
    domain = os.environ.get("E2E_DOMAIN", "")
    account = os.environ.get("E2E_ACCOUNT_ID", "")
    if not token or not domain or not account:
        print("E2E skipped: sandbox env not configured (minimally scoped token required).")
        return 0
    print("E2E placeholder: sandbox account/zone configured; real live probe not executed in this hermetic repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
