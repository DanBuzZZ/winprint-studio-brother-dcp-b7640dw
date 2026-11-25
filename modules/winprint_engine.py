#!/usr/bin/env python3
"""
winprint_engine.py - Direct-to-Printer Non-CUPS Print Engine (Windows-style Architecture)
Renders PDF/XPS deterministically and streams via TCP Port 9100 (AppSocket / RAW)
with custom PJL control (Duplex, F4/Folio Paper, Toner Save, Resolution).
"""

import sys
import os
import socket
import argparse
import subprocess
import time

_MOD_DIR = os.path.dirname(os.path.abspath(__file__))
if _MOD_DIR not in sys.path:
    sys.path.insert(0, _MOD_DIR)

import winprint_comm
import winprint_layout
import winprint_engine_v2

PAGE_SIZES = {
    "A4": {"w_pt": 595, "h_pt": 842, "pjl": "A4"},
    "F4": {"w_pt": 609, "h_pt": 935, "pjl": "FOLIO"},        # 215 x 330 mm (Standar F4 Indonesia)
    "Folio": {"w_pt": 609, "h_pt": 935, "pjl": "FOLIO"},     # 215 x 330 mm
    "8.5x13": {"w_pt": 612, "h_pt": 936, "pjl": "FOLIO"},    # 8.5 x 13 inch (612 x 936 pt)
    "FanFoldGermanLegal": {"w_pt": 612, "h_pt": 936, "pjl": "FOLIO"}, # 8.5 x 13 inch
    "Legal": {"w_pt": 612, "h_pt": 1008, "pjl": "LEGAL"},
    "Letter": {"w_pt": 612, "h_pt": 792, "pjl": "LETTER"},
    "A5": {"w_pt": 420, "h_pt": 595, "pjl": "A5"},
    "Executive": {"w_pt": 522, "h_pt": 756, "pjl": "EXECUTIVE"},
    "B5": {"w_pt": 516, "h_pt": 729, "pjl": "B5"}
}


def build_pjl_header(job_name: str, paper: str, duplex: str, toner_save: bool, resolution: int, copies: int = 1, orientation: str = "portrait") -> bytes:
    pjl_paper = PAGE_SIZES.get(paper, {}).get("pjl", "A4")
    economode = "ON" if toner_save else "OFF"
    
    duplex_cmd = "@PJL SET DUPLEX = OFF\n"
    if duplex == "long":
        duplex_cmd = "@PJL SET DUPLEX = ON\n@PJL SET BINDING = LONGEDGE\n"
    elif duplex == "short":
        duplex_cmd = "@PJL SET DUPLEX = ON\n@PJL SET BINDING = SHORTEDGE\n"
        
    # Note: Orientation in PCL-XL is handled exclusively by the PCL-XL BeginPage
    # stream operator (eLandscapeOrientation / ePortraitOrientation). Sending
    # legacy @PJL SET ORIENTATION conflicts with Brother PCL-XL coordinate origins
    # and pushes page content to the physical edge.
    header = (
        "\x1b%-12345X@PJL\n"
        "@PJL RESET\n"
        f"@PJL SET JOBNAME = \"{job_name}\"\n"
        f"@PJL SET RESOLUTION = {resolution}\n"
        f"@PJL SET PAPER = {pjl_paper}\n"
        f"@PJL SET ECONOMODE = {economode}\n"
        f"@PJL SET COPIES = {copies}\n"
        f"@PJL SET QTY = {copies}\n"
        f"{duplex_cmd}"
        "@PJL ENTER LANGUAGE = PCLXL\n"
    )
    return header.encode("latin1")


def build_pjl_trailer() -> bytes:
    trailer = "\x1b%-12345X@PJL EOJ\n\x1b%-12345X"
    return trailer.encode("latin1")


def strip_gs_pjl_wrapper(raw_pclxl: bytes) -> bytes:
    """Strips Ghostscript-generated outer PJL header and UEL trailer to prevent double UEL corruption."""
    uel = b"\x1b%-12345X"
    # Find start of pure PCL-XL binary stream
    marker = b") HP-PCL XL;"
    idx = raw_pclxl.find(marker)
    if idx != -1:
        raw_pclxl = raw_pclxl[idx:]
    else:
        # Fallback: strip after ENTER LANGUAGE = PCLXL\n
        pjl_lang = b"@PJL ENTER LANGUAGE = PCLXL\n"
        idx_lang = raw_pclxl.find(pjl_lang)
        if idx_lang != -1:
            raw_pclxl = raw_pclxl[idx_lang + len(pjl_lang):]

    # Strip trailing UEL
    if raw_pclxl.endswith(uel):
        raw_pclxl = raw_pclxl[:-len(uel)]
    return raw_pclxl


