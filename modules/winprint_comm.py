#!/usr/bin/env python3
"""
winprint_comm.py - Bidirectional Printer Telemetry & Handshake Module
Dedicated to Brother DCP-B7640DW (Firmware Ver. 1.28) and compatible models.
Executes non-blocking, non-destructive read-only PJL queries (INFO STATUS, INFO VARIABLES)
with strict single FormFeed (\x0c) framing and quad-state taxonomy mapping.
"""

import socket
import time
from typing import Dict, Any, Optional

STATUS_MAP_DCP_B7640DW_V1_28 = {
    10001: ("READY", "DCP_B7640DW_READY"),
    10003: ("BUSY", "DCP_B7640DW_WARMING_UP"),
    10023: ("BUSY", "DCP_B7640DW_PRINTING"),
    40000: ("READY", "DCP_B7640DW_NORMAL_STANDBY"),
    40001: ("ERROR", "OUT_OF_PAPER"),
    40021: ("ERROR", "COVER_OPEN"),
    40040: ("ERROR", "PAPER_JAM"),
}


def _read_until_formfeed(sock: socket.socket, timeout: float) -> bytes:
    """Reads socket chunks until single FormFeed (0x0c) delimiter is encountered."""
    sock.settimeout(timeout)
    buf = bytearray()
    while True:
        try:
            chunk = sock.recv(2048)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\x0c" in chunk:
                break
        except socket.timeout:
            break
    # Strip after first formfeed if present
    ff_idx = buf.find(b"\x0c")
    if ff_idx != -1:
        return bytes(buf[:ff_idx])
    return bytes(buf)


def _parse_pjl_key_values(raw_text: str) -> Dict[str, str]:
    """Parses raw PJL response lines into key-value pairs."""
    data = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("@PJL"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            # Handle brackets like FOLIO[39 ENUMERATED] -> FOLIO
            if "[" in v:
                v = v.split("[", 1)[0]
            # Strip quotes if string
            v = v.strip().strip('"')
            data[k] = v
    return data


def parse_telemetry_payload(status_text: str, variables_text: str, latency_ms: float) -> Dict[str, Any]:
    """
    Parses raw STATUS and VARIABLES payloads into structured quad-state telemetry.
    Adheres strictly to Brother DCP-B7640DW firmware 1.28 taxonomy.
    """
    status_kv = _parse_pjl_key_values(status_text)
    vars_kv = _parse_pjl_key_values(variables_text)

    # 1. Evaluate Status Code
    raw_code_str = status_kv.get("CODE")
    status_code: Optional[int] = None
    if raw_code_str and raw_code_str.isdigit():
        status_code = int(raw_code_str)

    display = status_kv.get("DISPLAY", "")
    online_str = status_kv.get("ONLINE", "").upper()
    is_online = (online_str == "TRUE")

    # 2. Quad-State Taxonomy Evaluation
    device_state = "UNKNOWN"
    reason = "UNMAPPED_STATUS_CODE"

    if status_code is not None:
        if status_code in STATUS_MAP_DCP_B7640DW_V1_28:
            mapped_state, mapped_reason = STATUS_MAP_DCP_B7640DW_V1_28[status_code]
            if status_code in (10001, 10003, 10023, 40000):
                # Active/standby codes require explicit ONLINE flag to avoid false READY on truncated packets
                if not online_str:
                    device_state = "UNKNOWN"
                    reason = "INCOMPLETE_STATUS_RESPONSE"
                elif not is_online:
                    device_state = "ERROR"
                    reason = "OFFLINE"
                else:
                    device_state = mapped_state
                    reason = mapped_reason
            else:
                device_state = mapped_state
                reason = mapped_reason
        else:
            device_state = "UNKNOWN"
            reason = f"UNVERIFIED_CODE_{status_code}"
    elif display.lower() in ("printing", "processing"):
        device_state = "BUSY"
        reason = "PRINTING_IN_PROGRESS"
    elif not is_online and status_kv:
        device_state = "ERROR"
        reason = "OFFLINE"

    # 3. Paper Tray Configuration (Separated from physical paper presence)
    intray2_size = vars_kv.get("INTRAY2SIZE")
    paper_tray = {}
    if intray2_size:
        paper_tray["tray2"] = {
            "configured_size": intray2_size,
            "paper_present": None,               # Presence cannot be asserted by INTRAY2SIZE
            "paper_presence_verified": False
        }

    return {
        "connection": "CONNECTED",
        "online": is_online,
        "display": display,
        "status_code": status_code,
        "paper_tray": paper_tray,
        "device_state": device_state,
        "reason": reason,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "latency_ms": round(latency_ms, 2),
        "raw_status": status_kv,
        "raw_variables": vars_kv
    }


def get_printer_telemetry(ip: str, port: int = 9100,
                          connect_timeout: float = 0.5,
                          read_timeout: float = 1.0) -> Dict[str, Any]:
    """
    Connects to physical printer via port 9100, executes sequential single-FF
    PJL queries (INFO STATUS, INFO VARIABLES), and returns structured telemetry.
    Guarantees non-destructive read-only execution (never sends @PJL RESET).
    """
    t0 = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(connect_timeout)

    try:
        sock.connect((ip, port))
    except Exception as e:
        sock.close()
        return {
            "connection": "DISCONNECTED",
            "online": False,
            "display": "",
            "status_code": None,
            "paper_tray": {},
            "device_state": "UNKNOWN",
            "reason": f"CONNECTION_FAILED: {str(e)}",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "latency_ms": round((time.time() - t0) * 1000, 2),
            "raw_status": {},
            "raw_variables": {}
        }

    status_text = ""
    variables_text = ""

    try:
        # Step 1: Send INFO STATUS and read until single FormFeed
        sock.sendall(b"\x1b%-12345X@PJL\r\n@PJL INFO STATUS\r\n\x1b%-12345X")
        raw_status = _read_until_formfeed(sock, read_timeout)
        status_text = raw_status.decode("latin1", "ignore")

        # Step 2: Send INFO VARIABLES and read until single FormFeed
        sock.sendall(b"\x1b%-12345X@PJL\r\n@PJL INFO VARIABLES\r\n\x1b%-12345X")
        raw_vars = _read_until_formfeed(sock, read_timeout)
        variables_text = raw_vars.decode("latin1", "ignore")

    except socket.timeout:
        pass
    except Exception as e:
        status_text += f"\nERROR={str(e)}"
    finally:
        sock.close()

    total_latency_ms = (time.time() - t0) * 1000.0

    if not status_text and not variables_text:
        return {
            "connection": "TIMEOUT",
            "online": False,
            "display": "",
            "status_code": None,
            "paper_tray": {},
            "device_state": "UNKNOWN",
            "reason": "SOCKET_READ_TIMEOUT",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "latency_ms": round(total_latency_ms, 2),
            "raw_status": {},
            "raw_variables": {}
        }

    return parse_telemetry_payload(status_text, variables_text, total_latency_ms)
