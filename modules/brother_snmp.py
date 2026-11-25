#!/usr/bin/env python3
"""
brother_snmp.py - Zero-dependency SNMP v1/v2c client for Brother Printers
Queries Toner Level (TN-B028), Drum Life (DR-B028), Page Counter, and LCD Display text.
Designed for Printer Wizard v2.0 (Brother DCP-B7640DW / DCP-L2540DW).
"""

import sys
import os
import socket
import struct
import json
import argparse
import subprocess
import concurrent.futures

# Brother & Standard Printer MIB OIDs
OID_SYS_DESCR          = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME           = "1.3.6.1.2.1.1.5.0"
OID_DEVICE_DESCR       = "1.3.6.1.2.1.25.3.2.1.3.1"
OID_TONER_LEVEL        = "1.3.6.1.2.1.43.11.1.1.9.1.1"      # prtMarkerSuppliesLevel
OID_TONER_MAX          = "1.3.6.1.2.1.43.11.1.1.8.1.1"      # prtMarkerSuppliesMaxCapacity
OID_DRUM_LIFE          = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.8.0"  # Brother Private MIB: Drum life %
OID_PAGE_COUNT         = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.1.0"  # Brother Private MIB: Total pages
OID_LCD_BUFFER_1       = "1.3.6.1.2.1.43.16.5.1.2.1.1"      # prtConsoleDisplayBufferText line 1
OID_LCD_BUFFER_2       = "1.3.6.1.2.1.43.16.5.1.2.1.2"      # prtConsoleDisplayBufferText line 2
OID_PRT_STATUS         = "1.3.6.1.2.1.25.3.2.1.5.1"          # hrDeviceStatus (1=unknown,2=running,3=warning,4=testing,5=down)


def encode_length(length: int) -> bytes:
    if length < 128:
        return bytes([length])
    sub_lens = []
    while length > 0:
        sub_lens.append(length & 0xFF)
        length >>= 8
    sub_lens.reverse()
    return bytes([0x80 | len(sub_lens)] + sub_lens)


def encode_oid(oid_str: str) -> bytes:
    parts = [int(x) for x in oid_str.strip('.').split('.')]
    if len(parts) < 2:
        return b''
    first = 40 * parts[0] + parts[1]
    res = bytearray([first])
    for p in parts[2:]:
        if p < 128:
            res.append(p)
        else:
            buf = []
            while p > 0:
                buf.append(p & 0x7F)
                p >>= 7
            for i in range(len(buf) - 1, 0, -1):
                res.append(buf[i] | 0x80)
            res.append(buf[0])
    return bytes(res)


def build_get_request(oid: str, community: str = "public", req_id: int = 1, version: int = 1) -> bytes:
    # version: 0 = v1, 1 = v2c
    enc_oid = encode_oid(oid)
    varbind = bytes([0x30]) + encode_length(len(enc_oid) + 4) + bytes([0x06, len(enc_oid)]) + enc_oid + bytes([0x05, 0x00])
    varbindlist = bytes([0x30]) + encode_length(len(varbind)) + varbind
    
    # PDU GetRequest (0xA0)
    pdu_payload = (
        struct.pack(">I", req_id) +
        bytes([0x02, 0x01, 0x00]) + # error-status = 0
        bytes([0x02, 0x01, 0x00]) + # error-index = 0
        varbindlist
    )
    pdu = bytes([0xA0]) + encode_length(len(pdu_payload)) + pdu_payload
    
    # SNMP Message
    comm_bytes = community.encode("latin1")
    msg_payload = (
        bytes([0x02, 0x01, version]) +
        bytes([0x04, len(comm_bytes)]) + comm_bytes +
        pdu
    )
    return bytes([0x30]) + encode_length(len(msg_payload)) + msg_payload


def decode_ber(data: bytes, offset: int = 0):
    if offset >= len(data):
        return None, offset
    tag = data[offset]
    offset += 1
    length_byte = data[offset]
    offset += 1
    if length_byte & 0x80:
        num_octets = length_byte & 0x7F
        length = 0
        for _ in range(num_octets):
            length = (length << 8) | data[offset]
            offset += 1
    else:
        length = length_byte
    val_bytes = data[offset:offset + length]
    return (tag, val_bytes), offset + length


