#!/usr/bin/env python3
"""
Unit tests for winprint_layout.py verifying PPD parsing, ImageableArea geometry,
aspect-ratio preservation, back-side offset isolation, and 3x2 calibration PDF generation.
Runs completely offline without physical printer.
"""

import os
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_layout

WINPRINT_PPD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Brother_B7640DW_WinPrint.ppd"))
BROTHER_WIN_PPD = "/tmp/brother_windows_driver/brppb7640dw.ppd"


class TestWinPrintLayout(unittest.TestCase):
    def test_1_parse_ppd_a4_and_folio(self):
        ppd = BROTHER_WIN_PPD if os.path.isfile(BROTHER_WIN_PPD) else WINPRINT_PPD
        geom_a4 = winprint_layout.get_media_geometry(ppd, "A4", "portrait")
        self.assertAlmostEqual(geom_a4.width_pt, 595.0, delta=1.0)
        self.assertAlmostEqual(geom_a4.height_pt, 842.0, delta=1.0)
        self.assertGreater(geom_a4.printable_width_pt, 550.0)
        self.assertLess(geom_a4.printable_width_pt, geom_a4.width_pt)

        geom_folio = winprint_layout.get_media_geometry(ppd, "Folio", "portrait")
        self.assertAlmostEqual(geom_folio.width_pt, 612.0, delta=3.0)
        self.assertAlmostEqual(geom_folio.height_pt, 936.0, delta=1.0)
        self.assertGreater(geom_folio.printable_height_pt, 850.0)

    def test_2_landscape_orientation_swap(self):
        ppd = WINPRINT_PPD
        geom_port = winprint_layout.get_media_geometry(ppd, "A4", "portrait")
        geom_land = winprint_layout.get_media_geometry(ppd, "A4", "landscape")
        self.assertAlmostEqual(geom_land.width_pt, geom_port.height_pt, delta=0.1)
        self.assertAlmostEqual(geom_land.height_pt, geom_port.width_pt, delta=0.1)

    def test_3_aspect_ratio_fit_and_centering(self):
        ppd = WINPRINT_PPD
        geom = winprint_layout.get_media_geometry(ppd, "F4", "portrait")
        # Fit an A4 doc (595x842) onto F4 printable area
        tr = winprint_layout.compute_layout_transform(595.0, 842.0, geom, fit_to_printable=True)
        self.assertFalse(tr.clips_printable_area)
        self.assertGreater(tr.scale, 0.9)
        # Aspect ratio preserved
        self.assertAlmostEqual(tr.rendered_width_pt / tr.rendered_height_pt, 595.0 / 842.0, places=3)

    def test_4_back_side_offset_isolation(self):
        ppd = WINPRINT_PPD
        geom = winprint_layout.get_media_geometry(ppd, "A4", "portrait")
        tr_front = winprint_layout.compute_layout_transform(595.0, 842.0, geom, is_back_side=False, offset_y_pt=12.0)
        tr_back = winprint_layout.compute_layout_transform(595.0, 842.0, geom, is_back_side=True, offset_y_pt=12.0)
        self.assertAlmostEqual(tr_back.ty_pt - tr_front.ty_pt, 12.0, places=3)
        self.assertAlmostEqual(tr_back.tx_pt, tr_front.tx_pt, places=3)

    def test_5_generate_calibration_pdf_3x2(self):
        ppd = WINPRINT_PPD
        geom = winprint_layout.get_media_geometry(ppd, "F4", "portrait")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            pdf_path = tf.name
        try:
            winprint_layout.generate_calibration_pdf(pdf_path, geom)
            self.assertTrue(os.path.isfile(pdf_path))
            out = subprocess.check_output(["pdfinfo", pdf_path], text=True)
            self.assertIn("Pages:           2", out)
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_6_sheet_fit_wysiwyg_scaling(self):
        ppd = WINPRINT_PPD
        geom_f4 = winprint_layout.get_media_geometry(ppd, "F4", "portrait")
        # Same-size F4-on-F4 at fit_to_printable=False stays 1.0
        tr_same = winprint_layout.compute_layout_transform(geom_f4.width_pt, geom_f4.height_pt, geom_f4, fit_to_printable=False)
        self.assertAlmostEqual(tr_same.scale, 1.0, places=5)
        self.assertAlmostEqual(tr_same.tx_pt, 0.0, places=3)
        self.assertAlmostEqual(tr_same.ty_pt, 0.0, places=3)
        # Mismatched A4-on-F4 scales proportionally by min(w_f4/w_a4, h_f4/h_a4)
        tr_a4 = winprint_layout.compute_layout_transform(595.0, 842.0, geom_f4, fit_to_printable=False)
        expected = min(geom_f4.width_pt / 595.0, geom_f4.height_pt / 842.0)
        self.assertAlmostEqual(tr_a4.scale, expected, places=4)

    def test_7_rotate_landscape_to_portrait_normalization(self):
        ppd = WINPRINT_PPD
        geom_land = winprint_layout.get_media_geometry(ppd, "A4", "landscape")
        fd1, src_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd1)
        fd2, out_pdf = tempfile.mkstemp(suffix="_norm.pdf")
        os.close(fd2)
        try:
            winprint_layout.generate_calibration_pdf(src_pdf, geom_land)
            winprint_layout.normalize_pdf(
                src_pdf, out_pdf, geom_land,
                fit_to_printable=False, rotate_landscape_to_portrait=True
            )
            w_out, h_out = winprint_layout.get_pdf_page_size(out_pdf)
            self.assertLess(w_out, h_out)
            self.assertAlmostEqual(w_out, geom_land.height_pt, delta=1.0)
            self.assertAlmostEqual(h_out, geom_land.width_pt, delta=1.0)
        finally:
            for p in (src_pdf, out_pdf):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
