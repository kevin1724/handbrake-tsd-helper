import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch


TEST_ROOT = tempfile.mkdtemp(prefix="handbrake-api-tests-")
TEST_DATA = os.path.join(TEST_ROOT, "data")
TEST_MEDIA = os.path.join(TEST_ROOT, "media")
TEST_PRESETS = os.path.join(TEST_ROOT, "presets")
for path in (TEST_DATA, TEST_MEDIA, TEST_PRESETS):
    os.makedirs(path, exist_ok=True)
os.environ["HB_DATA_DIR"] = TEST_DATA
os.environ["HB_PRESET_DIR"] = TEST_PRESETS
os.environ["HB_MEDIA_BASE"] = TEST_MEDIA
os.environ["HB_ROOTS_JSON"] = json.dumps([[TEST_MEDIA, "Test media"]])
os.environ["FLASK_DEBUG"] = "0"
os.environ["FLASK_ENV"] = "production"

from webui.app import create_app  # noqa: E402
from webui.app.smart_presets import (  # noqa: E402
    SMART_PRESETS_FILE,
    feedback_context,
    record_feedback,
)


class ApiRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def test_release_discovery_and_automation_page(self):
        node = self.client.get("/api/node/discovery")
        self.assertEqual(node.status_code, 200)
        self.assertEqual(node.get_json()["protocol_version"], 2)

        mobile = self.client.get("/api/mobile/v1/discovery")
        self.assertEqual(mobile.status_code, 200)
        self.assertEqual(mobile.get_json()["api_version"], "v1")

        automation = self.client.get("/settings/automation")
        self.assertEqual(automation.status_code, 200)
        self.assertIn(b"Autopilot", automation.data)
        self.assertIn(b"Companion app access", automation.data)

        status = self.client.get("/api/autopilot/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["release"], "2.0.0")

    def test_mobile_bearer_flow_and_scope_enforcement(self):
        pairing_response = self.client.post("/api/mobile/pairing_code", json={"scope": "read"})
        self.assertEqual(pairing_response.status_code, 200)
        code = pairing_response.get_json()["pairing"]["code"]

        paired = self.client.post(
            "/api/mobile/v1/pair",
            json={"code": code, "device_id": "smoke-phone", "device_name": "Smoke phone", "platform": "android"},
        )
        self.assertEqual(paired.status_code, 200)
        token = paired.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        status = self.client.get("/api/mobile/v1/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["device"]["id"], "smoke-phone")

        control = self.client.post("/api/mobile/v1/queue", json={"paused": True}, headers=headers)
        self.assertEqual(control.status_code, 403)

    def test_smart_presets_generate_candidates_and_unlock_after_feedback(self):
        try:
            os.remove(SMART_PRESETS_FILE)
        except FileNotFoundError:
            pass

        media_path = os.path.join(TEST_MEDIA, "Example.Movie.1080p.mkv")
        with open(media_path, "wb") as handle:
            handle.write(b"0" * 4096)

        profile = self.client.post(
            "/api/smart_presets/profile",
            json={
                "goal": "balanced",
                "compatibility": "modern",
                "hardware": "software",
                "audio_strategy": "eac3_surround",
                "automation_enabled": True,
                "minimum_feedback": 3,
                "confidence_threshold": 0.55,
            },
        )
        self.assertEqual(profile.status_code, 200)
        saved_profile = profile.get_json()["profile"]
        self.assertEqual(saved_profile["audio_strategy"], "eac3_surround")
        self.assertEqual(saved_profile["audio_languages"], ["eng", "spa"])
        self.assertEqual(saved_profile["subtitle_languages"], ["eng", "spa"])

        partial_profile = self.client.post(
            "/api/smart_presets/profile",
            json={"goal": "balanced"},
        )
        self.assertEqual(partial_profile.status_code, 200)
        self.assertEqual(partial_profile.get_json()["profile"]["audio_strategy"], "eac3_surround")

        probe = {
            "duration_sec": 7200.0,
            "width": 1920,
            "height": 1080,
            "fps": 23.976,
            "is_hdr": False,
        }
        with patch("webui.app.routes._probe_media", return_value=probe):
            response = self.client.post(
                "/api/smart_presets/recommend",
                json={"src": media_path, "preset": "auto", "target_size_auto": True},
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(len(payload["candidates"]), 3)
        self.assertIn(payload["recommended_id"], {row["id"] for row in payload["candidates"]})
        self.assertFalse(payload["learning"]["automation_ready"])
        for candidate in payload["candidates"]:
            options = candidate["options"]
            self.assertEqual(options["smart_audio_strategy"], "eac3_surround")
            self.assertEqual(options["audio_mode"], "eac3")
            self.assertEqual(options["audio_bitrate"], "640")
            self.assertEqual(options["audio_tracks"], "all")
            self.assertEqual(options["audio_languages"], ["eng", "spa"])
            self.assertEqual(options["subtitle_mode"], "all")
            self.assertEqual(options["subtitle_languages"], ["eng", "spa"])

        with patch("webui.app.routes._probe_media", return_value=probe):
            preview = self.client.post(
                "/wizard_preview",
                json={
                    "src": media_path,
                    "ai_mode": True,
                    "smart_audio_strategy": "eac3_surround",
                    "audio_languages": ["fra"],
                    "subtitle_languages": ["fra"],
                    "ai_audio_scope": "all",
                    "ai_subtitle_scope": "all",
                },
            )
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        preview_payload = preview.get_json()
        args = preview_payload["suggested_extra_args"]
        self.assertIn("--all-audio", args)
        self.assertIn("--all-subtitles", args)
        self.assertEqual(args[args.index("--audio-lang-list") + 1], "eng,spa")
        self.assertEqual(args[args.index("--subtitle-lang-list") + 1], "eng,spa")
        self.assertEqual(args[args.index("-E") + 1], "eac3")
        self.assertEqual(args[args.index("-B") + 1], "640")
        self.assertEqual(args[args.index("-6") + 1], "5point1")

        with patch("webui.app.routes._probe_media", return_value=probe):
            copy_preview = self.client.post(
                "/wizard_preview",
                json={
                    "src": media_path,
                    "ai_mode": True,
                    "smart_audio_strategy": "copy",
                    "ai_copy_audio": False,
                    "audio_languages": ["fra"],
                    "subtitle_languages": ["fra"],
                    "ai_audio_scope": "first",
                    "ai_subtitle_scope": "none",
                },
            )
        self.assertEqual(copy_preview.status_code, 200, copy_preview.get_data(as_text=True))
        copy_payload = copy_preview.get_json()
        copy_args = copy_payload["suggested_extra_args"]
        self.assertEqual(copy_args[copy_args.index("-E") + 1], "copy")
        self.assertEqual(copy_args[copy_args.index("--audio-lang-list") + 1], "eng,spa")
        self.assertEqual(copy_args[copy_args.index("--subtitle-lang-list") + 1], "eng,spa")
        self.assertIn("--all-audio", copy_args)
        self.assertIn("--all-subtitles", copy_args)

        sample_plan = {
            "preset": "1080",
            "probe": {
                **probe,
                "source_type": "movie",
                "source_size_bytes": 8 * 1024**3,
            },
            "options": {
                "ai_goal": "balanced",
                "video_codec": "h265",
                "encoder_family": "software",
                "quality": "balanced",
                "encoder_speed": "medium",
            },
            "inputs": {"target_mb": 5120},
            "estimates": {
                "output_resolution": {"width": 1920, "height": 1080},
                "video_bitrate_kbps": 5600,
                "encoder": "x265_10bit",
                "quality_code": "good",
            },
        }
        context = feedback_context(sample_plan, "balanced")
        for _index in range(3):
            record_feedback(context, "approve", "looks_good")

        state = self.client.get("/api/smart_presets")
        self.assertEqual(state.status_code, 200)
        self.assertTrue(state.get_json()["learning"]["automation_ready"])


if __name__ == "__main__":
    unittest.main()