def parse_snmp_value(tag: int, val: bytes):
    if tag == 0x02:  # Integer
        res = 0
        is_neg = bool(val[0] & 0x80)
        for b in val:
            res = (res << 8) | b
        if is_neg:
            res -= (1 << (8 * len(val)))
        return res
    elif tag == 0x04:  # Octet String
        try:
            return val.decode("utf-8", errors="replace").strip()
        except Exception:
            return val.hex()
    elif tag in (0x41, 0x42):  # Counter32, Gauge32
        res = 0
        for b in val:
            res = (res << 8) | b
        return res
    elif tag == 0x06:  # OID
        return "oid:" + val.hex()
    elif tag == 0x05:  # Null
        return None
    elif tag in (0x80, 0x81, 0x82):  # NoSuchObject, NoSuchInstance, EndOfMib
        return None
    return val


def snmp_get(ip: str, oid: str, community: str = "public", port: int = 161, timeout: float = 2.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    req = build_get_request(oid, community)
    try:
        sock.sendto(req, (ip, port))
        data, _ = sock.recvfrom(4096)
    except (socket.timeout, OSError):
        return None
    finally:
        sock.close()

    try:
        # Message Sequence
        msg_seq, _ = decode_ber(data, 0)
        offset = 0
        # Version
        ver, offset = decode_ber(msg_seq[1], offset)
        # Community
        comm, offset = decode_ber(msg_seq[1], offset)
        # PDU Response (0xA2)
        pdu, offset = decode_ber(msg_seq[1], offset)
        if not pdu or pdu[0] != 0xA2:
            return None
        
        pdu_offset = 0
        req_id, pdu_offset = decode_ber(pdu[1], pdu_offset)
        err_stat, pdu_offset = decode_ber(pdu[1], pdu_offset)
        err_idx, pdu_offset = decode_ber(pdu[1], pdu_offset)
        
        if parse_snmp_value(err_stat[0], err_stat[1]) != 0:
            return None
        
        vblist, pdu_offset = decode_ber(pdu[1], pdu_offset)
        vb, _ = decode_ber(vblist[1], 0)
        
        vb_offset = 0
        ret_oid, vb_offset = decode_ber(vb[1], vb_offset)
        ret_val, vb_offset = decode_ber(vb[1], vb_offset)
        
        return parse_snmp_value(ret_val[0], ret_val[1])
    except Exception:
        return None


def get_http_pjl_telemetry(ip: str):
    """Fallback telemetry via Port 9100 PJL and Port 80 Embedded Web Server."""
    data = {}
    import re
    # 1. PJL Query over TCP 9100
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((ip, 9100))
        s.sendall(b'@PJL INFO ID\r\n@PJL INFO STATUS\r\n@PJL INFO PAGECOUNT\r\n')
        buf = b""
        for _ in range(10):
            try:
                chunk = s.recv(512)
                if not chunk:
                    break
                buf += chunk
                if buf.count(b'\x0c') >= 3:
                    break
            except socket.timeout:
                break
        s.close()
        text = buf.decode("latin1", errors="replace")
        m_id = re.search(r'\"Brother ([^\":]+)', text)
        if m_id:
            data["model"] = "Brother " + m_id.group(1).strip()
        m_disp = re.search(r'DISPLAY=\"([^\"]+)\"', text)
        if m_disp:
            data["lcd_text"] = m_disp.group(1).strip()
        m_pc = re.search(r'PAGECOUNT=(\d+)', text)
        if m_pc:
            data["page_count"] = int(m_pc.group(1))
    except Exception:
        pass

    # 2. HTTP Web Interface over Port 80
    import urllib.request
    import html as html_parser
    urls = [
        f"http://{ip}/home/status.html",
        f"http://{ip}/general/information.html?kind=item",
        f"http://{ip}/general/status.html"
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                html = resp.read().decode("latin1", errors="replace")
                if "model" not in data:
                    m_model = re.search(r'<title>Brother ([^<]+)</title>', html, re.I) or re.search(r'<div id=\"modelName\"[^>]*>([^<]+)</div>', html, re.I)
                    if m_model:
                        data["model"] = "Brother " + m_model.group(1).strip()
                if "toner_pct" not in data:
                    m_toner = re.search(r'class=\"tonerremain\"\s+height=\"(\d+)\"', html)
                    if m_toner:
                        h = int(m_toner.group(1))
                        data["toner_pct"] = max(0, min(100, int((h / 56.0) * 100)))
                if "drum_pct" not in data:
                    m_drum = re.search(r'Life\s*Remaining\)</dt><dd>\(([0-9.]+)%\)</dd>', html, re.I)
                    if m_drum:
                        data["drum_pct"] = int(float(m_drum.group(1)))
                if "page_count" not in data:
                    m_pc2 = re.search(r'<dt>Page\s*Counter</dt><dd>(\d+)</dd>', html, re.I)
                    if m_pc2:
                        data["page_count"] = int(m_pc2.group(1))
                if "lcd_text" not in data:
                    m_stat = re.search(r'class=\"moni[^>]*\">([^<]+)</span>', html)
                    if m_stat:
                        data["lcd_text"] = m_stat.group(1).strip()
        except Exception:
            pass

    # Estimate drum life from page count if not directly exposed
    if data.get("page_count") and "drum_pct" not in data:
        data["drum_pct"] = max(0, min(100, int((1.0 - data["page_count"] / 15000.0) * 100)))

    return data


def get_printer_telemetry(ip: str, community: str = "public"):
    data = {
        "ip": ip,
        "online": False,
        "model": None,
        "status": "Offline",
        "toner_pct": None,
        "toner_raw": None,
        "toner_max": None,
        "drum_pct": None,
        "page_count": None,
        "lcd_text": ""
    }
    
    # Check responsiveness via SNMP first
    model = snmp_get(ip, OID_DEVICE_DESCR, community) or snmp_get(ip, OID_SYS_DESCR, community)
    if model is not None:
        data["online"] = True
        data["model"] = model
        data["status"] = "Online"
        
        # Toner
        t_level = snmp_get(ip, OID_TONER_LEVEL, community)
        t_max = snmp_get(ip, OID_TONER_MAX, community)
        data["toner_raw"] = t_level
        data["toner_max"] = t_max
        
        if isinstance(t_level, int) and isinstance(t_max, int) and t_max > 0:
            data["toner_pct"] = max(0, min(100, int((t_level / t_max) * 100)))
        elif isinstance(t_level, int) and t_level >= 0:
            data["toner_pct"] = max(0, min(100, t_level))
            
        # Drum
        d_life = snmp_get(ip, OID_DRUM_LIFE, community)
        if isinstance(d_life, int):
            data["drum_pct"] = max(0, min(100, d_life))
            
        # Total Pages
        p_count = snmp_get(ip, OID_PAGE_COUNT, community)
        if isinstance(p_count, int):
            data["page_count"] = p_count
            
        # LCD
        lcd1 = snmp_get(ip, OID_LCD_BUFFER_1, community) or ""
        lcd2 = snmp_get(ip, OID_LCD_BUFFER_2, community) or ""
        lcd_combined = f"{lcd1} {lcd2}".strip()
        data["lcd_text"] = lcd_combined if lcd_combined else "Ready"
        return data

    # Fallback to HTTP & PJL
    fallback = get_http_pjl_telemetry(ip)
    if fallback:
        data["online"] = True
        data["status"] = "Online"
        data["model"] = fallback.get("model") or "Brother Laser Multi-Function"
        data["lcd_text"] = fallback.get("lcd_text", "Ready")
        data["toner_pct"] = fallback.get("toner_pct", 100)
        data["drum_pct"] = fallback.get("drum_pct")
        data["page_count"] = fallback.get("page_count")

    return data


def make_gauge_bar(percent: int, length: int = 15) -> str:
    if percent is None:
        return "[Tidak Tersedia]"
    filled = int(length * (percent / 100))
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}] {percent}%"


