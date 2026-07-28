import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
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
from webui.app import config as app_config  # noqa: E402
from webui.app import routes as app_routes  # noqa: E402
from webui.app.media_metadata import _cache_sidecar, _sidecar_directories  # noqa: E402
from webui.app.smart_presets import (  # noqa: E402
    SMART_PRESETS_FILE,
    feedback_context,
    record_feedback,
)


class ApiRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Pytest imports every test module before running the suite. Another
        # module may therefore import app config before this file establishes
        # its isolated media root. Update the shared lists in place so aliases
        # already imported by routes/jobs see the test root too.
        cls.original_roots = list(app_config.ROOTS)
        cls.original_allowed_prefixes = list(app_config.ALLOWED_PREFIXES)
        app_config.ROOTS[:] = [(TEST_MEDIA, "Test media")]
        app_config.ALLOWED_PREFIXES[:] = [TEST_MEDIA]
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_config.ROOTS[:] = cls.original_roots
        app_config.ALLOWED_PREFIXES[:] = cls.original_allowed_prefixes
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
        self.assertIn(b"Teach Autopilot what looks good", automation.data)

        status = self.client.get("/api/autopilot/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["release"], "2.2.0")

        library_page = self.client.get("/")
        self.assertEqual(library_page.status_code, 200)
        self.assertIn(b"Your complete media catalog", library_page.data)
        dashboard_page = self.client.get("/dashboard")
        self.assertEqual(dashboard_page.status_code, 200)
        self.assertIn(b"Operations Dashboard", dashboard_page.data)

    def test_autopilot_preview_training_is_visible_and_records_feedback(self):
        try:
            os.remove(SMART_PRESETS_FILE)
        except FileNotFoundError:
            pass
        app_routes.AUTOPILOT_REVIEW_STATE.clear()
        app_routes.AUTOPILOT_REVIEW_STATE["cursor"] = 0
        app_routes.PREVIEW_TASKS.clear()

        media_path = os.path.join(TEST_MEDIA, "Training.Movie.1080p.mkv")
        with open(media_path, "wb") as handle:
            handle.write(b"0" * 4096)
        library = {
            "movies": [{
                "id": "training-movie",
                "title": "Training Movie",
                "year": 2026,
                "path": media_path,
                "poster_url": "/api/media/artwork/local-abc.jpg",
            }],
            "shows": [],
        }
        probe = {
            "duration_sec": 7200.0,
            "width": 1920,
            "height": 1080,
            "fps": 23.976,
            "is_hdr": False,
        }
        with (
            patch("webui.app.routes._beta_load_library_cache", return_value=library),
            patch("webui.app.routes._probe_media", return_value=probe),
            patch("webui.app.routes.threading.Thread") as preview_thread,
        ):
            response = self.client.post("/api/autopilot/review", json={})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        review = response.get_json()["review"]
        self.assertEqual(review["title"], "Training Movie")
        self.assertEqual(review["preview"]["state"], "queued")
        self.assertTrue(review["learning"]["automation_enabled"])
        preview_thread.return_value.start.assert_called_once()

        feedback_token = app_routes._register_smart_feedback_context(
            {"source": {"kind": "movie"}, "features": {"codec": "h265"}, "plan": {}}
        )
        app_routes._preview_set_task(
            review["preview_id"],
            state="done",
            progress=100,
            message="Accurate preview ready.",
            result={"ok": True, "smart_feedback_token": feedback_token},
        )
        feedback = self.client.post(
            "/api/autopilot/review/feedback",
            json={"verdict": "approve", "reason": "looks_good"},
        )
        self.assertEqual(feedback.status_code, 200, feedback.get_data(as_text=True))
        feedback_review = feedback.get_json()["review"]
        self.assertTrue(feedback_review["reviewed"])
        self.assertEqual(feedback_review["learning"]["feedback_count"], 1)

    def test_local_poster_lookup_does_not_walk_into_shared_parent(self):
        title_one = os.path.join(TEST_MEDIA, "Title One")
        title_two = os.path.join(TEST_MEDIA, "Title Two")
        os.makedirs(title_one, exist_ok=True)
        os.makedirs(title_two, exist_ok=True)
        first = os.path.join(title_one, "movie.mkv")
        second = os.path.join(title_two, "movie.mkv")
        self.assertEqual(_sidecar_directories([first]), [title_one])
        self.assertNotIn(TEST_MEDIA, _sidecar_directories([first, second]))

    def test_movie_poster_lookup_rejects_shared_loose_movie_directory(self):
        shared = os.path.join(TEST_MEDIA, "Loose Movies")
        dedicated = os.path.join(TEST_MEDIA, "Dedicated Movie")
        os.makedirs(shared, exist_ok=True)
        os.makedirs(dedicated, exist_ok=True)
        first = os.path.join(shared, "First Movie (2024).mkv")
        second = os.path.join(shared, "Second Movie (2025).mkv")
        dedicated_movie = os.path.join(dedicated, "Only Movie (2026).mkv")
        for path in (first, second, dedicated_movie):
            with open(path, "wb") as handle:
                handle.write(b"movie")
        for directory in (shared, dedicated):
            with open(os.path.join(directory, "poster.jpg"), "wb") as handle:
                handle.write(b"poster")

        self.assertEqual(_cache_sidecar([first]), {})
        self.assertTrue(_cache_sidecar([dedicated_movie]).get("poster_url", "").startswith("/api/media/artwork/local-"))

    def test_library_cache_sanitizer_removes_shared_poster_from_unrelated_titles(self):
        shared_url = "/api/media/artwork/local-shared.jpg"
        data = {
            "movies": [
                {"type": "movie", "title": "Joker", "year": 2019, "poster_url": shared_url, "metadata_source": "local"},
                {"type": "movie", "title": "Scarface", "year": 1983, "poster_url": shared_url, "metadata_source": "local"},
            ],
            "shows": [],
        }

        self.assertTrue(app_routes._beta_sanitize_duplicate_artwork(data))
        self.assertEqual([movie["poster_url"] for movie in data["movies"]], ["", ""])
        self.assertTrue(all(movie["metadata_source"] == "local_duplicate_removed" for movie in data["movies"]))

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

    def test_bytesqueeze_dashboard_library_and_control_surface(self):
        pairing_response = self.client.post("/api/mobile/pairing_code", json={"scope": "control"})
        self.assertEqual(pairing_response.status_code, 200)
        code = pairing_response.get_json()["pairing"]["code"]
        paired = self.client.post(
            "/api/mobile/v1/pair",
            json={"code": code, "device_id": "bytesqueeze-phone", "device_name": "ByteSqueeze", "platform": "android"},
        )
        self.assertEqual(paired.status_code, 200)
        headers = {"Authorization": f"Bearer {paired.get_json()['access_token']}"}
        library = {
            "movies": [
                {
                    "id": "movie-1",
                    "title": "Example Movie",
                    "poster_url": "https://image.tmdb.org/t/p/w342/example.jpg",
                    "paths": [],
                }
            ],
            "shows": [{"id": "show-1", "title": "Example Show", "poster_url": ""}],
            "scanned_at": 123.0,
        }

        with patch("webui.app.routes._beta_load_library_cache", return_value=library):
            dashboard = self.client.get("/api/mobile/v1/dashboard", headers=headers)
            mobile_library = self.client.get("/api/mobile/v1/library", headers=headers)

        self.assertEqual(dashboard.status_code, 200, dashboard.get_data(as_text=True))
        dashboard_payload = dashboard.get_json()
        self.assertEqual(dashboard_payload["library"]["movies"], 1)
        self.assertIn("automation", dashboard_payload)
        self.assertIn("storage", dashboard_payload)

        self.assertEqual(mobile_library.status_code, 200, mobile_library.get_data(as_text=True))
        library_payload = mobile_library.get_json()["library"]
        self.assertEqual(library_payload["movies"][0]["title"], "Example Movie")
        self.assertTrue(library_payload["movies"][0]["poster_url"].endswith("example.jpg"))

        automation = self.client.get("/api/mobile/v1/automation", headers=headers)
        self.assertEqual(automation.status_code, 200, automation.get_data(as_text=True))
        self.assertIn("autopilot_enabled", automation.get_json()["settings"])

        automation_update = self.client.post(
            "/api/mobile/v1/automation",
            json={"action": "save", "autopilot_enabled": True, "autopilot_mode": "observe"},
            headers=headers,
        )
        self.assertEqual(automation_update.status_code, 200, automation_update.get_data(as_text=True))
        self.assertTrue(automation_update.get_json()["settings"]["autopilot_enabled"])

        storage = self.client.get("/api/mobile/v1/storage", headers=headers)
        self.assertEqual(storage.status_code, 200, storage.get_data(as_text=True))
        self.assertIn("summary", storage.get_json())

        smart = self.client.get("/api/mobile/v1/smart_presets", headers=headers)
        self.assertEqual(smart.status_code, 200, smart.get_data(as_text=True))
        self.assertIn("profile", smart.get_json())

        node_target_path = os.path.join(TEST_MEDIA, "Node.Target.Movie.1080p.mkv")
        with open(node_target_path, "wb") as handle:
            handle.write(b"node-target")
        node_target = self.client.post(
            "/api/mobile/v1/library/queue",
            json={"paths": [node_target_path], "preset": "auto", "mode": "best"},
            headers=headers,
        )
        self.assertEqual(node_target.status_code, 400, node_target.get_data(as_text=True))
        self.assertIn("no worker node available", node_target.get_data(as_text=True))

    def test_keyless_calendar_and_local_sidecar_artwork(self):
        from webui.app import media_metadata

        future_date = (datetime.now() + timedelta(days=30)).date().isoformat()

        show_dir = os.path.join(TEST_MEDIA, "Reference Show")
        os.makedirs(show_dir, exist_ok=True)
        episode_path = os.path.join(show_dir, "Reference.Show.S01E01.mkv")
        poster_path = os.path.join(show_dir, "poster.jpg")
        with open(episode_path, "wb") as handle:
            handle.write(b"episode")
        with open(poster_path, "wb") as handle:
            handle.write(b"poster-bytes")

        with patch("webui.app.media_metadata._show_remote", return_value={
            "metadata_source": "tvmaze",
            "tvmaze_id": 42,
            "release_calendar": [{
                "show_title": "Reference Show",
                "season": 1,
                "episode": 2,
                "name": "Next",
                "airdate": future_date,
            }],
        }):
            metadata = media_metadata.lookup(
                "show",
                "Reference Show",
                2098,
                [episode_path],
                refresh_hours=1,
            )

        self.assertEqual(metadata["metadata_source"], "local")
        self.assertTrue(metadata["poster_url"].startswith("/api/media/artwork/local-"))
        cached_name = metadata["poster_url"].rsplit("/", 1)[-1]
        self.assertTrue(os.path.isfile(media_metadata.artwork_path(cached_name)))

        pairing_response = self.client.post("/api/mobile/pairing_code", json={"scope": "read"})
        code = pairing_response.get_json()["pairing"]["code"]
        paired = self.client.post(
            "/api/mobile/v1/pair",
            json={"code": code, "device_id": "calendar-phone", "device_name": "Calendar phone", "platform": "android"},
        )
        headers = {"Authorization": f"Bearer {paired.get_json()['access_token']}"}
        library = {
            "release_calendar": {
                "generated_at": 1,
                "provider": {"name": "TVmaze"},
                "episodes": [{
                    "library_show_id": "show-1",
                    "show_title": "Reference Show",
                    "airdate": future_date,
                    "tracked": True,
                    "monitor_releases": True,
                    "poster_url": metadata["poster_url"],
                }],
            },
            "movies": [],
            "shows": [],
        }
        with patch("webui.app.routes._beta_load_library_cache", return_value=library):
            response = self.client.get("/api/mobile/v1/calendar?days=730", headers=headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIn("TVmaze", response.get_data(as_text=True))
        self.assertEqual(response.get_json()["calendar"]["count"], 1)
        self.assertTrue(response.get_json()["calendar"]["episodes"][0]["poster_url"].startswith("http://localhost/api/media/artwork/"))

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
