#!/usr/bin/env python3
"""
Tests covering WinPrint v2.1 enhancements:
- Pure vector imposition (qpdf page range + Poppler/Cairo 2-up, booklet, watermark)
- Symmetric binding gutter shift in winprint_layout
- Hardware controls (Tray, MediaType, Quiet Mode, Density) in winprint_engine_v2
- 1-sheet hardware Copies=N vs multi-sheet PJL collation + single-socket streaming & cancel_event
- winprint_spooler.update_config persistence
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_imposition
import winprint_layout
import winprint_engine_v2
import winprint_engine
import winprint_spooler

WINPRINT_PPD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Brother_B7640DW_WinPrint.ppd"))


class TestWinPrintV21(unittest.TestCase):
    def setUp(self):
        self.geom_f4 = winprint_layout.get_media_geometry(WINPRINT_PPD, "F4", "portrait")
        fd, self.src_2p = tempfile.mkstemp(suffix="_2p.pdf")
        os.close(fd)
        winprint_layout.generate_calibration_pdf(self.src_2p, self.geom_f4)

        fd4, self.src_4p = tempfile.mkstemp(suffix="_4p.pdf")
        os.close(fd4)
        subprocess.run(
            ["qpdf", "--empty", "--pages", self.src_2p, "1-2", self.src_2p, "1-2", "--", self.src_4p],
            check=True,
        )

    def tearDown(self):
        for p in (self.src_2p, self.src_4p):
            if os.path.exists(p):
                os.remove(p)

    def test_1_vector_imposition_booklet_and_range_preserves_fonts(self):
        fd_out, out_pdf = tempfile.mkstemp(suffix="_imp.pdf")
        os.close(fd_out)
        fd_rng, rng_pdf = tempfile.mkstemp(suffix="_rng.pdf")
        os.close(fd_rng)
        try:
            ok_rng = winprint_imposition.build_imposed_pdf(
                self.src_4p, rng_pdf, page_range_str="1,3-4", n_up=1, reverse_order=True
            )
            self.assertTrue(ok_rng)
            self.assertEqual(winprint_imposition.get_pdf_page_count(rng_pdf), 3)

            ok_bk = winprint_imposition.build_imposed_pdf(
                self.src_4p,
                out_pdf,
                n_up=2,
                booklet=True,
                booklet_binding="right",
                add_border=True,
                watermark_text="RAHASIA",
            )
            self.assertTrue(ok_bk)
            self.assertEqual(winprint_imposition.get_pdf_page_count(out_pdf), 2)
            fonts_out = subprocess.check_output(["pdffonts", out_pdf], text=True)
            self.assertIn("TrueType", fonts_out)
        finally:
            for p in (out_pdf, rng_pdf):
                if os.path.exists(p):
                    os.remove(p)

    def test_2_symmetric_binding_gutter_transform(self):
        tr_front = winprint_layout.compute_layout_transform(
            612.0, 936.0, self.geom_f4, fit_to_printable=False,
            is_back_side=False, binding_gutter_pt=10.0,
        )
        tr_back = winprint_layout.compute_layout_transform(
            612.0, 936.0, self.geom_f4, fit_to_printable=False,
            is_back_side=True, offset_x_pt=0.0, offset_y_pt=0.0, binding_gutter_pt=10.0,
        )
        self.assertAlmostEqual(tr_front.tx_pt - tr_back.tx_pt, 20.0, places=2)

    @unittest.skipUnless(os.path.isfile(winprint_engine_v2.RAWTOBR3_PATH), "rawtobr3 not installed")
    def test_3_hardware_controls_and_copy_acceleration_modes(self):
        fd1, src_1p = tempfile.mkstemp(suffix="_1p.pdf")
        os.close(fd1)
        try:
            subprocess.run(
                ["qpdf", "--empty", "--pages", self.src_2p, "1", "--", src_1p],
                check=True,
            )
            # 1-page simplex -> safe hardware Copies=25 (\x1b&l25X) at 34 PPM
            res_hw = winprint_engine_v2.render_job(
                input_pdf=src_1p,
                media="F4",
                duplex="SIMPLEX",
                copies=25,
                geometry=self.geom_f4,
                paper_source="manual",
                media_type="thick",
                quiet_mode=True,
                density=2,
                binding_gutter_mm=5.0,
                collate=True,
                backend="brother_pcl",
            )
            m_hw = res_hw["manifest"]
            stream_hw = res_hw["stream"]
            self.assertEqual(m_hw["copy_mode"], "hardware_copies")
            self.assertEqual(len(res_hw["copies_payloads"]), 1)
            self.assertIn(b"@PJL SET SOURCETRAY = MPTRAY", stream_hw)
            self.assertIn(b"@PJL SET MEDIATYPE = THICK", stream_hw)
            self.assertIn(b"@PJL SET PAPERFEEDSPEED=HALF", stream_hw)
            self.assertIn(b"@PJL SET DENSITY = 2", stream_hw)
            self.assertIn(b"\x1b&l25X", stream_hw)
        finally:
            if os.path.exists(src_1p):
                os.remove(src_1p)

        # 2-page duplex must still use per-copy PJL envelopes so front isn't duplicated onto back
        res_col = winprint_engine_v2.render_job(
            input_pdf=self.src_2p,
            media="F4",
            duplex="LONG_EDGE",
            copies=3,
            geometry=self.geom_f4,
            collate=True,
            backend="brother_pcl",
        )
        self.assertEqual(res_col["manifest"]["copy_mode"], "pjl_collated")
        self.assertEqual(len(res_col["copies_payloads"]), 3)
        self.assertEqual(res_col["stream"].count(b"@PJL JOB NAME ="), 3)

    def test_4_single_socket_stream_and_cancel_event(self):
        received = []
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        port = srv.getsockname()[1]

        def accept_one():
            conn, _ = srv.accept()
            chunks = []
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                chunks.append(data)
            received.append(b"".join(chunks))
            conn.close()

        t = threading.Thread(target=accept_one, daemon=True)
        t.start()
        try:
            ok = winprint_engine.send_jobs_stream("127.0.0.1", [b"JOB1;", b"JOB2;", b"JOB3;"], port=port)
            t.join(timeout=2.0)
            self.assertTrue(ok)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0], b"JOB1;JOB2;JOB3;")

            ev = threading.Event()
            ev.set()
            ok_cancel = winprint_engine.send_jobs_stream(
                "127.0.0.1", [b"JOB1;", b"JOB2;"], port=port, cancel_event=ev
            )
            self.assertFalse(ok_cancel)
            self.assertIn("dibatalkan", winprint_engine.get_last_error().lower())
        finally:
            srv.close()

    def test_5_spooler_update_config(self):
        tmp_dir = tempfile.mkdtemp(prefix="winprint_cfg_test_")
        try:
            cfg_path = os.path.join(tmp_dir, "config.json")
            with patch.object(winprint_spooler, "DB_DIR", tmp_dir), \
                 patch.object(winprint_spooler, "CONFIG_PATH", cfg_path):
                updated = winprint_spooler.update_config({"printer_ip": "192.168.100.236", "default_paper": "F4"})
                self.assertEqual(updated["printer_ip"], "192.168.100.236")
                with open(cfg_path, "r") as f:
                    saved = json.load(f)
                self.assertEqual(saved["default_paper"], "F4")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