def format_zenity_text(data: dict) -> str:
    if not data["online"]:
        return (
            f"❌ STATUS: PRINTER OFFLINE\n\n"
            f"Alamat IP : {data['ip']}\n"
            f"Pesan     : Tidak dapat terhubung ke printer via SNMP.\n\n"
            f"Petunjuk  : Pastikan printer dalam kondisi menyala dan terhubung\n"
            f"            ke jaringan Wi-Fi / LAN yang sama."
        )
    
    toner_bar = make_gauge_bar(data["toner_pct"])
    drum_bar = make_gauge_bar(data["drum_pct"])
    pages = f"{data['page_count']:,} lembar" if data["page_count"] is not None else "-"
    
    # Alerts
    alerts = []
    if data["toner_pct"] is not None and data["toner_pct"] <= 10:
        alerts.append("⚠️ PERINGATAN: Sisa TonerBox sangat rendah (<10%). Siapkan cartridge TN-B028 baru.")
    if data["drum_pct"] is not None and data["drum_pct"] <= 10:
        alerts.append("⚠️ PERINGATAN: Umur unit drum DR-B028 hampir habis (<10%).")
        
    alert_str = "\n" + "\n".join(alerts) + "\n" if alerts else ""
    
    return (
        f"🖨️  INFORMASI PERANGKAT & TELEMETRI STATUS\n"
        f"═════════════════════════════════════════════════════\n"
        f"Model Printer       : {data['model']}\n"
        f"Alamat IP           : {data['ip']}\n"
        f"Layar LCD Printer   : \"{data['lcd_text']}\"\n"
        f"Total Halaman Cetak : {pages}\n\n"
        f"KONSUMSI BAHAN HABIS PAKAI (SUPPLIES)\n"
        f"─────────────────────────────────────────────────────\n"
        f"TonerBox (TN-B028)  : {toner_bar}\n"
        f"Drum Unit (DR-B028) : {drum_bar}\n"
        f"{alert_str}"
        f"═════════════════════════════════════════════════════\n"
        f"Status Komunikasi: Terhubung Normal (SNMP v1/v2c)"
    )


