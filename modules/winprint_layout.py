#!/usr/bin/env python3
"""
winprint_layout.py - PPD-Sourced Media Geometry & WYSIWYG Layout Engine
Single source of truth for paper dimensions, ImageableArea margins,
proportional aspect-ratio scaling, and 3x2 registration calibration sheets.
"""

import os
import re
import subprocess
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple
import cairo

PT_PER_MM = 72.0 / 25.4  # ~2.83464567 pt/mm

MEDIA_ALIASES = {
    "F4": ["F4", "215x330mm", "FanFoldGermanLegal", "Folio"],
    "Folio": ["FanFoldGermanLegal", "Folio", "8.5x13", "F4"],
    "8.5x13": ["8.5x13", "FanFoldGermanLegal", "Folio"],
    "FanFoldGermanLegal": ["FanFoldGermanLegal", "Folio", "8.5x13"],
    "A4": ["A4"],
    "Letter": ["Letter"],
    "Legal": ["Legal"],
    "A5": ["A5"],
    "B5": ["B5"],
    "Executive": ["Executive"],
}


@dataclass(frozen=True)
class MediaGeometry:
    media_name: str
    ppd_key: str
    orientation: str
    width_pt: float
    height_pt: float
    imageable_llx: float
    imageable_lly: float
    imageable_urx: float
    imageable_ury: float

    @property
    def printable_width_pt(self) -> float:
        return max(0.0, self.imageable_urx - self.imageable_llx)

    @property
    def printable_height_pt(self) -> float:
        return max(0.0, self.imageable_ury - self.imageable_lly)

    @property
    def margin_left_pt(self) -> float:
        return self.imageable_llx

    @property
    def margin_bottom_pt(self) -> float:
        return self.imageable_lly

    @property
    def margin_right_pt(self) -> float:
        return max(0.0, self.width_pt - self.imageable_urx)

    @property
    def margin_top_pt(self) -> float:
        return max(0.0, self.height_pt - self.imageable_ury)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["printable_width_pt"] = round(self.printable_width_pt, 2)
        d["printable_height_pt"] = round(self.printable_height_pt, 2)
        return d


@dataclass(frozen=True)
class LayoutTransform:
    scale: float
    tx_pt: float
    ty_pt: float
    rendered_width_pt: float
    rendered_height_pt: float
    is_back_side: bool
    clips_printable_area: bool


def parse_ppd_geometries(ppd_path: str) -> Dict[str, Tuple[Tuple[float, float], Tuple[float, float, float, float]]]:
    """
    Parses *PaperDimension and *ImageableArea from a CUPS/Windows PPD file.
    Returns mapping: key -> ((w_pt, h_pt), (llx, lly, urx, ury)).
    """
    if not os.path.isfile(ppd_path):
        raise FileNotFoundError(f"PPD file not found: {ppd_path}")

    dimensions: Dict[str, Tuple[float, float]] = {}
    imageables: Dict[str, Tuple[float, float, float, float]] = {}

    dim_re = re.compile(r'^\*PaperDimension\s+([^\s/:]+)(?:/[^:]*)?:\s*"\s*([\d.]+)\s+([\d.]+)\s*"')
    img_re = re.compile(r'^\*ImageableArea\s+([^\s/:]+)(?:/[^:]*)?:\s*"\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*"')

    with open(ppd_path, "r", encoding="latin1") as f:
        for line in f:
            line = line.strip()
            m_dim = dim_re.match(line)
            if m_dim:
                key = m_dim.group(1)
                dimensions[key] = (float(m_dim.group(2)), float(m_dim.group(3)))
                continue
            m_img = img_re.match(line)
            if m_img:
                key = m_img.group(1)
                imageables[key] = (
                    float(m_img.group(2)),
                    float(m_img.group(3)),
                    float(m_img.group(4)),
                    float(m_img.group(5)),
                )

    result = {}
    for key, dim in dimensions.items():
        if key in imageables:
            result[key] = (dim, imageables[key])
    return result


