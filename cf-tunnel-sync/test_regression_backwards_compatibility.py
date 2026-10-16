"""
QA Regression & Backwards Compatibility Test Suite for cf-docker-tunnel-sync

Validates:
1. Strict Zero Breaking Changes across existing docker-compose topologies:
   - Single-compose architectures (e.g. examples/01-single-compose)
   - Dual/multi-compose architectures (e.g. examples/02-multi-compose gateway + isolated service stacks)
   - Multi-account / scoped tunnel architectures (e.g. examples/03-multi-account)
2. Backwards compatibility for legacy label formats:
   - cloudflared.hostname, cloudflared.domain
   - cloudflared.port, bare 'port'
   - cloudflared.proto, cloudflared.protocol, cloudflared.scheme, bare 'proto'
   - cloudflared.service, bare 'service'
   - cloudflared.notlsverify, cloudflared.notls_verify, bare 'notlsverify'
   - cloudflared.name, cloudflared.tunnel
3. Precedence hierarchy:
   - cf.tunnel.* (modern) > cloudflared.* (legacy) > bare shorthand (proto, port, notlsverify)
"""

import os
import sys
import unittest
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import app


class TestComposeTopologiesRegression(unittest.TestCase):
    """
    Validates regression behavior against existing docker-compose architectures.
    """

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_TUNNEL_NAME": "cf-docker-tunnel-sync",
            "CLOUDFLARED_CONTAINER_NAME": ""
        })
        self.env_patcher.start()
        app.sync_state["status"] = "Initializing"
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["logs"] = []

    def tearDown(self):
        self.env_patcher.stop()

    @patch("app.docker_api")
    def test_examples_01_single_compose_architecture(self, mock_docker_api):
        """
        Simulate examples/01-single-compose/docker-compose.yml:
        - cloudflared sibling container
        - cf-tunnel-sync container
        - cf-tunnel-dashboard container
        - web-app with standard cf.tunnel.hostname and cf.tunnel.port
        """
        containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Status": "Up 2 hours",
                "Image": "cloudflare/cloudflared:latest",
                "Labels": {
                    "com.docker.compose.service": "cloudflared",
                    "com.docker.compose.project": "single-compose"
                }
            },
            {
                "Names": ["/cf-tunnel-sync"],
                "State": "running",
                "Status": "Up 2 hours",
                "Image": "hapheus/cf-tunnel-sync:latest",
                "Labels": {
                    "com.docker.compose.service": "cf-tunnel-sync",
                    "com.docker.compose.project": "single-compose"
                }
            },
            {
                "Names": ["/cf-tunnel-dashboard"],
                "State": "running",
                "Status": "Up 2 hours",
                "Image": "hapheus/cf-tunnel-dashboard:latest",
                "Labels": {
                    "com.docker.compose.service": "cf-tunnel-dashboard",
                    "com.docker.compose.project": "single-compose"
                }
            },
            {
                "Names": ["/single-compose-web-app-1"],
                "State": "running",
                "Status": "Up 2 hours",
                "Image": "traefik/whoami:latest",
                "Labels": {
                    "com.docker.compose.service": "web-app",
                    "com.docker.compose.project": "single-compose",
                    "cf.tunnel.hostname": "app.example.com",
                    "cf.tunnel.port": "80"
                }
            }
        ]
        mock_docker_api.return_value = containers

        # 1. Cloudflared auto-discovery
        c_name = app.find_cloudflared_container_name()
        self.assertEqual(c_name, "cloudflared")

        # 2. Container service extraction
        services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        svc = services[0]
        self.assertEqual(svc["hostname"], "app.example.com")
        self.assertEqual(svc["service"], "http://single-compose-web-app-1:80")
        self.assertFalse(svc.get("no_tls_verify", False))

        # 3. Ingress rule generation
        rules = app.build_ingress_rules(services)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]["hostname"], "app.example.com")
        self.assertEqual(rules[0]["service"], "http://single-compose-web-app-1:80")
        self.assertNotIn("originRequest", rules[0])
        self.assertEqual(rules[1], {"service": "http_status:404"})

    @patch("app.docker_api")
    def test_examples_02_multi_compose_architecture(self, mock_docker_api):
        """
        Simulate examples/02-multi-compose/:
        - Gateway stack: cloudflared + sync + dashboard
        - Isolated stacks: whoami (80), website (80), api (3000)
        All attached via external cf-tunnel-net network.
        """
        containers = [
            {
                "Names": ["/gateway-cloudflared-1"],
                "State": "running",
                "Status": "Up 5 hours",
                "Image": "cloudflare/cloudflared:latest",
                "Labels": {"com.docker.compose.project": "gateway", "com.docker.compose.service": "cloudflared"}
            },
            {
                "Names": ["/service-whoami-whoami-1"],
                "State": "running",
                "Status": "Up 3 hours",
                "Image": "traefik/whoami:latest",
                "Labels": {
                    "cf.tunnel.hostname": "whoami.example.com",
                    "cf.tunnel.port": "80"
                }
            },
            {
                "Names": ["/service-website-web-1"],
                "State": "running",
                "Status": "Up 3 hours",
                "Image": "nginx:alpine",
                "Labels": {
                    "cf.tunnel.hostname": "www.example.com",
                    "cf.tunnel.port": "80"
                }
            },
            {
                "Names": ["/service-api-backend-1"],
                "State": "running",
                "Status": "Up 3 hours",
                "Image": "node:alpine",
                "Labels": {
                    "cf.tunnel.hostname": "api.example.com",
                    "cf.tunnel.port": "3000"
                }
            }
        ]
        mock_docker_api.return_value = containers

        services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 3)

        rules = app.build_ingress_rules(services)
        # Deterministic sorting: api.example.com, whoami.example.com, www.example.com
        hostnames = [r["hostname"] for r in rules if "hostname" in r]
        self.assertEqual(hostnames, ["api.example.com", "whoami.example.com", "www.example.com"])
        self.assertEqual(rules[-1]["service"], "http_status:404")

    @patch("app.docker_api")
    def test_examples_03_multi_account_tunnel_scoping(self, mock_docker_api):
        """
        Simulate examples/03-multi-account/:
        Two gateway instances scoped by CLOUDFLARE_TUNNEL_NAME:
        - personal-tunnel only synchronizes containers marked cf.tunnel.name=personal-tunnel
        - business-tunnel only synchronizes containers marked cf.tunnel.name=business-tunnel
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/personal-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": "me.example.com",
                    "cf.tunnel.name": "personal-tunnel"
                }
            },
            {
                "Names": ["/business-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": "corp.example.com",
                    "cf.tunnel.name": "business-tunnel"
                }
            }
        ]

        # Scenario A: Scoped to personal-tunnel
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_NAME": "personal-tunnel"}):
            services, _ = app.get_docker_containers()
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["hostname"], "me.example.com")

        # Scenario B: Scoped to business-tunnel
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_NAME": "business-tunnel"}):
            services, _ = app.get_docker_containers()
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["hostname"], "corp.example.com")


class TestLegacyLabelBackwardsCompatibility(unittest.TestCase):
    """
    Validates backward compatibility for legacy label keys:
    - cloudflared.*
    - bare shorthand (proto, notlsverify, port, service)
    - precedence hierarchy
    """

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_TUNNEL_NAME": "cf-docker-tunnel-sync"
        })
        self.env_patcher.start()
        app.sync_state["status"] = "Initializing"
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["logs"] = []

    def tearDown(self):
        self.env_patcher.stop()

    @patch("app.docker_api")
    def test_legacy_cloudflared_hostname_and_port(self, mock_docker_api):
        """
        Legacy containers using cloudflared.hostname and cloudflared.port.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/legacy-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "legacy.example.com",
                    "cloudflared.port": "8080"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["hostname"], "legacy.example.com")
        self.assertEqual(services[0]["service"], "http://legacy-app:8080")

    @patch("app.docker_api")
    def test_legacy_cloudflared_domain_fallback(self, mock_docker_api):
        """
        Legacy containers using cloudflared.domain instead of hostname.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/legacy-domain-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.domain": "domain-legacy.example.com"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["hostname"], "domain-legacy.example.com")
        self.assertEqual(services[0]["service"], "http://legacy-domain-app:80")

    @patch("app.docker_api")
    def test_legacy_cloudflared_proto_and_protocol(self, mock_docker_api):
        """
        Legacy containers using cloudflared.proto or cloudflared.protocol.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/legacy-proto-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "proto.example.com",
                    "cloudflared.proto": "https"
                }
            },
            {
                "Names": ["/legacy-protocol-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "protocol.example.com",
                    "cloudflared.protocol": "https",
                    "cloudflared.port": "8443"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        svc_map = {s["hostname"]: s for s in services}
        self.assertIn("proto.example.com", svc_map)
        self.assertEqual(svc_map["proto.example.com"]["service"], "https://legacy-proto-app:443")
        self.assertIn("protocol.example.com", svc_map)
        self.assertEqual(svc_map["protocol.example.com"]["service"], "https://legacy-protocol-app:8443")

    @patch("app.docker_api")
    def test_legacy_shorthand_proto_and_port(self, mock_docker_api):
        """
        Bare shorthand labels: 'proto' and 'port'.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/shorthand-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": "shorthand.example.com",
                    "proto": "https",
                    "port": "9443"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["hostname"], "shorthand.example.com")
        self.assertEqual(services[0]["service"], "https://shorthand-app:9443")

    @patch("app.docker_api")
    def test_legacy_shorthand_notlsverify(self, mock_docker_api):
        """
        Bare shorthand label: 'notlsverify=true'.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/notls-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": "notls.example.com",
                    "cf.tunnel.protocol": "https",
                    "notlsverify": "true"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0].get("no_tls_verify"))

        rules = app.build_ingress_rules(services)
        self.assertEqual(rules[0]["originRequest"], {"noTLSVerify": True})

    @patch("app.docker_api")
    def test_legacy_cloudflared_notlsverify(self, mock_docker_api):
        """
        Legacy cloudflared.notlsverify / cloudflared.notls_verify label.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/cf-notls-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "cf-notls.example.com",
                    "cloudflared.proto": "https",
                    "cloudflared.notlsverify": "1"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0].get("no_tls_verify"))

        rules = app.build_ingress_rules(services)
        self.assertEqual(rules[0]["originRequest"], {"noTLSVerify": True})

    @patch("app.docker_api")
    def test_legacy_cloudflared_service_override(self, mock_docker_api):
        """
        Legacy cloudflared.service direct URI override.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/direct-svc-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "direct.example.com",
                    "cloudflared.service": "https://custom-target:9000"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service"], "https://custom-target:9000")

    @patch("app.docker_api")
    def test_legacy_cloudflared_name_and_tunnel_scoping(self, mock_docker_api):
        """
        Legacy cloudflared.name and cloudflared.tunnel scoping labels.
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/scoped-name-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "name-scope.example.com",
                    "cloudflared.name": "legacy-tunnel"
                }
            },
            {
                "Names": ["/scoped-tunnel-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "tunnel-scope.example.com",
                    "cloudflared.tunnel": "legacy-tunnel"
                }
            },
            {
                "Names": ["/other-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cloudflared.hostname": "other.example.com",
                    "cloudflared.name": "different-tunnel"
                }
            }
        ]
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_NAME": "legacy-tunnel"}):
            services, _ = app.get_docker_containers()
            self.assertEqual(len(services), 2)
            hostnames = {s["hostname"] for s in services}
            self.assertEqual(hostnames, {"name-scope.example.com", "tunnel-scope.example.com"})

    @patch("app.docker_api")
    def test_precedence_hierarchy_modern_over_legacy_over_shorthand(self, mock_docker_api):
        """
        Precedence must be strictly maintained:
        1. cf.tunnel.* (modern)
        2. cloudflared.* (legacy)
        3. bare shorthand (proto, port, notlsverify)
        """
        mock_docker_api.return_value = [
            {
                "Names": ["/precedence-app"],
                "State": "running",
                "Status": "Up",
                "Labels": {
                    # Hostname
                    "cf.tunnel.hostname": "modern.example.com",
                    "cloudflared.hostname": "legacy.example.com",
                    # Port
                    "cf.tunnel.port": "8081",
                    "cloudflared.port": "8082",
                    "port": "8083",
                    # Protocol
                    "cf.tunnel.protocol": "https",
                    "cloudflared.proto": "http",
                    "proto": "http",
                    # TLS Verify
                    "cf.tunnel.notlsverify": "true",
                    "cloudflared.notlsverify": "false",
                    "notlsverify": "false"
                }
            }
        ]
        services, _ = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        svc = services[0]
        # cf.tunnel.hostname wins over cloudflared.hostname
        self.assertEqual(svc["hostname"], "modern.example.com")
        # cf.tunnel.protocol (https) + cf.tunnel.port (8081) win
        self.assertEqual(svc["service"], "https://precedence-app:8081")
        # cf.tunnel.notlsverify (true) wins
        self.assertTrue(svc["no_tls_verify"])


if __name__ == "__main__":
    unittest.main()
