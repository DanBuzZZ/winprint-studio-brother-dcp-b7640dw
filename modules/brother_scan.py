#!/usr/bin/env python3
"""
brother_scan.py - Standalone Scan Hub & OCR Pipeline for Brother DCP-B7640DW
Supports eSCL / AirScan REST API and SANE backend.
Includes Tesseract OCR pipeline for Searchable PDF generation.
"""

import sys
import os
import time
import argparse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import subprocess
import shutil

ESCL_SETTINGS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.0</pwg:Version>
  <pwg:ScanRegions>
    <pwg:ScanRegion>
      <pwg:Height>{height}</pwg:Height>
      <pwg:Width>{width}</pwg:Width>
      <pwg:XOffset>0</pwg:XOffset>
      <pwg:YOffset>0</pwg:YOffset>
    </pwg:ScanRegion>
  </pwg:ScanRegions>
  <scan:InputSource>{input_source}</scan:InputSource>
  <scan:ColorMode>{color_mode}</scan:ColorMode>
  <scan:XResolution>{resolution}</scan:XResolution>
  <scan:YResolution>{resolution}</scan:YResolution>
  <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
</scan:ScanSettings>"""


def get_escl_base_url(ip: str, timeout: float = 2.0) -> str:
    """Probes ports 80, 8080, and 443 for eSCL ScannerCapabilities."""
    candidates = [
        f"http://{ip}/eSCL",
        f"http://{ip}:8080/eSCL",
        f"https://{ip}/eSCL"
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(f"{url}/ScannerCapabilities", headers={"User-Agent": "BrotherScanHub/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    return None


def run_ocr_on_images(image_paths: list, output_pdf: str, lang: str = "ind+eng") -> bool:
    """Converts images to a Searchable PDF using Tesseract and merges with pdfunite."""
    if not shutil.which("tesseract"):
        print("Tesseract belum terpasang, mengabaikan OCR...", file=sys.stderr)
        return False
        
    temp_pdfs = []
    try:
        for idx, img in enumerate(image_paths):
            base_out = f"/tmp/ocr_page_{idx}_{os.getpid()}"
            cmd = ["tesseract", img, base_out, "-l", lang, "pdf"]
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pdf_path = f"{base_out}.pdf"
            if proc.returncode == 0 and os.path.exists(pdf_path):
                temp_pdfs.append(pdf_path)
            else:
                # Fallback: convert directly without OCR if tesseract failed on this image
                if shutil.which("convert"):
                    subprocess.run(["convert", img, pdf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(pdf_path):
                        temp_pdfs.append(pdf_path)
                        
        if not temp_pdfs:
            return False
            
        if len(temp_pdfs) == 1:
            shutil.copyfile(temp_pdfs[0], output_pdf)
        else:
            if shutil.which("pdfunite"):
                subprocess.run(["pdfunite"] + temp_pdfs + [output_pdf], check=True)
            else:
                shutil.copyfile(temp_pdfs[0], output_pdf)
        return True
    finally:
        for p in temp_pdfs:
            try:
                os.remove(p)
            except OSError:
                pass


def scan_escl(base_url: str, source: str, resolution: int, color_mode: str, output_path: str, do_ocr: bool = False):
    # Dimensions for A4 at current dpi
    # A4: 210 x 297 mm -> 8.27 x 11.69 inches
    width = int(8.27 * resolution)
    height = int(11.69 * resolution)
    
    escl_source = "Feeder" if source.lower() == "adf" else "Platen"
    escl_color = "RGB24" if color_mode.lower() == "color" else ("Grayscale8" if color_mode.lower() == "gray" else "BlackAndWhite1")
    
    payload = ESCL_SETTINGS_TEMPLATE.format(
        width=width,
        height=height,
        input_source=escl_source,
        color_mode=escl_color,
        resolution=resolution
    ).encode("utf-8")
    
    req = urllib.request.Request(
        f"{base_url}/ScanJobs",
        data=payload,
        headers={
            "Content-Type": "text/xml",
            "User-Agent": "BrotherScanHub/2.0"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            job_url = resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        print(f"Gagal memulai pekerjaan pindaian eSCL: {e.code} {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Koneksi eSCL gagal: {e}", file=sys.stderr)
        return False
        
    if not job_url:
        print("Printer tidak mengembalikan URL pekerjaan pindaian.", file=sys.stderr)
        return False
        
    # Poll & Download pages
    downloaded_images = []
    page_num = 1
    doc_url = f"{job_url}/NextDocument"
    
    print(f"Memindai dari {escl_source} ({resolution} dpi, {color_mode})...")
    
    while True:
        try:
            req_doc = urllib.request.Request(doc_url, headers={"User-Agent": "BrotherScanHub/2.0"})
            with urllib.request.urlopen(req_doc, timeout=30.0) as resp:
                if resp.status == 200:
                    temp_img = f"/tmp/brother_scan_p{page_num}_{os.getpid()}.jpg"
                    with open(temp_img, "wb") as f:
                        f.write(resp.read())
                    downloaded_images.append(temp_img)
                    print(f"Halaman {page_num} berhasil dipindai.")
                    page_num += 1
                    if escl_source == "Platen":
                        break # Flatbed is single page
                elif resp.status in (404, 503):
                    # No more pages in ADF
                    break
        except urllib.error.HTTPError as e:
            if e.code in (404, 503):
                break # Finished
            print(f"Selesai atau status halaman: {e.code}", file=sys.stderr)
            break
        except Exception as e:
            print(f"Peringatan pindaian: {e}", file=sys.stderr)
            break
            
    if not downloaded_images:
        print("Tidak ada dokumen yang dihasilkan. Pastikan kertas terpasang di ADF atau flatbed.", file=sys.stderr)
        return False
        
    # Process outputs
    ext = os.path.splitext(output_path)[1].lower()
    
    if do_ocr or ext == ".pdf":
        print("Memproses dokumen menjadi Searchable PDF via Tesseract OCR...")
        success = run_ocr_on_images(downloaded_images, output_path)
        if not success and shutil.which("convert"):
            subprocess.run(["convert"] + downloaded_images + [output_path], check=True)
    elif ext in (".jpg", ".jpeg"):
        shutil.copyfile(downloaded_images[0], output_path)
    elif ext == ".png" and shutil.which("convert"):
        subprocess.run(["convert", downloaded_images[0], output_path], check=True)
    else:
        shutil.copyfile(downloaded_images[0], output_path)
        
    # Clean up
    for img in downloaded_images:
        try:
            os.remove(img)
        except OSError:
            pass
            
    print(f"Pemindaian selesai: {output_path}")
    return True


def scan_sane_fallback(ip: str, source: str, resolution: int, color_mode: str, output_path: str, do_ocr: bool = False):
    """Fallback scanner using scanimage (SANE) if available."""
    if not shutil.which("scanimage"):
        print("Driver scanimage / SANE tidak ditemukan.", file=sys.stderr)
        return False
        
    print(f"Mencoba pemindaian via SANE scanimage (IP: {ip})...")
    temp_img = f"/tmp/brother_sane_{os.getpid()}.pnm"
    
    sane_source = "Automatic Document Feeder" if source.lower() == "adf" else "Flatbed"
    sane_mode = "Color" if color_mode.lower() == "color" else "Gray"
    
    device_name = f"escl:http://{ip}:80/eSCL/"
    cmd = [
        "scanimage",
        "-d", device_name,
        f"--resolution={resolution}",
        f"--mode={sane_mode}",
        f"--source={sane_source}",
        f"--output-file={temp_img}"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        if os.path.exists(temp_img):
            if do_ocr or output_path.lower().endswith(".pdf"):
                run_ocr_on_images([temp_img], output_path)
            elif shutil.which("convert"):
                subprocess.run(["convert", temp_img, output_path], check=True)
            else:
                shutil.copyfile(temp_img, output_path)
            os.remove(temp_img)
            return True
    except Exception as e:
        print(f"SANE scanimage gagal: {e}", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description="Brother DCP-B7640DW Scan Hub & OCR Pipeline")
    parser.add_argument("ip", help="Printer IP address")
    parser.add_argument("--source", choices=["flatbed", "adf"], default="flatbed", help="Scan source (flatbed or adf)")
    parser.add_argument("--resolution", type=int, choices=[100, 150, 200, 300, 600], default=300, help="Resolution in DPI")
    parser.add_argument("--color", choices=["color", "gray", "mono"], default="color", help="Color mode")
    parser.add_argument("--ocr", action="store_true", help="Generate Searchable PDF with Tesseract OCR")
    parser.add_argument("--output", default="scan_result.pdf", help="Output file path (PDF, PNG, JPG)")
    args = parser.parse_args()
    
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    
    base_url = get_escl_base_url(args.ip)
    if base_url:
        success = scan_escl(base_url, args.source, args.resolution, args.color, args.output, args.ocr)
        if success:
            sys.exit(0)
            
    # Try SANE fallback
    fallback_ok = scan_sane_fallback(args.ip, args.source, args.resolution, args.color, args.output, args.ocr)
    if not fallback_ok:
        print("Gagal melakukan pemindaian. Pastikan printer terhubung dan fungsi pemindai aktif.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
