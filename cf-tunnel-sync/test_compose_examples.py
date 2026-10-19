import glob
import os
import unittest

import yaml


class TestComposeExamplesAndSchemaValidation(unittest.TestCase):
    def setUp(self):
        # Locate the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.root_dir = os.path.abspath(os.path.join(current_dir, ".."))
        self.compose_files = sorted(glob.glob(os.path.join(self.root_dir, "**/docker-compose*.y*ml"), recursive=True))

    def test_compose_files_discovered(self):
        """Verify that compose files are discovered across root and examples directories."""
        self.assertGreaterEqual(len(self.compose_files), 8)
        root_compose = os.path.join(self.root_dir, "docker-compose.yml")
        self.assertIn(root_compose, self.compose_files)

    def test_compose_files_valid_yaml_and_structure(self):
        """Verify all compose files parse cleanly as valid YAML and contain a services block."""
        for path in self.compose_files:
            with self.subTest(file=os.path.relpath(path, self.root_dir)):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                self.assertIsInstance(data, dict, f"{path} must parse into a YAML dictionary")
                self.assertIn("services", data, f"{path} must contain a top-level 'services' section")
                services = data["services"]
                self.assertIsInstance(services, dict, f"'services' in {path} must be a dictionary")
                self.assertGreater(len(services), 0, f"{path} must define at least one service")

    def test_canonical_labels_enforced_across_compose_examples(self):
        """Verify all exposed services in all compose files use canonical cf.tunnel.* labels."""
        legacy_prefixes = ("cloudflared.", "notlsverify", "proto=", "port=")

        for path in self.compose_files:
            rel_path = os.path.relpath(path, self.root_dir)
            with self.subTest(file=rel_path):
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                for service_name, service_cfg in data.get("services", {}).items():
                    if not isinstance(service_cfg, dict):
                        continue
                    labels = service_cfg.get("labels", [])

                    # Labels can be a list or dict
                    label_list = []
                    if isinstance(labels, list):
                        label_list = labels
                    elif isinstance(labels, dict):
                        label_list = [f"{k}={v}" for k, v in labels.items()]

                    for lbl in label_list:
                        # Check against legacy aliases
                        for leg in legacy_prefixes:
                            self.assertFalse(
                                lbl.startswith(leg) or (f" {leg}" in lbl),
                                f"Service '{service_name}' in {rel_path} uses non-canonical label '{lbl}'. Use cf.tunnel.* instead.",
                            )

    def test_headless_gateway_example_has_no_published_ports(self):
        """Verifies that the canonical headless gateway example has zero host-published ports (Issue #92)."""
        headless_compose = os.path.join(
            self.root_dir, "examples", "02-multi-stack-external-net", "core-tunnel-stack", "docker-compose.headless.yml"
        )
        self.assertTrue(os.path.isfile(headless_compose), "docker-compose.headless.yml must exist")

        with open(headless_compose, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        services = data.get("services", {})
        self.assertIn("cloudflared", services, "Headless gateway must define cloudflared")
        self.assertIn("cf-tunnel-sync", services, "Headless gateway must define cf-tunnel-sync")
        self.assertNotIn("cf-tunnel-dashboard", services, "Headless gateway must not include dashboard service")

        # Zero published ports on any service
        for sname, scfg in services.items():
            self.assertNotIn("ports", scfg, f"Headless gateway service '{sname}' must not publish any host ports")

        # Verify network definition
        networks = data.get("networks", {})
        self.assertIn("cf-tunnel-net", networks, "Headless gateway must configure cf-tunnel-net bridge network")

    def test_root_and_gateway_compose_port_bindings_remain_unchanged(self):
        """Verifies backward compatibility: root docker-compose.yml preserves dashboard port 8080 (Issue #92)."""
        root_compose = os.path.join(self.root_dir, "docker-compose.yml")
        with open(root_compose, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        services = data.get("services", {})
        self.assertIn("cf-tunnel-sync", services)
        sync_ports = services["cf-tunnel-sync"].get("ports", [])
        self.assertTrue(
            any("8080" in str(p) for p in sync_ports),
            "Root docker-compose.yml must retain dashboard port binding for backward compatibility",
        )

        gateway_compose = os.path.join(
            self.root_dir,
            "examples",
            "02-multi-stack-external-net",
            "core-tunnel-stack",
            "docker-compose.with-dashboard.yml",
        )
        with open(gateway_compose, "r", encoding="utf-8") as f:
            gw_data = yaml.safe_load(f)
        gw_services = gw_data.get("services", {})
        self.assertIn("cf-tunnel-dashboard", gw_services)
        gw_ports = gw_services["cf-tunnel-dashboard"].get("ports", [])
        self.assertTrue(
            any("8080" in str(p) for p in gw_ports),
            "Gateway docker-compose.yml must retain dashboard port binding",
        )

    def test_flagship_multi_compose_walkthrough_docs(self):
        """Verifies that examples/02-multi-stack-external-net/README.md is the complete flagship walkthrough (Issue #96)."""
        walkthrough_path = os.path.join(self.root_dir, "examples", "02-multi-stack-external-net", "README.md")
        self.assertTrue(os.path.isfile(walkthrough_path), "Flagship walkthrough README must exist")

        with open(walkthrough_path, "r", encoding="utf-8") as f:
            doc = f.read()

        # Check required sections
        self.assertIn("docker-compose.headless.yml", doc)
        self.assertIn("traefik/whoami", doc)
        self.assertIn("--preflight", doc)
        self.assertIn("cf-tunnel-net", doc)
        self.assertIn("curl -I", doc)
        self.assertIn("docker compose down", doc)

    def test_env_example_files_clean_and_present(self):
        """Issue #125: Verify all example stacks define .env.example with zero real secrets."""
        forbidden_secret_tokens = ["ghp_", "cf_pat_", "eyJ", "xoxb-", "hooks.slack.com/services/T"]

        env_examples = sorted(glob.glob(os.path.join(self.root_dir, "examples/**/.env.example"), recursive=True))
        self.assertGreaterEqual(len(env_examples), 5, "Every major example stack must define .env.example")

        for path in env_examples:
            rel = os.path.relpath(path, self.root_dir)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            for bad_tok in forbidden_secret_tokens:
                self.assertNotIn(
                    bad_tok, content, f"Possible real secret or sensitive prefix found in {rel}: {bad_tok}"
                )

    def test_automated_compose_interpolation_smoke(self):
        """Issue #126: Automated CI parse of every compose file with fixture environment."""
        fixture_env = {
            "DOMAIN_NAME": "test.example.com",
            "CLOUDFLARE_API_TOKEN": "mock-pat-token-12345",
            "CLOUDFLARE_TUNNEL_NAME": "ci-smoke-tunnel",
            "CLOUDFLARE_TUNNEL_ID": "8a7b6c5d-4e3f-2a1b-0c9d-8e7f6a5b4c3d",
            "CF_NETWORK_NAME": "cf-tunnel-net",
            "DASHBOARD_AUTH_ENABLED": "true",
            "DASHBOARD_USERNAME": "admin",
            "DASHBOARD_PASSWORD": "ci-password",
            "BASIC_AUTH_USERNAME": "admin",
            "BASIC_AUTH_PASSWORD": "ci-password",
            "DASHBOARD_PORT": "8080",
            "DASHBOARD_BIND_ADDRESS": "127.0.0.1",
            "CLOUDFLARED_PROTOCOL": "auto",
            "LOG_LEVEL": "INFO",
        }

        for path in self.compose_files:
            rel = os.path.relpath(path, self.root_dir)
            with open(path, "r", encoding="utf-8") as f:
                raw_text = f.read()

            # Simple regex-based shell variable interpolation simulating docker compose config
            import re

            def repl(m):
                var = m.group(1) or m.group(2)
                default = m.group(3) if len(m.groups()) >= 3 else None
                return fixture_env.get(var, default or "")

            interpolated = re.sub(
                r"\$\{(\w+):-([^}]*)\}|\$\{(\w+)\}",
                lambda m: fixture_env.get(m.group(1) or m.group(3), m.group(2) or ""),
                raw_text,
            )
            parsed = yaml.safe_load(interpolated)
            self.assertIsInstance(parsed, dict, f"Interpolated compose file {rel} must parse as valid YAML")
            self.assertIn("services", parsed, f"Interpolated compose file {rel} must contain services section")

    def test_mocked_cloudflare_smoke_run_for_compose_examples(self):
        """Issue #126: Run mock reconcile smoke run asserting valid ChangePlans for example services."""
        from reconcile import RemoteState, build_discovery_snapshot, compute_change_plan

        # Simulate containers discovered from compose example stacks
        discovered_services = [
            {"container": "whoami", "hostname": "whoami.test.example.com", "service": "http://whoami:80"},
            {"container": "website", "hostname": "web.test.example.com", "service": "http://website:80"},
            {"container": "api", "hostname": "api.test.example.com", "service": "http://api:3000"},
        ]
        all_containers = [
            {"name": "whoami", "state": "running", "hostname": "whoami.test.example.com", "is_tunneled": True},
            {"name": "website", "state": "running", "hostname": "web.test.example.com", "is_tunneled": True},
            {"name": "api", "state": "running", "hostname": "api.test.example.com", "is_tunneled": True},
        ]

        snapshot = build_discovery_snapshot(
            services=discovered_services,
            all_containers=all_containers,
            docker_ok=True,
            timestamp=1792311900.0,
        )
        remote = RemoteState(
            tunnel_id="smoke-tunnel-id",
            tunnel_name="smoke-tunnel",
            zone_id="smoke-zone-id",
            tunnel_target="smoke-tunnel-id.cfargotunnel.com",
            existing_ingress_rules=[],
            existing_dns_records=[],
        )
        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1792311900.0,
            dry_run=True,
        )

        self.assertEqual(plan.summary.total_services_discovered, 3)
        self.assertEqual(plan.summary.ingress_creates, 3)
        self.assertEqual(plan.summary.dns_creates, 3)
        self.assertEqual(len(plan.final_ingress_rules), 4)  # 3 services + 404 catch-all

    def test_cloudflared_token_file_contract(self):
        """Verify that cloudflared never expects manual CLOUDFLARED_TUNNEL_TOKEN and always uses the shared token-file."""
        for path in self.compose_files:
            rel = os.path.relpath(path, self.root_dir)
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)

            if not isinstance(content, dict) or "services" not in content:
                continue

            services = content["services"]
            if "cloudflared" in services:
                cf_svc = services["cloudflared"]
                cmd = cf_svc.get("command", "")
                if isinstance(cmd, list):
                    cmd = " ".join(cmd)

                self.assertNotIn(
                    "CLOUDFLARED_TUNNEL_TOKEN",
                    cmd,
                    f"{rel}: cloudflared must not use CLOUDFLARED_TUNNEL_TOKEN in command",
                )
                self.assertNotIn(
                    "run --token ",
                    cmd,
                    f"{rel}: cloudflared must not pass raw token via --token",
                )
                self.assertIn(
                    "--token-file /etc/cloudflared/token",
                    cmd,
                    f"{rel}: cloudflared must run with '--token-file /etc/cloudflared/token'",
                )

                # Ensure shared volume mounted to /etc/cloudflared
                cf_vols = cf_svc.get("volumes", [])
                has_token_vol = any(v.endswith(":/etc/cloudflared") or ":/etc/cloudflared:" in v for v in cf_vols)
                self.assertTrue(
                    has_token_vol,
                    f"{rel}: cloudflared must mount shared volume to /etc/cloudflared",
                )

                # Ensure cf-tunnel-sync also mounts /etc/cloudflared
                if "cf-tunnel-sync" in services:
                    sync_vols = services["cf-tunnel-sync"].get("volumes", [])
                    has_sync_token_vol = any(
                        v.endswith(":/etc/cloudflared") or ":/etc/cloudflared:" in v for v in sync_vols
                    )
                    self.assertTrue(
                        has_sync_token_vol,
                        f"{rel}: cf-tunnel-sync must mount shared volume to /etc/cloudflared",
                    )


if __name__ == "__main__":
    unittest.main()
