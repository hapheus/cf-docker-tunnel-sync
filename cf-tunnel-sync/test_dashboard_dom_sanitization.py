import re
import subprocess
from pathlib import Path

import app
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
EMBEDDED_INDEX_PATH = REPO_ROOT / "cf-tunnel-sync" / "static" / "index.html"
STANDALONE_INDEX_PATH = REPO_ROOT / "cf-tunnel-dashboard" / "index.html"


def extract_js_from_html(html_content: str) -> str:
    """Extract all inline script content from HTML."""
    scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html_content, re.DOTALL | re.IGNORECASE)
    return "\n".join(s for s in scripts if "fetchStatus" in s or "escapeHtml" in s or "sanitizeUrl" in s)


def run_js(js_code: str) -> str:
    """Execute a JS snippet using Node.js and return standard output."""
    mock_env = """
    const document = {
        getElementById: () => ({ innerText: '', textContent: '', className: '', firstChild: null, removeChild: () => {}, appendChild: () => {} }),
        createElement: () => ({ setAttribute: () => {}, appendChild: () => {} }),
        createElementNS: () => ({ setAttribute: () => {}, appendChild: () => {} }),
    };
    const window = { location: { reload: () => {} } };
    const setInterval = () => {};
    const fetch = () => Promise.resolve({ status: 200, json: () => Promise.resolve({}) });
    """
    full_code = f"{mock_env}\n{js_code}"
    res = subprocess.run(
        ["node", "-e", full_code],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


class TestDashboardDomSanitization:
    """Hermetic tests for Dashboard DOM sink sanitization and XSS prevention (Issue #44 / F05)."""

    def test_tc_44_01_container_name_escaped(self):
        """TC-44-01: Container Name with <script>alert(1)</script> must be sanitized/escaped."""
        raw_html = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        js_code = extract_js_from_html(raw_html)

        assert "function escapeHtml" in js_code, "escapeHtml function must be defined in dashboard script"

        test_payload = "<script>alert(1)</script>"
        runner = f"""
        {js_code}
        console.log(escapeHtml({test_payload!r}));
        """
        escaped = run_js(runner)
        assert escaped == "&lt;script&gt;alert(1)&lt;/script&gt;"
        assert "<script>" not in escaped

    def test_tc_44_02_container_image_escaped(self):
        """TC-44-02: Container Image with attributes/quotes must be sanitized/escaped."""
        raw_html = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        js_code = extract_js_from_html(raw_html)

        test_payload = 'nginx:latest"<img src=x onerror=alert(1)>'
        runner = f"""
        {js_code}
        console.log(escapeHtml({test_payload!r}));
        """
        escaped = run_js(runner)
        assert "<img" not in escaped
        assert "&quot;" in escaped or "&#039;" in escaped or "&lt;img" in escaped
        assert "&lt;" in escaped and "&gt;" in escaped

    def test_tc_44_03_hostname_link_sanitize_url(self):
        """TC-44-03: Hostname link must neutralize javascript: and pseudo-protocols."""
        raw_html = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        js_code = extract_js_from_html(raw_html)

        assert "function sanitizeUrl" in js_code, "sanitizeUrl function must be defined in dashboard script"

        malicious_vectors = [
            "javascript:alert(document.cookie)",
            "javascript:alert(1)",
            "JAVASCRIPT:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ]
        for vec in malicious_vectors:
            runner = f"""
            {js_code}
            console.log(sanitizeUrl({vec!r}));
            """
            result = run_js(runner)
            assert result == "#", f"Vector '{vec}' was not blocked, got: {result}"

        # Legitimate hosts
        valid_hosts = [
            ("app.example.com", "https://app.example.com/"),
            ("https://app.example.com", "https://app.example.com/"),
            ("http://internal.local:8080", "http://internal.local:8080/"),
        ]
        for host, expected_prefix in valid_hosts:
            runner = f"""
            {js_code}
            console.log(sanitizeUrl({host!r}));
            """
            result = run_js(runner)
            assert result.startswith(expected_prefix) or result == expected_prefix.rstrip("/"), (
                f"Valid host '{host}' produced unexpected sanitized url: {result}"
            )

    def test_tc_44_04_container_service_escaped(self):
        """TC-44-04: Container service strings with HTML tags are escaped."""
        raw_html = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        js_code = extract_js_from_html(raw_html)

        test_payload = "http://10.0.0.1:8080<b onmouseover=alert(1)>"
        runner = f"""
        {js_code}
        console.log(escapeHtml({test_payload!r}));
        """
        escaped = run_js(runner)
        assert "<b" not in escaped
        assert "&lt;b" in escaped

        # sanitizeUrl should also reject URLs with embedded angle brackets
        runner_url = f"""
        {js_code}
        console.log(sanitizeUrl({test_payload!r}));
        """
        sanitized_url = run_js(runner_url)
        assert sanitized_url == "#"

    def test_tc_44_05_log_stream_escaped(self):
        """TC-44-05: Log entries with SVG/HTML payloads are properly escaped."""
        raw_html = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        js_code = extract_js_from_html(raw_html)

        test_payload = "[ERROR] Failed container: <svg/onload=alert(1)>"
        runner = f"""
        {js_code}
        console.log(escapeHtml({test_payload!r}));
        """
        escaped = run_js(runner)
        assert "<svg" not in escaped
        assert "&lt;svg" in escaped

    def test_tc_44_06_template_parity_and_no_unsafe_innerhtml(self):
        """TC-44-06: Embedded and standalone index.html must be in parity and free of dynamic innerHTML sinks."""
        embedded_content = EMBEDDED_INDEX_PATH.read_text(encoding="utf-8")
        standalone_content = STANDALONE_INDEX_PATH.read_text(encoding="utf-8")

        # PARITY: Script logic should be identical
        js_embedded = extract_js_from_html(embedded_content)
        js_standalone = extract_js_from_html(standalone_content)
        assert js_embedded == js_standalone, "Embedded and standalone dashboard scripts must be identical in parity"

        # No dynamic innerHTML sinks in either file
        for label, content in [("embedded", embedded_content), ("standalone", standalone_content)]:
            unsafe_inner_html = re.findall(
                r"\.innerHTML\s*=\s*([^\n;]+)",
                content,
            )
            for sink in unsafe_inner_html:
                stripped = sink.strip()
                assert stripped in ("''", '""'), f"Found unsafe innerHTML sink in {label} dashboard: {stripped}"

    def test_csp_meta_tag_present(self):
        """Both embedded and standalone dashboards must define CSP meta tags."""
        for path in [EMBEDDED_INDEX_PATH, STANDALONE_INDEX_PATH]:
            content = path.read_text(encoding="utf-8")
            assert 'http-equiv="Content-Security-Policy"' in content, f"Missing CSP meta tag in {path.name}"
            assert "default-src 'self'" in content
            assert "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com" in content

    def test_fastapi_dashboard_security_headers(self):
        """FastAPI / and /dashboard endpoints must return CSP and defensive security headers."""
        client = TestClient(app.app)
        for route in ["/", "/dashboard"]:
            resp = client.get(route)
            assert resp.status_code == 200
            assert "Content-Security-Policy" in resp.headers
            csp = resp.headers["Content-Security-Policy"]
            assert "default-src 'self'" in csp
            assert "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com" in csp
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("X-Frame-Options") == "DENY"
