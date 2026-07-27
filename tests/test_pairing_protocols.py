import os
import tempfile
import threading
import unittest
from unittest import mock

from webui.app import mobile_linking, node_linking


class NodePairingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_node_file = node_linking.NODE_LINK_FILE
        node_linking.NODE_LINK_FILE = os.path.join(self.tempdir.name, "linked_nodes.json")

    def tearDown(self):
        node_linking.NODE_LINK_FILE = self.original_node_file
        self.tempdir.cleanup()

    def test_lost_pair_response_can_be_retried_by_same_controller(self):
        pairing = node_linking.create_pairing_code()
        controller = {
            "controller_id": "controller-a",
            "controller_name": "Main",
            "request_id": "first-attempt",
            "protocol_version": "not-a-number",
        }
        first = node_linking.accept_pairing(pairing["code"], controller)
        second = node_linking.accept_pairing(pairing["code"], {**controller, "request_id": "retry"})

        self.assertFalse(first["retry_recovered"])
        self.assertTrue(second["retry_recovered"])
        self.assertNotEqual(first["token"], second["token"])
        self.assertEqual(second["protocol_version"], node_linking.NODE_PROTOCOL_VERSION)

        with self.assertRaisesRegex(ValueError, "already used"):
            node_linking.accept_pairing(pairing["code"], {"controller_id": "controller-b"})

    def test_backup_failure_does_not_break_successful_pairing(self):
        with mock.patch.object(node_linking.shutil, "copy2", side_effect=OSError("NAS backup unavailable")):
            pairing = node_linking.create_pairing_code()
            accepted = node_linking.accept_pairing(pairing["code"], {"controller_id": "controller-a"})
        self.assertTrue(accepted["token"])
        self.assertTrue(os.path.isfile(node_linking.NODE_LINK_FILE))

    def test_concurrent_node_updates_do_not_erase_each_other(self):
        threads = [
            threading.Thread(target=node_linking.save_node, args=({"id": f"node-{index}", "name": f"Node {index}"},))
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(node_linking.list_nodes_private()), 20)

    def test_new_controller_preserves_case_sensitive_v1_pairing_codes(self):
        responses = [
            {"protocol_version": 1, "capabilities": []},
            {"token": "worker-token", "recovery_token": "recovery", "worker_id": "legacy-worker"},
        ]
        with mock.patch.object(node_linking, "_request_json", side_effect=responses) as request_json:
            node_linking.pair_worker("http://legacy-worker:8080", "AbC_def-12")
        pairing_body = request_json.call_args_list[1].kwargs["body"]
        self.assertEqual(pairing_body["code"], "AbC_def-12")

    def test_headless_discovery_requires_remote_transfer(self):
        with mock.patch.dict(os.environ, {"TSD_WORKER_MODE": "1"}):
            discovery = node_linking.node_discovery()

        self.assertEqual(discovery["worker_mode"], "headless")
        self.assertTrue(discovery["requires_remote_transfer"])
        self.assertEqual(discovery["recommended_transfer_mode"], "remote")
        self.assertIn("remote-transfer-only", discovery["capabilities"])

    def test_headless_worker_forces_remote_mode_and_drops_path_mappings(self):
        responses = [
            {
                "protocol_version": 2,
                "capabilities": ["headless-worker", "remote-transfer-only"],
                "worker_mode": "headless",
                "requires_remote_transfer": True,
            },
            {
                "token": "worker-token",
                "recovery_token": "recovery-token",
                "worker_id": "headless-worker",
                "worker_name": "Garage worker",
                "protocol_version": 2,
                "worker_mode": "headless",
                "requires_remote_transfer": True,
            },
        ]
        with mock.patch.object(node_linking, "_request_json", side_effect=responses):
            worker = node_linking.pair_worker(
                "http://worker:8080",
                "ABCDE-FGHJK",
                transfer_mode="local",
                path_mappings=[{"controller": "/media", "worker": "/mnt/media"}],
                controller_url="http://controller:8080",
            )

        self.assertEqual(worker["worker_mode"], "headless")
        self.assertTrue(worker["requires_remote_transfer"])
        self.assertEqual(worker["transfer_mode"], "remote")
        self.assertEqual(worker["path_mappings"], [])


class MobilePairingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_mobile_file = mobile_linking.MOBILE_STATE_FILE
        mobile_linking.MOBILE_STATE_FILE = os.path.join(self.tempdir.name, "mobile_devices.json")

    def tearDown(self):
        mobile_linking.MOBILE_STATE_FILE = self.original_mobile_file
        self.tempdir.cleanup()

    def test_mobile_pairing_refresh_and_revoke(self):
        pairing = mobile_linking.create_mobile_pairing(scope="control")
        first = mobile_linking.accept_mobile_pairing(
            pairing["code"],
            {"device_id": "phone-a", "device_name": "Kevin's phone", "platform": "android"},
        )
        retry = mobile_linking.accept_mobile_pairing(
            pairing["code"],
            {"device_id": "phone-a", "device_name": "Kevin's phone", "platform": "android"},
        )
        self.assertTrue(retry["retry_recovered"])
        self.assertIsNone(mobile_linking.authenticate_mobile_token(first["access_token"]))
        self.assertEqual(mobile_linking.authenticate_mobile_token(retry["access_token"])["id"], "phone-a")

        refreshed = mobile_linking.refresh_mobile_token("phone-a", retry["refresh_token"])
        self.assertIsNone(mobile_linking.authenticate_mobile_token(retry["access_token"]))
        self.assertEqual(mobile_linking.authenticate_mobile_token(refreshed["access_token"])["scope"], "control")

        self.assertTrue(mobile_linking.revoke_mobile_device("phone-a"))
        self.assertIsNone(mobile_linking.authenticate_mobile_token(refreshed["access_token"]))

    def test_read_only_device_cannot_get_control_scope(self):
        pairing = mobile_linking.create_mobile_pairing(scope="read")
        credentials = mobile_linking.accept_mobile_pairing(pairing["code"], {"device_id": "tablet-a"})
        self.assertIsNotNone(mobile_linking.authenticate_mobile_token(credentials["access_token"], required_scope="read"))
        self.assertIsNone(mobile_linking.authenticate_mobile_token(credentials["access_token"], required_scope="control"))


if __name__ == "__main__":
    unittest.main()
