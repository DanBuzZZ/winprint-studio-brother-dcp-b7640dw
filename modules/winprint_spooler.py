#!/usr/bin/env python3
"""
winprint_spooler.py - Robust SQLite-backed Print Spooler Daemon for WinPrint-Linux
Manages asynchronous print queues, job retention, auto-retry on printer sleep/offline,
and desktop notifications. Zero CUPS dependency.
"""

import sys
import os
import time
import sqlite3
import subprocess
import shutil
import json
from datetime import datetime

# Import sibling modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_engine
import brother_snmp

DB_DIR = os.path.expanduser("~/.local/share/winprint")
DB_PATH = os.path.join(DB_DIR, "spool.db")
CONFIG_PATH = os.path.join(DB_DIR, "config.json")
OFFICE_MANIFEST_PATH = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "office_manifest.json")
)

AUTHORITATIVE_POLICY_KEYS = (
    "printer_model",
    "printer_name",
    "default_paper",
    "default_duplex",
    "default_toner_save",
    "default_resolution",
    "auto_retry",
    "intercept_to_studio",
    "safe_fit_to_printable",
)


def load_office_manifest(manifest_path: str = OFFICE_MANIFEST_PATH) -> dict:
    """Loads authoritative office configuration manifest if present."""
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def apply_authoritative_manifest(
    config_path: str = CONFIG_PATH,
    manifest_path: str = OFFICE_MANIFEST_PATH,
    preserve_network_cache: bool = True,
) -> dict:
    """Overwrites policy keys in config.json from authoritative office_manifest.json."""
    manifest = load_office_manifest(manifest_path)
    existing = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    merged = dict(existing) if preserve_network_cache else {}
    for k in AUTHORITATIVE_POLICY_KEYS:
        if k in manifest:
            merged[k] = manifest[k]
    if "manifest_version" in manifest:
        merged["office_profile_version"] = manifest["manifest_version"]
    if "printer_ip" not in merged:
        merged["printer_ip"] = ""

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp_path, config_path)
    return merged


def get_config() -> dict:
    default_cfg = {
        "printer_ip": "",
        "printer_name": "Brother-DCP-B7640DW",
        "printer_model": "Brother DCP-B7640DW",
        "default_paper": "F4",
        "default_duplex": "long",
        "default_toner_save": False,
        "default_resolution": 600,
        "auto_retry": True,
        "intercept_to_studio": True,
        "safe_fit_to_printable": True,
    }
    manifest = load_office_manifest()
    if manifest.get("authoritative"):
        for k in AUTHORITATIVE_POLICY_KEYS:
            if k in manifest:
                default_cfg[k] = manifest[k]

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
                default_cfg.update(saved)
        except Exception:
            pass

    if manifest.get("authoritative") and not default_cfg.get("keep_local_override"):
        for k in AUTHORITATIVE_POLICY_KEYS:
            if k in manifest:
                default_cfg[k] = manifest[k]

    return default_cfg


def save_config(cfg: dict):
    os.makedirs(DB_DIR, exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp_path, CONFIG_PATH)


def update_config(updates: dict) -> dict:
    """Merges updates into config.json and returns the updated configuration."""
    cfg = get_config()
    if isinstance(updates, dict):
        cfg.update(updates)
        save_config(cfg)
    return cfg