def get_pdf_page_count(pdf_path: str) -> int:
    """Gets total page count of a PDF using pdfinfo or qpdf deterministically."""
    try:
        res = subprocess.run(["pdfinfo", pdf_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        for line in res.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    try:
        res = subprocess.run(["qpdf", "--show-npages", pdf_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return int(res.stdout.strip())
    except Exception:
        pass
    return 1


def render_pdf_to_pclxl(input_pdf: str, paper: str, resolution: int, duplex: str = "none",
                        orientation: str = "portrait", scale: float = 1.0,
                        duplex_offset_y: float = 18.0) -> bytes:
    """
    Renders PDF to PCL-XL monochrome stream using Ghostscript pxlmono device.
    Includes:
    - Duplex back-page vertical compensation (+18 pt / ~6.3 mm default) to eliminate Brother reverse-roller drop.
    - Odd-page duplex padding (blank trailing showpage) so the last sheet ejects immediately.
    - Centered content scaling (e.g. 112% for F4 / Folio fill).
    """
    paper_info = PAGE_SIZES.get(paper, PAGE_SIZES["A4"])
    w_pt = paper_info["w_pt"]
    h_pt = paper_info["h_pt"]
    
    if str(orientation).lower() == "landscape":
        w_pt, h_pt = h_pt, w_pt
    
    cmd = [
        "gs",
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=pxlmono",
        f"-r{resolution}",
        f"-dDEVICEWIDTHPOINTS={w_pt}",
        f"-dDEVICEHEIGHTPOINTS={h_pt}",
        "-dPDFFitPage",
        "-dCenterPages",
    ]
    
    if duplex == "long":
        cmd.extend(["-dDuplex=true", "-dTumble=false"])
    elif duplex == "short":
        cmd.extend(["-dDuplex=true", "-dTumble=true"])
    else:
        cmd.extend(["-dDuplex=false"])
        
    cmd.append("-sOutputFile=-")

    # PostScript BeginPage hook for duplex back-page alignment and/or content scaling
    has_scale = scale and abs(scale - 1.0) > 0.001
    has_duplex_shift = duplex in ("long", "short") and abs(duplex_offset_y) > 0.001

    if has_scale or has_duplex_shift:
        ps_lines = ["<< /BeginPage { /p exch def"]
        if has_scale:
            ps_lines.append("currentpagedevice /PageSize get aload pop 2 div /cy exch def 2 div /cx exch def")
        
        if has_duplex_shift:
            # Shift even pages (0-indexed p mod 2 == 1, i.e. back sides) UP by duplex_offset_y
            # to cancel Brother physical duplex reverse-roller paper drop (~4-5 lines / ~18 pt)
            ps_lines.append(f"p 2 mod 1 eq {{ 0 {duplex_offset_y:.1f} translate }} if")

        if has_scale:
            ps_lines.append(f"cx cy translate {scale:.3f} {scale:.3f} scale cx neg cy neg translate")

        ps_lines.append("} >> setpagedevice")
        cmd.extend(["-c", " ".join(ps_lines)])

    cmd.extend(["-f", input_pdf])

    # Odd-page duplex padding: Brother DCP-B7640DW duplex unit stalls when an odd-paged
    # document ends without an even back page. Appending a blank showpage guarantees immediate ejection.
    if duplex in ("long", "short"):
        total_p = get_pdf_page_count(input_pdf)
        if total_p % 2 != 0:
            cmd.extend(["-c", "showpage"])
    
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return strip_gs_pjl_wrapper(proc.stdout)


LAST_ERROR = ""


def get_last_error() -> str:
    """Returns the last error message from the engine operations."""
    global LAST_ERROR
    return LAST_ERROR


def send_to_printer(ip: str, data: bytes, port: int = 9100,
                    connect_timeout: float = 15.0,
                    transfer_timeout: float = 180.0,
                    max_attempts: int = 3,
                    progress_callback=None,
                    cancel_event=None) -> bool:
    """Streams print data directly to port 9100 with progress tracking, auto-retry, and cancellation support."""
    global LAST_ERROR
    LAST_ERROR = ""
    
    total = len(data)
    chunk_size = 32768
    
    for attempt in range(1, max_attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            LAST_ERROR = "Pencetakan dibatalkan oleh pengguna."
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except (AttributeError, OSError):
            pass

        try:
            if progress_callback and attempt > 1:
                progress_callback(5, f"Membangunkan printer dari Sleep (Percobaan {attempt}/{max_attempts})...")
            sock.settimeout(connect_timeout)
            sock.connect((ip, port))
            
            # Connected: set transfer timeout
            sock.settimeout(transfer_timeout)
            sent = 0
            
            while sent < total:
                if cancel_event is not None and cancel_event.is_set():
                    LAST_ERROR = "Pengiriman data cetak dibatalkan oleh pengguna."
                    return False
                chunk = data[sent:sent + chunk_size]
                sock.sendall(chunk)
                sent += len(chunk)
                pct = int((sent / total) * 100) if total else 100
                if progress_callback:
                    progress_callback(pct, f"Mengirim data cetak ({pct}%)...")
                elif sent % (chunk_size * 4) == 0 or sent == total:
                    sys.stdout.write(f"\rMengirim data cetak ke printer ({ip}): {pct}%")
                    sys.stdout.flush()
                    
            if progress_callback:
                progress_callback(100, "Pengiriman data selesai. Dokumen sedang diproses printer...")
            print("\nPengiriman data selesai. Dokumen sedang diproses printer.")
            LAST_ERROR = ""
            return True
        except socket.timeout:
            LAST_ERROR = f"Timeout: Printer di {ip}:{port} tidak merespons (melebihi {int(transfer_timeout)} detik)."
            print(f"\n{LAST_ERROR}", file=sys.stderr)
        except ConnectionRefusedError:
            LAST_ERROR = f"Koneksi ditolak oleh printer di {ip}:{port}. Pastikan RAW Port 9100 aktif dan printer tidak sibuk."
            print(f"\n{LAST_ERROR}", file=sys.stderr)
        except OSError as e:
            LAST_ERROR = f"Kesalahan jaringan ({ip}:{port}): {e}"
            print(f"\n{LAST_ERROR}", file=sys.stderr)
        finally:
            try:
                sock.shutdown(socket.SHUT_WR)
            except Exception:
                pass
            sock.close()

        if cancel_event is not None and cancel_event.is_set():
            LAST_ERROR = "Pencetakan dibatalkan oleh pengguna."
            return False
        if attempt < max_attempts:
            time.sleep(2.5)

    return False


_ORIG_SEND_TO_PRINTER = send_to_printer


def send_jobs_stream(ip: str, payloads: list, port: int = 9100,
                     connect_timeout: float = 15.0,
                     transfer_timeout: float = 180.0,
                     max_attempts: int = 3,
                     progress_callback=None,
                     cancel_event=None) -> bool:
    """Streams multiple collated @PJL JOB payloads over a single continuous TCP socket when possible."""
    global LAST_ERROR
    if not payloads:
        return True
    if len(payloads) == 1:
        return send_to_printer(
            ip, payloads[0], port=port,
            connect_timeout=connect_timeout,
            transfer_timeout=transfer_timeout,
            max_attempts=max_attempts,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    LAST_ERROR = ""
    total_bytes = sum(len(p) for p in payloads)
    chunk_size = 32768

    for attempt in range(1, max_attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            LAST_ERROR = "Pencetakan dibatalkan oleh pengguna."
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            sock.settimeout(connect_timeout)
            sock.connect((ip, port))
            sock.settimeout(transfer_timeout)

            sent_total = 0
            for idx, payload in enumerate(payloads, start=1):
                offset = 0
                p_len = len(payload)
                while offset < p_len:
                    if cancel_event is not None and cancel_event.is_set():
                        LAST_ERROR = f"Pengiriman dibatalkan pada salinan {idx}/{len(payloads)}."
                        return False
                    chunk = payload[offset:offset + chunk_size]
                    sock.sendall(chunk)
                    offset += len(chunk)
                    sent_total += len(chunk)
                    if progress_callback and total_bytes:
                        pct = int((sent_total / total_bytes) * 100)
                        progress_callback(pct, f"Salinan {idx}/{len(payloads)} ({pct}%)...")

            if progress_callback:
                progress_callback(100, "Seluruh salinan selesai dikirim ke printer.")
            LAST_ERROR = ""
            return True
        except socket.timeout:
            LAST_ERROR = f"Timeout: Printer di {ip}:{port} tidak merespons."
        except ConnectionRefusedError:
            LAST_ERROR = f"Koneksi ditolak oleh printer di {ip}:{port}."
        except OSError as e:
            LAST_ERROR = f"Kesalahan jaringan ({ip}:{port}): {e}"
        finally:
            try:
                sock.shutdown(socket.SHUT_WR)
            except Exception:
                pass
            sock.close()

        if cancel_event is not None and cancel_event.is_set():
            LAST_ERROR = "Pencetakan dibatalkan oleh pengguna."
            return False
        if attempt < max_attempts:
            time.sleep(2.5)

    return False


def resolve_ppd_path() -> str:
    """Returns official Brother PPD if available, falling back to WinPrint CUPS PPD."""
    base_dir = os.path.dirname(_MOD_DIR)
    for fname in ("BRPPB7640DW.PPD", "Brother_B7640DW_WinPrint.ppd"):
        candidate = os.path.join(base_dir, fname)
        if os.path.isfile(candidate):
            return candidate
    return "/opt/brother/Printers/DCPB7640DW/cupswrapper/brother-DCPB7640DW-cups-en.ppd"


def print_file_direct(ip: str, file_path: str, paper: str = "A4", duplex: str = "none",
                      toner_save: bool = False, resolution: int = 600, copies: int = 1,
                      orientation: str = "portrait", scale: float = 1.0,
                      duplex_offset_y: float = None,
                      duplex_offset_x: float = None,
                      fit_to_printable: bool = False,
                      backend: str = "auto",
                      printer_model: str = "Brother DCP-B7640DW",
                      paper_source: str = "auto",
                      media_type: str = "plain",
                      quiet_mode: bool = False,
                      density: int = 0,
                      binding_gutter_mm: float = 0.0,
                      collate: bool = True,
                      cancel_event=None,
                      progress_callback=None) -> bool:
    """
    Executes pre-flight PJL telemetry check, normalizes PDF via PPD geometry & calibrated
    back-side offsets, renders via Brother Native PCL (`rawtobr3`) or pure PCL-XL fallback,
    and streams hardware-copied or collated copies to TCP port 9100.
    """
    global LAST_ERROR
    LAST_ERROR = ""

    if not os.path.exists(file_path):
        LAST_ERROR = f"File tidak ditemukan: {file_path}"
        print(LAST_ERROR, file=sys.stderr)
        return False

    job_name = os.path.basename(file_path)
    num_copies = max(1, int(copies))

    # 1. Pre-flight bidirectional PJL telemetry (fail-open unless ERROR state)
    telemetry = winprint_comm.get_printer_telemetry(ip, connect_timeout=0.5, read_timeout=1.0)
    if telemetry.get("device_state") == "ERROR":
        LAST_ERROR = f"Printer tidak siap ({telemetry.get('reason')}): {telemetry.get('display') or 'Error fisik terdeteksi'}"
        print(LAST_ERROR, file=sys.stderr)
        return False

    try:
        ppd_path = resolve_ppd_path()
        geometry = winprint_layout.get_media_geometry(ppd_path, paper, orientation=orientation)

        result = winprint_engine_v2.render_job(
            input_pdf=file_path,
            media=paper,
            duplex=duplex,
            copies=num_copies,
            geometry=geometry,
            offset_x_pt=duplex_offset_x,
            offset_y_pt=duplex_offset_y,
            fit_to_printable=fit_to_printable,
            manual_scale=scale,
            job_name=job_name,
            resolution=resolution,
            toner_save=toner_save,
            backend=backend,
            printer_model=printer_model,
            paper_source=paper_source,
            media_type=media_type,
            quiet_mode=quiet_mode,
            density=density,
            binding_gutter_mm=binding_gutter_mm,
            collate=collate,
        )
        m = result["manifest"]
        copies_payloads = result["copies_payloads"]

        print("=== WinPrint Direct Engine v2 (Calibrated) ===")
        print(f"Perangkat  : {printer_model} ({ip}:9100) [{telemetry.get('device_state')} {telemetry.get('status_code')}]")
        print(f"Backend    : {m['backend']} (GS {m['gs_version']})")
        print(f"Dokumen    : {job_name}")
        print(f"Ukuran     : {paper} ({geometry.width_pt}x{geometry.height_pt} pt)")
        print(f"Orientasi  : {orientation.capitalize()} | Skala: {int(scale * 100)}%")
        print(f"Duplex     : {m['duplex']} | Offset: X={m['offset_x_pt']:+.2f} pt, Y={m['offset_y_pt']:+.2f} pt | Gutter: {binding_gutter_mm:.1f} mm")
        print(f"Hardware   : Tray={paper_source}, Media={media_type}, Quiet={quiet_mode}, Density={density}")
        print(f"Salinan    : {num_copies} rangkap ({m.get('copy_mode', 'pjl_collated')})")
        print(f"SHA-256    : {m['final_stream_sha256'][:16]}...")
        print("----------------------------------------")

        if len(copies_payloads) > 1 and send_to_printer is _ORIG_SEND_TO_PRINTER:
            return send_jobs_stream(
                ip, copies_payloads,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )

        for c_idx, copy_stream in enumerate(copies_payloads, start=1):
            if cancel_event is not None and cancel_event.is_set():
                LAST_ERROR = "Pengiriman cetak dibatalkan."
                return False
            if len(copies_payloads) > 1:
                print(f"Mengirim salinan {c_idx}/{len(copies_payloads)}...")
                if progress_callback:
                    base_pct = int(((c_idx - 1) / len(copies_payloads)) * 100)
                    progress_callback(base_pct, f"Mengirim salinan {c_idx}/{len(copies_payloads)}...")

            def set_progress(pct, msg, _c=c_idx):
                if progress_callback:
                    if len(copies_payloads) > 1:
                        overall = int(((_c - 1) + (pct / 100.0)) / len(copies_payloads) * 100)
                        progress_callback(overall, f"Salinan {_c}/{len(copies_payloads)}: {msg}")
                    else:
                        progress_callback(pct, msg)

            ok = send_to_printer(ip, copy_stream, progress_callback=set_progress)
            if not ok:
                return False

        return True
    except Exception as e:
        LAST_ERROR = f"Gagal memproses dokumen cetak: {e}"
        print(LAST_ERROR, file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="WinPrint Direct Engine (Bypass CUPS to Port 9100)")
    parser.add_argument("ip", help="Printer IP address")
    parser.add_argument("file", help="Path to PDF file to print")
    parser.add_argument("--paper", choices=["A4", "F4", "Folio", "Legal", "Letter"], default="A4", help="Paper size")
    parser.add_argument("--orientation", choices=["portrait", "landscape"], default="portrait", help="Page orientation")
    parser.add_argument("--duplex", choices=["none", "long", "short"], default="none", help="2-sided duplex mode")
    parser.add_argument("--duplex-offset-y", type=float, default=None, help="Duplex back page vertical compensation in points (None=profile)")
    parser.add_argument("--duplex-offset-x", type=float, default=None, help="Duplex back page horizontal compensation in points (None=profile)")
    parser.add_argument("--toner-save", action="store_true", help="Enable Economode / Toner Save")
    parser.add_argument("--resolution", type=int, choices=[300, 600, 1200], default=600, help="Print resolution in DPI")
    parser.add_argument("--copies", type=int, default=1, help="Number of copies")
    parser.add_argument("--scale", type=float, default=1.0, help="Content scale factor (e.g. 1.0 for 1:1 WYSIWYG)")
    parser.add_argument("--fit-printable", action="store_true", help="Scale document proportionally inside PPD ImageableArea")
    parser.add_argument("--backend", choices=["auto", "brother_pcl", "pclxl"], default="auto", help="Rendering backend")
    args = parser.parse_args()

    success = print_file_direct(
        ip=args.ip,
        file_path=args.file,
        paper=args.paper,
        duplex=args.duplex,
        duplex_offset_y=args.duplex_offset_y,
        duplex_offset_x=args.duplex_offset_x,
        toner_save=args.toner_save,
        resolution=args.resolution,
        copies=args.copies,
        orientation=args.orientation,
        scale=args.scale,
        fit_to_printable=args.fit_printable,
        backend=args.backend,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
