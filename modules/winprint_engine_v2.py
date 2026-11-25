#!/usr/bin/env python3
"""
winprint_engine_v2.py - Enterprise Print Engine (v1.0.1 Calibrated Baseline)
Supports:
- Primary Brother Native PCL Raster backend (`gs -sDEVICE=bit` + `rawtobr3`), which
  uses Brother proprietary PCL paper code 1038 for Folio (5100x7800 px) and avoids the
  50.8 mm PCL-XL Folio duplex origin fallback bug.
- Pure PCL-XL fallback (`gs -sDEVICE=pxlmono -dPDFFitPage=false`) when `rawtobr3` is absent.
- Per-profile calibration lookup (`calibration_profiles.json`: model + media + duplex).
- Independent `@PJL JOB` / `@PJL EOJ` envelopes per software-collated copy.
- Reproducibility SHA-256 manifest.
"""

import hashlib
import json
import os
import subprocess
import tempfile
from typing import Dict, Any, List, Optional, Tuple
from winprint_layout import MediaGeometry, PT_PER_MM, normalize_pdf

BUNDLED_RAWTOBR3_B7640 = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "drivers", "b7640dw", "rawtobr3")
)
SYSTEM_RAWTOBR3_B7640 = "/opt/brother/Printers/DCPB7640DW/lpd/x86_64/rawtobr3"
RAWTOBR3_PATH = SYSTEM_RAWTOBR3_B7640 if os.path.isfile(SYSTEM_RAWTOBR3_B7640) else BUNDLED_RAWTOBR3_B7640
DEFAULT_CALIBRATION_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "calibration_profiles.json")
)

BROTHER_DRIVER_SPECS = {
    "Brother DCP-B7640DW": {
        "rawtobr3": SYSTEM_RAWTOBR3_B7640,
        "bundled_rawtobr3": BUNDLED_RAWTOBR3_B7640,
        "rc_section": "DCPB7640DW",
        "flags": "0000000000000500",
    },
    "Brother DCP-L2540DW": {
        "rawtobr3": "/opt/brother/Printers/DCPL2540DW/lpd/rawtobr3",
        "bundled_rawtobr3": "",
        "rc_section": "DCPL2540DW",
        "flags": "0000000000000000",
    },
}


def resolve_rawtobr3_path(printer_model: str = "Brother DCP-B7640DW") -> Optional[str]:
    """Returns usable rawtobr3 binary path (system install first, then bundled 64-bit binary)."""
    spec = BROTHER_DRIVER_SPECS.get(printer_model, BROTHER_DRIVER_SPECS["Brother DCP-B7640DW"])
    for cand in (spec.get("rawtobr3"), spec.get("bundled_rawtobr3")):
        if cand and os.path.isfile(cand):
            return cand
    return None

PJL_PAPER_MAP = {
    "A4": "A4",
    "F4": "FOLIO",
    "Folio": "FOLIO",
    "8.5x13": "FOLIO",
    "FanFoldGermanLegal": "FOLIO",
    "Legal": "LEGAL",
    "Letter": "LETTER",
    "A5": "A5",
    "Executive": "EXECUTIVE",
    "B5": "B5",
}

# Exact Brother lpdfilter pixel table at 600 DPI
BROTHER_PCL_PAPERS = {
    "A4": ("A4", 4961, 7016),
    "F4": ("FOLIO", 5100, 7800),
    "Folio": ("FOLIO", 5100, 7800),
    "8.5x13": ("FOLIO", 5100, 7800),
    "FanFoldGermanLegal": ("FOLIO", 5100, 7800),
    "Legal": ("Legal", 5100, 8400),
    "Letter": ("Letter", 5100, 6600),
    "A5": ("A5", 3505, 4960),
    "Executive": ("Exective", 4350, 6300),
    "B5": ("B5", 4157, 5900),
}

BROTHER_PAPER_SOURCES = {
    "auto": "AutoSelect",
    "autoselect": "AutoSelect",
    "tray1": "Tray1",
    "manual": "MpTray",
    "mptray": "MpTray",
    "bypass": "MpTray",
}