def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            paper TEXT DEFAULT 'A4',
            orientation TEXT DEFAULT 'portrait',
            duplex TEXT DEFAULT 'none',
            toner_save INTEGER DEFAULT 0,
            resolution INTEGER DEFAULT 600,
            copies INTEGER DEFAULT 1,
            scale REAL DEFAULT 1.0,
            printer_model TEXT DEFAULT 'Brother DCP-B7640DW',
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            error_message TEXT
        )
    """)
    for ddl in (
        "ALTER TABLE jobs ADD COLUMN orientation TEXT DEFAULT 'portrait'",
        "ALTER TABLE jobs ADD COLUMN scale REAL DEFAULT 1.0",
        "ALTER TABLE jobs ADD COLUMN printer_model TEXT DEFAULT 'Brother DCP-B7640DW'",
    ):
        try:
            cursor.execute(ddl)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def send_desktop_notification(title: str, message: str, icon: str = "printer"):
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "WinPrint", "-i", icon, title, message], check=False)
        except Exception:
            pass


def submit_job(file_path: str, job_name: str = None, paper: str = None, duplex: str = None,
               toner_save: bool = None, resolution: int = None, copies: int = 1,
               orientation: str = "portrait", scale: float = 1.0,
               printer_model: str = None) -> int:
    init_db()
    cfg = get_config()
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File dokumen tidak ditemukan: {file_path}")
        
    # Store a safe copy in spool storage
    spool_storage = os.path.join(DB_DIR, "spool_files")
    os.makedirs(spool_storage, exist_ok=True)
    
    timestamp = int(time.time() * 1000)
    base_name = os.path.basename(file_path)
    job_name = job_name or base_name
    spooled_file = os.path.join(spool_storage, f"{timestamp}_{base_name}")
    shutil.copyfile(file_path, spooled_file)
    
    paper = paper or cfg.get("default_paper", "A4")
    duplex = duplex or cfg.get("default_duplex", "none")
    toner_save = toner_save if toner_save is not None else cfg.get("default_toner_save", False)
    resolution = resolution or cfg.get("default_resolution", 600)
    orientation = orientation or "portrait"
    scale = float(scale if scale is not None else 1.0)
    printer_model = printer_model or cfg.get("printer_model", "Brother DCP-B7640DW")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO jobs (job_name, file_path, paper, orientation, duplex, toner_save, resolution, copies, scale, printer_model, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (job_name, spooled_file, paper, orientation, duplex, 1 if toner_save else 0, resolution, copies, scale, printer_model))
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    send_desktop_notification("Pekerjaan Cetak Diterima", f"'{job_name}' ditambahkan ke antrean (ID #{job_id}).")
    return job_id


def list_jobs(limit: int = 20) -> list:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, job_name, paper, orientation, duplex, toner_save, copies, status, created_at, error_message
        FROM jobs
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def cancel_job(job_id: int) -> bool:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE jobs
        SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status IN ('PENDING', 'PRINTING')
    """, (job_id,))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    if updated:
        send_desktop_notification("Pekerjaan Dibatalkan", f"Tugas cetak #{job_id} telah dibatalkan.")
    return updated


def clear_completed_jobs():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM jobs WHERE status IN ('COMPLETED', 'CANCELLED', 'FAILED')")
    for row in cursor.fetchall():
        fpath = row[0]
        if os.path.exists(fpath) and fpath.startswith(os.path.join(DB_DIR, "spool_files")):
            try:
                os.remove(fpath)
            except OSError:
                pass
    cursor.execute("DELETE FROM jobs WHERE status IN ('COMPLETED', 'CANCELLED', 'FAILED')")
    conn.commit()
    conn.close()


