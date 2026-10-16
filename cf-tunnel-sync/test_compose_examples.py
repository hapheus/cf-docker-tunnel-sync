import glob
import os
import unittest

import yaml


class TestComposeExamplesAndSchemaValidation(unittest.TestCase):
    def setUp(self):
        # Locate the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.root_dir = os.path.abspath(os.path.join(current_dir, ".."))
        self.compose_files = sorted(
            glob.glob(os.path.join(self.root_dir, "**/docker-compose.y*ml"), recursive=True)
        )

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


if __name__ == "__main__":
    unittest.main()
