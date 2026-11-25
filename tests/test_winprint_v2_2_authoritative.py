import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "modules"))

import winprint_engine_v2  # noqa: E402
import winprint_ipp_server  # noqa: E402
import winprint_layout  # noqa: E402
import winprint_spooler  # noqa: E402


MANIFEST_PATH = os.path.join(BASE_DIR, "office_manifest.json")
PPD_PATH = os.path.join(BASE_DIR, "Brother_B7640DW_WinPrint.ppd")


class TestWinPrintV22Authoritative(unittest.TestCase):
    def test_authoritative_manifest_overrides_stale_config_preserving_network_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            stale = {
                "printer_ip": "192.168.1.99",
                "default_paper": "A4",
                "default_duplex": "none",
                "safe_fit_to_printable": False,
                "known_macs": {"aa:bb:cc:dd:ee:ff": "192.168.1.55"},
                "known_printers": {"192.168.1.55": {"model": "Brother DCP-B7640DW"}},
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(stale, f)

            applied = winprint_spooler.apply_authoritative_manifest(
                config_path=cfg_path,
                manifest_path=MANIFEST_PATH,
                preserve_network_cache=True,
            )
            self.assertEqual(applied["default_paper"], "F4")
            self.assertEqual(applied["default_duplex"], "long")
            self.assertTrue(applied["safe_fit_to_printable"])
            self.assertEqual(applied["office_profile_version"], "2.2.0")
            self.assertEqual(applied["known_macs"], {"aa:bb:cc:dd:ee:ff": "192.168.1.55"})
            self.assertEqual(applied["known_printers"], {"192.168.1.55": {"model": "Brother DCP-B7640DW"}})

            # Verify get_config merges manifest policy unless keep_local_override is True
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"default_paper": "A4", "default_duplex": "none"}, f)
            orig_cfg = winprint_spooler.CONFIG_PATH
            orig_man = winprint_spooler.OFFICE_MANIFEST_PATH
            try:
                winprint_spooler.CONFIG_PATH = cfg_path
                winprint_spooler.OFFICE_MANIFEST_PATH = MANIFEST_PATH
                enforced = winprint_spooler.get_config()
                self.assertEqual(enforced["default_paper"], "F4")
                self.assertEqual(enforced["default_duplex"], "long")

                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "default_paper": "A4",
                            "default_duplex": "none",
                            "keep_local_override": True,
                        },
                        f,
                    )
                kept = winprint_spooler.get_config()
                self.assertEqual(kept["default_paper"], "A4")
                self.assertEqual(kept["default_duplex"], "none")
            finally:
                winprint_spooler.CONFIG_PATH = orig_cfg
                winprint_spooler.OFFICE_MANIFEST_PATH = orig_man

    def test_calibration_overrides_uncalibrated_zero_and_respects_ui_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof_path = os.path.join(tmp, "calibration_profiles.json")
            with open(prof_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "Brother DCP-B7640DW": {
                            "F4": {
                                "LONG_EDGE": {
                                    "offset_x_mm": 0.0,
                                    "offset_y_mm": 0.0,
                                    "notes": "Default neutral",
                                }
                            }
                        }
                    },
                    f,
                )

            x_mm, y_mm = winprint_engine_v2.get_calibration_mm(
                "F4", "LONG_EDGE", profile_path=prof_path
            )
            self.assertAlmostEqual(x_mm, 2.5, places=3)
            self.assertAlmostEqual(y_mm, -3.8, places=3)

            winprint_engine_v2.save_calibration_mm(
                "F4",
                "LONG_EDGE",
                0.0,
                0.0,
                notes="Saved from WinPrint Studio UI",
                profile_path=prof_path,
            )
            x_ui, y_ui = winprint_engine_v2.get_calibration_mm(
                "F4", "LONG_EDGE", profile_path=prof_path
            )
            self.assertAlmostEqual(x_ui, 0.0, places=3)
            self.assertAlmostEqual(y_ui, 0.0, places=3)

    def test_ppd_defaults_f4_duplex_and_safe_margin_prevents_clipping(self):
        with open(PPD_PATH, "r", encoding="utf-8") as f:
            ppd_text = f.read()
        self.assertIn("*DefaultPageSize: F4", ppd_text)
        self.assertIn("*DefaultDuplex: DuplexNoTumble", ppd_text)

        geom = winprint_layout.get_media_geometry(PPD_PATH, "F4", "portrait")
        self.assertAlmostEqual(geom.width_pt, 612.0, places=1)
        self.assertAlmostEqual(geom.height_pt, 936.0, places=1)

        # Native F4 document with fit_to_printable=True must not clip hardware borders
        tf_f4 = winprint_layout.compute_layout_transform(
            612.0, 936.0, geom, fit_to_printable=True, manual_scale=1.0
        )
        self.assertFalse(tf_f4.clips_printable_area)

        # Native A4 document fitted onto F4 with fit_to_printable=True must not clip
        tf_a4 = winprint_layout.compute_layout_transform(
            595.28, 841.89, geom, fit_to_printable=True, manual_scale=1.0
        )
        self.assertFalse(tf_a4.clips_printable_area)

    def test_ipp_advertises_folio_and_two_sided_long_edge(self):
        body = winprint_ipp_server.build_printer_attributes_response(1)
        self.assertIn(b"na_fanfold-german-legal_8.5x13in", body)
        self.assertIn(b"two-sided-long-edge", body)


if __name__ == "__main__":
    unittest.main()
