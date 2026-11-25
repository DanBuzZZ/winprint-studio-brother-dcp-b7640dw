#!/usr/bin/env python3
"""
winprint_cli.py - Command-Line Interface for WinPrint-Linux Subsystem
Provides direct print, status telemetry, scanning, queue management, and daemon controls.
"""

import sys
import os
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import winprint_engine
import winprint_converter
import brother_snmp
import brother_scan


def cmd_status(args):
    cfg = winprint_spooler.get_config()
    p_model = getattr(args, "printer", None) or cfg.get("printer_model", "Brother DCP-B7640DW")
    ip = args.ip or brother_snmp.resolve_printer_ip(p_model, cfg.get("printer_ip"))
    if not ip:
        print("Alamat IP printer belum disetel. Jalankan: winprint set-ip <IP_PRINTER>")
        sys.exit(1)
    telemetry = brother_snmp.get_printer_telemetry(ip)
    if args.json:
        import json
        print(json.dumps(telemetry, indent=2))
    elif args.zenity:
        print(brother_snmp.format_zenity_text(telemetry))
    else:
        print(brother_snmp.format_zenity_text(telemetry))


def cmd_print(args):
    cfg = winprint_spooler.get_config()
    p_model = args.printer or cfg.get("printer_model", "Brother DCP-B7640DW")
    ip = args.ip or brother_snmp.resolve_printer_ip(p_model, cfg.get("printer_ip"))
    if not ip:
        print("Alamat IP printer belum disetel. Jalankan: winprint set-ip <IP_PRINTER>")
        sys.exit(1)
        
    try:
        final_file = winprint_converter.ensure_pdf(args.file, paper=args.paper)
    except Exception as e:
        print(f"[!] Catatan konversi dokumen: {e}", file=sys.stderr)
        final_file = args.file

    if args.direct:
        # Direct synchronous print without queue
        success = winprint_engine.print_file_direct(
            ip=ip,
            file_path=final_file,
            paper=args.paper,
            duplex=args.duplex,
            toner_save=args.toner_save,
            resolution=args.resolution,
            copies=args.copies,
            scale=args.scale,
            printer_model=p_model,
            paper_source=args.tray,
            media_type=args.media_type,
            quiet_mode=args.quiet,
            density=args.density,
            binding_gutter_mm=args.gutter_mm,
            collate=not args.no_collate,
        )
        sys.exit(0 if success else 1)
    else:
        # Submit to asynchronous spooler queue
        job_id = winprint_spooler.submit_job(
            file_path=final_file,
            paper=args.paper,
            duplex=args.duplex,
            toner_save=args.toner_save,
            resolution=args.resolution,
            copies=args.copies,
            scale=args.scale,
            printer_model=p_model,
        )
        print(f"[✓] Tugas cetak #{job_id} ({p_model}) berhasil didaftarkan ke antrean WinPrint.")


def cmd_scan(args):
    cfg = winprint_spooler.get_config()
    ip = args.ip or cfg.get("printer_ip")
    if not ip:
        print("Alamat IP printer belum disetel. Jalankan: winprint set-ip <IP_PRINTER>")
        sys.exit(1)
        
    out = args.output or ("scan_dokumen.pdf" if args.ocr else "scan_dokumen.jpg")
    source = "adf" if args.adf else "flatbed"
    
    base_url = brother_scan.get_escl_base_url(ip)
    if base_url:
        ok = brother_scan.scan_escl(base_url, source, args.resolution, args.color, out, args.ocr)
    else:
        ok = brother_scan.scan_sane_fallback(ip, source, args.resolution, args.color, out, args.ocr)
        
    if ok:
        print(f"[✓] Pemindaian selesai disimpan ke: {out}")
    else:
        print("[✗] Pemindaian gagal.")
        sys.exit(1)


