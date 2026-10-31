"""Isolated contracts for settings."""

import logging

from tunnel_sync.configuration.settings import Settings


def test_settings_copy_environment_and_hide_secrets_in_repr():
    environment = {"CLOUDFLARE_API_TOKEN": "private", "DOMAIN_NAME": "Example.COM."}
    settings = Settings(environment)
    environment["DOMAIN_NAME"] = "changed.example"
    assert settings.domain == "example.com"
    assert "private" not in repr(settings)


def test_settings_normalizes_legacy_basic_auth_and_emits_deprecation_warning(caplog):
    environment = {
        "BASIC_AUTH_USERNAME": "operator",
        "BASIC_AUTH_PASSWORD": "secret_password",
    }
    with caplog.at_level(logging.WARNING):
        settings = Settings(environment)

    assert settings.get("DASHBOARD_USERNAME") == "operator"
    assert settings.get("DASHBOARD_PASSWORD") == "secret_password"
    assert settings.get("BASIC_AUTH_USERNAME") == "operator"
    assert any("BASIC_AUTH_USERNAME' is deprecated" in record.message for record in caplog.records)
    assert any("BASIC_AUTH_PASSWORD' is deprecated" in record.message for record in caplog.records)


def test_settings_canonical_credentials_take_precedence_without_warning(caplog):
    environment = {
        "DASHBOARD_USERNAME": "canonical_user",
        "DASHBOARD_PASSWORD": "canonical_password",
        "BASIC_AUTH_USERNAME": "ignored_legacy",
    }
    with caplog.at_level(logging.WARNING):
        settings = Settings(environment)

    assert settings.get("DASHBOARD_USERNAME") == "canonical_user"
    assert settings.get("DASHBOARD_PASSWORD") == "canonical_password"
    assert not any("BASIC_AUTH_USERNAME is deprecated" in record.message for record in caplog.records)
