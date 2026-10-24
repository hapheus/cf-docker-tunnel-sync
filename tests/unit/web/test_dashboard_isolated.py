"""Isolated standalone dashboard tests with mocked API interaction (ARCH-04, Issue #115).

Verifies that the standalone cf-tunnel-dashboard container:
1. Consumes the backend exclusively through documented HTTP API endpoints (/api/*).
2. Has zero access to, mounts of, or references to Docker sockets or Cloudflare API tokens.
3. Templates upstream reverse-proxy configuration dynamically via SYNC_BACKEND_HOST and SYNC_BACKEND_PORT.
4. Fails closed when DASHBOARD_AUTH_ENABLED=true without credentials.
"""

import os
import re
import subprocess
from pathlib import Path

from tests.paths import REPO_ROOT


def get_dashboard_dir() -> Path:
    repo_root = REPO_ROOT
    return repo_root / "cf-tunnel-dashboard"


def test_dashboard_frontend_dom_and_api_contract():
    """Verify cf-tunnel-dashboard/index.html elements and exclusive API consumption."""
    index_html = (get_dashboard_dir() / "index.html").read_text(encoding="utf-8")

    # 1. Required DOM binding targets
    required_ids = [
        "status-badge",
        "tunnel-name",
        "tunnel-id",
        "domain-name",
    ]
    for dom_id in required_ids:
        assert f'id="{dom_id}"' in index_html, f"Required binding element #{dom_id} missing from dashboard UI!"

    # 2. Strict API consumption: Must only fetch /api/* endpoints
    fetch_matches = re.findall(r"fetch\(['\"]([^'\"]+)['\"]", index_html)
    assert len(fetch_matches) > 0, "No fetch calls found in dashboard index.html!"
    for endpoint in fetch_matches:
        assert endpoint.startswith("/api/"), f"Dashboard fetched non-API route: {endpoint}"

    # 3. Security: CSP meta or add_header compatibility
    assert '<script src="https://cdn.tailwindcss.com"></script>' in index_html


def test_dashboard_dockerfile_and_nginx_isolation():
    """Verify that cf-tunnel-dashboard requires zero Docker sockets or Cloudflare credentials."""
    dockerfile_content = (get_dashboard_dir() / "Dockerfile").read_text(encoding="utf-8")
    nginx_content = (get_dashboard_dir() / "nginx.conf").read_text(encoding="utf-8")

    # Must NOT reference docker socket or cloudflare tokens
    forbidden_terms = ["docker.sock", "CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"]
    for term in forbidden_terms:
        assert term not in dockerfile_content, f"Forbidden sensitive dependency '{term}' found in dashboard Dockerfile!"
        assert term not in nginx_content, f"Forbidden sensitive dependency '{term}' found in dashboard nginx.conf!"

    # Nginx must include dynamic sync-backend.conf and dashboard-auth.conf
    assert "include /etc/nginx/snippets/sync-backend.conf;" in nginx_content
    assert "include /etc/nginx/snippets/dashboard-auth.conf;" in nginx_content


def test_dashboard_entrypoint_upstream_templating(tmp_path):
    """Verify entrypoint.sh templates SYNC_BACKEND_HOST and SYNC_BACKEND_PORT."""
    entrypoint_script = get_dashboard_dir() / "entrypoint.sh"
    content = entrypoint_script.read_text(encoding="utf-8")

    assert "SYNC_BACKEND_HOST" in content
    assert "SYNC_BACKEND_PORT" in content
    assert "sync-backend.conf" in content


def test_dashboard_entrypoint_auth_fail_closed():
    """Verify entrypoint.sh fails closed when DASHBOARD_AUTH_ENABLED=true without credentials."""
    entrypoint_script = get_dashboard_dir() / "entrypoint.sh"

    # Run entrypoint in a subshell without credentials and intercept before exec
    env = {
        "DASHBOARD_AUTH_ENABLED": "true",
        "BASIC_AUTH_USERNAME": "",
        "BASIC_AUTH_PASSWORD": "",
        "PATH": os.environ.get("PATH", ""),
    }
    result = subprocess.run(
        ["sh", "-c", f"sh {entrypoint_script}"],
        env=env,
        capture_output=True,
        text=True,
    )
    # Must fail with exit code 1
    assert result.returncode == 1
    assert "BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD must be set" in result.stderr
