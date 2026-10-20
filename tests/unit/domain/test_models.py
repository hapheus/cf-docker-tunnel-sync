import unittest

from models import ContainerItem, DiscoveredService, SyncStateModel


class TestDataModels(unittest.TestCase):
    def test_discovered_service_model_validation(self):
        """Verify DiscoveredService validates correct input data and defaults."""
        svc = DiscoveredService(container="my-web", hostname="web.example.com", service="http://my-web:80")
        self.assertEqual(svc.container, "my-web")
        self.assertTrue(svc.network_connected)
        self.assertFalse(svc.no_tls_verify)
        self.assertIsNone(svc.network_warning)

    def test_container_item_model(self):
        """Verify ContainerItem defaults."""
        c = ContainerItem(name="app", image="nginx:alpine", state="running", status="Up 2 hours")
        self.assertEqual(c.hostname, "-")
        self.assertFalse(c.is_tunneled)

    def test_sync_state_model_roundtrip(self):
        """Verify SyncStateModel serializes and deserializes cleanly."""
        state = SyncStateModel(domain_name="example.com", status="Active / Synced")
        dump = state.model_dump()
        self.assertEqual(dump["domain_name"], "example.com")
        self.assertEqual(dump["status"], "Active / Synced")
        self.assertTrue(dump["docker_connected"])


if __name__ == "__main__":
    unittest.main()
