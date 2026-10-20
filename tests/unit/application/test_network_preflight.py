import os
import unittest
from unittest.mock import patch

import app
from app import NetworkPlausibilityResult, evaluate_origin_network_plausibility


class TestNetworkPreflight(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["_deprecations_warned"] = set()

    def test_tc_45_01_shared_network_plausibility_and_e2e(self):
        """TC-45-01: Shared Network Match across container and connector."""
        res = evaluate_origin_network_plausibility(
            service_target="http://web-app:80",
            container_networks={"homelab-net"},
            container_network_mode=None,
            connector_networks={"homelab-net", "bridge"},
        )
        self.assertIsInstance(res, NetworkPlausibilityResult)
        self.assertTrue(res.is_plausible)
        self.assertEqual(res.connection_mode, "shared_docker_network")
        self.assertIn("homelab-net", res.shared_networks)

        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"homelab-net": {}}},
            },
            {
                "Names": ["/web-app"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "web.example.com",
                    "cf.tunnel.port": "80",
                },
                "NetworkSettings": {"Networks": {"homelab-net": {}}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])

    def test_tc_45_02_disjoint_networks_detection(self):
        """TC-45-02: Disjoint Networks Detection with clear remediation diagnostic."""
        res = evaluate_origin_network_plausibility(
            service_target="http://app-frontend:3000",
            container_networks={"frontend-net"},
            container_network_mode=None,
            connector_networks={"backend-net"},
        )
        self.assertFalse(res.is_plausible)
        self.assertEqual(res.connection_mode, "disjoint")
        self.assertEqual(res.shared_networks, [])
        self.assertIn("frontend-net", res.diagnostic_message)
        self.assertIn("backend-net", res.diagnostic_message)
        self.assertIn("502 Bad Gateway", res.diagnostic_message)

        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"backend-net": {}}},
            },
            {
                "Names": ["/app-frontend"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "frontend.example.com",
                    "cf.tunnel.port": "3000",
                },
                "NetworkSettings": {"Networks": {"frontend-net": {}}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "STRICT_NETWORK_CHECK": "false"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertFalse(services[0]["network_connected"])
        self.assertIn("network_warning", services[0])
        self.assertIn("Missing shared network", services[0]["network_warning"])

    def test_tc_45_03_multi_connector_host_scoping(self):
        """TC-45-03: Multi-Connector Host - Ensure unrelated cloudflared containers do not leak networks."""
        mock_containers = [
            {
                "Id": "cf-target-id",
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"net-a": {}}},
            },
            {
                "Id": "cf-other-id",
                "Names": ["/cloudflared-secondary"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared-secondary"},
                "NetworkSettings": {"Networks": {"net-b": {}}},
            },
            {
                "Names": ["/app-on-b"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "b.example.com",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"net-b": {}}},
            },
        ]
        # Target connector is default 'cloudflared' (on net-a). App is on net-b -> Disjoint
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "CLOUDFLARED_CONTAINER_NAME": "cloudflared"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertFalse(services[0]["network_connected"])
        self.assertIn("network_warning", services[0])

        # Target connector changed to 'cloudflared-secondary' (on net-b) -> Connected
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(
                os.environ, {"DOMAIN_NAME": "example.com", "CLOUDFLARED_CONTAINER_NAME": "cloudflared-secondary"}
            ):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])

    def test_tc_45_04_host_network_mode_awareness(self):
        """TC-45-04: Host Network Mode container resolves via host without false warning."""
        res_container = evaluate_origin_network_plausibility(
            service_target="http://host-app:8080",
            container_networks=set(),
            container_network_mode="host",
            connector_networks={"bridge"},
        )
        self.assertTrue(res_container.is_plausible)
        self.assertEqual(res_container.connection_mode, "host_mode")

        res_net = evaluate_origin_network_plausibility(
            service_target="http://host-app:8080",
            container_networks={"host"},
            container_network_mode=None,
            connector_networks={"bridge"},
        )
        self.assertTrue(res_net.is_plausible)
        self.assertEqual(res_net.connection_mode, "host_mode")

        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"bridge": {}}},
            },
            {
                "Names": ["/host-app"],
                "State": "running",
                "HostConfig": {"NetworkMode": "host"},
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "hostapp.example.com",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])

    def test_tc_45_05_loopback_and_gateway_host_target(self):
        """TC-45-05: Gateway / host loopback targets (host.docker.internal, 172.17.0.1, localhost)."""
        for target in [
            "http://host.docker.internal:8080",
            "http://172.17.0.1:8080",
            "http://gateway.docker.internal:9000",
            "http://localhost:3000",
            "http://127.0.0.1:8000",
        ]:
            res = evaluate_origin_network_plausibility(
                service_target=target,
                container_networks={"isolated-net"},
                container_network_mode=None,
                connector_networks={"connector-net"},
            )
            self.assertTrue(res.is_plausible, f"Failed for {target}")
            self.assertEqual(res.connection_mode, "gateway")

        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"connector-net": {}}},
            },
            {
                "Names": ["/gateway-service"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "gateway.example.com",
                    "cf.tunnel.service": "http://host.docker.internal:8080",
                },
                "NetworkSettings": {"Networks": {"app-net": {}}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])

    def test_tc_45_06_explicit_external_service_target(self):
        """TC-45-06: Explicit external routable IP or FQDN target."""
        for target in [
            "http://192.168.1.50:8080",
            "https://external.example.com",
            "http://10.0.0.5:9090",
            "https://myrouter.lan:8443",
        ]:
            res = evaluate_origin_network_plausibility(
                service_target=target,
                container_networks={"isolated-net"},
                container_network_mode=None,
                connector_networks={"connector-net"},
            )
            self.assertTrue(res.is_plausible, f"Failed for {target}")
            self.assertEqual(res.connection_mode, "external_target")

        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"connector-net": {}}},
            },
            {
                "Names": ["/external-app"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "external.example.com",
                    "cf.tunnel.service": "http://192.168.1.50:8080",
                },
                "NetworkSettings": {"Networks": {"app-net": {}}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])

    def test_tc_45_07_per_container_state_isolation(self):
        """TC-45-07: Per-Container State Isolation - flags cleanly reset without leakage."""
        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"tunnel-net": {}}},
            },
            # Container 1: Disjoint network (network_connected: False)
            {
                "Names": ["/c1-disjoint"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "c1.example.com",
                    "cf.tunnel.port": "8001",
                },
                "NetworkSettings": {"Networks": {"disjoint-net": {}}},
            },
            # Container 2: Connected on tunnel-net (network_connected: True, must not leak False from c1)
            {
                "Names": ["/c2-connected"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "c2.example.com",
                    "cf.tunnel.port": "8002",
                },
                "NetworkSettings": {"Networks": {"tunnel-net": {}}},
            },
            # Container 3: Untunneled container (default network_connected: True, must not leak False)
            {
                "Names": ["/c3-untunneled"],
                "State": "running",
                "Labels": {},
                "NetworkSettings": {"Networks": {"disjoint-net": {}}},
            },
        ]
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "STRICT_NETWORK_CHECK": "false"}):
                services, all_c = app.get_docker_containers()

        self.assertEqual(len(services), 2)
        # Verify c1 is False
        self.assertEqual(services[0]["name"], "c1-disjoint")
        self.assertFalse(services[0]["network_connected"])
        self.assertIn("network_warning", services[0])

        # Verify c2 is True
        self.assertEqual(services[1]["name"], "c2-connected")
        self.assertTrue(services[1]["network_connected"])
        self.assertNotIn("network_warning", services[1])

        # Verify all_containers entries
        all_c_map = {c["name"]: c for c in all_c}
        self.assertFalse(all_c_map["c1-disjoint"]["network_connected"])
        self.assertTrue(all_c_map["c2-connected"]["network_connected"])
        self.assertTrue(all_c_map["c3-untunneled"]["network_connected"])

    def test_tc_45_08_non_blocking_diagnostics_vs_strict_mode(self):
        """TC-45-08: Non-blocking by default (STRICT_NETWORK_CHECK=false) vs strict mode."""
        mock_containers = [
            {
                "Names": ["/cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"tunnel-net": {}}},
            },
            {
                "Names": ["/disjoint-app"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "disjoint.example.com",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"other-net": {}}},
            },
        ]

        # 1. Non-blocking (default / STRICT_NETWORK_CHECK=false)
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "STRICT_NETWORK_CHECK": "false"}):
                services, all_c = app.get_docker_containers()
        self.assertEqual(len(services), 1)
        self.assertFalse(services[0]["network_connected"])
        self.assertIn("network_warning", services[0])

        # 2. Strict mode (STRICT_NETWORK_CHECK=true) drops container from ingress services
        with patch("app.docker_api", return_value=mock_containers):
            with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "STRICT_NETWORK_CHECK": "true"}):
                services_strict, all_c_strict = app.get_docker_containers()
        self.assertEqual(len(services_strict), 0)
        self.assertEqual(len(all_c_strict), 2)
        app_entry = next(c for c in all_c_strict if c["name"] == "disjoint-app")
        self.assertFalse(app_entry["is_tunneled"])
        self.assertFalse(app_entry["network_connected"])


if __name__ == "__main__":
    unittest.main()