def cmd_queue(args):
    if args.cancel:
        ok = winprint_spooler.cancel_job(args.cancel)
        print(f"Pembatalan tugas #{args.cancel}: {'Berhasil' if ok else 'Gagal'}")
    elif args.clear:
        winprint_spooler.clear_completed_jobs()
        print("Riwayat antrean telah dibersihkan.")
    else:
        jobs = winprint_spooler.list_jobs(limit=args.limit)
        if not jobs:
            print("Antrean cetak kosong.")
        else:
            print(f"{'ID':<4} | {'STATUS':<10} | {'UKURAN':<6} | {'DUPLEX':<6} | {'NAMA DOKUMEN':<30} | {'WAKTU'}")
            print("-" * 80)
            for j in jobs:
                print(f"{j['id']:<4} | {j['status']:<10} | {j['paper']:<6} | {j['duplex']:<6} | {j['job_name'][:28]:<30} | {j['created_at']}")


def cmd_set_ip(args):
    cfg = winprint_spooler.get_config()
    cfg["printer_ip"] = args.ip
    winprint_spooler.save_config(cfg)
    print(f"[✓] IP Printer default WinPrint berhasil diperbarui menjadi: {args.ip}")


def cmd_daemon(args):
    import winprint_daemon
    winprint_daemon.main()


