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
            self.root_dir, "examples", "02-multi-compose", "gateway", "docker-compose.headless.yml"
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

        gateway_compose = os.path.join(self.root_dir, "examples", "02-multi-compose", "gateway", "docker-compose.yml")
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
        """Verifies that examples/02-multi-compose/README.md is the complete flagship walkthrough (Issue #96)."""
        walkthrough_path = os.path.join(self.root_dir, "examples", "02-multi-compose", "README.md")
        self.assertTrue(os.path.isfile(walkthrough_path), "Flagship walkthrough README must exist")

        with open(walkthrough_path, "r", encoding="utf-8") as f:
            doc = f.read()

        # Check required sections
        self.assertIn("docker-compose.headless.yml", doc)
        self.assertIn("service-whoami", doc)
        self.assertIn("--preflight", doc)
        self.assertIn("cf-tunnel-net", doc)
        self.assertIn("curl -I", doc)
        self.assertIn("docker compose down", doc)


if __name__ == "__main__":
    unittest.main()
