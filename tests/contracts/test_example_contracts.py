"""Isolated behavioral checks for the documented deployment examples."""

import os
import re
import shlex
import shutil
import subprocess
from copy import deepcopy
from unittest.mock import patch

import pytest
import yaml

import app
from tests.paths import REPO_ROOT

ROOT = REPO_ROOT
EXAMPLES = ROOT / "examples"
COMPOSE_FILES = sorted(EXAMPLES.rglob("docker-compose*.yml"))
VARIABLE = re.compile(r"\$\{(\w+)(?:(:-|:\?)([^}]*))?\}")


@pytest.fixture(autouse=True)
def isolate_discovery_state():
    with patch.dict(app.sync_state, deepcopy(app.sync_state), clear=True):
        yield


def read_environment(path):
    return {
        key: value
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }


def render_example(path, overrides=None):
    values = read_environment(path.parent / ".env.example")
    values.update(
        CLOUDFLARE_API_TOKEN="dummy-token",
        CLOUDFLARE_ACCOUNT_ID="dummy-account",
        BASIC_AUTH_PASSWORD="dummy-dashboard-password",
        POSTGRES_PASSWORD="dummy-database-password",
        CF_NETWORK_NAME="custom-example-network",
    )
    values.update(overrides or {})

    def substitute(match):
        key, operator, default = match.groups()
        value = values.get(key, "")
        if value:
            return value
        if operator == ":?":
            raise AssertionError(f"Missing example input: {key}")
        return default or ""

    return yaml.safe_load(VARIABLE.sub(substitute, path.read_text()))


def service_environment(service):
    entries = service.get("environment", {})
    return dict(entry.split("=", 1) for entry in entries) if isinstance(entries, list) else entries


@pytest.mark.parametrize("template", sorted(EXAMPLES.rglob(".env.example")))
def test_environment_templates_only_advertise_inputs_used_by_their_compose_files(template):
    references = {
        match[0]
        for compose in template.parent.glob("docker-compose*.yml")
        for match in VARIABLE.findall(compose.read_text())
    }
    assert set(read_environment(template)) <= references


@pytest.mark.parametrize("path", COMPOSE_FILES)
def test_custom_network_and_account_settings_reach_the_actual_services(path):
    config = render_example(path)
    assert config["networks"]["cf-tunnel-net"]["name"] == "custom-example-network"
    sync = config["services"].get("cf-tunnel-sync")
    if sync:
        environment = service_environment(sync)
        assert environment["CF_NETWORK_NAME"] == "custom-example-network"
        assert environment["CLOUDFLARE_ACCOUNT_ID"] == "dummy-account"
        assert environment["CLOUDFLARED_CONTAINER_NAME"] == config["services"]["cloudflared"]["container_name"]


@pytest.mark.parametrize(
    "path", [path for path in COMPOSE_FILES if "cf-tunnel-dashboard" in yaml.safe_load(path.read_text())["services"]]
)
def test_disabled_dashboard_auth_remains_configurable_without_a_password(path):
    config = render_example(path, {"DASHBOARD_AUTH_ENABLED": "false", "BASIC_AUTH_PASSWORD": ""})
    environment = service_environment(config["services"]["cf-tunnel-dashboard"])
    assert environment["DASHBOARD_AUTH_ENABLED"] == "false"
    assert environment["BASIC_AUTH_PASSWORD"] == ""


@pytest.mark.parametrize("path", COMPOSE_FILES)
def test_documented_application_labels_are_consumed_by_real_discovery(path):
    config = render_example(path)
    services = config["services"]
    environment = service_environment(services.get("cf-tunnel-sync", {}))
    environment.setdefault("DOMAIN_NAME", read_environment(path.parent / ".env.example")["DOMAIN_NAME"])
    environment.setdefault("CF_NETWORK_NAME", "custom-example-network")
    inventory = []
    expected = {}
    for name, service in services.items():
        labels = dict(entry.split("=", 1) for entry in service.get("labels", []))
        hostname = labels.get("cf.tunnel.hostname")
        if hostname:
            expected[hostname] = labels
        inventory.append(
            {
                "Id": name,
                "Names": ["/" + service.get("container_name", name)],
                "Image": service["image"],
                "State": "running",
                "Labels": labels,
                "NetworkSettings": {
                    "Networks": {
                        config["networks"][network].get("name", network): {} for network in service["networks"]
                    }
                },
                "Ports": [{"PrivatePort": 80}],
            }
        )
    with patch.dict(os.environ, environment, clear=True), patch.object(app, "docker_api", return_value=inventory):
        discovered, _ = app.get_docker_containers()
    assert {origin["hostname"] for origin in discovered} == set(expected)
    for origin in discovered:
        labels = expected[origin["hostname"]]
        if "cf.tunnel.service" in labels:
            assert origin["service"] == labels["cf.tunnel.service"]
        elif "cf.tunnel.port" in labels:
            assert origin["service"].endswith(":" + labels["cf.tunnel.port"])
        if "cf.tunnel.httpHostHeader" in labels:
            assert origin["originRequest"]["httpHostHeader"] == labels["cf.tunnel.httpHostHeader"]
        if "cf.tunnel.originServerName" in labels:
            assert origin["originRequest"]["originServerName"] == labels["cf.tunnel.originServerName"]
        if labels.get("cf.tunnel.originRequest.noTLSVerify") == "true":
            assert origin["originRequest"]["noTLSVerify"] is True