def get_media_geometry(ppd_path: str, media_name: str, orientation: str = "portrait") -> MediaGeometry:
    """
    Resolves media_name against PPD PaperDimension and ImageableArea,
    validating bounds and applying portrait/landscape orientation swap.
    """
    geoms = parse_ppd_geometries(ppd_path)
    candidates = MEDIA_ALIASES.get(media_name, [media_name])
    matched_key = next((c for c in candidates if c in geoms), None)
    if not matched_key:
        raise ValueError(f"Media '{media_name}' not found in PPD '{ppd_path}'. Available: {list(geoms.keys())}")

    (w_pt, h_pt), (llx, lly, urx, ury) = geoms[matched_key]
    if not (0 <= llx < urx <= w_pt and 0 <= lly < ury <= h_pt):
        raise ValueError(f"Invalid PPD geometry for {matched_key}: dim=({w_pt},{h_pt}), img=({llx},{lly},{urx},{ury})")

    orient = orientation.lower()
    if orient == "landscape":
        # Rotate 90 degrees CCW: (w, h) -> (h, w), margins rotate accordingly
        w_pt, h_pt = h_pt, w_pt
        new_llx = lly
        new_lly = w_pt - urx if False else (geoms[matched_key][0][0] - urx)
        new_urx = ury
        new_ury = geoms[matched_key][0][0] - llx
        llx, lly, urx, ury = new_llx, new_lly, new_urx, new_ury

    return MediaGeometry(
        media_name=media_name,
        ppd_key=matched_key,
        orientation=orient,
        width_pt=w_pt,
        height_pt=h_pt,
        imageable_llx=llx,
        imageable_lly=lly,
        imageable_urx=urx,
        imageable_ury=ury,
    )


def compute_layout_transform(
    doc_w_pt: float,
    doc_h_pt: float,
    geometry: MediaGeometry,
    fit_to_printable: bool = True,
    manual_scale: float = 1.0,
    is_back_side: bool = False,
    offset_x_pt: float = 0.0,
    offset_y_pt: float = 0.0,
    binding_gutter_pt: float = 0.0,
) -> LayoutTransform:
    """
    Computes proportional scaling and centered translation inside ImageableArea.
    Applies calibration offsets on back pages and symmetric binding gutter shifts
    (+gutter on front right-shift, -gutter on back left-shift for long-edge binding).
    """
    if doc_w_pt <= 0 or doc_h_pt <= 0:
        raise ValueError("Document dimensions must be positive.")

    if fit_to_printable:
        scale_x = geometry.printable_width_pt / doc_w_pt
        scale_y = geometry.printable_height_pt / doc_h_pt
        scale = min(scale_x, scale_y) * manual_scale
    else:
        scale = min(geometry.width_pt / doc_w_pt, geometry.height_pt / doc_h_pt) * manual_scale

    rendered_w = doc_w_pt * scale
    rendered_h = doc_h_pt * scale

    if fit_to_printable:
        cx_target = geometry.imageable_llx + (geometry.printable_width_pt / 2.0)
        cy_target = geometry.imageable_lly + (geometry.printable_height_pt / 2.0)
    else:
        # Preserve exact 1:1 sheet origin when not fitting to ImageableArea
        cx_target = geometry.width_pt / 2.0
        cy_target = geometry.height_pt / 2.0

    tx = cx_target - (rendered_w / 2.0)
    ty = cy_target - (rendered_h / 2.0)

    if abs(binding_gutter_pt) > 1e-4:
        tx += (-binding_gutter_pt if is_back_side else binding_gutter_pt)

    if is_back_side:
        tx += offset_x_pt
        ty += offset_y_pt

    clips = (
        tx < geometry.imageable_llx - 0.1
        or ty < geometry.imageable_lly - 0.1
        or (tx + rendered_w) > geometry.imageable_urx + 0.1
        or (ty + rendered_h) > geometry.imageable_ury + 0.1
    )

    return LayoutTransform(
        scale=round(scale, 6),
        tx_pt=round(tx, 3),
        ty_pt=round(ty, 3),
        rendered_width_pt=round(rendered_w, 3),
        rendered_height_pt=round(rendered_h, 3),
        is_back_side=is_back_side,
        clips_printable_area=clips,
    )


