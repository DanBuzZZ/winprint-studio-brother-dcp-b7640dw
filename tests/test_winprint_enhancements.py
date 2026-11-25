#!/usr/bin/env python3
"""
Tests covering Enhancements Steps 1-4:
- winprint_spooler sqlite3.Row scale/printer_model schema migration & worker execution
- winprint_layout.detect_pdf_media across canonical paper sizes and orientations
- winprint_engine_v2 calibration read/write & Brother DCP-L2540DW PCL rendering
- WinPrintThreadingIPPServer concurrent Get-Printer-Attributes handling
"""

import concurrent.futures
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_spooler
import winprint_layout
import winprint_engine_v2
import winprint_ipp_server

WINPRINT_PPD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Brother_B7640DW_WinPrint.ppd"))
L2540_RAWTOBR3 = winprint_engine_v2.BROTHER_DRIVER_SPECS["Brother DCP-L2540DW"]["rawtobr3"]


class TestWinPrintEnhancements(unittest.TestCase):
    def test_1_spooler_sqlite_row_migration_and_worker(self):
        tmp_dir = tempfile.mkdtemp(prefix="winprint_spool_test_")
        try:
            db_path = os.path.join(tmp_dir, "spool.db")
            cfg_path = os.path.join(tmp_dir, "config.json")
            src_pdf = os.path.join(tmp_dir, "sample.pdf")
            with open(src_pdf, "wb") as f:
                f.write(b"%PDF-1.4\n%%EOF\n")

            # Seed legacy jobs table without `scale` or `printer_model` columns
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    paper TEXT DEFAULT 'A4',
                    duplex TEXT DEFAULT 'none',
                    toner_save INTEGER DEFAULT 0,
                    resolution INTEGER DEFAULT 600,
                    copies INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            """)
            conn.commit()
            conn.close()

            calls = []

            def fake_print_direct(**kwargs):
                calls.append(kwargs)
                return True

            with patch.object(winprint_spooler, "DB_DIR", tmp_dir), \
                 patch.object(winprint_spooler, "DB_PATH", db_path), \
                 patch.object(winprint_spooler, "CONFIG_PATH", cfg_path), \
                 patch.object(winprint_spooler, "send_desktop_notification"), \
                 patch.object(winprint_spooler.winprint_engine, "print_file_direct", side_effect=fake_print_direct):
                job_id = winprint_spooler.submit_job(
                    file_path=src_pdf,
                    job_name="Ujian_L2540",
                    paper="F4",
                    duplex="long",
                    copies=2,
                    scale=1.12,
                    printer_model="Brother DCP-L2540DW",
                )
                winprint_spooler.process_queue_worker(printer_ip="192.168.100.236", run_once=True)

            self.assertEqual(len(calls), 1)
            self.assertAlmostEqual(calls[0]["scale"], 1.12, places=2)
            self.assertEqual(calls[0]["printer_model"], "Brother DCP-L2540DW")
            self.assertEqual(calls[0]["ip"], "192.168.100.236")

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            conn.close()
            self.assertEqual(row[0], "COMPLETED")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_2_detect_pdf_media(self):
        self.assertEqual(winprint_layout.detect_pdf_media(612.0, 936.0), "F4")
        self.assertEqual(winprint_layout.detect_pdf_media(609.45, 935.43), "F4")
        self.assertEqual(winprint_layout.detect_pdf_media(936.0, 612.0), "F4")
        self.assertEqual(winprint_layout.detect_pdf_media(595.28, 841.89), "A4")
        self.assertEqual(winprint_layout.detect_pdf_media(841.89, 595.28), "A4")
        self.assertEqual(winprint_layout.detect_pdf_media(612.0, 1008.0), "Legal")
        self.assertEqual(winprint_layout.detect_pdf_media(612.0, 792.0), "Letter")
        self.assertEqual(winprint_layout.detect_pdf_media(419.53, 595.28), "A5")
        self.assertIsNone(winprint_layout.detect_pdf_media(400.0, 400.0))

    def test_3_calibration_profile_roundtrip_f4_folio_sync(self):
        fd, profile_json = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(profile_json)
        try:
            winprint_engine_v2.save_calibration_mm(
                media="F4",
                duplex_mode="LONG_EDGE",
                offset_x_mm=1.8,
                offset_y_mm=-2.2,
                printer_model="Brother DCP-L2540DW",
                profile_path=profile_json,
            )
            self.assertEqual(
                winprint_engine_v2.get_calibration_mm("F4", "LONG_EDGE", "Brother DCP-L2540DW", profile_json),
                (1.8, -2.2),
            )
            self.assertEqual(
                winprint_engine_v2.get_calibration_mm("Folio", "LONG_EDGE", "Brother DCP-L2540DW", profile_json),
                (1.8, -2.2),
            )
            x_pt, y_pt = winprint_engine_v2.load_calibration_offset(
                "F4", "LONG_EDGE", "Brother DCP-L2540DW", profile_json
            )
            self.assertAlmostEqual(x_pt, 1.8 * winprint_layout.PT_PER_MM, places=2)
            self.assertAlmostEqual(y_pt, -2.2 * winprint_layout.PT_PER_MM, places=2)
        finally:
            if os.path.exists(profile_json):
                os.remove(profile_json)

    @unittest.skipUnless(os.path.isfile(L2540_RAWTOBR3), "L2540DW rawtobr3 not installed")
    def test_4_l2540dw_brother_pcl_render(self):
        geom_f4 = winprint_layout.get_media_geometry(WINPRINT_PPD, "F4", "portrait")
        fd, temp_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            winprint_layout.generate_calibration_pdf(temp_pdf, geom_f4)
            res = winprint_engine_v2.render_job(
                input_pdf=temp_pdf,
                media="F4",
                duplex="LONG_EDGE",
                copies=1,
                geometry=geom_f4,
                offset_x_pt=0.0,
                offset_y_pt=0.0,
                backend="auto",
                printer_model="Brother DCP-L2540DW",
            )
            self.assertEqual(res["manifest"]["backend"], "brother_pcl")
            self.assertEqual(res["manifest"]["printer_model"], "Brother DCP-L2540DW")
            self.assertIn(b"@PJL ENTER LANGUAGE = PCL\n", res["stream"])
            # DCPL2540DW native rawtobr3 Folio paper header & Long-Edge Duplex 1S
            self.assertIn(b"\x1b&l4096a3a", res["stream"])
            self.assertIn(b"\x1b&l1S", res["stream"])
        finally:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)

    def test_5_threading_ipp_server_concurrent_requests(self):
        server = winprint_ipp_server.WinPrintThreadingIPPServer(("127.0.0.1", 0), winprint_ipp_server.WinPrintIPPHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        t.start()

        # Minimal IPP Get-Printer-Attributes (0x000B) packet with attributes-charset & natural-language
        req_pkt = (
            struct.pack(">BBHI", 2, 0, winprint_ipp_server.IPP_OP_GET_PRINTER_ATTRIBUTES, 42)
            + bytes([winprint_ipp_server.IPP_TAG_OPERATION])
            + b"\x47\x00\x12attributes-charset\x00\x05utf-8"
            + b"\x48\x00\x1battributes-natural-language\x00\x02en"
            + bytes([winprint_ipp_server.IPP_TAG_END])
        )

        def send_ipp(idx: int):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/printers/Brother_B7640DW",
                data=req_pkt,
                headers={"Content-Type": "application/ipp"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status, resp.read()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(send_ipp, range(4)))
            for http_code, body in results:
                self.assertEqual(http_code, 200)
                self.assertGreater(len(body), 16)
                _, _, status_code, req_id = struct.unpack(">BBHI", body[:8])
                self.assertEqual(status_code, winprint_ipp_server.IPP_STATUS_OK)
                self.assertEqual(req_id, 42)
                self.assertIn(b"Brother_B7640DW_WinPrint", body)
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