def test_two_gateway_connector_selection_is_unambiguous_even_with_reversed_inventory():
    stacks = [render_example(path) for path in COMPOSE_FILES if "05-multi-account" in path.parts]
    names = [stack["services"]["cloudflared"]["container_name"] for stack in stacks]
    assert len(set(names)) == 2
    inventory = [
        {"Id": f"connector-{index}", "Names": ["/" + name], "Labels": {"com.docker.compose.service": "cloudflared"}}
        for index, name in enumerate(names)
    ]
    for stack in stacks:
        environment = service_environment(stack["services"]["cf-tunnel-sync"])
        for candidates in (inventory, list(reversed(inventory))):
            with patch.dict(os.environ, environment, clear=True):
                connector = app.resolve_target_connector_container(candidates)
            assert connector["Names"] == ["/" + environment["CLOUDFLARED_CONTAINER_NAME"]]


def test_connector_start_gate_rejects_a_missing_or_empty_token(tmp_path):
    commands = set()
    for path in COMPOSE_FILES:
        services = render_example(path)["services"]
        if "cloudflared" not in services:
            continue
        assert services["cloudflared"]["depends_on"]["cf-tunnel-sync"]["condition"] == "service_healthy"
        command = services["cf-tunnel-sync"]["healthcheck"]["test"]
        assert command[0] == "CMD-SHELL"
        commands.add(command[1])
    token = tmp_path / "token"
    (tmp_path / "healthcheck.py").write_text("raise SystemExit(0)\n")
    for command in commands:
        actual = command.replace("/etc/cloudflared/token", shlex.quote(str(token)))
        assert subprocess.run(["sh", "-c", actual], cwd=tmp_path, check=False).returncode != 0
        token.touch()
        assert subprocess.run(["sh", "-c", actual], cwd=tmp_path, check=False).returncode != 0
        token.write_text("dummy-token")
        assert subprocess.run(["sh", "-c", actual], cwd=tmp_path, check=False).returncode == 0
        token.unlink()


def test_documented_certificate_command_generates_a_valid_matching_key_and_certificate(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("Local OpenSSL is required for certificate-command validation")
    text = (EXAMPLES / "04-advanced-labels-tls-multiport/README.md").read_text()
    command = re.search(r"^openssl req .*?(?=\n```)", text, re.M | re.S).group(0).replace("\\\n", " ")
    (tmp_path / "certs").mkdir()
    result = subprocess.run(shlex.split(command), cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    certificate = tmp_path / "certs/origin.crt"
    private_key = tmp_path / "certs/origin.key"
    subprocess.run([openssl, "x509", "-in", str(certificate), "-noout", "-checkhost", "origin.internal"], check=True)
    cert_public = subprocess.check_output([openssl, "x509", "-in", str(certificate), "-pubkey", "-noout"])
    key_public = subprocess.check_output([openssl, "pkey", "-in", str(private_key), "-pubout"])
    assert cert_public == key_public


def test_advanced_origin_targets_match_the_listeners_configured_in_the_example():
    path = EXAMPLES / "04-advanced-labels-tls-multiport/docker-compose.yml"
    services = render_example(path)["services"]
    for name in ("app-selfsigned-https", "app-custom-headers"):
        service = services[name]
        arguments = dict(argument.removeprefix("--").split("=", 1) for argument in service["command"])
        labels = dict(label.split("=", 1) for label in service["labels"])
        assert arguments["port"] == "8443"
        assert arguments["cert"] == "/certs/origin.crt"
        assert arguments["key"] == "/certs/origin.key"
        assert "./certs:/certs:ro" in service["volumes"]
        assert labels.get("cf.tunnel.protocol") == "https" or labels["cf.tunnel.service"].startswith("https://")
    multip = services["app-multi-port"]
    label_port = dict(label.split("=", 1) for label in multip["labels"])["cf.tunnel.port"]
    nginx = (path.parent / "multiport.conf").read_text()
    listeners = set(re.findall(r"listen\s+(\d+);", nginx))
    assert len(listeners) > 1 and label_port in listeners
    assert label_port != "80"
    assert "$server_port" in nginx
