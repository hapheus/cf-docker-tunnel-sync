"""Preflight CLI output in a fresh process without provider connections."""

import subprocess
import sys
import textwrap

import pytest

from tests.paths import REPO_ROOT


@pytest.mark.parametrize("environment_only", [False, True])
def test_preflight_cli_prints_checks_and_success(environment_only):
    code = textwrap.dedent(
        """
        from tests.fakes import composition
        from tunnel_sync.runtime import cli

        services, cloudflare, _, _ = composition()
        request = cloudflare.request

        def read(endpoint, *args, **kwargs):
            if endpoint == '/user/tokens/verify':
                return {'result': {'status': 'active'}}
            return request(endpoint, *args, **kwargs)

        services.preflight.cloudflare._request = read
        cli.create_services = lambda settings: services
        cli.main()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code, *([] if environment_only else ["--preflight"])],
        cwd=REPO_ROOT,
        env={"PREFLIGHT_ONLY": "true"} if environment_only else {},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[PREFLIGHT PASS] Docker daemon connected" in result.stderr
    assert "[PREFLIGHT PASS] Cloudflare API token verified" in result.stderr
    assert "[PREFLIGHT PASS] Cloudflare Zone verified" in result.stderr
    assert "[PREFLIGHT SUCCESS]" in result.stderr
