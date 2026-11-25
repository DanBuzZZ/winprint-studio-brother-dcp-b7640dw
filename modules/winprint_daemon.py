#!/usr/bin/env python3
"""
winprint_daemon.py - Master Background Service for WinPrint-Linux (Daemon)
Runs Spooler Worker, IPP Loopback Bridge, and Background SNMP Language Monitor.
Zero root required, runs cleanly as a systemd user service or background daemon.
"""

import sys
import os
import time
import threading
import signal
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import winprint_ipp_server
import brother_snmp

STOP_EVENT = threading.Event()


def language_monitor_thread(interval: float = 60.0):
    """Background thread resolving active DHCP IP, cleaning stale temp files, and polling SNMP status."""
    last_alerted = {}
    last_cleanup = 0.0
    try:
        cfg = winprint_spooler.get_config()
        active_model = cfg.get("printer_model", "Brother DCP-B7640DW")
        resolved_ip = brother_snmp.resolve_printer_ip(active_model, cfg.get("printer_ip"), set_active=True)
        print(f"[*] Discovery awal {active_model}: {resolved_ip}")
        winprint_ipp_server.cleanup_stale_temp_files()
        last_cleanup = time.time()
    except Exception:
        pass

    while not STOP_EVENT.is_set():
        cfg = winprint_spooler.get_config()
        ip = cfg.get("printer_ip")
        if time.time() - last_cleanup > 3600.0:
            winprint_ipp_server.cleanup_stale_temp_files()
            last_cleanup = time.time()
        if ip:
            try:
                telemetry = brother_snmp.get_printer_telemetry(ip)
                if not telemetry.get("online"):
                    active_model = cfg.get("printer_model", "Brother DCP-B7640DW")
                    new_ip = brother_snmp.resolve_printer_ip(active_model, ip, set_active=True)
                    if new_ip and new_ip != ip:
                        telemetry = brother_snmp.get_printer_telemetry(new_ip)
                if telemetry.get("online"):
                    toner = telemetry.get("toner_pct")
                    drum = telemetry.get("drum_pct")
                    lcd = telemetry.get("lcd_text", "").lower()
                    
                    # Check paper jam or error
                    if "jam" in lcd or "error" in lcd:
                        now = time.time()
                        if now - last_alerted.get("jam", 0) > 300: # alert once every 5m
                            winprint_spooler.send_desktop_notification(
                                "Masalah Perangkat Keras",
                                f"Printer Brother ({ip}) mendeteksi: {telemetry.get('lcd_text')}",
                                icon="dialog-error"
                            )
                            last_alerted["jam"] = now
                            
                    # Check low toner
                    if toner is not None and toner <= 10:
                        now = time.time()
                        if now - last_alerted.get("toner", 0) > 1800: # alert once every 30m
                            winprint_spooler.send_desktop_notification(
                                "TonerBox Hampir Habis",
                                f"Sisa toner Brother tinggal {toner}%. Segera siapkan toner pengganti.",
                                icon="dialog-warning"
                            )
                            last_alerted["toner"] = now
            except Exception:
                pass
        STOP_EVENT.wait(interval)


def spooler_thread():
    """Runs the spooler queue worker loop."""
    while not STOP_EVENT.is_set():
        winprint_spooler.process_queue_worker(poll_interval=2.0, run_once=True)
        STOP_EVENT.wait(2.0)


def ipp_server_thread(port: int = 9631):
    """Runs the concurrent loopback IPP server."""
    winprint_ipp_server.cleanup_stale_temp_files()
    server = winprint_ipp_server.WinPrintThreadingIPPServer(("127.0.0.1", port), winprint_ipp_server.WinPrintIPPHandler)
    server.timeout = 1.0
    while not STOP_EVENT.is_set():
        server.handle_request()
    server.server_close()


def sig_handler(signum, frame):
    print("\n[!] Menghentikan layanan WinPrint Daemon...")
    STOP_EVENT.set()


def main():
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    
    print("==================================================")
    print("  WinPrint-Linux Master Daemon (Beyond-CUPS Engine)")
    print("  Brother DCP-B7640DW Full-Function Subsystem")
    print("==================================================")
    
    cfg = winprint_spooler.get_config()
    print(f"[*] Target Printer IP : {cfg.get('printer_ip')}")
    print(f"[*] Spool Database    : {winprint_spooler.DB_PATH}")
    print(f"[*] IPP Loopback Port : 9631 (ipp://127.0.0.1:9631/)")
    
    t_spool = threading.Thread(target=spooler_thread, daemon=True, name="SpoolerWorker")
    t_ipp = threading.Thread(target=ipp_server_thread, args=(9631,), daemon=True, name="IPPServer")
    t_lang = threading.Thread(target=language_monitor_thread, args=(60.0,), daemon=True, name="LanguageMonitor")
    
    t_spool.start()
    t_ipp.start()
    t_lang.start()
    
    print("[✓] Semua subsistem aktif. Berjalan di latar belakang (Ctrl+C untuk keluar).")
    
    while not STOP_EVENT.is_set():
        time.sleep(1.0)
        
    print("[✓] WinPrint Daemon berhenti dengan aman.")


if __name__ == "__main__":
    main()
