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
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