BROTHER_MEDIA_TYPES = {
    "plain": "PlainPaper",
    "regular": "PlainPaper",
    "thick": "ThickPaper",
    "thicker": "Thicker Paper",
    "recycled": "Recycled",
    "envelope": "Envelopes",
    "envelopes": "Envelopes",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_gs_version() -> str:
    try:
        return subprocess.check_output(["gs", "--version"], text=True).strip()
    except Exception:
        return "unknown"


def get_pdf_page_count(pdf_path: str) -> int:
    try:
        res = subprocess.run(["pdfinfo", pdf_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        for line in res.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return 1


def normalize_duplex_mode(duplex: str) -> str:
    d = str(duplex).strip().upper()
    if d in ("LONG", "LONG_EDGE", "LONGEDGE", "DUPLEXNOTUMBLE"):
        return "LONG_EDGE"
    if d in ("SHORT", "SHORT_EDGE", "SHORTEDGE", "DUPLEXTUMBLE"):
        return "SHORT_EDGE"
    return "SIMPLEX"


def get_calibration_mm(
    media: str,
    duplex_mode: str,
    printer_model: str = "Brother DCP-B7640DW",
    profile_path: str = DEFAULT_CALIBRATION_PATH,
) -> Tuple[float, float]:
    """Reads calibrated (offset_x_mm, offset_y_mm) from JSON profile."""
    if duplex_mode == "SIMPLEX" or not os.path.isfile(profile_path):
        return 0.0, 0.0
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        model_prof = profiles.get(printer_model, {})
        media_prof = model_prof.get(media)
        if not media_prof and media in ("F4", "Folio"):
            media_prof = model_prof.get("Folio" if media == "F4" else "F4", {})
        entry = (media_prof or {}).get(duplex_mode, {})
        return float(entry.get("offset_x_mm", 0.0)), float(entry.get("offset_y_mm", 0.0))
    except Exception:
        return 0.0, 0.0


def save_calibration_mm(
    media: str,
    duplex_mode: str,
    offset_x_mm: float,
    offset_y_mm: float,
    printer_model: str = "Brother DCP-B7640DW",
    notes: str = "Saved from WinPrint Studio UI",
    profile_path: str = DEFAULT_CALIBRATION_PATH,
) -> None:
    """Persists (offset_x_mm, offset_y_mm) atomically to calibration_profiles.json."""
    if duplex_mode == "SIMPLEX":
        return
    profiles = {}
    if os.path.isfile(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                profiles = json.load(f)
        except Exception:
            profiles = {}

    model_prof = profiles.setdefault(printer_model, {})
    target_keys = ["F4", "Folio"] if media in ("F4", "Folio") else [media]
    entry = {
        "offset_x_mm": round(float(offset_x_mm), 2),
        "offset_y_mm": round(float(offset_y_mm), 2),
        "notes": notes,
    }
    for m_key in target_keys:
        media_prof = model_prof.setdefault(m_key, {})
        media_prof[duplex_mode] = dict(entry)

    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    tmp_path = profile_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)
    os.replace(tmp_path, profile_path)


def load_calibration_offset(
    media: str,
    duplex_mode: str,
    printer_model: str = "Brother DCP-B7640DW",
    profile_path: str = DEFAULT_CALIBRATION_PATH,
) -> Tuple[float, float]:
    """Loads calibrated (offset_x_pt, offset_y_pt) from JSON profile for back pages."""
    off_x_mm, off_y_mm = get_calibration_mm(
        media=media,
        duplex_mode=duplex_mode,
        printer_model=printer_model,
        profile_path=profile_path,
    )
    return round(off_x_mm * PT_PER_MM, 4), round(off_y_mm * PT_PER_MM, 4)


def build_job_pjl_header(
    job_name: str,
    media: str,
    duplex_mode: str,
    resolution: int = 600,
    toner_save: bool = False,
    experimental_pjl: bool = False,
    copies: int = 1,
    paper_source: str = "auto",
    media_type: str = "plain",
    quiet_mode: bool = False,
    density: int = 0,
) -> bytes:
    """
    Constructs PJL job header with @PJL JOB boundary first (since JOB resets PJL env),
    followed by @PJL SET commands.
    """
    pjl_paper = PJL_PAPER_MAP.get(media, "A4")
    economode = "ON" if toner_save else "OFF"
    rc_source = BROTHER_PAPER_SOURCES.get(str(paper_source).lower(), "AutoSelect")
    pjl_source = {"AutoSelect": "AUTO", "Tray1": "TRAY1", "MpTray": "MPTRAY"}.get(rc_source, "AUTO")
    rc_media = BROTHER_MEDIA_TYPES.get(str(media_type).lower(), "PlainPaper")
    pjl_media = {"PlainPaper": "REGULAR", "ThickPaper": "THICK", "Recycled": "RECYCLED", "Envelopes": "ENVELOPES"}.get(rc_media, "REGULAR")
    hw_copies = max(1, int(copies))

    lines = [
        "\x1b%-12345X@PJL",
        f'@PJL JOB NAME = "{job_name}"',
        f"@PJL SET RESOLUTION = {resolution}",
        f"@PJL SET PAPER = {pjl_paper}",
        f"@PJL SET SOURCETRAY = {pjl_source}",
        f"@PJL SET MEDIATYPE = {pjl_media}",
        f"@PJL SET ECONOMODE = {economode}",
        f"@PJL SET COPIES = {hw_copies}",
        "@PJL SET QTY = 1",
    ]
    if quiet_mode:
        lines.append("@PJL SET PAPERFEEDSPEED=HALF")
    if density:
        lines.append(f"@PJL SET DENSITY = {max(-2, min(2, int(density)))}")

    if duplex_mode == "LONG_EDGE":
        lines.append("@PJL SET DUPLEX = ON")
        lines.append("@PJL SET BINDING = LONGEDGE")
    elif duplex_mode == "SHORT_EDGE":
        lines.append("@PJL SET DUPLEX = ON")
        lines.append("@PJL SET BINDING = SHORTEDGE")
    else:
        lines.append("@PJL SET DUPLEX = OFF")

    if experimental_pjl and duplex_mode != "SIMPLEX":
        lines.append("@PJL SET DXBACKSIDEFIRSTSENDMODE = ON")
        lines.append("@PJL SET PCLCONPULSORYFFIGNOREMODE = ON")

    lines.append("@PJL ENTER LANGUAGE = PCLXL")
    return ("\n".join(lines) + "\n").encode("latin1")


def build_job_pjl_trailer(job_name: str) -> bytes:
    return f'\x1b%-12345X@PJL EOJ NAME = "{job_name}"\n\x1b%-12345X'.encode("latin1")


def strip_gs_pjl_wrapper(raw_pclxl: bytes) -> bytes:
    """Strips Ghostscript's outer PJL wrapper and UEL so only pure PCL-XL stream remains."""
    uel = b"\x1b%-12345X"
    marker = b") HP-PCL XL;"
    idx = raw_pclxl.find(marker)
    if idx != -1:
        raw_pclxl = raw_pclxl[idx:]
    else:
        pjl_lang = b"@PJL ENTER LANGUAGE = PCLXL\n"
        idx_lang = raw_pclxl.find(pjl_lang)
        if idx_lang != -1:
            raw_pclxl = raw_pclxl[idx_lang + len(pjl_lang):]
    if raw_pclxl.endswith(uel):
        raw_pclxl = raw_pclxl[:-len(uel)]
    return raw_pclxl


def render_pdf_to_pure_pclxl(
    normalized_pdf: str,
    geometry: MediaGeometry,
    duplex_mode: str,
    resolution: int = 600,
) -> bytes:
    """
    Renders a normalized PDF 1:1 to pure PCL-XL via Ghostscript pxlmono
    with -dPDFFitPage=false (no PostScript BeginPage transforms).
    """
    w_pt = int(round(geometry.width_pt))
    h_pt = int(round(geometry.height_pt))

    cmd = [
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-sDEVICE=pxlmono",
        f"-r{resolution}",
        f"-dDEVICEWIDTHPOINTS={w_pt}",
        f"-dDEVICEHEIGHTPOINTS={h_pt}",
        "-dPDFFitPage=false",
    ]

    if duplex_mode == "LONG_EDGE":
        cmd.extend(["-dDuplex=true", "-dTumble=false"])
    elif duplex_mode == "SHORT_EDGE":
        cmd.extend(["-dDuplex=true", "-dTumble=true"])
    else:
        cmd.extend(["-dDuplex=false"])

    cmd.extend(["-sOutputFile=-", "-f", normalized_pdf])

    if duplex_mode != "SIMPLEX" and get_pdf_page_count(normalized_pdf) % 2 != 0:
        cmd.extend(["-c", "showpage"])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return strip_gs_pjl_wrapper(proc.stdout)


def render_pdf_to_brother_pcl(
    normalized_pdf: str,
    media: str,
    duplex_mode: str,
    orientation: str = "portrait",
    resolution: int = 600,
    toner_save: bool = False,
    printer_model: str = "Brother DCP-B7640DW",
    copies: int = 1,
    paper_source: str = "auto",
    media_type: str = "plain",
    quiet_mode: bool = False,
    density: int = 0,
) -> Tuple[bytes, bytes]:
    """
    Renders normalized PDF via Brother official `rawtobr3` PCL raster filter.
    Returns (pjl_settings_and_pcl_body, pcl_settings_header_preview).
    """
    spec = BROTHER_DRIVER_SPECS.get(printer_model, BROTHER_DRIVER_SPECS["Brother DCP-B7640DW"])
    rawtobr3_bin = resolve_rawtobr3_path(printer_model)
    if not rawtobr3_bin:
        raise FileNotFoundError(f"rawtobr3 filter binary not found for {printer_model}")
    br_paper, px_w, px_h = BROTHER_PCL_PAPERS.get(media, ("A4", 4961, 7016))
    rc_source = BROTHER_PAPER_SOURCES.get(str(paper_source).lower(), "AutoSelect")
    rc_media = BROTHER_MEDIA_TYPES.get(str(media_type).lower(), "PlainPaper")
    hw_copies = max(1, int(copies))

    # Scale pixel dimensions proportionally if resolution != 600
    scale_r = resolution / 600.0
    gs_w = int(round(px_w * scale_r))
    gs_h = int(round(px_h * scale_r))

    dup_on = "ON" if duplex_mode != "SIMPLEX" else "OFF"
    dup_type = "Short" if duplex_mode == "SHORT_EDGE" else "Long"
    toner_str = "ON" if toner_save else "OFF"

    fd_rc, rc_path = tempfile.mkstemp(suffix=".rc")
    os.close(fd_rc)
    try:
        with open(rc_path, "w", encoding="utf-8") as f:
            f.write(
                f"[{spec['rc_section']}]\n"
                f"Language=LANG_USA\n"
                f"Resolution={resolution}\n"
                f"PaperSource={rc_source}\n"
                f"Duplex={dup_on}\n"
                f"DuplexType={dup_type}\n"
                f"PaperType={br_paper}\n"
                f"Media={rc_media}\n"
                f"Copies={hw_copies}\n"
                f"Sleep=PrinterDefault\n"
                f"TonerSaveMode={toner_str}\n"
            )

        gs_cmd = [
            "gs", "-q", "-dNOPROMPT", "-dNOPAUSE", "-dBATCH", "-dSAFER",
            f"-r{resolution}",
            f"-g{gs_w}x{gs_h}",
            "-sDEVICE=bit",
            "-sOutputFile=-",
            "-f", normalized_pdf,
        ]
        if duplex_mode != "SIMPLEX" and get_pdf_page_count(normalized_pdf) % 2 != 0:
            gs_cmd.extend(["-c", "showpage"])

        gs_bytes = subprocess.check_output(gs_cmd)

        raw_out = subprocess.check_output(
            [rawtobr3_bin, "-rc", rc_path, "-flags", spec["flags"], "-offset", "0", "-ps", f"{px_w}x{px_h}"],
            input=gs_bytes,
        )
    finally:
        if os.path.exists(rc_path):
            os.remove(rc_path)

    # Strip outer UEL / @PJL EOJ so caller can wrap each copy in clean @PJL JOB ... @PJL EOJ
    uel = b"\x1b%-12345X"
    start_pjl = raw_out.find(b"@PJL SET ")
    if start_pjl == -1:
        start_pjl = raw_out.find(b"@PJL\n")
    eoj_idx = raw_out.rfind(uel + b"@PJL EOJ")
    if eoj_idx == -1:
        eoj_idx = len(raw_out)
    inner_stream = raw_out[start_pjl:eoj_idx] if start_pjl != -1 else raw_out[:eoj_idx]

    extra_pjl = []
    if quiet_mode:
        extra_pjl.append("@PJL SET PAPERFEEDSPEED=HALF")
    if density:
        extra_pjl.append(f"@PJL SET DENSITY = {max(-2, min(2, int(density)))}")
    if extra_pjl:
        marker = b"@PJL ENTER LANGUAGE = PCL\n"
        m_idx = inner_stream.find(marker)
        if m_idx != -1:
            inject = ("\n".join(extra_pjl) + "\n").encode("latin1")
            inner_stream = inner_stream[:m_idx] + inject + inner_stream[m_idx:]

    enter_idx = inner_stream.find(b"@PJL ENTER LANGUAGE = PCL\n")
    pcl_header_line = inner_stream[enter_idx:enter_idx + 60] if enter_idx != -1 else inner_stream[:80]
    return inner_stream, pcl_header_line


def render_job(
    input_pdf: str,
    media: str,
    duplex: str,
    copies: int,
    geometry: MediaGeometry,
    experimental_pjl: bool = False,
    offset_x_pt: Optional[float] = None,
    offset_y_pt: Optional[float] = None,
    fit_to_printable: bool = False,
    manual_scale: float = 1.0,
    job_name: str = "WinPrint_Job",
    resolution: int = 600,
    toner_save: bool = False,
    backend: str = "auto",
    printer_model: str = "Brother DCP-B7640DW",
    paper_source: str = "auto",
    media_type: str = "plain",
    quiet_mode: bool = False,
    density: int = 0,
    binding_gutter_mm: float = 0.0,
    collate: bool = True,
) -> Dict[str, Any]:
    """
    Normalizes PDF onto MediaGeometry (applying calibrated back-side offsets and binding gutter),
    renders via Brother Native PCL (`rawtobr3`) or Pure PCL-XL (`pxlmono`),
    and selects hardware multi-copy (1-sheet or uncollated) vs collated `@PJL JOB`/`@PJL EOJ` envelopes.
    """
    if not os.path.isfile(input_pdf):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    copies = max(1, int(copies))
    duplex_mode = normalize_duplex_mode(duplex)
    is_duplex = duplex_mode != "SIMPLEX"

    spec = BROTHER_DRIVER_SPECS.get(printer_model, BROTHER_DRIVER_SPECS["Brother DCP-B7640DW"])
    chosen_backend = backend
    if chosen_backend == "auto":
        chosen_backend = "brother_pcl" if resolve_rawtobr3_path(printer_model) else "pclxl"

    prof_x_pt, prof_y_pt = load_calibration_offset(media, duplex_mode, printer_model=printer_model)
    eff_off_x = prof_x_pt if offset_x_pt is None else offset_x_pt
    eff_off_y = prof_y_pt if offset_y_pt is None else offset_y_pt
    gutter_pt = float(binding_gutter_mm or 0.0) * PT_PER_MM

    fd, norm_pdf = tempfile.mkstemp(suffix="_norm.pdf")
    os.close(fd)
    try:
        layout_info = normalize_pdf(
            input_pdf=input_pdf,
            output_pdf=norm_pdf,
            geometry=geometry,
            fit_to_printable=fit_to_printable,
            manual_scale=manual_scale,
            is_duplex=is_duplex,
            offset_x_pt=eff_off_x,
            offset_y_pt=eff_off_y,
            rotate_landscape_to_portrait=(chosen_backend == "brother_pcl"),
            binding_gutter_pt=gutter_pt,
        )
        norm_pdf_sha256 = sha256_file(norm_pdf)
        page_count = get_pdf_page_count(norm_pdf)

        # In PCL/PCL-XL, per-page Copy Count (\x1b&lNX) duplicates each page before the next;
        # on 2+ page duplex jobs it would duplicate front onto back. Therefore hardware Copies=N is safe
        # strictly for 1-page jobs (or uncollated simplex), while >=2-page or duplex jobs stream via @PJL JOB/EOJ.
        use_hw_copies = (copies > 1) and ((page_count == 1 and not is_duplex) or (not collate and not is_duplex))
        hw_copies = copies if use_hw_copies else 1
        stream_envelopes = 1 if use_hw_copies else copies
        copy_mode = "hardware_copies" if use_hw_copies else ("pjl_collated" if copies > 1 else "single")

        copies_payloads: List[bytes] = []
        if chosen_backend == "brother_pcl":
            inner_body, hdr_preview = render_pdf_to_brother_pcl(
                normalized_pdf=norm_pdf,
                media=media,
                duplex_mode=duplex_mode,
                orientation=geometry.orientation,
                resolution=resolution,
                toner_save=toner_save,
                printer_model=printer_model,
                copies=hw_copies,
                paper_source=paper_source,
                media_type=media_type,
                quiet_mode=quiet_mode,
                density=density,
            )
            pcl_header_str = repr(hdr_preview)
            for copy_idx in range(1, stream_envelopes + 1):
                copy_job_name = f"{job_name}_Set_{copy_idx}of{stream_envelopes}" if stream_envelopes > 1 else job_name
                chunk = (
                    f'\x1b%-12345X@PJL\n@PJL JOB NAME = "{copy_job_name}"\n'.encode("latin1")
                    + inner_body
                    + build_job_pjl_trailer(copy_job_name)
                )
                copies_payloads.append(chunk)
            body_sha = sha256_bytes(inner_body)
        else:
            pclxl_body = render_pdf_to_pure_pclxl(
                normalized_pdf=norm_pdf,
                geometry=geometry,
                duplex_mode=duplex_mode,
                resolution=resolution,
            )
            first_nl = pclxl_body.find(b"\n")
            pcl_header_str = pclxl_body[:first_nl].decode("latin1", "ignore") if first_nl != -1 else ""
            for copy_idx in range(1, stream_envelopes + 1):
                copy_job_name = f"{job_name}_Set_{copy_idx}of{stream_envelopes}" if stream_envelopes > 1 else job_name
                header = build_job_pjl_header(
                    job_name=copy_job_name,
                    media=media,
                    duplex_mode=duplex_mode,
                    resolution=resolution,
                    toner_save=toner_save,
                    experimental_pjl=experimental_pjl,
                    copies=hw_copies,
                    paper_source=paper_source,
                    media_type=media_type,
                    quiet_mode=quiet_mode,
                    density=density,
                )
                trailer = build_job_pjl_trailer(copy_job_name)
                copies_payloads.append(header + pclxl_body + trailer)
            body_sha = sha256_bytes(pclxl_body)
    finally:
        if os.path.exists(norm_pdf):
            os.remove(norm_pdf)

    final_bytes = b"".join(copies_payloads)

    manifest = {
        "backend": chosen_backend,
        "printer_model": printer_model,
        "gs_version": get_gs_version(),
        "input_pdf_sha256": sha256_file(input_pdf),
        "normalized_pdf_sha256": norm_pdf_sha256,
        "body_sha256": body_sha,
        "final_stream_sha256": sha256_bytes(final_bytes),
        "stream_header": pcl_header_str,
        "media": media,
        "geometry": geometry.to_dict(),
        "layout_info": layout_info,
        "duplex": duplex_mode,
        "copies": copies,
        "copy_mode": copy_mode,
        "paper_source": paper_source,
        "media_type": media_type,
        "quiet_mode": quiet_mode,
        "density": density,
        "binding_gutter_mm": binding_gutter_mm,
        "experimental_pjl": experimental_pjl,
        "offset_x_pt": eff_off_x,
        "offset_y_pt": eff_off_y,
        "resolution": resolution,
        "total_bytes": len(final_bytes),
    }

    return {"stream": final_bytes, "copies_payloads": copies_payloads, "manifest": manifest}
