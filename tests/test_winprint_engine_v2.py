#!/usr/bin/env python3
"""
Unit tests for winprint_engine_v2.py verifying Brother Native PCL (`rawtobr3`),
pure PCL-XL fallback (`pxlmono`), JOB/EOJ collation boundaries, calibration profile loading,
experimental PJL isolation, and reproducibility manifest.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_layout
import winprint_engine_v2

WINPRINT_PPD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Brother_B7640DW_WinPrint.ppd"))


class TestWinPrintEngineV2(unittest.TestCase):
    def setUp(self):
        self.geom_f4 = winprint_layout.get_media_geometry(WINPRINT_PPD, "F4", "portrait")
        self.geom_a4 = winprint_layout.get_media_geometry(WINPRINT_PPD, "A4", "portrait")
        fd, self.temp_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        winprint_layout.generate_calibration_pdf(self.temp_pdf, self.geom_f4)

    def tearDown(self):
        if os.path.exists(self.temp_pdf):
            os.remove(self.temp_pdf)

    def test_1_pure_pclxl_fallback_and_manifest(self):
        res = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf,
            media="F4",
            duplex="LONG_EDGE",
            copies=1,
            geometry=self.geom_f4,
            experimental_pjl=False,
            backend="pclxl",
        )
        stream = res["stream"]
        manifest = res["manifest"]

        self.assertEqual(manifest["backend"], "pclxl")
        self.assertIn(b") HP-PCL XL;", stream)
        self.assertNotIn(b"setpagedevice", stream)
        self.assertNotIn(b"BeginPage", stream)
        self.assertTrue(manifest["stream_header"].startswith(") HP-PCL XL;"))
        self.assertEqual(len(manifest["final_stream_sha256"]), 64)
        self.assertNotEqual(manifest["gs_version"], "unknown")

    def test_2_experimental_pjl_flag_isolation_pclxl(self):
        res_off = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf, media="A4", duplex="LONG_EDGE",
            copies=1, geometry=self.geom_a4, experimental_pjl=False, backend="pclxl"
        )
        self.assertNotIn(b"DXBACKSIDEFIRSTSENDMODE", res_off["stream"])

        res_on = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf, media="A4", duplex="LONG_EDGE",
            copies=1, geometry=self.geom_a4, experimental_pjl=True, backend="pclxl"
        )
        self.assertIn(b"@PJL SET DXBACKSIDEFIRSTSENDMODE = ON", res_on["stream"])
        self.assertIn(b"@PJL SET PCLCONPULSORYFFIGNOREMODE = ON", res_on["stream"])

    def test_3_software_collation_job_eoj_boundaries(self):
        res = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf, media="F4", duplex="LONG_EDGE",
            copies=3, geometry=self.geom_f4, experimental_pjl=False, backend="pclxl"
        )
        stream = res["stream"]
        self.assertEqual(stream.count(b"@PJL JOB NAME ="), 3)
        self.assertEqual(stream.count(b"@PJL EOJ NAME ="), 3)
        self.assertEqual(stream.count(b"@PJL SET COPIES = 1"), 3)
        self.assertEqual(stream.count(b") HP-PCL XL;"), 3)

    @unittest.skipUnless(os.path.isfile(winprint_engine_v2.RAWTOBR3_PATH), "rawtobr3 not installed")
    def test_4_brother_pcl_folio_1038_and_calibration_profile(self):
        res = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf,
            media="Folio",
            duplex="LONG_EDGE",
            copies=2,
            geometry=self.geom_f4,
            backend="brother_pcl",
        )
        stream = res["stream"]
        m = res["manifest"]
        self.assertEqual(m["backend"], "brother_pcl")
        self.assertAlmostEqual(m["offset_x_pt"], 2.5 * winprint_layout.PT_PER_MM, places=2)
        self.assertAlmostEqual(m["offset_y_pt"], -3.8 * winprint_layout.PT_PER_MM, places=2)
        self.assertEqual(stream.count(b"@PJL JOB NAME ="), 2)
        self.assertEqual(stream.count(b"@PJL EOJ NAME ="), 2)
        self.assertIn(b"@PJL ENTER LANGUAGE = PCL\n", stream)
        # Brother Folio PCL code 1038 & Long-Edge Duplex 1S
        self.assertIn(b"\x1b&l1038a", stream)
        self.assertIn(b"\x1b&l1S", stream)
        self.assertEqual(len(res["copies_payloads"]), 2)

    @unittest.skipUnless(os.path.isfile(winprint_engine_v2.RAWTOBR3_PATH), "rawtobr3 not installed")
    def test_5_landscape_brother_pcl_preserves_native_paper_codes(self):
        geom_a4_land = winprint_layout.get_media_geometry(WINPRINT_PPD, "A4", "landscape")
        res_a4 = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf, media="A4", duplex="SIMPLEX",
            copies=1, geometry=geom_a4_land, backend="brother_pcl"
        )
        self.assertIn(b"\x1b&l26a", res_a4["stream"])
        self.assertNotIn(b"\x1b&l3a", res_a4["stream"])

        geom_f4_land = winprint_layout.get_media_geometry(WINPRINT_PPD, "Folio", "landscape")
        res_f4 = winprint_engine_v2.render_job(
            input_pdf=self.temp_pdf, media="Folio", duplex="SIMPLEX",
            copies=1, geometry=geom_f4_land, backend="brother_pcl"
        )
        self.assertIn(b"\x1b&l1038a", res_f4["stream"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
