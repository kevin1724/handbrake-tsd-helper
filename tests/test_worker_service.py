import os
import tempfile
import unittest
from unittest import mock

from webui.app import jobs, node_linking, settings
from worker.app import create_worker_app


class HeadlessWorkerServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.work_dir = os.path.join(self.tempdir.name, "work", "jobs")
        self.node_file = os.path.join(self.tempdir.name, "work", "state", "linked_nodes.json")
        self.settings_file = os.path.join(self.tempdir.name, "work", "state", "settings.json")
        self.original_node_file = node_linking.NODE_LINK_FILE
        self.original_settings_file = settings.SETTINGS_FILE
        self.original_settings_cache = settings._settings_cache
        node_linking.NODE_LINK_FILE = self.node_file
        settings.SETTINGS_FILE = self.settings_file
        settings._settings_cache = None
        self.env = mock.patch.dict(
            os.environ,
            {
                "TSD_WORKER_MODE": "1",
                "TSD_WORKER_NAME": "Test headless worker",
                "TSD_WORKER_TEMP_DIR": self.work_dir,
            },
        )
        self.env.start()
        self.app = create_worker_app(announce_pairing=False)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()
        node_linking.NODE_LINK_FILE = self.original_node_file
        settings.SETTINGS_FILE = self.original_settings_file
        settings._settings_cache = self.original_settings_cache
        self.tempdir.cleanup()

    def test_worker_exposes_only_headless_service_and_node_api(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.get_json()["service"], "bytesqueeze-headless-worker")
        self.assertEqual(self.client.get("/settings").status_code, 404)

        discovery = self.client.get("/api/node/discovery")
        self.assertEqual(discovery.status_code, 200)
        self.assertEqual(discovery.get_json()["worker_mode"], "headless")
        self.assertTrue(discovery.get_json()["requires_remote_transfer"])

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["work"]["path"], self.work_dir)

    def test_pairing_response_marks_worker_as_transfer_only(self):
        pairing = node_linking.create_pairing_code()
        response = self.client.post(
            "/api/node/pair/accept",
            json={
                "code": pairing["code"],
                "controller_id": "controller-test",
                "controller_name": "Main controller",
                "controller_url": "http://controller:8080",
                "protocol_version": 2,
            },
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["worker_mode"], "headless")
        self.assertTrue(response.get_json()["requires_remote_transfer"])
        self.assertTrue(response.get_json()["token"])
        self.assertEqual(self.client.get("/api/node/status").status_code, 401)

    def test_controller_encoding_policy_keeps_large_output_auto_stop(self):
        job = {
            "encoding_policy": {
                "hb_threads": 6,
                "auto_stop_large_output_enabled": True,
                "auto_stop_large_output_percent": 85,
            },
            "estimated_out_checked_progress": 25,
            "estimated_out_bytes": 900,
            "src_bytes": 1000,
        }

        with mock.patch.object(
            jobs,
            "load_settings",
            return_value={"auto_stop_large_output_enabled": False},
        ):
            stop = jobs._estimated_output_stop_guard(job)

        self.assertIsNotNone(stop)
        self.assertEqual(stop["threshold_percent"], 85.0)
        self.assertEqual(jobs._job_encoding_policy(job)["hb_threads"], 6)


if __name__ == "__main__":
    unittest.main()
