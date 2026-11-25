#!/usr/bin/env python3
"""
run_matrix_t1_t6.py - Isolated Acceptance Test Runner (T1-T6)
Generates identical 3x2 calibration PDFs (or 4-page collation PDF for T6),
runs pre-flight PJL telemetry, builds pure PCL-XL stream via winprint_engine_v2,
logs SHA-256 reproducibility manifests, and optionally transmits to printer on port 9100.
"""

import argparse
import json
import os
import socket
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "modules")))
import winprint_comm
import winprint_layout
import winprint_engine_v2

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PPD_PATH = os.path.join(BASE_DIR, "BRPPB7640DW.PPD") if os.path.isfile(os.path.join(BASE_DIR, "BRPPB7640DW.PPD")) else os.path.join(BASE_DIR, "Brother_B7640DW_WinPrint.ppd")
LOG_DIR = os.path.join(BASE_DIR, "test_logs")

CASES = {
    "T1": {"media": "A4", "duplex": "SIMPLEX", "copies": 1, "experimental_pjl": False, "offset_y_pt": 0.0, "desc": "A4 Simplex baseline"},
    "T2": {"media": "A4", "duplex": "LONG_EDGE", "copies": 1, "experimental_pjl": False, "offset_y_pt": 0.0, "desc": "A4 Duplex PJL OFF"},
    "T3": {"media": "A4", "duplex": "LONG_EDGE", "copies": 1, "experimental_pjl": True, "offset_y_pt": 0.0, "desc": "A4 Duplex DXBACKSIDEFIRSTSENDMODE=ON"},
    "T4": {"media": "Folio", "duplex": "SIMPLEX", "copies": 1, "experimental_pjl": False, "offset_y_pt": 0.0, "desc": "Folio Simplex printable area"},
    "T5": {"media": "Folio", "duplex": "LONG_EDGE", "copies": 1, "experimental_pjl": True, "offset_y_pt": 0.0, "desc": "Folio Duplex 1-sheet experiment"},
    "T6": {"media": "Folio", "duplex": "LONG_EDGE", "copies": 3, "experimental_pjl": True, "offset_y_pt": 0.0, "desc": "4-page 3-copy software collation"},
}


def send_raw_9100(ip: str, port: int, payload: bytes, timeout: float = 10.0) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        sock.sendall(payload)
    finally:
        sock.close()


def run_case(case_id: str, printer_ip: str, execute: bool = False, offset_y_pt: float = None, fit_to_printable: bool = True) -> dict:
    cfg = dict(CASES[case_id])
    if offset_y_pt is not None:
        cfg["offset_y_pt"] = offset_y_pt

    os.makedirs(LOG_DIR, exist_ok=True)
    geom = winprint_layout.get_media_geometry(PPD_PATH, cfg["media"], "portrait")

    telemetry = winprint_comm.get_printer_telemetry(printer_ip)

    fd, src_pdf = tempfile.mkstemp(suffix=f"_{case_id}.pdf")
    os.close(fd)
    try:
        winprint_layout.generate_calibration_pdf(src_pdf, geom)
        if case_id == "T6":
            # Expand 2-page calibration PDF to 4 pages by concatenating with gs
            fd4, pdf4 = tempfile.mkstemp(suffix=f"_{case_id}_4p.pdf")
            os.close(fd4)
            import subprocess
            subprocess.run([
                "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
                f"-sOutputFile={pdf4}", src_pdf, src_pdf
            ], check=True)
            os.replace(pdf4, src_pdf)

        result = winprint_engine_v2.render_job(
            input_pdf=src_pdf,
            media=cfg["media"],
            duplex=cfg["duplex"],
            copies=cfg["copies"],
            geometry=geom,
            experimental_pjl=cfg["experimental_pjl"],
            offset_y_pt=cfg["offset_y_pt"],
            fit_to_printable=fit_to_printable,
            job_name=f"WinPrint_{case_id}",
        )
    finally:
        if os.path.exists(src_pdf):
            os.remove(src_pdf)

    transmitted = False
    tx_error = None
    if execute:
        if telemetry["device_state"] == "ERROR":
            tx_error = f"Blocked by ERROR telemetry: {telemetry['reason']}"
        else:
            try:
                send_raw_9100(printer_ip, 9100, result["stream"])
                transmitted = True
            except Exception as e:
                tx_error = str(e)

    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"{case_id}_{ts}.json")
    report = {
        "case_id": case_id,
        "description": cfg["desc"],
        "execute": execute,
        "transmitted": transmitted,
        "tx_error": tx_error,
        "telemetry": {k: v for k, v in telemetry.items() if k != "raw_variables"},
        "manifest": result["manifest"],
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return {"log_path": log_path, "report": report}


def main():
    parser = argparse.ArgumentParser(description="WinPrint T1-T6 Acceptance Test Runner")
    parser.add_argument("--case", choices=list(CASES.keys()) + ["ALL"], default="ALL")
    parser.add_argument("--ip", default="192.168.100.229")
    parser.add_argument("--execute", action="store_true", help="Actually send print job to printer")
    parser.add_argument("--offset-y", type=float, default=None, help="Override back-side offset_y_pt")
    parser.add_argument("--no-fit", action="store_true", help="Disable fit_to_printable (1:1 physical coords)")
    args = parser.parse_args()

    targets = list(CASES.keys()) if args.case == "ALL" else [args.case]
    for cid in targets:
        out = run_case(cid, args.ip, execute=args.execute, offset_y_pt=args.offset_y, fit_to_printable=not args.no_fit)
        r = out["report"]
        m = r["manifest"]
        print(
            f"[{cid}] state={r['telemetry']['device_state']} "
            f"bytes={m['total_bytes']} sha256={m['final_stream_sha256'][:12]}... "
            f"tx={r['transmitted']} log={out['log_path']}"
        )


if __name__ == "__main__":
    main()