B7640_MAC = ""
L2540_MAC = ""
DEFAULT_B7640_IP = "192.168.100.229"

PRINTER_CATALOG = {
    "Brother DCP-B7640DW": {
        "cups_name": "Brother-DCP-B7640DW",
        "mac": B7640_MAC,
        "default_ip": "192.168.100.229",
        "keywords": ("B7640", "7640"),
        "exclude": ("2540",),
    },
    "Brother DCP-L2540DW": {
        "cups_name": "Brother-DCP-L2540DW",
        "mac": L2540_MAC,
        "default_ip": "192.168.100.236",
        "keywords": ("L2540", "2540"),
        "exclude": ("7640",),
    },
}


def is_port_open(ip: str, port: int = 80, timeout: float = 0.5) -> bool:
    """Checks if a TCP port is open. Default port 80 (HTTP) to avoid locking RAW Port 9100."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def sync_printer_config(ip: str, printer_model: str = "Brother DCP-B7640DW", set_active: bool = True):
    """Saves discovered IP for printer_model to config.json and synchronizes CUPS queue."""
    cfg_file = os.path.expanduser("~/.local/share/winprint/config.json")
    spec = PRINTER_CATALOG.get(printer_model, PRINTER_CATALOG["Brother DCP-B7640DW"])
    try:
        cfg = {}
        if os.path.exists(cfg_file):
            with open(cfg_file, "r") as f:
                cfg = json.load(f)

        known = cfg.get("known_printers")
        if not isinstance(known, dict):
            known = {}
        changed = (known.get(printer_model) != ip)
        known[printer_model] = ip
        cfg["known_printers"] = known

        active_model = cfg.get("printer_model", "Brother DCP-B7640DW")
        if set_active or active_model == printer_model:
            if (
                cfg.get("printer_ip") != ip
                or cfg.get("printer_model") != printer_model
                or cfg.get("printer_name") != spec["cups_name"]
            ):
                changed = True
            cfg["printer_ip"] = ip
            cfg["printer_model"] = printer_model
            cfg["printer_name"] = spec["cups_name"]

        if changed:
            os.makedirs(os.path.dirname(cfg_file), exist_ok=True)
            tmp_file = cfg_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp_file, cfg_file)

            # Update CUPS destination IP if queue exists
            subprocess.run(
                ["lpadmin", "-p", spec["cups_name"], "-v", f"socket://{ip}", "-E"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0
            )
    except Exception:
        pass


def _probe_matches_spec(ip: str, spec: dict) -> bool:
    if not (is_port_open(ip, 80, timeout=0.6) or is_port_open(ip, 631, timeout=0.6) or is_port_open(ip, 9100, timeout=0.6)):
        return False
    t = get_printer_telemetry(ip)
    m = t.get("model") or ""
    return any(k in m for k in spec["keywords"]) and not any(ex in m for ex in spec["exclude"])


def resolve_printer_ip(
    printer_model: str = "Brother DCP-B7640DW",
    preferred_ip: str = None,
    set_active: bool = False,
) -> str:
    """
    Dynamically discovers and validates a Brother printer by model and MAC address.
    Auto-updates known_printers and active config in config.json on DHCP IP changes.
    """
    spec = PRINTER_CATALOG.get(printer_model, PRINTER_CATALOG["Brother DCP-B7640DW"])
    cfg_file = os.path.expanduser("~/.local/share/winprint/config.json")
    cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    known = cfg.get("known_printers") if isinstance(cfg.get("known_printers"), dict) else {}
    other_model_ips = {v for k, v in known.items() if k != printer_model and v}

    candidates_to_test = []
    for cand in (
        preferred_ip,
        known.get(printer_model),
        cfg.get("printer_ip") if cfg.get("printer_model", "Brother DCP-B7640DW") == printer_model else None,
        spec["default_ip"],
    ):
        if cand and cand not in candidates_to_test and cand not in other_model_ips:
            candidates_to_test.append(cand)

    for ip in candidates_to_test:
        if _probe_matches_spec(ip, spec):
            sync_printer_config(ip, printer_model=printer_model, set_active=set_active)
            return ip

    # 2. Check ARP / Neighbor table for configured MAC if available
    known_macs = cfg.get("known_macs") if isinstance(cfg.get("known_macs"), dict) else {}
    mac_target = (known_macs.get(printer_model) or spec.get("mac") or "").lower()
    if mac_target:
        try:
            neigh_out = subprocess.check_output(["ip", "neigh", "show"], stderr=subprocess.DEVNULL).decode("utf-8")
            for line in neigh_out.splitlines():
                if mac_target in line.lower():
                    cand_ip = line.split()[0]
                    if _probe_matches_spec(cand_ip, spec):
                        sync_printer_config(cand_ip, printer_model=printer_model, set_active=set_active)
                        return cand_ip
        except Exception:
            pass

    # 3. Fast multithreaded probe on common DHCP range (.210 - .245)
    subnet_prefix = "192.168.100."
    try:
        route_out = subprocess.check_output(["ip", "route"], stderr=subprocess.DEVNULL).decode("utf-8")
        for line in route_out.splitlines():
            if "default" in line:
                gw = line.split()[2]
                subnet_prefix = ".".join(gw.split(".")[:3]) + "."
                break
    except Exception:
        pass

    probe_ips = [f"{subnet_prefix}{i}" for i in range(210, 245) if f"{subnet_prefix}{i}" not in other_model_ips]
    alive_ips = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_ip = {executor.submit(is_port_open, ip, 80, 0.4): ip for ip in probe_ips}
        for future in concurrent.futures.as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                if future.result():
                    alive_ips.append(ip)
            except Exception:
                pass

    for cand_ip in alive_ips:
        if _probe_matches_spec(cand_ip, spec):
            sync_printer_config(cand_ip, printer_model=printer_model, set_active=set_active)
            return cand_ip

    return preferred_ip or known.get(printer_model) or spec["default_ip"]


def resolve_b7640_ip(preferred_ip: str = None) -> str:
    """Backward-compatible wrapper resolving Brother DCP-B7640DW IP."""
    return resolve_printer_ip("Brother DCP-B7640DW", preferred_ip=preferred_ip, set_active=False)


def main():
    parser = argparse.ArgumentParser(description="Brother Printer SNMP Telemetry Monitor")
    parser.add_argument("ip", help="Printer IP address or hostname")
    parser.add_argument("--community", default="public", help="SNMP community string (default: public)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--zenity", action="store_true", help="Output formatted for Zenity dialog")
    args = parser.parse_args()
    
    telemetry = get_printer_telemetry(args.ip, args.community)
    
    if args.json:
        print(json.dumps(telemetry, indent=2))
    elif args.zenity:
        print(format_zenity_text(telemetry))
    else:
        print(f"Model : {telemetry['model']}")
        print(f"Status: {telemetry['status']}")
        print(f"LCD   : {telemetry['lcd_text']}")
        print(f"Toner : {telemetry['toner_pct']}%")
        print(f"Drum  : {telemetry['drum_pct']}%")
        print(f"Pages : {telemetry['page_count']}")


if __name__ == "__main__":
    main()
