"""Isolated contracts for settings."""

from tunnel_sync.configuration.settings import Settings


def test_settings_copy_environment_and_hide_secrets_in_repr():
    environment = {"CLOUDFLARE_API_TOKEN": "private", "DOMAIN_NAME": "Example.COM."}
    settings = Settings(environment)
    environment["DOMAIN_NAME"] = "changed.example"
    assert settings.domain == "example.com"
    assert "private" not in repr(settings)