def generate_calibration_pdf(output_pdf: str, geometry: MediaGeometry) -> str:
    """
    Generates a 2-page 3x2 Registration Calibration Sheet PDF matching exact MediaGeometry.
    Targets placed at 25mm from left/right and top/center/bottom to distinguish
    constant translation, feed/scale distortion, and skew.
    """
    w_pt = geometry.width_pt
    h_pt = geometry.height_pt

    surface = cairo.PDFSurface(output_pdf, w_pt, h_pt)
    ctx = cairo.Context(surface)

    margin_mm = 25.0
    x_left = margin_mm * PT_PER_MM
    x_right = w_pt - (margin_mm * PT_PER_MM)
    y_top = margin_mm * PT_PER_MM
    y_mid = h_pt / 2.0
    y_bot = h_pt - (margin_mm * PT_PER_MM)

    targets = [
        ("TOP-L", x_left, y_top), ("TOP-R", x_right, y_top),
        ("MID-L", x_left, y_mid), ("MID-R", x_right, y_mid),
        ("BOT-L", x_left, y_bot), ("BOT-R", x_right, y_bot),
    ]

    for page_idx, side_label in enumerate(["FRONT (HALAMAN 1)", "BACK (HALAMAN 2 - TERAWANG)"]):
        # Draw printable area bounding box (dashed)
        ctx.save()
        ctx.set_source_rgb(0.4, 0.4, 0.4)
        ctx.set_line_width(0.5)
        ctx.set_dash([4.0, 4.0])
        # Note: Cairo Y=0 is top-left, PPD lly is bottom-left
        p_x = geometry.imageable_llx
        p_y = h_pt - geometry.imageable_ury
        ctx.rectangle(p_x, p_y, geometry.printable_width_pt, geometry.printable_height_pt)
        ctx.stroke()
        ctx.restore()

        # Header text (centered using text_extents)
        ctx.save()
        ctx.set_source_rgb(0, 0, 0)
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(11)
        header_txt = f"WINPRINT 3x2 CALIBRATION - {geometry.media_name} - {side_label}"
        ext = ctx.text_extents(header_txt)
        ctx.move_to((w_pt - ext.width) / 2.0, 38)
        ctx.show_text(header_txt)
        ctx.new_path()
        ctx.restore()

        # Draw faint horizontal alignment guide lines between L and R targets
        ctx.save()
        ctx.set_source_rgb(0.75, 0.75, 0.75)
        ctx.set_line_width(0.4)
        for _, gy in [("TOP", y_top), ("MID", y_mid), ("BOT", y_bot)]:
            ctx.new_path()
            ctx.move_to(x_left, gy)
            ctx.line_to(x_right, gy)
            ctx.stroke()
        ctx.restore()

        # Draw 6 crosshairs: Front gets circle + +-15mm vertical ruler, Back gets sharp '+' target
        for label, tx, ty in targets:
            ctx.save()
            ctx.set_source_rgb(0, 0, 0)
            if page_idx == 0:
                ctx.set_line_width(0.8)
                ctx.new_path()
                ctx.arc(tx, ty, 7.0, 0, 6.28318)
                ctx.stroke()
                ctx.new_path()
                ctx.move_to(tx - 12, ty)
                ctx.line_to(tx + 12, ty)
                ctx.move_to(tx, ty - 12)
                ctx.line_to(tx, ty + 12)
                ctx.stroke()
                # Millimeter ruler ticks along vertical axis (-15mm to +15mm)
                ctx.set_line_width(0.45)
                ctx.new_path()
                for mm in range(-15, 16):
                    if mm == 0:
                        continue
                    tick_y = ty + (mm * PT_PER_MM)
                    tick_w = 8.0 if mm % 10 == 0 else (5.0 if mm % 5 == 0 else 2.5)
                    ctx.move_to(tx - tick_w, tick_y)
                    ctx.line_to(tx + tick_w, tick_y)
                ctx.stroke()
            else:
                # Back side: bold thick '+' crosshair for crisp contrast when held to light
                ctx.set_line_width(1.4)
                ctx.new_path()
                ctx.move_to(tx - 16, ty)
                ctx.line_to(tx + 16, ty)
                ctx.move_to(tx, ty - 16)
                ctx.line_to(tx, ty + 16)
                ctx.stroke()
            ctx.set_font_size(7)
            ctx.move_to(tx + 11, ty - 8)
            ctx.show_text(label)
            ctx.new_path()
            ctx.restore()

        surface.show_page()

    surface.finish()
    return output_pdf


def get_pdf_page_size(pdf_path: str) -> Tuple[float, float]:
    """Reads first page size (width_pt, height_pt) using pdfinfo."""
    out = subprocess.check_output(["pdfinfo", pdf_path], text=True)
    for line in out.splitlines():
        if line.startswith("Page size:"):
            m = re.search(r'([\d.]+)\s*x\s*([\d.]+)\s*pts', line)
            if m:
                return float(m.group(1)), float(m.group(2))
    return 595.28, 841.89


