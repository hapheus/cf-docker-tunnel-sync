"""
Fuzz Testing Suite for Docker Label Parsing and Ingress Configuration.
Uses Hypothesis to generate pseudo-random, adversarial, and mutated inputs.
Ensures zero unhandled exceptions / crashes on malformed container labels.
"""

import os
from unittest.mock import patch

import app
from hypothesis import given, settings
from hypothesis import strategies as st


@settings(max_examples=100, deadline=None)
@given(
    hostname=st.text(min_size=0, max_size=200),
    service=st.text(min_size=0, max_size=200),
    no_tls_verify=st.text(min_size=0, max_size=50),
    origin_server_name=st.text(min_size=0, max_size=100),
    http_host_header=st.text(min_size=0, max_size=100),
)
def test_fuzz_container_label_parsing_resilience(
    hostname: str,
    service: str,
    no_tls_verify: str,
    origin_server_name: str,
    http_host_header: str,
):
    """
    Fuzz test: Verify that arbitrary Docker label inputs never cause unhandled crashes
    in get_docker_containers() or ingress rule synthesis.
    """
    raw_labels = {
        "cf.tunnel.hostname": hostname,
        "cf.tunnel.service": service,
        "cf.tunnel.originRequest.noTLSVerify": no_tls_verify,
        "cf.tunnel.originRequest.originServerName": origin_server_name,
        "cf.tunnel.originRequest.httpHostHeader": http_host_header,
    }

    mock_container = {
        "Names": ["/fuzz-test-container"],
        "State": "running",
        "Labels": raw_labels,
        "NetworkSettings": {
            "Networks": {
                "cf-tunnel-net": {
                    "IPAddress": "172.18.0.2",
                    "Aliases": ["fuzz-test-container"],
                }
            }
        },
    }

    with patch("app.docker_api", return_value=[mock_container]):
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "CF_NETWORK_NAME": "cf-tunnel-net"}):
            # Must complete safely without raising uncaught exceptions
            try:
                services, containers = app.get_docker_containers()
                assert isinstance(services, list)
                assert isinstance(containers, list)
            except Exception as e:
                # Any exception raised indicates a crash vulnerability on malformed inputs
                raise AssertionError(f"Unhandled exception during label fuzzing: {type(e).__name__}: {e}") from e


@settings(max_examples=100, deadline=None)
@given(
    arbitrary_keys=st.dictionaries(
        keys=st.text(min_size=1, max_size=100),
        values=st.text(min_size=0, max_size=200),
        max_size=20,
    )
)
def test_fuzz_arbitrary_labels_dictionary(arbitrary_keys: dict):
    """
    Fuzz test: Verify resilience against arbitrary non-cf labels and malformed key spaces.
    """
    mock_container = {
        "Names": ["/random-label-container"],
        "State": "running",
        "Labels": arbitrary_keys,
        "NetworkSettings": {"Networks": {}},
    }

    with patch("app.docker_api", return_value=[mock_container]):
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            services, containers = app.get_docker_containers()
            assert isinstance(services, list)
            assert isinstance(containers, list)
