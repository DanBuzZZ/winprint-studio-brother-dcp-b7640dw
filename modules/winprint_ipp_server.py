#!/usr/bin/env python3
"""
winprint_ipp_server.py - Lightweight IPP (Internet Printing Protocol) Loopback Server
Listens on localhost (default port 9631) to receive print jobs from desktop apps
(Chrome, Firefox, LibreOffice, Evince) and submits them directly into the WinPrint Spooler.
"""

import sys
import os
import struct
import io
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse

import subprocess
import shutil
import time


class WinPrintThreadingIPPServer(ThreadingHTTPServer):
    """Concurrent loopback IPP server preventing large print payloads from blocking attribute polls."""
    daemon_threads = True
    allow_reuse_address = True


def cleanup_stale_temp_files(max_age_sec: int = 14400) -> int:
    """Removes stale WinPrint intercept and preview temporary files in /tmp."""
    tmp_dir = "/tmp"
    prefixes = ("winprint_intercept_", "winprint_prev_")
    cutoff = time.time() - max(0, max_age_sec)
    removed = 0
    try:
        for entry in os.scandir(tmp_dir):
            if entry.name.startswith(prefixes) and entry.is_file(follow_symlinks=False):
                try:
                    if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                        os.unlink(entry.path)
                        removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return removed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import winprint_converter


def get_gui_env():
    """Detects active desktop session environment (Wayland/X11) for launching GUI."""
    env = os.environ.copy()
    if "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env:
        try:
            out = subprocess.check_output(["systemctl", "--user", "show-environment"], text=True)
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY"):
                        env[k] = v
        except Exception:
            pass
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    return env

IPP_TAG_OPERATION = 0x01
IPP_TAG_JOB = 0x02
IPP_TAG_END = 0x03
IPP_TAG_PRINTER = 0x04

IPP_OP_PRINT_JOB = 0x0002
IPP_OP_VALIDATE_JOB = 0x0004
IPP_OP_GET_PRINTER_ATTRIBUTES = 0x000B

IPP_STATUS_OK = 0x0000


