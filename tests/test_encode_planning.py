import json
import os
import tempfile
import unittest
from unittest import mock

from webui.app import jobs, presets


class EncodePlanningTests(unittest.TestCase):
    def test_requested_qsv_scenarios_use_the_expected_decode_and_resolution_plan(self):
        scenarios = (
            ("local H.264 1080p", "local", "1080", "h264", 1920, 1080, (1920, 1080)),
            ("remote HEVC 10-bit 4K", "remote_transfer", "4k", "hevc", 3840, 2160, (3840, 2160)),
            ("remote HEVC 10-bit 4K to 1080p", "remote_transfer", "1080", "hevc", 3840, 2160, (1920, 1080)),
        )
        for label, job_mode, preset_key, codec, width, height, expected in scenarios:
            with self.subTest(label=label):
                source = {
                    "codec": codec,
                    "profile": "Main 10" if codec == "hevc" else "High",
                    "pix_fmt": "yuv420p10le" if codec == "hevc" else "yuv420p",
                    "width": width,
                    "height": height,
                    "error": "",
                }
                decode = jobs._hardware_decode_plan("qsv_h265_10bit", source, "auto")
                dimensions = jobs._resolution_plan(preset_key, source)

                self.assertIn(job_mode, {"local", "remote_transfer"})
                self.assertTrue(decode["enabled"])
                self.assertEqual(decode["cli_args"], ["--enable-hw-decoding", "qsv"])
                self.assertEqual(
                    (dimensions["target_width"], dimensions["target_height"]),
                    expected,
                )

    def test_resolution_ceiling_never_upscales_and_preserves_aspect_ratio(self):
        source = {"width": 1280, "height": 720}
        plan_1080 = jobs._resolution_plan("1080", source)
        plan_4k = jobs._resolution_plan("4k", source)
        width_only = jobs._resolution_plan("1080", {"width": 3840, "height": 2160}, "--width 1280")

        self.assertEqual((plan_1080["target_width"], plan_1080["target_height"]), (1280, 720))
        self.assertEqual((plan_4k["target_width"], plan_4k["target_height"]), (1280, 720))
        self.assertEqual((width_only["target_width"], width_only["target_height"]), (1280, 720))
        self.assertEqual(plan_1080["cli_args"], ["--maxWidth", "1920", "--maxHeight", "1080"])

    def test_hardware_decode_modes_and_unsupported_source_fall_back_safely(self):
        h264 = {"codec": "h264", "error": ""}
        av1 = {"codec": "av1", "error": ""}

        self.assertTrue(jobs._hardware_decode_plan("x265", h264, "qsv")["enabled"])
        self.assertFalse(jobs._hardware_decode_plan("x265", h264, "auto")["enabled"])
        self.assertFalse(jobs._hardware_decode_plan("qsv_h265_10bit", h264, "off")["enabled"])
        unsupported = jobs._hardware_decode_plan("qsv_h265_10bit", av1, "auto")
        self.assertFalse(unsupported["enabled"])
        self.assertEqual(unsupported["cli_args"], ["--disable-hw-decoding"])
        self.assertIn("not in the supported", unsupported["reason"])

    def test_decode_log_evidence_distinguishes_active_qsv_from_encode_only(self):
        positive = (
            '"HWDecode": 1',
            '"HardwareDecode": 4',
            '"QSV": {"Decode": true}',
            'encqsvInit: using full QSV path',
            'hevc_qsv-decoder: opening decoder',
        )
        negative = (
            '"HWDecode": 0',
            '"HardwareDecode": 0',
            '"QSV": {"Decode": false}',
            'encqsvInit: using encode-only via system memory path',
            '[ByteSqueeze] Hardware decode: software fallback (QSV decode attempt exited 1)',
        )
        for line in positive:
            self.assertEqual(jobs._qsv_decode_log_evidence(line), "active")
        for line in negative:
            self.assertEqual(jobs._qsv_decode_log_evidence(line), "fallback")

    def test_1080_mapping_repair_replaces_a_4k_preset_and_persists_it(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bad_file = os.path.join(tempdir, "bad-4k.json")
            good_file = os.path.join(tempdir, "good-1080.json")
            config_file = os.path.join(tempdir, "preset_config.json")
            with open(bad_file, "w", encoding="utf-8") as stream:
                json.dump({"PresetList": [{"PresetName": "Wrong 4K", "PictureWidth": 3840, "PictureHeight": 2160}]}, stream)
            with open(good_file, "w", encoding="utf-8") as stream:
                json.dump({"PresetList": [{"PresetName": "Correct 1080p", "PictureWidth": 1920, "PictureHeight": 1080}]}, stream)
            defaults = {
                "1080": {"file": good_file, "name": "Correct 1080p"},
                "4k": {"file": bad_file, "name": "Wrong 4K"},
            }
            with open(config_file, "w", encoding="utf-8") as stream:
                json.dump({"1080": {"file": bad_file, "name": "Wrong 4K"}, "4k": defaults["4k"]}, stream)

            with mock.patch.object(presets, "PRESET_CONFIG_FILE", config_file), mock.patch.object(
                presets,
                "DEFAULT_PRESET_CONFIG",
                defaults,
            ):
                presets.load_preset_config()
                selected_file, selected_name = presets.resolve_preset_file_and_name("1080")

            self.assertEqual((selected_file, selected_name), (good_file, "Correct 1080p"))
            self.assertEqual(presets.preset_config["4k"]["name"], "Wrong 4K")
            with open(config_file, "r", encoding="utf-8") as stream:
                persisted = json.load(stream)
            self.assertEqual(persisted["1080"], defaults["1080"])

    def test_shell_command_enforces_caps_and_retries_failed_qsv_decode_in_software(self):
        script_path = os.path.join(os.path.dirname(__file__), "..", "worker", "encode-one.sh")
        with open(script_path, "r", encoding="utf-8") as stream:
            script = stream.read()

        self.assertLess(script.index("${EXTRA_ARGS}"), script.index("${DIMENSION_OPTS}"))
        self.assertLess(script.index("${DIMENSION_OPTS}"), script.index("${HW_DECODE_OPTS}"))
        self.assertIn('HW_DECODE_OPTS="${HB_HW_DECODE_OPTS:---disable-hw-decoding}"', script)
        self.assertIn('rm -f -- "$OUT"', script)
        self.assertIn("--disable-hw-decoding", script)


if __name__ == "__main__":
    unittest.main()
