"""Explicit health probe; importing this module never makes a request."""

import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=2):
            return 0
    except Exception:
        return 1
