"""Hermetic tests for safe configuration schema validation, typo detection, and backward compatibility (Issue #54 - R07)."""

import os
import unittest
from unittest.mock import patch

from app import perform_startup_validation
from config import (
    KNOWN_ENV_VARS,
    LABEL_ALIASES,
    detect_env_typos,
    resolve_canonical_label,
    validate_tunnel_uuid,
)


class TestConfigValidation(unittest.TestCase):
    def test_known_env_vars_complete(self):
        """Ensure critical environment variables are part of the known set."""
        required = {
            "DOMAIN_NAME",
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_TUNNEL_NAME",
            "CLOUDFLARE_TUNNEL_ID",
            "PREFLIGHT_ONLY",
            "DRY_RUN",
            "MAX_DELETIONS_PER_SYNC",
            "ALLOW_MASS_DELETIONS",
            "LOG_FORMAT",
            "NOTIFICATION_WEBHOOK_URL",
        }
        for var in required:
            self.assertIn(var, KNOWN_ENV_VARS)

    def test_detect_env_typos_suggests_match(self):
        """Verify typos in configuration variables produce actionable suggestions."""
        env_sample = {
            "CLOUDFLARE_TUNNEL_NAM": "my-tunnel",
            "MAX_DELETIONS_PER_SYN": "5",
            "PREFLIGHT_ONL": "true",
            "PATH": "/usr/bin:/bin",  # Standard system var, should not trigger typo warning
            "HOME": "/home/user",
        }

        warnings = detect_env_typos(env_sample)
        warning_text = "\n".join(warnings)

        self.assertIn("CLOUDFLARE_TUNNEL_NAM", warning_text)
        self.assertIn("CLOUDFLARE_TUNNEL_NAME", warning_text)
        self.assertIn("MAX_DELETIONS_PER_SYN", warning_text)
        self.assertIn("MAX_DELETIONS_PER_SYNC", warning_text)
        self.assertNotIn("PATH", warning_text)
        self.assertNotIn("HOME", warning_text)

    def test_tunnel_uuid_validation(self):
        """Verify UUID validation handles valid and invalid UUID formats."""
        # Valid UUIDs
        valid_uuids = [
            "12345678-1234-4234-8234-123456789abc",
            "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            "A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11",
            None,
            "",
            "   ",
        ]
        for val in valid_uuids:
            is_valid, err = validate_tunnel_uuid(val)
            self.assertTrue(is_valid, f"Expected '{val}' to be valid UUID")
            self.assertIsNone(err)

        # Invalid UUIDs
        invalid_uuids = [
            "not-a-uuid",
            "12345678-1234-1234-1234",
            "12345678123412341234123456789abc",  # Missing hyphens
            "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
            "12345678-1234-1234-1234-123456789abcdef",  # Too long
        ]
        for val in invalid_uuids:
            is_valid, err = validate_tunnel_uuid(val)
            self.assertFalse(is_valid, f"Expected '{val}' to be invalid UUID")
            self.assertIsNotNone(err)
            self.assertIn("Invalid CLOUDFLARE_TUNNEL_ID", err)

    def test_startup_validation_exit_on_invalid_uuid(self):
        """Verify startup validation exits with code 1 when exit_on_error=True and UUID is invalid."""
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_ID": "invalid-uuid-format"}):
            with self.assertRaises(SystemExit) as ctx:
                perform_startup_validation(exit_on_error=True)
            self.assertEqual(ctx.exception.code, 1)

    def test_startup_validation_warns_without_exit(self):
        """Verify startup validation logs warning and returns errors when exit_on_error=False."""
        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_TUNNEL_NAM": "typo-tunnel",
                "CLOUDFLARE_TUNNEL_ID": "invalid-uuid",
            },
        ):
            warnings = perform_startup_validation(exit_on_error=False)
            self.assertTrue(any("CLOUDFLARE_TUNNEL_NAM" in w for w in warnings))
            self.assertTrue(any("Invalid CLOUDFLARE_TUNNEL_ID" in w for w in warnings))

    def test_historical_label_aliases_matrix(self):
        """100% test matrix verifying historical label aliases map to canonical equivalents."""
        expected_aliases = {
            "cloudflared.hostname": "cf.tunnel.hostname",
            "cloudflared.domain": "cf.tunnel.domain",
            "cloudflared.port": "cf.tunnel.port",
            "cloudflared.service": "cf.tunnel.service",
            "cloudflared.path": "cf.tunnel.path",
            "cloudflared.enable": "cf.tunnel.enable",
            "cloudflared.access.policy": "cf.tunnel.access.policy",
            "cf.tunnel.access_policy": "cf.tunnel.access.policy",
            "cf.tunnel.no_tls_verify": "cf.tunnel.originRequest.noTLSVerify",
            "cf.tunnel.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
            "cf.tunnel.originServerName": "cf.tunnel.originRequest.originServerName",
            "cf.tunnel.origin_server_name": "cf.tunnel.originRequest.originServerName",
            "cf.tunnel.httpHostHeader": "cf.tunnel.originRequest.httpHostHeader",
            "cf.tunnel.http_host_header": "cf.tunnel.originRequest.httpHostHeader",
        }

        for alias, canonical in expected_aliases.items():
            self.assertEqual(
                resolve_canonical_label(alias),
                canonical,
                f"Alias '{alias}' did not resolve to canonical '{canonical}'",
            )
            self.assertEqual(
                LABEL_ALIASES[alias],
                canonical,
            )


if __name__ == "__main__":
    unittest.main()
