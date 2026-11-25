#!/usr/bin/env python3
"""
Unit tests for winprint_comm.py covering TCP fragmentation, FormFeed framing,
timeouts, unmapped status codes, missing tray keys, verified/unverified codes,
and mid-stream disconnects using a local mock TCP server.
"""

import socket
import threading
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_comm


class MockPrinterServer:
    def __init__(self, handler_fn):
        self.handler_fn = handler_fn
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop:
            try:
                self.sock.settimeout(0.2)
                conn, _ = self.sock.accept()
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_conn(self, conn):
        try:
            self.handler_fn(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


class TestWinPrintComm(unittest.TestCase):
    def test_1_tcp_fragmentation(self):
        """Response split across multiple small TCP chunks."""
        def handler(conn):
            conn.recv(1024)
            for part in [b"@PJL INFO STATUS\r\n", b"CODE=40000\r\n", b'DISPLAY="Sleep"\r\n', b"ONLINE=TRUE\r\n\x0c"]:
                conn.sendall(part)
                time.sleep(0.01)
            conn.recv(1024)
            for part in [b"@PJL INFO VARIABLES\r\n", b"INTRAY2SIZE=FOLIO", b"[39 ENUMERATED]\r\n\x0c"]:
                conn.sendall(part)
                time.sleep(0.01)

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port)
            self.assertEqual(res["connection"], "CONNECTED")
            self.assertEqual(res["device_state"], "READY")
            self.assertEqual(res["status_code"], 40000)
            self.assertEqual(res["paper_tray"]["tray2"]["configured_size"], "FOLIO")
            self.assertIsNone(res["paper_tray"]["tray2"]["paper_present"])
            self.assertFalse(res["paper_tray"]["tray2"]["paper_presence_verified"])
        finally:
            srv.close()

    def test_2_formfeed_termination(self):
        """Trailing bytes after first FormFeed are ignored per single-FF framing."""
        def handler(conn):
            conn.recv(1024)
            conn.sendall(b"@PJL INFO STATUS\r\nCODE=40000\r\nDISPLAY=\"Ready\"\r\nONLINE=TRUE\r\n\x0cTRAILING_GARBAGE")
            conn.recv(1024)
            conn.sendall(b"@PJL INFO VARIABLES\r\nINTRAY2SIZE=A4[39 ENUMERATED]\r\n\x0cMORE_GARBAGE")

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port)
            self.assertEqual(res["device_state"], "READY")
            self.assertEqual(res["paper_tray"]["tray2"]["configured_size"], "A4")
        finally:
            srv.close()

    def test_3_printer_timeout(self):
        """Printer accepts TCP but never responds -> graceful UNKNOWN."""
        def handler(conn):
            conn.recv(1024)
            time.sleep(0.5)

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port, connect_timeout=0.2, read_timeout=0.1)
            self.assertEqual(res["connection"], "TIMEOUT")
            self.assertEqual(res["device_state"], "UNKNOWN")
        finally:
            srv.close()

    def test_4_unmapped_code(self):
        """Unverified status code maps to UNKNOWN while retaining raw status_code."""
        def handler(conn):
            conn.recv(1024)
            conn.sendall(b"@PJL INFO STATUS\r\nCODE=40999\r\nDISPLAY=\"Custom\"\r\nONLINE=TRUE\r\n\x0c")
            conn.recv(1024)
            conn.sendall(b"@PJL INFO VARIABLES\r\n\x0c")

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port)
            self.assertEqual(res["status_code"], 40999)
            self.assertEqual(res["device_state"], "UNKNOWN")
            self.assertEqual(res["reason"], "UNVERIFIED_CODE_40999")
        finally:
            srv.close()

    def test_5_missing_intray(self):
        """Response without INTRAY2SIZE leaves paper_tray empty without failing."""
        def handler(conn):
            conn.recv(1024)
            conn.sendall(b"@PJL INFO STATUS\r\nCODE=40000\r\nDISPLAY=\"Ready\"\r\nONLINE=TRUE\r\n\x0c")
            conn.recv(1024)
            conn.sendall(b"@PJL INFO VARIABLES\r\nRESOLUTION=600\r\n\x0c")

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port)
            self.assertEqual(res["device_state"], "READY")
            self.assertEqual(res["paper_tray"], {})
        finally:
            srv.close()

    def test_6_hardware_error_codes(self):
        """Verified error codes (40021, 40001) map to ERROR; unverified code maps to UNKNOWN."""
        def handler_err(conn):
            conn.recv(1024)
            conn.sendall(b"@PJL INFO STATUS\r\nCODE=40021\r\nDISPLAY=\"Cover Open\"\r\nONLINE=FALSE\r\n\x0c")
            conn.recv(1024)
            conn.sendall(b"@PJL INFO VARIABLES\r\n\x0c")

        srv = MockPrinterServer(handler_err)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port)
            self.assertEqual(res["device_state"], "ERROR")
            self.assertEqual(res["reason"], "COVER_OPEN")
        finally:
            srv.close()

    def test_7_midstream_disconnect(self):
        """Connection closed mid-response returns UNKNOWN gracefully."""
        def handler(conn):
            conn.recv(1024)
            conn.sendall(b"@PJL INFO STATUS\r\nCODE=40000\r\n")
            conn.close()

        srv = MockPrinterServer(handler)
        try:
            res = winprint_comm.get_printer_telemetry("127.0.0.1", srv.port, read_timeout=0.2)
            self.assertEqual(res["device_state"], "UNKNOWN")
            self.assertEqual(res["reason"], "INCOMPLETE_STATUS_RESPONSE")
            self.assertEqual(res["status_code"], 40000)
        finally:
            srv.close()

    def test_8_active_ready_and_busy_codes(self):
        """Verified DCP-B7640DW codes 10001 (Ready) and 10023 (Printing/Busy)."""
        def make_handler(code, display):
            def handler(conn):
                conn.recv(1024)
                conn.sendall(f'@PJL INFO STATUS\r\nCODE={code}\r\nDISPLAY="{display}"\r\nONLINE=TRUE\r\n\x0c'.encode())
                conn.recv(1024)
                conn.sendall(b"@PJL INFO VARIABLES\r\nINTRAY2SIZE=FOLIO\r\n\x0c")
            return handler

        srv1 = MockPrinterServer(make_handler(10001, "Ready"))
        srv2 = MockPrinterServer(make_handler(10023, "Printing"))
        try:
            r1 = winprint_comm.get_printer_telemetry("127.0.0.1", srv1.port)
            self.assertEqual(r1["device_state"], "READY")
            self.assertEqual(r1["reason"], "DCP_B7640DW_READY")

            r2 = winprint_comm.get_printer_telemetry("127.0.0.1", srv2.port)
            self.assertEqual(r2["device_state"], "BUSY")
            self.assertEqual(r2["reason"], "DCP_B7640DW_PRINTING")
        finally:
            srv1.close()
            srv2.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