CANONICAL_MEDIA_SIZES_PT = (
    ("F4", 612.0, 936.0),
    ("F4", 609.45, 935.43),
    ("A4", 595.28, 841.89),
    ("Legal", 612.0, 1008.0),
    ("Letter", 612.0, 792.0),
    ("A5", 419.53, 595.28),
)


def detect_pdf_media(width_pt: float, height_pt: float, tolerance_pt: float = 12.0) -> Optional[str]:
    """Identifies standard paper media name from PDF dimensions regardless of orientation."""
    if width_pt <= 0 or height_pt <= 0:
        return None
    short_pt, long_pt = min(width_pt, height_pt), max(width_pt, height_pt)
    best_media = None
    best_delta = float("inf")
    for media_name, ref_w, ref_h in CANONICAL_MEDIA_SIZES_PT:
        dw = abs(short_pt - ref_w)
        dh = abs(long_pt - ref_h)
        if dw <= tolerance_pt and dh <= tolerance_pt:
            score = dw + dh
            if score < best_delta:
                best_delta = score
                best_media = media_name
    return best_media


def normalize_pdf(
    input_pdf: str,
    output_pdf: str,
    geometry: MediaGeometry,
    fit_to_printable: bool = True,
    manual_scale: float = 1.0,
    is_duplex: bool = False,
    offset_x_pt: float = 0.0,
    offset_y_pt: float = 0.0,
    rotate_landscape_to_portrait: bool = False,
    binding_gutter_pt: float = 0.0,
) -> Dict[str, Any]:
    """
    Normalizes an arbitrary PDF onto exact target MediaGeometry dimensions,
    fitting proportionally and applying back-side registration + binding gutter offsets.
    When rotate_landscape_to_portrait=True on landscape media, outputs portrait-fed
    physical pages rotated 90 deg CCW so portrait-fed printers keep native paper codes.
    """
    doc_w, doc_h = get_pdf_page_size(input_pdf)
    tr_front = compute_layout_transform(
        doc_w, doc_h, geometry, fit_to_printable=fit_to_printable,
        manual_scale=manual_scale, is_back_side=False,
        binding_gutter_pt=binding_gutter_pt,
    )
    tr_back = compute_layout_transform(
        doc_w, doc_h, geometry, fit_to_printable=fit_to_printable,
        manual_scale=manual_scale, is_back_side=is_duplex,
        offset_x_pt=offset_x_pt, offset_y_pt=offset_y_pt,
        binding_gutter_pt=binding_gutter_pt if is_duplex else 0.0,
    )

    is_rot = rotate_landscape_to_portrait and geometry.orientation == "landscape"
    out_w = geometry.height_pt if is_rot else geometry.width_pt
    out_h = geometry.width_pt if is_rot else geometry.height_pt
    rot_prefix = f"{out_w:.3f} 0 translate 90 rotate " if is_rot else ""

    needs_back_diff = is_duplex and (
        abs(offset_x_pt) > 1e-4 or abs(offset_y_pt) > 1e-4 or abs(binding_gutter_pt) > 1e-4
    )
    if needs_back_diff:
        ps_hook = (
            f"<< /BeginPage {{ /p exch def {rot_prefix}"
            f"p 2 mod 1 eq "
            f"{{ {tr_back.tx_pt:.3f} {tr_back.ty_pt:.3f} translate {tr_back.scale:.6f} {tr_back.scale:.6f} scale }} "
            f"{{ {tr_front.tx_pt:.3f} {tr_front.ty_pt:.3f} translate {tr_front.scale:.6f} {tr_front.scale:.6f} scale }} ifelse "
            f"}} >> setpagedevice"
        )
    else:
        ps_hook = (
            f"<< /BeginPage {{ pop {rot_prefix}"
            f"{tr_front.tx_pt:.3f} {tr_front.ty_pt:.3f} translate {tr_front.scale:.6f} {tr_front.scale:.6f} scale "
            f"}} >> setpagedevice"
        )

    cmd = [
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-sDEVICE=pdfwrite",
        f"-sOutputFile={output_pdf}",
        f"-dDEVICEWIDTHPOINTS={out_w:.2f}",
        f"-dDEVICEHEIGHTPOINTS={out_h:.2f}",
        "-dFIXEDMEDIA",
        "-c", ps_hook,
        "-f", input_pdf,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return {
        "source_size_pt": (doc_w, doc_h),
        "front_transform": asdict(tr_front),
        "back_transform": asdict(tr_back),
    }