def process_queue_worker(printer_ip: str = None, poll_interval: float = 3.0, run_once: bool = False):
    """Continuous background spooler worker daemon."""
    init_db()
    if not run_once:
        print(f"[*] WinPrint Spooler Daemon aktif.")
    
    while True:
        cfg = get_config()
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get next pending job
        cursor.execute("""
            SELECT * FROM jobs
            WHERE status = 'PENDING'
            ORDER BY id ASC
            LIMIT 1
        """)
        job = cursor.fetchone()
        conn.close()
        
        if not job:
            if run_once:
                break
            time.sleep(poll_interval)
            continue
            
        job_id = job["id"]
        job_name = job["job_name"]
        file_path = job["file_path"]
        job_keys = job.keys()
        paper = job["paper"]
        orientation = job["orientation"] if "orientation" in job_keys and job["orientation"] else "portrait"
        duplex = job["duplex"]
        toner_save = bool(job["toner_save"])
        resolution = job["resolution"]
        copies = job["copies"]
        scale_val = float(job["scale"]) if "scale" in job_keys and job["scale"] is not None else 1.0
        p_model = job["printer_model"] if "printer_model" in job_keys and job["printer_model"] else cfg.get("printer_model", "Brother DCP-B7640DW")

        if printer_ip:
            target_ip = printer_ip
        else:
            known_ip = cfg.get("known_printers", {}).get(p_model)
            if not known_ip and p_model == cfg.get("printer_model", "Brother DCP-B7640DW"):
                known_ip = cfg.get("printer_ip")
            if hasattr(brother_snmp, "resolve_printer_ip"):
                target_ip = brother_snmp.resolve_printer_ip(p_model, preferred_ip=known_ip, set_active=False)
            else:
                target_ip = known_ip or cfg.get("printer_ip")
        
        # Update status to PRINTING
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = 'PRINTING', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        
        print(f"\n[+] Memproses Tugas #{job_id}: '{job_name}' ke printer {p_model} ({target_ip})...")
        send_desktop_notification("Mencetak Dokumen", f"Sedang mencetak '{job_name}'...")
        
        success = False
        error_msg = None
        max_retries = 3
        
        for attempt in range(1, max_retries + 1):
            try:
                success = winprint_engine.print_file_direct(
                    ip=target_ip,
                    file_path=file_path,
                    paper=paper,
                    duplex=duplex,
                    toner_save=toner_save,
                    resolution=resolution,
                    copies=copies,
                    orientation=orientation,
                    scale=scale_val,
                    printer_model=p_model,
                )
                if success:
                    break
                else:
                    error_msg = winprint_engine.get_last_error() or "Printer tidak merespons pada port 9100."
            except Exception as e:
                error_msg = str(e)
                
            if attempt < max_retries:
                print(f"[!] Percobaan {attempt} gagal. Menunggu printer bangun (5 detik)...")
                time.sleep(5)
                
        # Finalize job in DB
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if success:
            cursor.execute("UPDATE jobs SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            print(f"[✓] Tugas #{job_id} BERHASIL dicetak.")
            send_desktop_notification("Cetak Selesai", f"'{job_name}' berhasil dicetak di {target_ip}.")
            # Clean spooled file
            if os.path.exists(file_path) and file_path.startswith(os.path.join(DB_DIR, "spool_files")):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        else:
            cursor.execute("UPDATE jobs SET status = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (error_msg, job_id))
            print(f"[✗] Tugas #{job_id} GAGAL: {error_msg}")
            send_desktop_notification("Cetak Gagal", f"Gagal mencetak '{job_name}': {error_msg}", icon="dialog-error")
        conn.commit()
        conn.close()
        
        if run_once:
            break
        time.sleep(1.0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="WinPrint Spooler Manager")
    parser.add_argument("--daemon", action="store_true", help="Run spooler in background daemon mode")
    parser.add_argument("--run-once", action="store_true", help="Process pending queue and exit")
    parser.add_argument("--submit", help="Submit file to print queue")
    parser.add_argument("--name", help="Job name")
    parser.add_argument("--paper", choices=["A4", "F4", "Folio", "Legal", "Letter"], default="A4")
    parser.add_argument("--duplex", choices=["none", "long", "short"], default="none")
    parser.add_argument("--toner-save", action="store_true")
    parser.add_argument("--resolution", type=int, default=600)
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--list", action="store_true", help="List print jobs")
    parser.add_argument("--cancel", type=int, help="Cancel job by ID")
    parser.add_argument("--clear", action="store_true", help="Clear completed jobs")
    parser.add_argument("--set-ip", help="Update default printer IP in config")
    args = parser.parse_args()
    
    if args.set_ip:
        cfg = get_config()
        cfg["printer_ip"] = args.set_ip
        save_config(cfg)
        print(f"IP Printer default diperbarui: {args.set_ip}")
        sys.exit(0)
        
    if args.submit:
        job_id = submit_job(
            file_path=args.submit,
            job_name=args.name,
            paper=args.paper,
            duplex=args.duplex,
            toner_save=args.toner_save,
            resolution=args.resolution,
            copies=args.copies
        )
        print(f"Pekerjaan #{job_id} berhasil didaftarkan ke antrean.")
        sys.exit(0)
        
    if args.list:
        jobs = list_jobs()
        if not jobs:
            print("Antrean cetak kosong.")
        else:
            print(f"{'ID':<4} | {'STATUS':<10} | {'UKURAN':<6} | {'DUPLEX':<6} | {'NAMA DOKUMEN':<30} | {'WAKTU'}")
            print("-" * 80)
            for j in jobs:
                print(f"{j['id']:<4} | {j['status']:<10} | {j['paper']:<6} | {j['duplex']:<6} | {j['job_name'][:28]:<30} | {j['created_at']}")
        sys.exit(0)
        
    if args.cancel:
        ok = cancel_job(args.cancel)
        print(f"Hasil pembatalan tugas #{args.cancel}: {'Berhasil' if ok else 'Gagal / Tidak ditemukan'}")
        sys.exit(0)
        
    if args.clear:
        clear_completed_jobs()
        print("Riwayat pekerjaan cetak selesai telah dibersihkan.")
        sys.exit(0)
        
    if args.daemon or args.run_once:
        process_queue_worker(run_once=args.run_once)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