def cmd_doctor(args):
    """Runs offline self-diagnostics verifying zero-drift authoritative setup."""
    import tempfile
    import shutil
    import subprocess
    import winprint_engine_v2
    import winprint_layout

    base_dir = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
    cfg = winprint_spooler.get_config()
    manifest = winprint_spooler.load_office_manifest()
    raw_bin = winprint_engine_v2.resolve_rawtobr3_path(cfg.get("printer_model", "Brother DCP-B7640DW"))
    ppd = winprint_engine.resolve_ppd_path()
    geom_f4 = winprint_layout.get_media_geometry(ppd, "F4", "portrait")
    off_x, off_y = winprint_engine_v2.get_calibration_mm("F4", "LONG_EDGE", cfg.get("printer_model", "Brother DCP-B7640DW"))

    print("=== WinPrint Doctor (Zero-Drift Self-Check) ===")
    print(f"Manifest Ver : {manifest.get('manifest_version', 'none')} (authoritative={manifest.get('authoritative', False)})")
    print(f"Config       : model={cfg.get('printer_model')} paper={cfg.get('default_paper')} duplex={cfg.get('default_duplex')} safe_fit={cfg.get('safe_fit_to_printable')}")
    print(f"PPD Active   : {ppd} (F4={geom_f4.width_pt}x{geom_f4.height_pt} pt)")
    print(f"rawtobr3     : {raw_bin or 'MISSING'}")
    print(f"Calib F4     : X={off_x:+.1f} mm, Y={off_y:+.1f} mm")

    if shutil.which("systemctl"):
        st = subprocess.run(["systemctl", "--user", "is-active", "winprint.service"], capture_output=True, text=True)
        print(f"Service      : {st.stdout.strip() or 'inactive'}")
    if shutil.which("lpstat"):
        lp = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
        print(f"CUPS Default : {lp.stdout.strip() or 'none'}")

    fd, pdf_tmp = tempfile.mkstemp(suffix="_doctor.pdf")
    os.close(fd)
    ok = True
    try:
        winprint_layout.generate_calibration_pdf(pdf_tmp, geom_f4)
        res = winprint_engine_v2.render_job(
            input_pdf=pdf_tmp,
            media="F4",
            duplex="LONG_EDGE",
            copies=1,
            geometry=geom_f4,
            fit_to_printable=bool(cfg.get("safe_fit_to_printable", True)),
            backend="auto",
            printer_model=cfg.get("printer_model", "Brother DCP-B7640DW"),
        )
        m = res["manifest"]
        has_1038 = b"\x1b&l1038a" in res["stream"]
        has_1s = b"\x1b&l1S" in res["stream"]
        print(f"Dry-Run F4   : backend={m['backend']} bytes={m['total_bytes']} PCL1038={has_1038} Duplex1S={has_1s}")
        if not raw_bin or m["backend"] != "brother_pcl" or not (has_1038 and has_1s):
            ok = False
        if abs(off_x - 2.5) > 0.05 or abs(off_y - (-3.8)) > 0.05:
            print("[WARN] Offset kalibrasi F4 berbeda dari standar kantor (+2.5, -3.8 mm)")
    finally:
        if os.path.exists(pdf_tmp):
            os.remove(pdf_tmp)

    print(f"Result       : {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description="WinPrint-Linux: Non-CUPS Print & Scan Suite for Brother Printers")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    
    # print
    p_print = subparsers.add_parser("print", help="Print a document (PDF)")
    p_print.add_argument("file", help="File to print")
    p_print.add_argument("--ip", help="Target printer IP")
    p_print.add_argument("--printer", choices=["Brother DCP-B7640DW", "Brother DCP-L2540DW"], help="Target printer model")
    p_print.add_argument("--paper", choices=["A4", "F4", "Folio", "Legal", "Letter"], default="A4")
    p_print.add_argument("--duplex", choices=["none", "long", "short"], default="none")
    p_print.add_argument("--scale", type=float, default=1.0, help="Content scale factor (e.g. 1.12 for 112%%)")
    p_print.add_argument("--gutter-mm", type=float, default=0.0, help="Binding gutter shift in mm")
    p_print.add_argument("--tray", choices=["auto", "tray1", "manual"], default="auto", help="Paper source tray")
    p_print.add_argument("--media-type", choices=["plain", "thick", "recycled", "envelope"], default="plain", help="Media thickness/type")
    p_print.add_argument("--quiet", action="store_true", help="Enable Quiet Mode (half feed speed)")
    p_print.add_argument("--density", type=int, choices=[-2, -1, 0, 1, 2], default=0, help="Print density offset")
    p_print.add_argument("--toner-save", action="store_true", help="Enable Economode / Toner Save")
    p_print.add_argument("--resolution", type=int, choices=[300, 600, 1200], default=600)
    p_print.add_argument("--copies", type=int, default=1)
    p_print.add_argument("--no-collate", action="store_true", help="Disable software collation for multi-sheet jobs")
    p_print.add_argument("--direct", action="store_true", help="Bypass queue and stream directly")
    p_print.set_defaults(func=cmd_print)
    
    # status
    p_status = subparsers.add_parser("status", help="Query real-time Toner & Drum status via SNMP")
    p_status.add_argument("--ip", help="Target printer IP")
    p_status.add_argument("--printer", choices=["Brother DCP-B7640DW", "Brother DCP-L2540DW"], help="Target printer model")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--zenity", action="store_true")
    p_status.set_defaults(func=cmd_status)
    
    # scan
    p_scan = subparsers.add_parser("scan", help="Scan document from ADF or Flatbed")
    p_scan.add_argument("--ip", help="Target printer IP")
    p_scan.add_argument("--adf", action="store_true", help="Scan from Auto Document Feeder (50-sheet)")
    p_scan.add_argument("--ocr", action="store_true", help="Generate Searchable PDF with Tesseract OCR")
    p_scan.add_argument("--resolution", type=int, choices=[100, 150, 200, 300, 600], default=300)
    p_scan.add_argument("--color", choices=["color", "gray", "mono"], default="color")
    p_scan.add_argument("--output", help="Output file path (PDF/JPG/PNG)")
    p_scan.set_defaults(func=cmd_scan)
    
    # queue
    p_queue = subparsers.add_parser("queue", help="Manage print queue")
    p_queue.add_argument("--limit", type=int, default=20)
    p_queue.add_argument("--cancel", type=int, help="Cancel job ID")
    p_queue.add_argument("--clear", action="store_true", help="Clear completed jobs")
    p_queue.set_defaults(func=cmd_queue)
    
    # set-ip
    p_setip = subparsers.add_parser("set-ip", help="Configure default printer IP")
    p_setip.add_argument("ip", help="Printer IP address")
    p_setip.set_defaults(func=cmd_set_ip)
    
    # daemon
    p_daemon = subparsers.add_parser("daemon", help="Run background spooler & IPP server daemon")
    p_daemon.set_defaults(func=cmd_daemon)

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Verify authoritative config, PPD, rawtobr3, and F4 dry-run")
    p_doctor.set_defaults(func=cmd_doctor)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
