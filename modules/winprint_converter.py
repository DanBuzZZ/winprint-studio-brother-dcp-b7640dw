#!/usr/bin/env python3
"""
winprint_converter.py - Universal Document Ingestion & Conversion Engine
Converts images, Office documents (Word/Excel/PowerPoint), plain text, HTML,
and PostScript into standard PDF for WinPrint Studio and Direct PCL-XL printing.
"""

import sys
import os
import subprocess
import tempfile
import shutil

PAPER_DIMENSIONS_POINTS = {
    "F4": (609.45, 935.43),   # 215 x 330 mm
    "A4": (595.28, 841.89),   # 210 x 297 mm
    "Legal": (612.0, 1008.0), # 216 x 356 mm
    "Letter": (612.0, 792.0), # 216 x 279 mm
    "A5": (419.53, 595.28)    # 148 x 210 mm
}


def is_pdf(file_path: str) -> bool:
    """Checks whether the file is a valid PDF by magic bytes or extension."""
    if not file_path or not os.path.exists(file_path):
        return False
    if file_path.lower().endswith(".pdf"):
        return True
    try:
        with open(file_path, "rb") as f:
            header = f.read(5)
            return header.startswith(b"%PDF-")
    except Exception:
        return False


def is_postscript(file_path: str) -> bool:
    if not file_path or not os.path.exists(file_path):
        return False
    if file_path.lower().endswith((".ps", ".eps")):
        return True
    try:
        with open(file_path, "rb") as f:
            header = f.read(4)
            return header.startswith(b"%!")
    except Exception:
        return False


def convert_image_to_pdf(image_path: str, output_pdf: str, paper: str = "A4") -> bool:
    """Converts image file to PDF fitting within specified paper boundaries."""
    # Method 1: ImageMagick convert
    if shutil.which("convert"):
        page_arg = "a4"
        if paper.upper() in ("F4", "FOLIO"):
            page_arg = "folio"
        elif paper.upper() == "LEGAL":
            page_arg = "legal"
        elif paper.upper() == "LETTER":
            page_arg = "letter"
            
        cmd = [
            "convert", image_path,
            "-page", page_arg,
            "-auto-orient",
            output_pdf
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0 and os.path.exists(output_pdf):
                return True
        except Exception:
            pass

    # Method 2: Python Pillow fallback if available
    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output_pdf, "PDF", resolution=300.0)
        return os.path.exists(output_pdf)
    except Exception:
        pass

    return False


def convert_office_to_pdf(doc_path: str, output_pdf: str) -> bool:
    """Converts Word (DOCX/DOC), Excel (XLSX/XLS), PPT, ODT, RTF to PDF using LibreOffice headless."""
    if not shutil.which("libreoffice"):
        return False

    tmp_dir = tempfile.mkdtemp(prefix="winprint_office_")
    try:
        cmd = [
            "libreoffice", "--headless", "--convert-to", "pdf",
            "--outdir", tmp_dir, doc_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = os.path.splitext(os.path.basename(doc_path))[0]
        gen_pdf = os.path.join(tmp_dir, base + ".pdf")
        if os.path.exists(gen_pdf):
            shutil.copyfile(gen_pdf, output_pdf)
            return True
        return False
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_text_to_pdf(text_path: str, output_pdf: str, paper: str = "A4") -> bool:
    """Converts plain text, markdown, or code file into clean paginated PDF."""
    # Method 1: LibreOffice Writer
    if shutil.which("libreoffice"):
        ok = convert_office_to_pdf(text_path, output_pdf)
        if ok:
            return True

    # Method 2: Ghostscript with enscript/paps if available, or pure Python fallback
    try:
        with open(text_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        # Write clean PostScript with pagination
        ps_tmp = tempfile.mktemp(suffix=".ps")
        pw, ph = PAPER_DIMENSIONS_POINTS.get(paper, (595.28, 841.89))
        margin_left = 50
        margin_top = ph - 50
        margin_bottom = 50
        line_height = 14
        
        with open(ps_tmp, "w", encoding="latin1") as ps:
            ps.write("%!PS\n")
            ps.write("/Courier findfont 10 scalefont setfont\n")
            ps.write(f"{margin_left} {margin_top} moveto\n")
            
            y = margin_top
            for line in lines:
                clean_line = line.rstrip("\r\n").replace("(", "\\(").replace(")", "\\)")
                ps.write(f"({clean_line}) show\n")
                y -= line_height
                if y < margin_bottom:
                    ps.write("showpage\n")
                    ps.write("/Courier findfont 10 scalefont setfont\n")
                    ps.write(f"{margin_left} {margin_top} moveto\n")
                    y = margin_top
                else:
                    ps.write(f"{margin_left} {y} moveto\n")
            ps.write("showpage\n")
            
        cmd = ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", f"-sOutputFile={output_pdf}", ps_tmp]
        subprocess.run(cmd, check=True)
        try:
            os.remove(ps_tmp)
        except OSError:
            pass
        return os.path.exists(output_pdf)
    except Exception:
        return False


def convert_postscript_to_pdf(ps_path: str, output_pdf: str) -> bool:
    """Converts PostScript to PDF via Ghostscript."""
    cmd = [
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
        f"-sOutputFile={output_pdf}", ps_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_pdf)
    except Exception:
        return False


def ensure_pdf(input_path: str, paper: str = "A4") -> str:
    """
    Universal Entry Point:
    Takes any input document/image path, determines format,
    converts it to PDF if necessary, and returns a path to a valid PDF.
    If already PDF, returns the input_path directly.
    """
    if not input_path or not os.path.exists(input_path):
        raise FileNotFoundError(f"Berkas tidak ditemukan: {input_path}")

    # Check if already a PDF
    if is_pdf(input_path):
        return input_path

    # Check Postscript
    if is_postscript(input_path):
        out_pdf = tempfile.mktemp(suffix="_ps_converted.pdf")
        if convert_postscript_to_pdf(input_path, out_pdf):
            return out_pdf

    # Check by extension
    ext = os.path.splitext(input_path)[1].lower()

    # Images
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"):
        out_pdf = tempfile.mktemp(suffix="_img_converted.pdf")
        if convert_image_to_pdf(input_path, out_pdf, paper=paper):
            return out_pdf

    # Office Documents
    if ext in (".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods", ".pptx", ".ppt", ".odp"):
        out_pdf = tempfile.mktemp(suffix="_office_converted.pdf")
        if convert_office_to_pdf(input_path, out_pdf):
            return out_pdf

    # Plain Text / Source Code / Web
    if ext in (".txt", ".csv", ".log", ".md", ".py", ".sh", ".json", ".xml", ".html", ".htm"):
        out_pdf = tempfile.mktemp(suffix="_txt_converted.pdf")
        if convert_text_to_pdf(input_path, out_pdf, paper=paper):
            return out_pdf

    # Fallback attempt via LibreOffice for any unknown format
    out_pdf = tempfile.mktemp(suffix="_auto_converted.pdf")
    if convert_office_to_pdf(input_path, out_pdf):
        return out_pdf

    # If all fails, raise error
    raise ValueError(f"Format berkas '{ext}' tidak dapat dikonversi ke PDF secara otomatis.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Penggunaan: winprint_converter.py <berkas_input> [output.pdf]")
        sys.exit(1)
        
    in_file = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/winprint_converted_test.pdf"
    res = ensure_pdf(in_file)
    print(f"[✓] Berkas berhasil disiapkan: {res}")
