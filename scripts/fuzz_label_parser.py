#!/usr/bin/env python3
"""
Atheris-compatible Fuzz Harness for cf-docker-tunnel-sync label parsing.
Can be executed with: python fuzz_label_parser.py
Or integrated into OSS-Fuzz / ClusterFuzzLite.
"""

import os
import sys
from unittest.mock import patch

try:
    import atheris
except ImportError:
    atheris = None

import app


def TestOneInput(data: bytes):
    """Fuzz harness entry point: parses raw fuzzed byte strings into Docker labels."""
    fdp = atheris.FuzzedDataProvider(data) if atheris else None
    if fdp:
        hostname = fdp.ConsumeUnicodeNoSurrogates(64)
        service = fdp.ConsumeUnicodeNoSurrogates(64)
        no_tls = fdp.ConsumeUnicodeNoSurrogates(16)
        origin_header = fdp.ConsumeUnicodeNoSurrogates(32)
    else:
        # Fallback pseudo-fuzz if atheris is not installed in local environment
        try:
            s = data.decode("utf-8", errors="replace")
        except Exception:
            return
        parts = s.split("\x00")
        hostname = parts[0] if len(parts) > 0 else ""
        service = parts[1] if len(parts) > 1 else ""
        no_tls = parts[2] if len(parts) > 2 else ""
        origin_header = parts[3] if len(parts) > 3 else ""

    mock_container = {
        "Names": ["/fuzzed-service"],
        "State": "running",
        "Labels": {
            "cf.tunnel.hostname": hostname,
            "cf.tunnel.service": service,
            "cf.tunnel.originRequest.noTLSVerify": no_tls,
            "cf.tunnel.originRequest.httpHostHeader": origin_header,
        },
        "NetworkSettings": {"Networks": {}},
    }

    with patch("app.docker_api", return_value=[mock_container]):
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            app.get_docker_containers()


def main():
    if atheris:
        atheris.instrument_all()
        atheris.Setup(sys.argv, TestOneInput)
        atheris.Fuzz()
    else:
        # Smoke verification with synthetic byte mutations
        for sample in [b"", b"\x00", b"test\x00http://srv:80\x00true\x00host", b"\xff" * 100]:
            TestOneInput(sample)
        print("Fuzz harness smoke test passed.")


if __name__ == "__main__":
    main()