def parse_ipp_attributes_and_data(payload: bytes):
    """Parses standard binary IPP packet to extract attributes and document payload."""
    if len(payload) < 9:
        return {}, b""
        
    version_major, version_minor, op_or_status, request_id = struct.unpack(">BBHI", payload[:8])
    offset = 8
    attributes = {}
    current_group = None
    
    while offset < len(payload):
        tag = payload[offset]
        offset += 1
        if tag == IPP_TAG_END:
            break
        elif tag in (IPP_TAG_OPERATION, IPP_TAG_JOB, IPP_TAG_PRINTER):
            current_group = tag
            continue
            
        if offset + 2 > len(payload):
            break
        name_len = struct.unpack(">H", payload[offset:offset + 2])[0]
        offset += 2
        name = payload[offset:offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        
        if offset + 2 > len(payload):
            break
        val_len = struct.unpack(">H", payload[offset:offset + 2])[0]
        offset += 2
        val_bytes = payload[offset:offset + val_len]
        offset += val_len
        
        # Decode value
        if tag == 0x21:  # integer
            val = struct.unpack(">i", val_bytes)[0] if len(val_bytes) == 4 else 0
        elif tag == 0x22:  # boolean
            val = bool(val_bytes[0]) if len(val_bytes) > 0 else False
        elif tag in (0x44, 0x45, 0x47, 0x41, 0x42):  # string/name/uri
            val = val_bytes.decode("utf-8", errors="replace")
        else:
            val = val_bytes.decode("utf-8", errors="replace")
            
        if name:
            attributes[name] = val
            
    document_data = payload[offset:]
    return attributes, document_data


def write_attr(buf, tag: int, name: str, val_bytes: bytes):
    buf.write(bytes([tag]))
    name_bytes = name.encode('utf-8')
    buf.write(struct.pack('>H', len(name_bytes)))
    buf.write(name_bytes)
    buf.write(struct.pack('>H', len(val_bytes)))
    buf.write(val_bytes)


def write_multi(buf, tag: int, val_bytes: bytes):
    buf.write(bytes([tag]))
    buf.write(struct.pack('>H', 0))
    buf.write(struct.pack('>H', len(val_bytes)))
    buf.write(val_bytes)


def build_ipp_response(request_id: int, status_code: int = IPP_STATUS_OK, version: tuple = (2, 0)) -> bytes:
    buf = io.BytesIO()
    buf.write(struct.pack(">BBHI", version[0], version[1], status_code, request_id))
    buf.write(bytes([IPP_TAG_OPERATION]))
    write_attr(buf, 0x47, "attributes-charset", b"utf-8")
    write_attr(buf, 0x48, "attributes-natural-language", b"en")
    buf.write(bytes([IPP_TAG_END]))
    return buf.getvalue()


def build_printer_attributes_response(request_id: int, version: tuple = (2, 0)) -> bytes:
    buf = io.BytesIO()
    buf.write(struct.pack('>BBHI', version[0], version[1], IPP_STATUS_OK, request_id))
    
    # Operation Group (0x01)
    buf.write(bytes([IPP_TAG_OPERATION]))
    write_attr(buf, 0x47, 'attributes-charset', b'utf-8')
    write_attr(buf, 0x48, 'attributes-natural-language', b'en')

    # Printer Group (0x04)
    buf.write(bytes([IPP_TAG_PRINTER]))
    write_attr(buf, 0x47, 'charset-configured', b'utf-8')
    write_attr(buf, 0x47, 'charset-supported', b'utf-8')
    write_attr(buf, 0x48, 'natural-language-configured', b'en')
    write_attr(buf, 0x48, 'generated-natural-language-supported', b'en')
    
    write_attr(buf, 0x42, 'printer-name', b'Brother_B7640DW_WinPrint')
    write_attr(buf, 0x41, 'printer-info', b'Brother DCP-B7640DW WinPrint Engine')
    write_attr(buf, 0x41, 'printer-make-and-model', b'Brother DCP-B7640DW')
    write_attr(buf, 0x41, 'printer-location', b'Wi-Fi Network')
    write_attr(buf, 0x45, 'printer-more-info', b'http://127.0.0.1:9631/')
    write_attr(buf, 0x45, 'printer-uri-supported', b'ipp://127.0.0.1:9631/printers/Brother_B7640DW')
    write_attr(buf, 0x44, 'uri-authentication-supported', b'none')
    write_attr(buf, 0x44, 'uri-security-supported', b'none')
    
    write_attr(buf, 0x23, 'printer-state', struct.pack('>i', 3)) # 0x23 = IPP_TAG_ENUM, 3 = idle
    write_attr(buf, 0x44, 'printer-state-reasons', b'none')
    write_attr(buf, 0x22, 'printer-is-accepting-jobs', b'\x01') # true
    write_attr(buf, 0x21, 'printer-up-time', struct.pack('>i', int(time.time())))
    
    write_attr(buf, 0x44, 'ipp-versions-supported', b'1.1')
    write_multi(buf, 0x44, b'2.0')
    
    write_attr(buf, 0x44, 'compression-supported', b'none')
    
    write_attr(buf, 0x23, 'operations-supported', struct.pack('>i', 2)) # 0x23 = IPP_TAG_ENUM
    write_multi(buf, 0x23, struct.pack('>i', 4)) # validate-job
    write_multi(buf, 0x23, struct.pack('>i', 8)) # cancel-job
    write_multi(buf, 0x23, struct.pack('>i', 9)) # get-job-attributes
    write_multi(buf, 0x23, struct.pack('>i', 10)) # get-jobs
    write_multi(buf, 0x23, struct.pack('>i', 11)) # get-printer-attributes
    
    write_attr(buf, 0x49, 'document-format-supported', b'application/pdf')
    write_multi(buf, 0x49, b'application/postscript')
    write_multi(buf, 0x49, b'application/octet-stream')
    write_multi(buf, 0x49, b'text/plain')
    write_multi(buf, 0x49, b'image/png')
    write_multi(buf, 0x49, b'image/jpeg')
    write_multi(buf, 0x49, b'image/pwg-raster')
    write_multi(buf, 0x49, b'image/urf')
    
    write_attr(buf, 0x49, 'document-format-default', b'application/pdf')
    
    write_attr(buf, 0x44, 'media-supported', b'iso_a4_210x297mm')
    write_multi(buf, 0x44, b'na_fanfold-german-legal_8.5x13in')
    write_multi(buf, 0x44, b'na_foolscap_8.5x13in')
    write_multi(buf, 0x44, b'om_folio-sp_215x330mm')
    write_multi(buf, 0x44, b'om_folio_210x330mm')
    write_multi(buf, 0x44, b'custom_f4_215x330mm')
    write_multi(buf, 0x44, b'na_letter_8.5x11in')
    write_multi(buf, 0x44, b'na_legal_8.5x14in')
    write_multi(buf, 0x44, b'iso_a5_148x210mm')
    write_multi(buf, 0x44, b'iso_a6_105x148mm')
    write_multi(buf, 0x44, b'jis_b5_182x257mm')
    write_multi(buf, 0x44, b'na_executive_7.25x10.5in')
    write_attr(buf, 0x44, 'media-default', b'iso_a4_210x297mm')
    
    write_attr(buf, 0x44, 'sides-supported', b'one-sided')
    write_multi(buf, 0x44, b'two-sided-long-edge')
    write_multi(buf, 0x44, b'two-sided-short-edge')
    write_attr(buf, 0x44, 'sides-default', b'one-sided')
    
    write_attr(buf, 0x33, 'copies-supported', struct.pack('>ii', 1, 999))
    write_attr(buf, 0x21, 'copies-default', struct.pack('>i', 1))
    
    write_attr(buf, 0x44, 'print-color-mode-supported', b'monochrome')
    write_attr(buf, 0x44, 'print-color-mode-default', b'monochrome')

    buf.write(bytes([IPP_TAG_END]))
    return buf.getvalue()


def build_print_job_response(request_id: int, job_id: int = 1, version: tuple = (2, 0)) -> bytes:
    buf = io.BytesIO()
    buf.write(struct.pack('>BBHI', version[0], version[1], IPP_STATUS_OK, request_id))
    
    # Operation Group (0x01)
    buf.write(bytes([IPP_TAG_OPERATION]))
    write_attr(buf, 0x47, 'attributes-charset', b'utf-8')
    write_attr(buf, 0x48, 'attributes-natural-language', b'en')

    # Job Group (0x02)
    buf.write(bytes([IPP_TAG_JOB]))
    write_attr(buf, 0x21, 'job-id', struct.pack('>i', job_id))
    write_attr(buf, 0x45, 'job-uri', f'ipp://127.0.0.1:9631/jobs/{job_id}'.encode('utf-8'))
    write_attr(buf, 0x23, 'job-state', struct.pack('>i', 9)) # 0x23 = IPP_TAG_ENUM, 9 = completed
    write_attr(buf, 0x44, 'job-state-reasons', b'job-completed-successfully')

    buf.write(bytes([IPP_TAG_END]))
    return buf.getvalue()


def build_get_job_attributes_response(request_id: int, job_id: int = 1, version: tuple = (2, 0)) -> bytes:
    buf = io.BytesIO()
    buf.write(struct.pack('>BBHI', version[0], version[1], IPP_STATUS_OK, request_id))
    
    # Operation Group (0x01)
    buf.write(bytes([IPP_TAG_OPERATION]))
    write_attr(buf, 0x47, 'attributes-charset', b'utf-8')
    write_attr(buf, 0x48, 'attributes-natural-language', b'en')

    # Job Group (0x02)
    buf.write(bytes([IPP_TAG_JOB]))
    write_attr(buf, 0x21, 'job-id', struct.pack('>i', job_id))
    write_attr(buf, 0x45, 'job-uri', f'ipp://127.0.0.1:9631/jobs/{job_id}'.encode('utf-8'))
    write_attr(buf, 0x23, 'job-state', struct.pack('>i', 9)) # 9 = completed
    write_attr(buf, 0x44, 'job-state-reasons', b'job-completed-successfully')
    write_attr(buf, 0x21, 'job-impressions-completed', struct.pack('>i', 1))

    buf.write(bytes([IPP_TAG_END]))
    return buf.getvalue()


def read_chunked_data(rfile):
    chunks = []
    while True:
        line = rfile.readline().strip()
        if not line:
            continue
        try:
            chunk_size = int(line.split(b';')[0], 16)
        except ValueError:
            break
        if chunk_size == 0:
            while True:
                trailer = rfile.readline().strip()
                if not trailer:
                    break
            break
        chunk_data = rfile.read(chunk_size)
        chunks.append(chunk_data)
        rfile.read(2)  # skip trailing \r\n
    return b"".join(chunks)


class WinPrintIPPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_expect_100(self):
        self.send_response_only(100)
        self.end_headers()
        return True

    def send_ipp_response(self, resp_bytes: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/ipp")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(resp_bytes)

    def do_POST(self):
        transfer_enc = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_enc:
            post_data = read_chunked_data(self.rfile)
        else:
            content_len = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_len) if content_len > 0 else b""
        
        if len(post_data) < 8:
            self.send_response(400)
            self.end_headers()
            return
            
        version_major, version_minor, op_code, req_id = struct.unpack(">BBHI", post_data[:8])
        attributes, doc_data = parse_ipp_attributes_and_data(post_data)
        
        if op_code == IPP_OP_PRINT_JOB:
            job_name = attributes.get("job-name", attributes.get("document-name", "IPP_Document"))
            sides = attributes.get("sides", "one-sided")
            duplex = "long" if "two-sided-long-edge" in sides else ("short" if "two-sided-short-edge" in sides else "none")
            copies = int(attributes.get("copies", 1))
            media = attributes.get("media", "iso_a4_210x297mm")
            
            m_lower = str(media).lower()
            paper = "A4"
            if any(k in m_lower for k in ["folio", "f4", "foolscap", "fanfold", "8.5x13", "215x330"]):
                paper = "F4"
            elif "legal" in m_lower:
                paper = "Legal"
            elif "letter" in m_lower:
                paper = "Letter"
            elif "a5" in m_lower:
                paper = "A5"
            elif "executive" in m_lower:
                paper = "Executive"
            elif "b5" in m_lower:
                paper = "B5"
                
            clean_name = "".join(c for c in job_name if c.isalnum() or c in (" ", "-", "_", ".")).strip()
            if not clean_name:
                clean_name = "Dokumen_Cetak"

            # Save raw document payload
            tmp_in = f"/tmp/winprint_intercept_{int(time.time())}_{req_id}.bin"
            with open(tmp_in, "wb") as f:
                f.write(doc_data)

            # Convert to PDF
            try:
                final_pdf = winprint_converter.ensure_pdf(tmp_in, paper=paper)
            except Exception as e:
                print(f"[IPP Server] Peringatan konversi berkas: {e}", file=sys.stderr)
                final_pdf = tmp_in

            cfg = winprint_spooler.get_config()
            intercept = cfg.get("intercept_to_studio", True)
            gui_env = get_gui_env()
            has_gui = bool(gui_env.get("DISPLAY") or gui_env.get("WAYLAND_DISPLAY"))

            assigned_job_id = int(time.time() % 100000)

            if intercept and has_gui:
                if final_pdf != tmp_in and os.path.exists(tmp_in):
                    try:
                        os.remove(tmp_in)
                    except OSError:
                        pass
                studio_bin = shutil.which("winprint-studio") or os.path.join(SCRIPT_DIR, "winprint_studio.py")
                print(f"[IPP Server] Intersepsi Cetak: Membuka WinPrint Studio untuk '{clean_name}' ({final_pdf})")
                cmd = [
                    sys.executable, studio_bin, final_pdf,
                    "--job-name", clean_name,
                    "--copies", str(max(1, copies)),
                    "--cleanup-temp",
                ]
                if "sides" in attributes and duplex in ("long", "short"):
                    cmd.extend(["--duplex", duplex])
                if "media" in attributes:
                    cmd.extend(["--paper", paper])
                subprocess.Popen(cmd, env=gui_env)
            else:
                try:
                    assigned_job_id = winprint_spooler.submit_job(
                        file_path=final_pdf,
                        job_name=clean_name,
                        paper=paper,
                        duplex=duplex,
                        copies=copies
                    )
                    print(f"[IPP Server] Headless Direct Spool -> Job #{assigned_job_id}")
                except Exception as e:
                    print(f"[IPP Server] Gagal spooler: {e}", file=sys.stderr)

            ver = (version_major, version_minor)
            resp_bytes = build_print_job_response(req_id, assigned_job_id, version=ver)
            self.send_ipp_response(resp_bytes)
            
        elif op_code == IPP_OP_GET_PRINTER_ATTRIBUTES:
            ver = (version_major, version_minor)
            resp_bytes = build_printer_attributes_response(req_id, version=ver)
            self.send_ipp_response(resp_bytes)
        elif op_code == 0x0009: # IPP_OP_GET_JOB_ATTRIBUTES
            ver = (version_major, version_minor)
            job_id = attributes.get("job-id", 1)
            if not isinstance(job_id, int):
                job_id = 1
            resp_bytes = build_get_job_attributes_response(req_id, job_id, version=ver)
            self.send_ipp_response(resp_bytes)
        else:
            # Validate job, Cancel job, etc.
            ver = (version_major, version_minor)
            resp_bytes = build_ipp_response(req_id, IPP_STATUS_OK, version=ver)
            self.send_ipp_response(resp_bytes)

    def log_message(self, format, *args):
        # Quiet logging
        return


def run_ipp_server(host: str = "127.0.0.1", port: int = 9631):
    cleanup_stale_temp_files()
    server = WinPrintThreadingIPPServer((host, port), WinPrintIPPHandler)
    print(f"[*] WinPrint IPP Bridge Server aktif di http://{host}:{port}/")
    print(f"[*] Aplikasi dapat mencetak langsung via IPP ke: ipp://{host}:{port}/printers/WinPrint")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    port = 9631
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_ipp_server(port=port)
