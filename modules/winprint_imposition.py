#!/usr/bin/env python3
"""
winprint_imposition.py - Document Imposition Engine for WinPrint Studio
Handles:
1. Page range filtering (e.g. '1-3, 5, 8', odd only, even only, reverse)
2. N-Up layout (1-up, 2-up, 4-up) with optional border lines
3. Saddle-stitch Booklet pagination (Booklet Imposition for F4 / A4 folding)
"""

import sys
import os
import math
import subprocess
import tempfile
import shutil


def parse_page_range(range_str: str, total_pages: int) -> list:
    """Parses range string like '1-3, 5, 7-9', 'odd', 'even' into a 1-based page list."""
    range_str = range_str.strip().lower()
    if not range_str or range_str in ("all", "semua"):
        return list(range(1, total_pages + 1))
    elif range_str in ("odd", "ganjil"):
        return [p for p in range(1, total_pages + 1) if p % 2 != 0]
    elif range_str in ("even", "genap"):
        return [p for p in range(1, total_pages + 1) if p % 2 == 0]

    pages = []
    parts = range_str.split(",")
    for part in parts:
        part = part.strip()
        if "-" in part:
            sub = part.split("-")
            try:
                start = max(1, int(sub[0]))
                end = min(total_pages, int(sub[1]))
                pages.extend(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.append(p)
            except ValueError:
                pass
    return sorted(list(set(pages))) if pages else list(range(1, total_pages + 1))


def get_pdf_page_count(pdf_path: str) -> int:
    """Returns number of pages in PDF using pdfinfo or gs."""
    if shutil.which("pdfinfo"):
        try:
            out = subprocess.check_output(["pdfinfo", pdf_path], stderr=subprocess.DEVNULL).decode("utf-8")
            for line in out.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())
        except Exception:
            pass

    # Fallback via Ghostscript
    try:
        cmd = [
            "gs", "-q", "-dNODISPLAY", "-c",
            f"({pdf_path}) (r) file runpdfbegin pdfpagecount = quit"
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        return int(out)
    except Exception:
        return 1


def generate_booklet_order(page_count: int, binding: str = "left") -> list:
    """
    Computes saddle-stitch booklet page pairs for duplex short-edge printing.
    Returns list of page numbers (or 0 for blank padding).
    """
    total = math.ceil(page_count / 4) * 4
    sheets = total // 4
    order = []

    for i in range(sheets):
        # Sheet Front (Outside / Right Cover)
        left_front = total - (2 * i)
        right_front = (2 * i) + 1
        
        # Sheet Back (Inside)
        left_back = (2 * i) + 2
        right_back = total - (2 * i) - 1

        if binding == "right":  # Arabic / Qur'an style right-to-left binding
            order.extend([right_front, left_front, right_back, left_back])
        else:
            order.extend([left_front, right_front, left_back, right_back])

    # Replace numbers > page_count with 0 (blank)
    return [p if p <= page_count else 0 for p in order]


def render_pdf_pages_to_images(pdf_path: str, pages: list, dpi: int = 150) -> tuple:
    """Renders specific PDF pages to PNG images in a temp dir."""
    temp_dir = tempfile.mkdtemp(prefix="winprint_pages_")
    img_map = {}

    # Render requested pages
    for p in pages:
        if p == 0:
            continue
        prefix = os.path.join(temp_dir, f"page_{p}")
        cmd = ["pdftoppm", "-png", "-r", str(dpi), "-f", str(p), "-l", str(p), pdf_path, prefix]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out_png = f"{prefix}-{p}.png"
        if not os.path.exists(out_png):
            out_png = f"{prefix}-1.png"
        img_map[p] = out_png

    # Create a 1x1 white blank image for padding if needed
    blank_png = os.path.join(temp_dir, "blank.png")
    if 0 in pages:
        # Match dimensions of first valid image
        first_valid = next(iter(img_map.values()), None)
        if first_valid and shutil.which("convert"):
            subprocess.run(["convert", first_valid, "-fill", "white", "-colorize", "100%", blank_png],
                           check=True, stdout=subprocess.DEVNULL)
        else:
            subprocess.run(["convert", "-size", "1000x1414", "xc:white", blank_png],
                           check=True, stdout=subprocess.DEVNULL)
        img_map[0] = blank_png

    return temp_dir, img_map


def build_imposed_pdf(input_pdf: str, output_pdf: str, page_range_str: str = "all",
                       n_up: int = 1, booklet: bool = False, booklet_binding: str = "left",
                       reverse_order: bool = False, add_border: bool = False,
                       watermark_text: str = None, dpi: int = 200) -> bool:
    """
    Transforms input_pdf into an imposed pure-vector output_pdf according to layout settings.
    Uses qpdf for lossless 1-up page selection and Poppler+Cairo for vector N-up, booklet,
    dividing borders, and diagonal watermarks, falling back to raster montage only if Poppler is absent.
    """
    total_pages = get_pdf_page_count(input_pdf)
    selected_pages = parse_page_range(page_range_str, total_pages)

    if reverse_order and not booklet:
        selected_pages.reverse()

    if booklet:
        booklet_pages = generate_booklet_order(len(selected_pages), binding=booklet_binding)
        target_page_sequence = [0 if idx == 0 else selected_pages[idx - 1] for idx in booklet_pages]
        effective_nup = 2
    else:
        target_page_sequence = selected_pages
        effective_nup = max(1, int(n_up))

    is_identity = (
        effective_nup == 1
        and not watermark_text
        and not add_border
        and selected_pages == list(range(1, total_pages + 1))
    )
    if is_identity:
        shutil.copyfile(input_pdf, output_pdf)
        return True

    # Fast pure-vector subset/reorder via qpdf when only filtering or reversing 1-up pages
    if effective_nup == 1 and not watermark_text and not add_border and shutil.which("qpdf"):
        spec = ",".join(str(p) for p in target_page_sequence if p > 0)
        if spec:
            subprocess.run(
                ["qpdf", "--empty", "--pages", input_pdf, spec, "--", output_pdf],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return os.path.exists(output_pdf)

    # Pure vector PDF composition via Poppler + Cairo
    try:
        import cairo
        import gi
        gi.require_version("Poppler", "0.18")
        from gi.repository import Poppler

        abs_in = os.path.abspath(input_pdf)
        doc = Poppler.Document.new_from_file("file://" + abs_in, None)
        first_valid_num = next((p for p in target_page_sequence if p > 0), 1)
        ref_page = doc.get_page(first_valid_num - 1)
        src_w, src_h = ref_page.get_size()

        if effective_nup == 2:
            sheet_w = max(src_w, src_h) * 1.4142 if src_h >= src_w else src_w * 2.0
            sheet_h = max(src_w, src_h)
            cols, rows = 2, 1
        elif effective_nup == 4:
            sheet_w, sheet_h = src_w, src_h
            cols, rows = 2, 2
        else:
            sheet_w, sheet_h = src_w, src_h
            cols, rows = 1, 1

        surface = cairo.PDFSurface(output_pdf, sheet_w, sheet_h)
        ctx = cairo.Context(surface)

        step = effective_nup
        num_sheets = max(1, math.ceil(len(target_page_sequence) / step))
        pad = 12.0 if effective_nup > 1 else 0.0
        cell_w = (sheet_w - pad * (cols + 1)) / cols
        cell_h = (sheet_h - pad * (rows + 1)) / rows

        for s_idx in range(num_sheets):
            chunk = target_page_sequence[s_idx * step : (s_idx + 1) * step]
            while len(chunk) < step:
                chunk.append(0)

            for slot_idx, p_num in enumerate(chunk):
                if p_num <= 0:
                    continue
                page = doc.get_page(p_num - 1)
                if page is None:
                    continue
                pw, ph = page.get_size()
                col = slot_idx % cols
                row = slot_idx // cols
                rx = pad + col * (cell_w + pad)
                ry = pad + row * (cell_h + pad)
                scale = min(cell_w / pw, cell_h / ph) if (pw > 0 and ph > 0) else 1.0
                dx = rx + (cell_w - pw * scale) / 2.0
                dy = ry + (cell_h - ph * scale) / 2.0

                ctx.save()
                ctx.rectangle(rx, ry, cell_w, cell_h)
                ctx.clip()
                ctx.translate(dx, dy)
                ctx.scale(scale, scale)
                page.render_for_printing(ctx)
                ctx.restore()

            if add_border and effective_nup > 1:
                ctx.save()
                ctx.set_source_rgb(0.6, 0.63, 0.68)
                ctx.set_line_width(0.6)
                if effective_nup == 2:
                    cx = sheet_w / 2.0
                    ctx.move_to(cx, pad)
                    ctx.line_to(cx, sheet_h - pad)
                elif effective_nup == 4:
                    cx = sheet_w / 2.0
                    cy = sheet_h / 2.0
                    ctx.move_to(cx, pad)
                    ctx.line_to(cx, sheet_h - pad)
                    ctx.move_to(pad, cy)
                    ctx.line_to(sheet_w - pad, cy)
                ctx.stroke()
                ctx.restore()

            if watermark_text:
                ctx.save()
                ctx.translate(sheet_w / 2.0, sheet_h / 2.0)
                ctx.rotate(-math.pi / 4.0)
                ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(max(24.0, sheet_w * 0.085))
                ctx.set_source_rgba(0.75, 0.15, 0.15, 0.25)
                ext = ctx.text_extents(watermark_text)
                ctx.move_to(-ext.width / 2.0, ext.height / 2.0)
                ctx.show_text(watermark_text)
                ctx.new_path()
                ctx.restore()

            surface.show_page()

        surface.finish()
        return os.path.exists(output_pdf)
    except Exception:
        pass

    # Legacy raster fallback if Poppler/Cairo bindings are missing
    temp_dir, img_map = render_pdf_pages_to_images(input_pdf, list(set(target_page_sequence)), dpi=dpi)

    try:
        sheet_pdfs = []
        step = effective_nup
        num_sheets = math.ceil(len(target_page_sequence) / step)

        for s_idx in range(num_sheets):
            chunk = target_page_sequence[s_idx * step : (s_idx + 1) * step]
            while len(chunk) < step:
                chunk.append(0)

            chunk_images = [img_map.get(p, img_map.get(0)) for p in chunk]
            sheet_img = os.path.join(temp_dir, f"sheet_{s_idx}.png")
            sheet_pdf = os.path.join(temp_dir, f"sheet_{s_idx}.pdf")

            if effective_nup == 1:
                shutil.copyfile(chunk_images[0], sheet_img)
            elif effective_nup == 2:
                cmd_montage = ["montage", "-mode", "concatenate", "-tile", "2x1"]
                if add_border:
                    cmd_montage.extend(["-border", "1", "-bordercolor", "#9ca3af"])
                cmd_montage.extend(chunk_images + [sheet_img])
                subprocess.run(cmd_montage, check=True, stdout=subprocess.DEVNULL)
            elif effective_nup == 4:
                cmd_montage = ["montage", "-mode", "concatenate", "-tile", "2x2"]
                if add_border:
                    cmd_montage.extend(["-border", "1", "-bordercolor", "#9ca3af"])
                cmd_montage.extend(chunk_images + [sheet_img])
                subprocess.run(cmd_montage, check=True, stdout=subprocess.DEVNULL)

            if watermark_text:
                cmd_wm = [
                    "convert", sheet_img,
                    "-pointsize", "60",
                    "-fill", "rgba(180,180,180,0.35)",
                    "-gravity", "Center",
                    "-annotate", "45", watermark_text,
                    sheet_img
                ]
                subprocess.run(cmd_wm, check=True, stdout=subprocess.DEVNULL)

            subprocess.run(["convert", sheet_img, sheet_pdf], check=True, stdout=subprocess.DEVNULL)
            sheet_pdfs.append(sheet_pdf)

        if len(sheet_pdfs) == 1:
            shutil.copyfile(sheet_pdfs[0], output_pdf)
        else:
            if shutil.which("pdfunite"):
                subprocess.run(["pdfunite"] + sheet_pdfs + [output_pdf], check=True)
            else:
                subprocess.run(["convert"] + sheet_pdfs + [output_pdf], check=True)

        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: winprint_imposition.py <input.pdf> <output.pdf> [nup] [booklet(0/1)]")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2]
    nup = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    bk = bool(int(sys.argv[4])) if len(sys.argv) > 4 else False
    success = build_imposed_pdf(inp, out, n_up=nup, booklet=bk)
    print("Imposition Success:", success)
