#!/usr/bin/env python3
"""
Smoke tests for winprint_engine.py cutover verifying integration with
winprint_comm, winprint_layout, and winprint_engine_v2 without physical printing.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_engine
import winprint_layout


class TestWinPrintEngineCutover(unittest.TestCase):
    def setUp(self):
        ppd = winprint_engine.resolve_ppd_path()
        geom = winprint_layout.get_media_geometry(ppd, "F4", "portrait")
        fd, self.temp_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        winprint_layout.generate_calibration_pdf(self.temp_pdf, geom)

    def tearDown(self):
        if os.path.exists(self.temp_pdf):
            os.remove(self.temp_pdf)

    def test_1_ready_telemetry_streams_calibrated_copies(self):
        sent_streams = []

        def fake_send(ip, data, **kwargs):
            sent_streams.append((ip, data))
            return True

        ready_tel = {
            "connection": "CONNECTED",
            "online": True,
            "display": "Ready",
            "status_code": 10001,
            "paper_tray": {"tray2": {"configured_size": "FOLIO"}},
            "device_state": "READY",
            "reason": "DCP_B7640DW_READY",
            "latency_ms": 120.0,
        }

        with patch("winprint_comm.get_printer_telemetry", return_value=ready_tel), \
             patch("winprint_engine.send_to_printer", side_effect=fake_send), \
             patch("time.sleep", return_value=None):
            ok = winprint_engine.print_file_direct(
                ip="192.168.100.229",
                file_path=self.temp_pdf,
                paper="F4",
                duplex="long",
                copies=2,
                scale=1.0,
                duplex_offset_y=None,
            )

        self.assertTrue(ok)
        self.assertEqual(len(sent_streams), 2)
        self.assertIn(b"@PJL JOB NAME =", sent_streams[0][1])
        self.assertIn(b"_Set_1of2", sent_streams[0][1])
        self.assertIn(b"_Set_2of2", sent_streams[1][1])
        if os.path.isfile("/opt/brother/Printers/DCPB7640DW/lpd/x86_64/rawtobr3"):
            self.assertIn(b"\x1b&l1038a", sent_streams[0][1])
            self.assertIn(b"\x1b&l1S", sent_streams[0][1])

    def test_2_error_telemetry_blocks_job(self):
        err_tel = {
            "connection": "CONNECTED",
            "online": False,
            "display": "Paper Jam",
            "status_code": 40040,
            "device_state": "ERROR",
            "reason": "PAPER_JAM",
        }
        with patch("winprint_comm.get_printer_telemetry", return_value=err_tel), \
             patch("winprint_engine.send_to_printer") as mock_send:
            ok = winprint_engine.print_file_direct(
                ip="192.168.100.229",
                file_path=self.temp_pdf,
                paper="F4",
                duplex="long",
            )
        self.assertFalse(ok)
        mock_send.assert_not_called()
        self.assertIn("PAPER_JAM", winprint_engine.get_last_error())

    def test_3_unknown_telemetry_fails_open(self):
        unk_tel = {
            "connection": "TIMEOUT",
            "online": False,
            "display": "",
            "status_code": None,
            "device_state": "UNKNOWN",
            "reason": "SOCKET_READ_TIMEOUT",
        }
        with patch("winprint_comm.get_printer_telemetry", return_value=unk_tel), \
             patch("winprint_engine.send_to_printer", return_value=True) as mock_send:
            ok = winprint_engine.print_file_direct(
                ip="192.168.100.229",
                file_path=self.temp_pdf,
                paper="F4",
                duplex="none",
            )
        self.assertTrue(ok)
        mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
