import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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
from webui.app import events as app_events  # noqa: E402
from webui.app import jobs as app_jobs  # noqa: E402
from webui.app import routes as app_routes  # noqa: E402
from webui.app import wizard_llm as app_wizard_llm  # noqa: E402
from webui.app.media_metadata import _cache_sidecar, _choose_movie, _sidecar_directories  # noqa: E402
from webui.app.smart_presets import (  # noqa: E402
    SMART_PRESETS_FILE,
    candidate_learning,
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
        self.assertEqual(automation.status_code, 302)
        self.assertTrue(automation.headers["Location"].endswith("/autopilot"))

        autopilot_page = self.client.get("/autopilot")
        self.assertEqual(autopilot_page.status_code, 200)
        self.assertIn(b"Autopilot, made understandable", autopilot_page.data)
        self.assertIn(b"Look at real preview comparisons", autopilot_page.data)
        self.assertIn(b"How did completed encodes actually look", autopilot_page.data)

        status = self.client.get("/api/autopilot/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["release"], "3.14.0-beta.1")
        self.assertIn("continuous_learning", status.get_json())
        self.assertIn("onboarding", status.get_json())

        library_page = self.client.get("/library")
        self.assertEqual(library_page.status_code, 200)
        self.assertIn(b"See the three-step workflow", library_page.data)
        self.assertIn(b"Smart Queue", library_page.data)
        self.assertIn(b"Fine tune queue", library_page.data)
        self.assertIn(b"Real encode preview", library_page.data)
        self.assertIn(b'id="quickFilterSelect"', library_page.data)
        home_page = self.client.get("/")
        self.assertEqual(home_page.status_code, 200)
        self.assertIn(b"Everything important, at a glance", home_page.data)
        jobs_page = self.client.get("/jobs")
        self.assertEqual(jobs_page.status_code, 200)
        self.assertIn(b"Jobs &amp; Queue", jobs_page.data)

        job_id = "jobs-dashboard-route-regression"
        app_jobs.jobs[job_id] = {
            "id": job_id,
            "src": os.path.join(TEST_MEDIA, "Dashboard.Movie.2026.mkv"),
            "preset": "test-preset",
            "status": "done",
            "created_at": 1,
        }
        try:
            jobs_data = self.client.get("/api/jobs")
            self.assertEqual(jobs_data.status_code, 200)
            self.assertTrue(jobs_data.is_json)
            self.assertIn(
                job_id,
                [job["id"] for job in jobs_data.get_json()["jobs"]],
            )
        finally:
            app_jobs.jobs.pop(job_id, None)

    def test_v3_interface_can_fall_back_to_v2_without_touching_app_behavior(self):
        original = self.client.get("/api/settings").get_json()["settings"]
        try:
            saved = self.client.post(
                "/api/settings",
                json={"ui_version": "v3", "ui_density": "comfortable"},
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.get_json()["settings"]["ui_version"], "v3")

            v3_page = self.client.get("/")
            self.assertEqual(v3_page.status_code, 200)
            self.assertIn(b'class="home-page ui-v3"', v3_page.data)
            self.assertIn(b'data-density="comfortable"', v3_page.data)
            self.assertIn(b'/static/v3.css', v3_page.data)
            self.assertIn(b'/static/v3.js', v3_page.data)

            temporary_v2 = self.client.get("/?ui=v2")
            self.assertIn(b'class="home-page ui-v2"', temporary_v2.data)
            self.assertEqual(
                self.client.get("/api/settings").get_json()["settings"]["ui_version"],
                "v3",
            )

            saved_v2 = self.client.post(
                "/api/settings",
                json={"ui_version": "v2", "ui_density": "compact"},
            )
            self.assertEqual(saved_v2.status_code, 200)
            classic_library = self.client.get("/library")
            self.assertIn(b'class="beta-page ui-v2"', classic_library.data)
            self.assertIn(b'data-density="compact"', classic_library.data)

            settings_page = self.client.get("/settings")
            self.assertIn(b"V3 Beta", settings_page.data)
            self.assertIn(b"V2 Classic", settings_page.data)
            self.assertIn(b'name="uiVersion"', settings_page.data)

            temporary_v3 = self.client.get("/library?ui=v3")
            self.assertIn(b'class="beta-page ui-v3"', temporary_v3.data)
        finally:
            self.client.post(
                "/api/settings",
                json={
                    "ui_version": original.get("ui_version", "v3"),
                    "ui_density": original.get("ui_density", "comfortable"),
                },
            )

    def test_v3_library_shell_prevents_duplicate_icons_and_has_mobile_tabs(self):
        library_page = self.client.get("/library?ui=v3")
        self.assertEqual(library_page.status_code, 200)
        self.assertIn(b'id="libraryControls"', library_page.data)
        self.assertIn(b'id="libraryBatchBar"', library_page.data)
        self.assertIn(b'data-library-view="movies"', library_page.data)
        self.assertIn(b'data-library-view="shows"', library_page.data)
        self.assertIn(b'data-mobile-view="movies"', library_page.data)

        v3_css = self.client.get("/static/v3.css")
        self.assertEqual(v3_css.status_code, 200)
        self.assertIn(b"body.ui-v3 .nav-link::before", v3_css.data)
        self.assertIn(b"content: none !important", v3_css.data)
        v3_css.close()

        v3_js = self.client.get("/static/v3.js")
        self.assertEqual(v3_js.status_code, 200)
        self.assertIn(b'link.classList.remove("nav-library"', v3_js.data)
        self.assertIn(b'body.dataset.v3Enhanced === "true"', v3_js.data)
        v3_js.close()

    def test_v3_operations_console_has_live_queue_and_customizable_overview(self):
        home_page = self.client.get("/?ui=v3")
        self.assertEqual(home_page.status_code, 200)
        self.assertIn(b'id="homeCustomizeDialog"', home_page.data)
        self.assertIn(b'data-home-widget="work"', home_page.data)
        self.assertIn(b"bytesqueezeHomeWidgets", home_page.data)

        jobs_page = self.client.get("/jobs?ui=v3")
        self.assertEqual(jobs_page.status_code, 200)
        self.assertIn(b'id="v3RunningSection"', jobs_page.data)
        self.assertIn(b"renderV3RunningJobs", jobs_page.data)

        v3_js = self.client.get("/static/v3.js")
        self.assertIn(b"v3-operations-dock", v3_js.data)
        self.assertIn(b"v3QueueComposer", v3_js.data)
        self.assertIn(b"v3-settings-search", v3_js.data)
        v3_js.close()

        v3_css = self.client.get("/static/v3.css")
        self.assertIn(b"V3 media operations console", v3_css.data)
        self.assertIn(b"body.ui-v3 .v3-operations-dock", v3_css.data)
        v3_css.close()

    def test_hardware_transcode_concurrency_setting_is_bounded_and_visible(self):
        original = self.client.get("/api/settings").get_json()["settings"]
        try:
            saved = self.client.post(
                "/api/settings",
                json={"hardware_transcode_concurrency": 99},
            )
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.get_json()["settings"]["hardware_transcode_concurrency"], 8)

            settings_page = self.client.get("/settings")
            self.assertEqual(settings_page.status_code, 200)
            self.assertIn(b'id="hardwareTranscodeConcurrency"', settings_page.data)
            self.assertIn(b"CPU/software jobs always run one at a time", settings_page.data)
        finally:
            self.client.post(
                "/api/settings",
                json={
                    "hardware_transcode_concurrency": original.get(
                        "hardware_transcode_concurrency",
                        1,
                    )
                },
            )

    def test_library_local_smart_batch_keeps_tuning_for_every_file(self):
        paths = []
        for episode in range(1, 4):
            path = os.path.join(TEST_MEDIA, f"Useful.Show.S01E{episode:02d}.mkv")
            with open(path, "wb") as handle:
                handle.write(b"0" * 256)
            paths.append(path)

        tuning = {
            "goal": "small",
            "resolution_mode": "1080",
            "hardware": "software",
            "audio_strategy": "copy",
            "subtitle_mode": "all",
            "target_scale": 0.85,
        }
        calls = []

        def fake_create_smart_job(src, **kwargs):
            calls.append((src, kwargs))
            return f"smart-{len(calls)}", {"recommended_id": "compact"}

        with patch("webui.app.routes._create_smart_job", side_effect=fake_create_smart_job):
            response = self.client.post(
                "/api/nodes/dispatch",
                json={
                    "paths": paths,
                    "preset": "smart",
                    "mode": "local",
                    "smart_tuning": tuning,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["count"], 3)
        self.assertEqual([row[0] for row in calls], paths)
        self.assertTrue(all(row[1]["tuning"] == tuning for row in calls))
        self.assertTrue(all(row[1]["automation_source"] == "library_smart" for row in calls))

    def test_jobs_api_merges_durable_encode_history_and_summary(self):
        original_history_cutoff = app_jobs.history_cleared_before
        app_jobs.history_cleared_before = 0.0
        live_id = "jobs-live-complete"
        queued_id = "jobs-live-queued"
        archived_id = "jobs-durable-complete"
        live_src = os.path.join(TEST_MEDIA, "Live.Movie.2026.mkv")
        queued_src = os.path.join(TEST_MEDIA, "Queued.Movie.2026.mkv")
        archived_src = os.path.join(TEST_MEDIA, "Archived.Movie.2025.mkv")
        app_jobs.jobs[live_id] = {
            "src": live_src,
            "preset": "1080",
            "status": "done",
            "progress": 100,
            "created_at": 200,
            "finished_at": 300,
            "duration_seconds": 100,
            "saved_bytes": 500,
        }
        app_jobs.jobs[queued_id] = {
            "src": queued_src,
            "preset": "1080",
            "status": "queued",
            "progress": 0,
            "created_at": 400,
        }
        app_jobs.job_queue.append(queued_id)
        ledger = [
            {
                "ts": 300,
                "job_id": live_id,
                "src": live_src,
                "out": os.path.join(TEST_MEDIA, "Live.Movie.2026-TSD.mkv"),
                "preset": "1080",
                "src_bytes": 1000,
                "out_bytes": 500,
                "saved_bytes": 500,
                "duration_seconds": 100,
            },
            {
                "ts": 250,
                "job_id": archived_id,
                "src": archived_src,
                "out": os.path.join(TEST_MEDIA, "Archived.Movie.2025-TSD.mkv"),
                "preset": "4k",
                "src_bytes": 4000,
                "out_bytes": 1000,
                "saved_bytes": 3000,
                "duration_seconds": 120,
                "is_hdr": True,
                "encode_method": "x265_10bit",
            },
        ]
        try:
            with patch.object(app_jobs, "list_encodes", return_value=ledger):
                response = self.client.get("/api/jobs")
        finally:
            app_jobs.jobs.pop(live_id, None)
            app_jobs.jobs.pop(queued_id, None)
            while queued_id in app_jobs.job_queue:
                app_jobs.job_queue.remove(queued_id)
            app_jobs.history_cleared_before = original_history_cutoff

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertIn("summary", payload)
        self.assertIn("paused", payload)
        ids = [job["id"] for job in payload["jobs"]]
        self.assertEqual(ids.count(live_id), 1, "live and ledger copies must be deduplicated")
        self.assertIn(archived_id, ids)
        self.assertEqual(ids[0], queued_id, "active queue records stay above terminal history")
        archived = next(job for job in payload["jobs"] if job["id"] == archived_id)
        self.assertEqual(archived["status"], "done")
        self.assertTrue(archived["archived"])
        self.assertEqual(archived["saved_bytes"], 3000)
        self.assertEqual(archived["history_source"], "encode_ledger")

    def test_clear_finished_hides_queue_rows_but_keeps_lifetime_totals(self):
        original_jobs = dict(app_jobs.jobs)
        original_queue = list(app_jobs.job_queue)
        original_paused = app_jobs.queue_paused
        original_totals = dict(app_jobs.dashboard_totals)
        original_history_cutoff = app_jobs.history_cleared_before
        state_path = os.path.join(TEST_DATA, "clear-finished-state.json")
        finished_id = "finished-before-clear"
        queued_id = "queued-during-clear"
        future_id = "finished-after-clear"
        ledger = [
            {
                "ts": 900,
                "job_id": finished_id,
                "src": os.path.join(TEST_MEDIA, "Old.Movie.mkv"),
                "out": os.path.join(TEST_MEDIA, "Old.Movie-TSD.mkv"),
                "preset": "1080",
                "src_bytes": 5000,
                "out_bytes": 2000,
                "saved_bytes": 3000,
                "duration_seconds": 100,
            },
            {
                "ts": 1100,
                "job_id": future_id,
                "src": os.path.join(TEST_MEDIA, "New.Movie.mkv"),
                "out": os.path.join(TEST_MEDIA, "New.Movie-TSD.mkv"),
                "preset": "4k",
                "src_bytes": 6000,
                "out_bytes": 2000,
                "saved_bytes": 4000,
                "duration_seconds": 60,
            },
        ]
        storage_summary = {
            "count": 2,
            "saved_bytes": 7000,
            "saved_gb": 0.0,
            "total_runtime_seconds": 160.0,
        }

        app_jobs.jobs.clear()
        app_jobs.jobs.update(
            {
                finished_id: {
                    "src": ledger[0]["src"],
                    "preset": "1080",
                    "status": "done",
                    "progress": 100,
                    "created_at": 800,
                    "finished_at": 900,
                    "duration_seconds": 100,
                    "saved_bytes": 3000,
                },
                queued_id: {
                    "src": os.path.join(TEST_MEDIA, "Queued.Movie.mkv"),
                    "preset": "1080",
                    "status": "queued",
                    "progress": 0,
                    "created_at": 950,
                },
            }
        )
        app_jobs.job_queue[:] = [queued_id]
        app_jobs.queue_paused = False
        app_jobs.dashboard_totals = app_jobs._empty_dashboard_totals()
        app_jobs.history_cleared_before = 0.0

        try:
            with (
                patch.object(app_jobs, "JOBS_FILE", state_path),
                patch.object(app_jobs, "_now_ts", return_value=1000.0),
                patch.object(app_jobs, "list_encodes", return_value=ledger),
                patch.object(app_jobs, "get_storage_summary", return_value=storage_summary),
            ):
                removed = app_jobs.clear_finished_jobs()
                self.assertEqual(removed, 1)
                self.assertEqual(app_jobs.history_cleared_before, 1000.0)

                visible_ids = [row["id"] for row in app_jobs.list_job_history_for_api()]
                self.assertNotIn(finished_id, visible_ids)
                self.assertIn(queued_id, visible_ids)
                self.assertIn(future_id, visible_ids, "jobs completed after Clear must remain visible")

                summary = app_jobs.get_job_summary()
                self.assertEqual(summary["counts"]["done"], 2)
                self.assertEqual(summary["saved_bytes"], 7000)
                self.assertEqual(summary["total_runtime_seconds"], 160.0)

                # Prove the clear boundary survives a controller restart.
                app_jobs.jobs.clear()
                app_jobs.job_queue.clear()
                app_jobs.dashboard_totals = app_jobs._empty_dashboard_totals()
                app_jobs.history_cleared_before = 0.0
                app_jobs.load_jobs()
                self.assertEqual(app_jobs.history_cleared_before, 1000.0)
                restarted_ids = [row["id"] for row in app_jobs.list_job_history_for_api()]
                self.assertNotIn(finished_id, restarted_ids)
                self.assertIn(queued_id, restarted_ids)
                self.assertIn(future_id, restarted_ids)
        finally:
            app_jobs.jobs.clear()
            app_jobs.jobs.update(original_jobs)
            app_jobs.job_queue[:] = original_queue
            app_jobs.queue_paused = original_paused
            app_jobs.dashboard_totals = original_totals
            app_jobs.history_cleared_before = original_history_cutoff

    def test_jobs_page_starts_critical_data_load_before_optional_work(self):
        response = self.client.get("/jobs")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        init_at = html.index("document.addEventListener('DOMContentLoaded'")
        first_jobs_load = html.index("refreshJobs();", init_at)
        optional_browser_init = html.index("populateRoots();", init_at)
        self.assertLess(first_jobs_load, optional_browser_init)
        self.assertIn("renderJobsSummary(data.summary || {})", html)
        self.assertIn("Lifetime totals above are never reset", html)
        self.assertIn("if (dashboardAutopilotButton)", html)
        self.assertIn("if (operationsStatusLine)", html)

    def test_home_summary_uses_lightweight_catalog_and_autopilot_data(self):
        lightweight_library = {"movies": 12, "shows": 4, "episodes": 88, "updated_at": 123.0}
        compact_autopilot = {
            "autopilot": {"enabled": True, "mode": "observe"},
            "readiness": {"ready": True, "score": 100, "recommendations": []},
            "continuous_learning": {"enabled": True, "pending": 0},
        }
        with (
            patch("webui.app.routes._beta_load_library_cache", side_effect=AssertionError("full catalog loaded")),
            patch("webui.app.routes._beta_load_library_summary", return_value=lightweight_library),
            patch("webui.app.routes._autopilot_status_payload", return_value=compact_autopilot) as autopilot_status,
        ):
            response = self.client.get("/api/home/summary")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["library"]["movies"], 12)
        self.assertEqual(payload["library"]["episodes"], 88)
        autopilot_status.assert_called_once_with(compact=True)

    def test_event_history_is_compacted_once_and_cached(self):
        events_path = os.path.join(TEST_DATA, "performance-events.json")
        oversized = [
            {
                "ts": float(index),
                "level": "info",
                "type": "beta_auto_scan",
                "message": f"Scan {index}",
                "decisions": [{"path": "x" * 400, "reason": "y" * 400} for _ in range(20)],
            }
            for index in range(app_events.MAX_EVENTS + 10)
        ]
        with open(events_path, "w", encoding="utf-8") as handle:
            json.dump(oversized, handle, indent=2)
        original_size = os.path.getsize(events_path)
        original_file = app_events.EVENTS_FILE
        original_cache = app_events._events_cache
        original_signature = app_events._events_signature
        try:
            app_events.EVENTS_FILE = events_path
            app_events._events_cache = None
            app_events._events_signature = None
            first = app_events.load_events(limit=app_events.MAX_EVENTS + 50)
            compacted_size = os.path.getsize(events_path)
            compacted_signature = app_events._events_signature
            second = app_events.load_events(limit=5)
            summaries = app_events.load_event_summaries(limit=5)
            self.assertEqual(len(first), app_events.MAX_EVENTS)
            self.assertEqual(len(second), 5)
            self.assertNotIn("decisions", summaries[0])
            self.assertLess(compacted_size, original_size)
            self.assertEqual(app_events._events_signature, compacted_signature)
        finally:
            app_events.EVENTS_FILE = original_file
            app_events._events_cache = original_cache
            app_events._events_signature = original_signature
            try:
                os.remove(events_path)
            except FileNotFoundError:
                pass

    def test_cold_home_summary_releases_expanded_library_cache(self):
        original_library_cache = app_routes.BETA_LIBRARY_MEMORY_CACHE.copy()
        original_summary_cache = app_routes.BETA_LIBRARY_SUMMARY_CACHE.copy()

        def load_catalog(_settings):
            catalog = {
                "movies": [{"title": "Example"}],
                "shows": [{"title": "Show", "episode_count": 3}],
                "stats": {"episodes": 3},
            }
            app_routes.BETA_LIBRARY_MEMORY_CACHE.update({"signature": ("loaded",), "data": catalog})
            return catalog

        try:
            app_routes.BETA_LIBRARY_MEMORY_CACHE.update({"signature": None, "data": None})
            app_routes.BETA_LIBRARY_SUMMARY_CACHE.update({"signature": None, "data": None})
            with (
                patch("webui.app.routes._beta_file_signature", return_value=None),
                patch("webui.app.routes._beta_mapped_roots", return_value=[]),
                patch("webui.app.routes._beta_load_library_cache", side_effect=load_catalog),
            ):
                summary = app_routes._beta_load_library_summary({})
            self.assertEqual(summary["movies"], 1)
            self.assertEqual(summary["episodes"], 3)
            self.assertIsNone(app_routes.BETA_LIBRARY_MEMORY_CACHE["data"])
        finally:
            app_routes.BETA_LIBRARY_MEMORY_CACHE.clear()
            app_routes.BETA_LIBRARY_MEMORY_CACHE.update(original_library_cache)
            app_routes.BETA_LIBRARY_SUMMARY_CACHE.clear()
            app_routes.BETA_LIBRARY_SUMMARY_CACHE.update(original_summary_cache)

    def test_ai_settings_are_secret_safe_and_provider_test_is_grounded(self):
        page = self.client.get("/settings/ai")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"AI &amp; API Keys", page.data)
        self.assertIn(b"Create Gemini key", page.data)
        self.assertIn(b"Save &amp; test selected provider", page.data)
        self.assertIn(b"Keep English and Spanish audio and subtitles", page.data)

        general_page = self.client.get("/settings")
        self.assertEqual(general_page.status_code, 200)
        self.assertIn(b"Looking for the Gemini or OpenAI API-key boxes?", general_page.data)
        self.assertIn(b'href="/settings/ai"', general_page.data)
        self.assertNotIn(b'id="ai-api-keys"', general_page.data)
        self.assertNotIn(b"Protect the source before saving space", general_page.data)

        smart_page = self.client.get("/settings/smart")
        self.assertEqual(smart_page.status_code, 200)
        self.assertIn(b"Smart Preset Settings", smart_page.data)
        self.assertIn(b"Protect the source before saving space", smart_page.data)
        self.assertIn(b"Never downscale or resize", smart_page.data)
        self.assertIn(b"Never transcode audio", smart_page.data)
        self.assertNotIn(b'id="ai-api-keys"', smart_page.data)
        with open(os.path.join(PROJECT_ROOT, "webui", "app", "static", "styleui.css"), "r", encoding="utf-8") as handle:
            settings_css = handle.read()
        self.assertIn("body.settings-subpage-main .ai-settings-section", settings_css)
        self.assertIn("body.settings-subpage-main .smart-settings-section", settings_css)
        self.assertIn("body.settings-subpage-smart .main-settings-section", settings_css)

        wizard_page = self.client.get("/size_wizard")
        self.assertEqual(wizard_page.status_code, 200)
        self.assertIn(b"Set up Gemini or OpenAI", wizard_page.data)
        self.assertIn(b'id="wizardAiSetupCard"', wizard_page.data)

        with open(os.path.join(PROJECT_ROOT, "docs", "AI_ADVISOR.md"), "r", encoding="utf-8") as handle:
            advisor_docs = handle.read()
        self.assertIn("Docker Compose environment variables", advisor_docs)
        self.assertIn("GEMINI_API_KEY", advisor_docs)
        self.assertIn("OPENAI_API_KEY", advisor_docs)

        saved = self.client.post(
            "/api/ai/settings",
            json={
                "provider": "gemini",
                "gemini_api_key": "test-secret-key",
                "gemini_model": "gemini-3.6-flash",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        payload = saved.get_json()
        self.assertTrue(payload["gemini_api_configured"])
        self.assertNotIn("gemini_api_key", payload)

        public_settings = self.client.get("/api/settings").get_json()["settings"]
        self.assertNotIn("gemini_api_key", public_settings)
        self.assertTrue(public_settings["gemini_api_configured"])

        with patch("webui.app.routes.run_wizard_llm", return_value={"ok": True, "answer": "Connection ready.", "status": {"provider": "gemini"}}) as advisor:
            tested = self.client.post("/api/ai/test")
        self.assertEqual(tested.status_code, 200)
        self.assertIn("Connection ready", tested.get_json()["answer"])
        advisor.assert_called_once()

        self.client.post("/api/ai/settings", json={"provider": "local", "clear_gemini_key": True})

    def test_probe_media_uses_ffprobe_when_handbrake_json_has_no_title_list(self):
        fallback = {
            "duration_sec": 9960.5,
            "width": 3840,
            "height": 2160,
            "fps": 23.976,
            "video_codec": "hevc",
            "is_hdr": True,
            "hdr_reason": "ffprobe transfer characteristic",
        }
        with (
            patch("webui.app.routes._run_cmd", return_value=(True, '{"Scan":{"Progress":1}}', "")),
            patch("webui.app.routes._ffprobe_media_fast", return_value=fallback) as ffprobe,
            patch("webui.app.routes._probe_media_text_fallback") as text_fallback,
        ):
            result = app_routes._probe_media("/media/example/Dune.Part.Two.2160p.mp4")

        self.assertEqual(result, fallback)
        ffprobe.assert_called_once_with("/media/example/Dune.Part.Two.2160p.mp4")
        text_fallback.assert_not_called()

    def test_probe_media_accepts_a_top_level_handbrake_title_array(self):
        scan = [{
            "Duration": {"Hours": 2, "Minutes": 46, "Seconds": 0},
            "Geometry": {"Width": 3840, "Height": 2160},
            "FrameRate": 23.976,
            "Video": {"CodecName": "hevc"},
        }]
        with (
            patch("webui.app.routes._run_cmd", return_value=(True, json.dumps(scan), "")),
            patch("webui.app.routes._ffprobe_media_fast") as ffprobe,
        ):
            result = app_routes._probe_media("/media/example/movie.mp4")

        self.assertEqual(result["width"], 3840)
        self.assertEqual(result["height"], 2160)
        self.assertEqual(result["duration_sec"], 9960.0)
        ffprobe.assert_not_called()

    def test_gemini_and_openai_advisors_use_supported_json_shapes(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

        plan = {
            "src": os.path.join(TEST_MEDIA, "Private.Movie.mkv"),
            "probe": {"width": 1920, "height": 1080, "duration_sec": 7200, "source_size_bytes": 10 * 1024**3, "is_hdr": False, "source_type": "movie"},
            "inputs": {"ai_goal": "balanced", "ai_risk": "safe", "target_mb": 5000, "video_codec": "h265", "encoder_family": "software", "audio_mode": "copy", "audio_tracks": "all", "subtitle_mode": "all"},
            "estimates": {"encoder": "x265", "quality_label": "Good", "output_resolution": {"width": 1920, "height": 1080}},
        }
        model_payload = {"answer": "The plan is balanced and keeps the requested tracks.", "updates": {}, "confidence": "high"}

        with patch(
            "webui.app.wizard_llm.urlopen",
            return_value=FakeResponse({"candidates": [{"content": {"parts": [{"text": json.dumps(model_payload)}]}}]}),
        ) as gemini_call:
            gemini = app_wizard_llm.run_wizard_llm(
                "Explain this plan.",
                plan,
                {"wizard_ai_provider": "gemini", "gemini_api_key": "gemini-secret", "gemini_model": "gemini-3.6-flash"},
            )
        self.assertTrue(gemini["ok"])
        gemini_request = gemini_call.call_args.args[0]
        self.assertIn(":generateContent", gemini_request.full_url)
        self.assertIn("gemini-3.6-flash", gemini_request.full_url)
        self.assertEqual(gemini_request.get_header("X-goog-api-key"), "gemini-secret")

        with patch(
            "webui.app.wizard_llm.urlopen",
            return_value=FakeResponse({"output": [{"content": [{"type": "output_text", "text": json.dumps(model_payload)}]}]}),
        ) as openai_call:
            openai = app_wizard_llm.run_wizard_llm(
                "Explain this plan.",
                plan,
                {"wizard_ai_provider": "openai", "openai_api_key": "openai-secret", "openai_model": "gpt-5.6-luna"},
            )
        self.assertTrue(openai["ok"])
        openai_request = openai_call.call_args.args[0]
        self.assertEqual(openai_request.full_url, "https://api.openai.com/v1/responses")
        sent = json.loads(openai_call.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(sent["model"], "gpt-5.6-luna")
        self.assertNotIn("reasoning", sent)

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

    def test_completed_smart_job_accepts_feedback_only_once(self):
        job_id = "completed-learning-job"
        app_jobs.jobs[job_id] = {
            "id": job_id,
            "status": "done",
            "src": os.path.join(TEST_MEDIA, "Completed.Movie.2026.mkv"),
            "preset": "1080",
            "smart_preset": True,
            "smart_candidate_id": "balanced",
            "automation_source": "autopilot",
            "smart_feedback_context": {
                "source": {"kind": "movie", "hdr": False, "resolution": "1080p"},
                "features": {"codec": "h265", "target_ratio": 0.45},
                "plan": {"encoder": "x265"},
            },
            "finished_at": 123.0,
        }
        try:
            response = self.client.post(
                f"/api/autopilot/completed/{job_id}/feedback",
                json={"verdict": "reject", "reason": "audio"},
            )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(response.get_json()["feedback"]["reason"], "audio")
            self.assertEqual(app_jobs.jobs[job_id]["quality_feedback"]["verdict"], "reject")

            duplicate = self.client.post(
                f"/api/autopilot/completed/{job_id}/feedback",
                json={"verdict": "approve", "reason": "looks_good"},
            )
            self.assertEqual(duplicate.status_code, 409)
        finally:
            app_jobs.jobs.pop(job_id, None)

    def test_quality_and_size_feedback_teach_a_direction(self):
        saved_context = {
            "source": {"kind": "movie", "hdr": False, "resolution": "1080p"},
            "features": {"codec": "h265", "encoder_family": "software", "output_resolution": "1080p", "target_ratio": 0.4},
        }
        profile = {"minimum_feedback": 2}
        quality_state = {"profile": profile, "feedback": [{"verdict": "reject", "reason": "quality", "context": saved_context}]}
        smaller = {"source": saved_context["source"], "features": {**saved_context["features"], "target_ratio": 0.3}}
        roomier = {"source": saved_context["source"], "features": {**saved_context["features"], "target_ratio": 0.55}}
        self.assertGreater(candidate_learning(roomier, quality_state)["acceptance"], candidate_learning(smaller, quality_state)["acceptance"])

        size_state = {"profile": profile, "feedback": [{"verdict": "reject", "reason": "size", "context": saved_context}]}
        self.assertGreater(candidate_learning(smaller, size_state)["acceptance"], candidate_learning(roomier, size_state)["acceptance"])

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

    def test_library_cache_sanitizer_removes_shared_remote_movie_match(self):
        shared_url = "https://is1-ssl.mzstatic.com/image/thumb/wrong/600x900bb.jpg"
        data = {
            "movies": [
                {"type": "movie", "title": "Joker Folie a Deux", "year": 2024, "poster_url": shared_url, "metadata_source": "apple", "metadata_provider_id": 10},
                {"type": "movie", "title": "Deadpool And Wolverine", "year": 2024, "poster_url": shared_url, "metadata_source": "apple", "metadata_provider_id": 10},
            ],
            "shows": [],
        }
        self.assertTrue(app_routes._beta_sanitize_duplicate_artwork(data))
        self.assertEqual([movie["poster_url"] for movie in data["movies"]], ["", ""])
        self.assertTrue(all("metadata_provider_id" not in movie for movie in data["movies"]))

    def test_keyless_movie_match_requires_the_title_not_just_the_year(self):
        rows = [
            {"trackName": "Alien vs. Predator", "releaseDate": "2004-08-13T07:00:00Z", "trackId": 1},
            {"trackName": "Joker: Folie a Deux", "releaseDate": "2024-10-04T07:00:00Z", "trackId": 2},
        ]
        self.assertIsNone(_choose_movie(rows, "Deadpool and Wolverine", 2024))
        match = _choose_movie(rows, "Joker Folie a Deux", 2024)
        self.assertIsNotNone(match)
        self.assertEqual(match["trackId"], 2)

    def test_tmdb_match_requires_title_and_year_fit(self):
        rows = [
            {"id": 1, "title": "Alien vs. Predator", "release_date": "2004-08-13", "poster_path": "/wrong.jpg"},
            {"id": 2, "title": "Joker: Folie a Deux", "release_date": "2024-10-04", "poster_path": "/right.jpg"},
            {"id": 3, "title": "Joker: Folie a Deux", "release_date": "1994-10-04", "poster_path": "/wrong-year.jpg"},
        ]
        self.assertIsNone(app_routes._beta_choose_tmdb_result(rows, "Deadpool and Wolverine", 2024))
        match = app_routes._beta_choose_tmdb_result(rows, "Joker Folie a Deux", 2024)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 2)

    def test_tmdb_artwork_wins_and_keyless_remains_the_fallback(self):
        settings = {
            "tmdb_api_key": "configured",
            "metadata_no_key_enabled": True,
            "episode_release_monitor_enabled": True,
        }

        def keyless(data, _settings):
            for movie in data.get("movies") or []:
                movie["poster_url"] = "https://apple.example/fallback.jpg"
                movie["metadata_source"] = "apple"
            return data

        preferred = {"movies": [{"title": "Example Movie", "year": 2026}], "shows": []}
        with (
            patch("webui.app.routes._beta_tmdb_search", return_value={
                "poster_url": "https://image.tmdb.org/t/p/w342/preferred.jpg",
                "source": "tmdb",
                "poster_source": "tmdb",
                "metadata_source": "tmdb",
                "tmdb_id": 42,
            }),
            patch("webui.app.routes.enrich_media_library", side_effect=keyless),
        ):
            result = app_routes._beta_enrich_metadata(preferred, settings)
        self.assertEqual(result["movies"][0]["poster_source"], "tmdb")
        self.assertTrue(result["movies"][0]["poster_url"].endswith("preferred.jpg"))
        self.assertEqual(result["metadata"]["artwork_priority"], "tmdb_then_keyless")

        fallback = {"movies": [{"title": "Missing Poster", "year": 2026}], "shows": []}
        with (
            patch("webui.app.routes._beta_tmdb_search", return_value={"poster_url": "", "source": "tmdb_empty"}),
            patch("webui.app.routes.enrich_media_library", side_effect=keyless),
        ):
            result = app_routes._beta_enrich_metadata(fallback, settings)
        self.assertEqual(result["movies"][0]["metadata_source"], "apple")
        self.assertTrue(result["movies"][0]["poster_url"].endswith("fallback.jpg"))

    def test_library_filename_parser_keeps_real_movie_title(self):
        cases = {
            "1976.Rocky.1920x1038.BDRip.x265.mkv": ("Rocky", 1976),
            "Deadpool.And.Wolverine.2024.2160p.UHD.BluRay.mkv": ("Deadpool And Wolverine", 2024),
            "Joker.Folie.a.Deux.2024.1080p.BluRay.mkv": ("Joker Folie a Deux", 2024),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                parsed = app_routes._beta_parse_media(os.path.join(TEST_MEDIA, name))
                self.assertEqual((parsed["title"], parsed["year"]), expected)

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

        preview = self.client.post(
            "/api/mobile/v1/library/preview",
            json={"src": os.path.join(TEST_MEDIA, "read-only.mkv")},
            headers=headers,
        )
        self.assertEqual(preview.status_code, 403)

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

        with (
            patch("webui.app.routes._beta_load_library_cache", return_value=library),
            patch(
                "webui.app.routes._beta_load_library_summary",
                return_value={"movies": 1, "shows": 1, "episodes": 0, "updated_at": 123.0, "configured": True},
            ),
        ):
            dashboard = self.client.get("/api/mobile/v1/dashboard", headers=headers)
            mobile_library = self.client.get("/api/mobile/v1/library", headers=headers)

        self.assertEqual(dashboard.status_code, 200, dashboard.get_data(as_text=True))
        dashboard_payload = dashboard.get_json()
        self.assertEqual(dashboard_payload["release"], "3.14.0-beta.1")
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

        onboarding = self.client.post(
            "/api/mobile/v1/autopilot/onboarding",
            json={"completed": True},
            headers=headers,
        )
        self.assertEqual(onboarding.status_code, 200, onboarding.get_data(as_text=True))
        self.assertTrue(onboarding.get_json()["onboarding"]["tour_completed"])

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

    def test_library_fine_tuning_is_transient_and_reaches_smart_candidates(self):
        media_path = os.path.join(TEST_MEDIA, "Fine.Tuned.Movie.2160p.mkv")
        with open(media_path, "wb") as handle:
            handle.write(b"0" * 4096)

        self.client.post(
            "/api/smart_presets/profile",
            json={
                "never_downscale": False,
                "keep_black_bars": False,
                "keep_aspect_ratio": False,
                "never_transcode_audio": False,
                "keep_all_audio_languages": False,
                "keep_all_subtitle_languages": False,
            },
        )

        probe = {
            "duration_sec": 7200.0,
            "width": 3840,
            "height": 2160,
            "fps": 23.976,
            "is_hdr": True,
        }
        tuning = {
            "goal": "small",
            "compatibility": "modern",
            "hardware": "software",
            "resolution_mode": "1080",
            "audio_strategy": "copy",
            "subtitle_mode": "none",
            "target_scale": 0.8,
        }
        with patch("webui.app.routes._probe_media", return_value=probe):
            response = self.client.post(
                "/api/smart_presets/recommend",
                json={"src": media_path, "preset": "auto", "smart_tuning": tuning},
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["profile"]["goal"], "small")
        self.assertEqual(payload["tuning"], tuning)
        self.assertEqual(len(payload["candidates"]), 3)
        for candidate in payload["candidates"]:
            self.assertEqual(candidate["options"]["resolution_mode"], "1080")
            self.assertEqual(candidate["options"]["audio_mode"], "copy")
            self.assertEqual(candidate["options"]["subtitle_mode"], "none")

    def test_library_preview_starts_real_smart_plan_and_exposes_status(self):
        media_path = os.path.join(TEST_MEDIA, "Preview.Movie.2160p.mkv")
        with open(media_path, "wb") as handle:
            handle.write(b"preview-source")
        tuning = {
            "goal": "quality",
            "resolution_mode": "1080",
            "target_scale": 1.1,
        }
        recommendation = {
            "selected_plan": {
                "options": {
                    "resolution_mode": "1080",
                    "audio_mode": "copy",
                    "subtitle_mode": "all",
                },
                "inputs": {"target_mb": 4096},
            },
            "recommended_id": "quality",
            "candidates": [
                {
                    "id": "quality",
                    "name": "Quality guard",
                    "summary": "Protects detail",
                }
            ],
            "tuning": tuning,
        }

        with (
            patch("webui.app.routes._smart_recommendation", return_value=recommendation),
            patch("webui.app.routes.threading.Thread") as thread_class,
        ):
            started = self.client.post(
                "/api/library/preview",
                json={"src": media_path, "smart_tuning": tuning},
            )

        self.assertEqual(started.status_code, 202, started.get_data(as_text=True))
        preview = started.get_json()["preview"]
        self.assertTrue(preview["preview_id"].startswith("library_"))
        self.assertEqual(preview["candidate_name"], "Quality guard")
        self.assertEqual(preview["tuning"], tuning)
        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once()
        preview_payload = thread_class.call_args.kwargs["args"][1]
        self.assertEqual(preview_payload["src"], media_path)
        self.assertEqual(preview_payload["resolution_mode"], "1080")
        self.assertEqual(preview_payload["target_size_value"], 4096)

        status = self.client.get(f"/api/library/preview/{preview['preview_id']}")
        self.assertEqual(status.status_code, 200, status.get_data(as_text=True))
        self.assertEqual(status.get_json()["preview"]["state"], "queued")

        missing = self.client.post(
            "/api/library/preview",
            json={"src": os.path.join(TEST_MEDIA, "missing.mkv")},
        )
        self.assertEqual(missing.status_code, 400)

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
                "never_downscale": False,
                "keep_black_bars": False,
                "keep_aspect_ratio": False,
                "keep_all_audio_languages": False,
                "keep_all_subtitle_languages": False,
                "never_transcode_audio": False,
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
        self.assertFalse(saved_profile["never_downscale"])
        self.assertFalse(saved_profile["never_transcode_audio"])

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
        self.assertEqual(args[args.index("--audio-lang-list") + 1], "fre")
        self.assertEqual(args[args.index("--subtitle-lang-list") + 1], "fre")
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
        self.assertEqual(copy_args[copy_args.index("--audio-lang-list") + 1], "fre")
        self.assertEqual(copy_args[copy_args.index("--subtitle-lang-list") + 1], "fre")
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

    def test_smart_preset_preservation_guardrails_override_season_tuning(self):
        try:
            os.remove(SMART_PRESETS_FILE)
        except FileNotFoundError:
            pass

        media_path = os.path.join(TEST_MEDIA, "Example.Show.S01E01.2160p.mkv")
        with open(media_path, "wb") as handle:
            handle.write(b"0" * 4096)

        profile_response = self.client.post(
            "/api/smart_presets/profile",
            json={
                "goal": "small",
                "audio_strategy": "eac3_surround",
                "audio_languages": ["eng", "jpn"],
                "subtitle_languages": ["eng", "jpn"],
            },
        )
        self.assertEqual(profile_response.status_code, 200)
        profile = profile_response.get_json()["profile"]
        self.assertTrue(profile["never_downscale"])
        self.assertTrue(profile["keep_black_bars"])
        self.assertTrue(profile["keep_aspect_ratio"])
        self.assertTrue(profile["keep_all_audio_languages"])
        self.assertTrue(profile["keep_all_subtitle_languages"])
        self.assertTrue(profile["never_transcode_audio"])

        probe = {
            "duration_sec": 2700.0,
            "width": 3840,
            "height": 2160,
            "fps": 23.976,
            "is_hdr": False,
        }
        with patch("webui.app.routes._probe_media", return_value=probe):
            recommendation = app_routes._smart_recommendation(
                {
                    "src": media_path,
                    "preset": "auto",
                    "smart_tuning": {
                        "resolution_mode": "720",
                        "audio_strategy": "eac3_surround",
                        "subtitle_mode": "none",
                    },
                }
            )

        plan = recommendation["selected_plan"]
        options = plan["options"]
        args = plan["extra_args"]
        self.assertEqual(options["resolution_mode"], "keep")
        self.assertEqual(plan["estimates"]["output_resolution"], {"width": 3840, "height": 2160})
        self.assertEqual(options["crop_mode"], "none")
        self.assertEqual(options["audio_mode"], "copy")
        self.assertEqual(options["audio_languages"], [])
        self.assertEqual(options["subtitle_languages"], [])
        self.assertEqual(options["subtitle_mode"], "all")
        self.assertEqual(args[args.index("--width") + 1], "3840")
        self.assertEqual(args[args.index("--height") + 1], "2160")
        self.assertIn("--keep-display-aspect", args)
        self.assertEqual(args[args.index("--crop") + 1], "0:0:0:0")
        self.assertIn("--all-audio", args)
        self.assertIn("--all-subtitles", args)
        self.assertNotIn("--audio-lang-list", args)
        self.assertNotIn("--subtitle-lang-list", args)
        self.assertEqual(args[args.index("-E") + 1], "copy")
        self.assertEqual(args[args.index("--audio-fallback") + 1], "none")


if __name__ == "__main__":
    unittest.main()
