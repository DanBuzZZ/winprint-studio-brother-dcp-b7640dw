#!/usr/bin/env python3
"""
winprint_studio.py - Enterprise Full-Featured Print Studio for Brother DCP-B7640DW
Enterprise Edition: Precision Layout, Imposition Engine, Live Paper Canvas, Telemetry
"""

import sys
import os
import argparse
import subprocess
import tempfile
import shutil
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QRadioButton,
    QButtonGroup, QTabWidget, QGroupBox, QFileDialog, QProgressBar,
    QScrollArea, QMessageBox, QFrame, QLineEdit, QSlider, QSizePolicy,
    QSplitter, QToolButton, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QFont, QPen, QBrush,
    QLinearGradient, QPainterPath, QAction, QCursor, QFontDatabase,
    QTransform, QShortcut, QKeySequence
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSize, QRectF, QPointF,
    QPropertyAnimation, QEasingCurve, QTimer, QVariantAnimation
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(SCRIPT_DIR, "modules")):
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "modules"))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import winprint_engine
import brother_snmp
import winprint_imposition
import winprint_converter
import winprint_comm
import winprint_layout
import winprint_engine_v2


def ensure_check_icon() -> str:
    path = os.path.expanduser("~/.local/share/winprint/check_icon.png")
    if not os.path.exists(path):
        import zlib, struct
        width, height = 16, 16
        raw_data = bytearray(height * (1 + width * 4))
        points = [
            (3, 8), (4, 9), (5, 10), (6, 11), (7, 12),
            (8, 10), (9, 8), (10, 6), (11, 4), (12, 3)
        ]
        coords = set()
        for x, y in points:
            coords.add((x, y))
            coords.add((x + 1, y))
            coords.add((x, y + 1))
        for y in range(height):
            raw_data[y * (1 + width * 4)] = 0
            for x in range(width):
                idx = y * (1 + width * 4) + 1 + x * 4
                if (x, y) in coords:
                    raw_data[idx:idx + 4] = b'\xff\xff\xff\xff'
                else:
                    raw_data[idx:idx + 4] = b'\x00\x00\x00\x00'
        png = bytearray(b'\x89PNG\r\n\x1a\n')
        ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
        png.extend(struct.pack('>I', 13) + b'IHDR' + ihdr + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr)))
        comp = zlib.compress(raw_data)
        png.extend(struct.pack('>I', len(comp)) + b'IDAT' + comp + struct.pack('>I', zlib.crc32(b'IDAT' + comp)))
        png.extend(struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND')))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "wb") as f:
                f.write(png)
        except Exception:
            pass
    return path

CHECK_ICON_PATH = ensure_check_icon()


# ==============================================================================
# ENTERPRISE WORKSTATION STYLESHEET (Ultra-Lux Obsidian Glass)
# ==============================================================================
ENTERPRISE_STYLE = """
QMainWindow, QWidget#CentralWidget {
    background-color: #060a12;
    color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Helvetica Neue", Ubuntu, sans-serif;
    font-size: 13px;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background: #060a12;
    width: 7px;
    margin: 0;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #1e293b;
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #334155;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    border: none;
    background: #060a12;
    height: 7px;
    margin: 0;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: #1e293b;
    min-width: 24px;
    border-radius: 3px;
}

/* GroupBox & Panels */
QGroupBox {
    background-color: #0b1424;
    border: 1px solid #1e293b;
    border-radius: 8px;
    margin-top: 16px;
    font-weight: 700;
    font-size: 12px;
    color: #38bdf8;
    padding: 14px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 3px;
    padding: 2px 8px;
    background-color: #0b1424;
    color: #38bdf8;
    border-radius: 4px;
    border: 1px solid #1e293b;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0a1120;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background-color: #070c16;
    color: #94a3b8;
    border: 1px solid #1e293b;
    border-bottom: none;
    padding: 9px 15px;
    margin-right: 3px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
}
QTabBar::tab:selected {
    background-color: #0a1120;
    color: #38bdf8;
    border-top: 2.5px solid #0ea5e9;
    font-weight: 800;
}
QTabBar::tab:hover:!selected {
    background-color: #0f192b;
    color: #f8fafc;
}

/* Inputs & Combos */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #070d18;
    border: 1.5px solid #1e293b;
    border-radius: 7px;
    padding: 6px 12px;
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    selection-background-color: #0284c7;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #0ea5e9;
    background-color: #0c1527;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #38bdf8;
    background-color: #0a1324;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid #1e293b;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
QComboBox QAbstractItemView {
    background-color: #0b1322;
    border: 1.5px solid #233148;
    selection-background-color: #0284c7;
    selection-color: white;
    color: #f8fafc;
    padding: 6px;
}

/* Checkboxes */
QCheckBox {
    spacing: 9px;
    color: #e2e8f0;
    font-size: 12px;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1.5px solid #334155;
    border-radius: 5px;
    background-color: #070d18;
}
QCheckBox::indicator:hover {
    border-color: #38bdf8;
    background-color: #0f1c30;
}
QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
    image: url(__CHECK_ICON__);
}

/* Default Buttons */
QPushButton {
    background-color: #111a2e;
    border: 1px solid #1e293b;
    border-radius: 7px;
    color: #f8fafc;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #1a2742;
    border-color: #38bdf8;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #0c1424;
    padding-top: 9px;
    padding-bottom: 5px;
}
QPushButton:disabled {
    background-color: #090e18;
    border-color: #172033;
    color: #475569;
}

/* Sliders */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #1e293b;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #0284c7;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #38bdf8;
    border: 2px solid #080d17;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #7dd3fc;
}

/* Status Bar */
QStatusBar {
    background-color: #060910;
    color: #94a3b8;
    border-top: 1px solid #172033;
    font-size: 12px;
    padding: 2px 8px;
}
""".replace("__CHECK_ICON__", CHECK_ICON_PATH)


# ==============================================================================
# TACTILE ANIMATED LUXURY BUTTON
# ==============================================================================
class AnimatedButton(QPushButton):
    """
    Luxury tactile button with dynamic glow elevation on hover,
    tactile depression on press, and smooth spring-damped return.
    """
    def __init__(self, text: str = "", parent=None, accent_color: str = "#0ea5e9", is_primary: bool = False):
        super().__init__(text, parent)
        self.accent_color = accent_color
        self.is_primary = is_primary
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        self.shadow = QGraphicsDropShadowEffect(self)
        base_blur = 10 if is_primary else 4
        self.shadow.setBlurRadius(base_blur)
        self.shadow.setColor(QColor(0, 0, 0, 90 if is_primary else 40))
        self.shadow.setOffset(0, 2)
        self.setGraphicsEffect(self.shadow)
        
        self.anim = QPropertyAnimation(self.shadow, b"blurRadius")
        self.anim.setDuration(120)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def enterEvent(self, event):
        if self.isEnabled():
            self.anim.stop()
            self.anim.setStartValue(self.shadow.blurRadius())
            self.anim.setEndValue(18 if self.is_primary else 10)
            col = QColor(self.accent_color)
            self.shadow.setColor(QColor(col.red(), col.green(), col.blue(), 130 if self.is_primary else 70))
            self.shadow.setOffset(0, 3)
            self.anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isEnabled():
            self.anim.stop()
            self.anim.setStartValue(self.shadow.blurRadius())
            self.anim.setEndValue(10 if self.is_primary else 4)
            self.shadow.setColor(QColor(0, 0, 0, 90 if self.is_primary else 40))
            self.shadow.setOffset(0, 2)
            self.anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.anim.stop()
            self.shadow.setBlurRadius(2)
            self.shadow.setOffset(0, 1)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.isEnabled():
            self.anim.stop()
            self.anim.setStartValue(2)
            target = 18 if (self.underMouse() and self.is_primary) else (10 if self.underMouse() else (10 if self.is_primary else 4))
            self.anim.setEndValue(target)
            self.shadow.setOffset(0, 2)
            self.anim.start()


# ==============================================================================
# BACKGROUND THREAD WORKERS
# ==============================================================================
class PageRenderWorker(QThread):
    rendered = pyqtSignal(int, str)

    def __init__(self, pdf_path: str, page_num: int, dpi: int = 130):
        super().__init__()
        self.pdf_path = pdf_path
        self.page_num = page_num
        self.dpi = dpi

    def run(self):
        tmp_prefix = f"/tmp/winprint_prev_{os.getpid()}_{self.page_num}_{id(self)}"
        cmd = [
            "pdftoppm", "-png", "-r", str(self.dpi),
            "-f", str(self.page_num), "-l", str(self.page_num),
            self.pdf_path, tmp_prefix
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out_img = f"{tmp_prefix}-{self.page_num}.png"
            if not os.path.exists(out_img):
                out_img = f"{tmp_prefix}-1.png"
            if os.path.exists(out_img):
                self.rendered.emit(self.page_num, out_img)
            else:
                self.rendered.emit(self.page_num, "")
        except Exception:
            self.rendered.emit(self.page_num, "")


class TelemetryWorker(QThread):
    telemetry_ready = pyqtSignal(dict)

    def __init__(self, ip: str, printer_model: str = "Brother DCP-B7640DW"):
        super().__init__()
        self.ip = ip
        self.printer_model = printer_model

    def run(self):
        try:
            spec = brother_snmp.PRINTER_CATALOG.get(self.printer_model, {})
            keywords = spec.get("keywords", ())
            exclude = spec.get("exclude", ())
            t = brother_snmp.get_printer_telemetry(self.ip)
            model_str = t.get("model") or ""
            model_ok = t.get("online") and (
                not keywords or (any(k in model_str for k in keywords) and not any(ex in model_str for ex in exclude))
            )
            if not model_ok:
                new_ip = brother_snmp.resolve_printer_ip(self.printer_model, self.ip, set_active=True)
                if new_ip and new_ip != self.ip:
                    self.ip = new_ip
                    t = brother_snmp.get_printer_telemetry(new_ip)
            pjl = winprint_comm.get_printer_telemetry(self.ip, connect_timeout=0.5, read_timeout=1.0)
            t["printer_model"] = self.printer_model
            t["pjl_state"] = pjl.get("device_state", "UNKNOWN")
            t["pjl_code"] = pjl.get("status_code")
            t["pjl_display"] = pjl.get("display", "")
            t["pjl_tray2"] = pjl.get("paper_tray", {}).get("tray2", {}).get("configured_size")
            t["pjl_latency_ms"] = pjl.get("latency_ms")
            if not t.get("online") and t["pjl_state"] in ("READY", "BUSY"):
                t["online"] = True
                t["lcd_text"] = t["pjl_display"] or "Sleep"
            self.telemetry_ready.emit(t)
        except Exception:
            self.telemetry_ready.emit({"online": False, "ip": self.ip, "printer_model": self.printer_model, "pjl_state": "UNKNOWN"})


class PrintExecutionWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_result = pyqtSignal(bool, str)

    def __init__(self, ip: str, pdf_path: str, settings: dict):
        super().__init__()
        self.ip = ip
        self.pdf_path = pdf_path
        self.settings = settings
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        p_model = self.settings.get("printer_model", "Brother DCP-B7640DW")
        self.progress.emit(10, f"Memverifikasi koneksi printer {p_model}...")
        self.ip = brother_snmp.resolve_printer_ip(p_model, self.ip, set_active=True)
        if self.cancel_event.is_set():
            self.finished_result.emit(False, "Pencetakan dibatalkan sebelum dikirim.")
            return
        self.progress.emit(20, f"Menyiapkan tata letak & kalkulasi imposisi ke {self.ip}...")
        temp_imposed = None
        try:
            needs_imposition = (
                self.settings.get("n_up", 1) > 1 or
                self.settings.get("booklet", False) or
                self.settings.get("page_range", "all") != "all" or
                self.settings.get("reverse_order", False) or
                bool(self.settings.get("watermark")) or
                bool(self.settings.get("add_border", False) and self.settings.get("n_up", 1) > 1)
            )
            
            final_pdf = self.pdf_path
            if needs_imposition:
                self.progress.emit(35, "Memproses penggabungan halaman (N-Up / Buklet / Tanda Air)...")
                temp_imposed = tempfile.mktemp(suffix="_imposed.pdf")
                ok = winprint_imposition.build_imposed_pdf(
                    input_pdf=self.pdf_path,
                    output_pdf=temp_imposed,
                    page_range_str=self.settings.get("page_range", "all"),
                    n_up=self.settings.get("n_up", 1),
                    booklet=self.settings.get("booklet", False),
                    booklet_binding=self.settings.get("booklet_binding", "left"),
                    reverse_order=self.settings.get("reverse_order", False),
                    add_border=self.settings.get("add_border", False),
                    watermark_text=self.settings.get("watermark")
                )
                if ok and os.path.exists(temp_imposed):
                    final_pdf = temp_imposed

            self.progress.emit(70, "Memproses tata letak & rasterisasi presisi Brother...")
            
            duplex = self.settings.get("duplex", "none")
            if self.settings.get("booklet", False):
                duplex = "short"

            def on_stream_progress(pct: int, msg: str):
                val = 72 + int(pct * 0.26)
                self.progress.emit(val, msg)

            success = winprint_engine.print_file_direct(
                ip=self.ip,
                file_path=final_pdf,
                paper=self.settings.get("paper", "A4"),
                duplex=duplex,
                toner_save=self.settings.get("toner_save", False),
                resolution=self.settings.get("resolution", 600),
                copies=self.settings.get("copies", 1),
                orientation=self.settings.get("orientation", "portrait"),
                scale=self.settings.get("content_scale", 1.0),
                duplex_offset_y=self.settings.get("duplex_offset_y", None),
                duplex_offset_x=self.settings.get("duplex_offset_x", None),
                printer_model=p_model,
                paper_source=self.settings.get("paper_source", "auto"),
                media_type=self.settings.get("media_type", "plain"),
                quiet_mode=self.settings.get("quiet_mode", False),
                density=self.settings.get("density", 0),
                binding_gutter_mm=self.settings.get("binding_gutter_mm", 0.0),
                collate=self.settings.get("collate", True),
                cancel_event=self.cancel_event,
                progress_callback=on_stream_progress
            )
            
            if success:
                self.progress.emit(100, "Selesai. Dokumen berhasil dikirim ke printer.")
                self.finished_result.emit(True, f"Pencetakan berhasil dikirim ke {p_model} ({self.ip}:9100).")
            else:
                err_detail = winprint_engine.get_last_error()
                if not err_detail:
                    err_detail = (
                        f"Gagal mengirim data cetak ke printer Brother ({self.ip}:9100).\n\n"
                        "Printer sedang dalam mode Deep Sleep atau port 9100 sedang sibuk. "
                        "Silakan coba tekan tombol 'CETAK SEKARANG' sekali lagi."
                    )
                self.finished_result.emit(False, err_detail)
        except Exception as e:
            self.finished_result.emit(False, str(e))
        finally:
            if temp_imposed and os.path.exists(temp_imposed):
                try:
                    os.remove(temp_imposed)
                except OSError:
                    pass


# ==============================================================================
# REALISTIC PAPER WORKSTATION CANVAS (Physical Sheet CAD Preview)
# ==============================================================================
class RealisticPaperCanvas(QWidget):
    """
    Renders an authentic physical paper sheet on an architectural drafting mat.
    Accurately scales to paper aspect ratio (F4 215x330mm, A4, Legal).
    Simulates N-Up grid divisions, booklet folding spine, margins, and watermark.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.pixmap_p1 = None
        self.pixmap_p2 = None
        self.pixmap_back_duplex = None
        self.show_duplex_back = False
        self.binding_gutter_mm = 0.0
        self.paper_code = "F4"
        self.paper_ratio = 330.0 / 215.0  # Default F4 Portrait (~1.535)
        self.paper_name = "F4 / Folio (215 x 330 mm)"
        self.orientation = "auto"
        self.n_up = 1
        self.booklet = False
        self.watermark_text = None
        self.show_margins = True
        self.zoom_factor = 1.0
        self.content_scale = 1.0
        self.auto_rotate = True
        self.detected_doc_landscape = False
        self._margin_cache = {}

        self.update_canvas_geometry()

    def update_canvas_geometry(self):
        """Calculates minimum canvas size based on zoom factor and paper ratio to drive QScrollArea."""
        if self.booklet or self.n_up == 2:
            is_landscape = True
        elif self.orientation == "auto":
            is_landscape = self.detected_doc_landscape
        else:
            is_landscape = (self.orientation == "landscape")

        ratio = (1.0 / self.paper_ratio) if is_landscape else self.paper_ratio
        if is_landscape:
            base_w = 640
            base_h = int(base_w * ratio)
        else:
            base_w = 440
            base_h = int(base_w * ratio)

        sheet_w = base_w * self.zoom_factor
        sheet_h = base_h * self.zoom_factor

        pad = 32
        req_w = int(sheet_w + pad * 2)
        req_h = int(sheet_h + pad * 2 + 24)
        self.setMinimumSize(req_w, req_h)

    def set_content_scale(self, scale: float):
        self.content_scale = max(0.5, min(2.0, scale))
        self.update()

    def set_auto_rotate(self, auto_rot: bool):
        self.auto_rotate = auto_rot
        self.update()

    def set_zoom(self, factor: float):
        self.zoom_factor = max(0.5, min(3.0, factor))
        self.update_canvas_geometry()
        self.update()

    def set_paper_size(self, paper_code: str):
        self.paper_code = paper_code or "F4"
        if paper_code in ("F4", "Folio", "8.5x13", "FanFoldGermanLegal"):
            self.paper_ratio = 330.2 / 215.9
            self.paper_name = "F4 / Folio (215 x 330 mm)"
        elif paper_code == "A4":
            self.paper_ratio = 297.0 / 210.0
            self.paper_name = "A4 (210 x 297 mm)"
        elif paper_code == "Legal":
            self.paper_ratio = 356.0 / 216.0
            self.paper_name = "Legal (216 x 356 mm)"
        elif paper_code == "Letter":
            self.paper_ratio = 279.0 / 216.0
            self.paper_name = "Letter (216 x 279 mm)"
        elif paper_code == "A5":
            self.paper_ratio = 210.0 / 148.0
            self.paper_name = "A5 (148 x 210 mm)"
        self.update_canvas_geometry()
        self.update()

    def _get_ppd_margin_fracs(self, is_landscape: bool):
        key = (self.paper_code, is_landscape)
        if key not in self._margin_cache:
            try:
                geom = winprint_layout.get_media_geometry(
                    winprint_engine.resolve_ppd_path(),
                    self.paper_code,
                    "landscape" if is_landscape else "portrait",
                )
                self._margin_cache[key] = (
                    geom.margin_left_pt / geom.width_pt,
                    geom.margin_top_pt / geom.height_pt,
                    geom.margin_right_pt / geom.width_pt,
                    geom.margin_bottom_pt / geom.height_pt,
                )
            except Exception:
                self._margin_cache[key] = (0.02, 0.015, 0.02, 0.015)
        return self._margin_cache[key]

    def set_orientation(self, orientation: str):
        self.orientation = str(orientation).lower()
        self.update_canvas_geometry()
        self.update()

    def set_layout_mode(self, n_up: int, booklet: bool):
        self.n_up = n_up
        self.booklet = booklet
        self.update_canvas_geometry()
        self.update()

    def set_watermark(self, text: str):
        self.watermark_text = text if text and text != "Tidak Ada" else None
        self.update()

    def set_pages(self, p1, p2=None):
        if isinstance(p1, QPixmap):
            self.pixmap_p1 = p1
        elif isinstance(p1, str) and os.path.exists(p1):
            self.pixmap_p1 = QPixmap(p1)
        else:
            self.pixmap_p1 = None

        if isinstance(p2, QPixmap):
            self.pixmap_p2 = p2
        elif isinstance(p2, str) and os.path.exists(p2):
            self.pixmap_p2 = QPixmap(p2)
        else:
            self.pixmap_p2 = None
        self.update()

    def set_duplex_back_preview(self, p_back):
        if isinstance(p_back, QPixmap):
            self.pixmap_back_duplex = p_back
        elif isinstance(p_back, str) and os.path.exists(p_back):
            self.pixmap_back_duplex = QPixmap(p_back)
        else:
            self.pixmap_back_duplex = None
        self.update()

    def set_show_duplex_back(self, enabled: bool):
        self.show_duplex_back = bool(enabled)
        self.update()

    def set_binding_gutter_mm(self, gutter_mm: float):
        self.binding_gutter_mm = max(0.0, float(gutter_mm or 0.0))
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            parent_window = self.window()
            if hasattr(parent_window, "zoom_in") and hasattr(parent_window, "zoom_out"):
                if delta > 0:
                    parent_window.zoom_in()
                else:
                    parent_window.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = max(self.width(), self.minimumWidth())
        h = max(self.height(), self.minimumHeight())

        # 1. Drafting Mat Background
        painter.fillRect(0, 0, w, h, QColor("#090d16"))

        # Subtle drafting grid lines
        grid_pen = QPen(QColor("#131c2e"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        grid_size = 28
        for x in range(0, w, grid_size):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, grid_size):
            painter.drawLine(0, y, w, y)

        # Determine sheet orientation & dimensions on canvas
        if self.booklet or self.n_up == 2:
            is_landscape_sheet = True
        elif self.orientation == "auto":
            is_landscape_sheet = self.detected_doc_landscape
        else:
            is_landscape_sheet = (self.orientation == "landscape")
        ratio = (1.0 / self.paper_ratio) if is_landscape_sheet else self.paper_ratio

        if is_landscape_sheet:
            base_w = 640
            base_h = int(base_w * ratio)
        else:
            base_w = 440
            base_h = int(base_w * ratio)

        sheet_w = base_w * self.zoom_factor
        sheet_h = base_h * self.zoom_factor

        # Bound to widget with margins / centered in available space
        sheet_x = max(32.0, (w - sheet_w) / 2.0)
        sheet_y = max(32.0, (h - sheet_h - 20) / 2.0)

        sheet_rect = QRectF(sheet_x, sheet_y, sheet_w, sheet_h)

        # 2. Realistic Paper Dropshadow (multi-layered)
        shadow_colors = [
            QColor(0, 0, 0, 100),
            QColor(0, 0, 0, 60),
            QColor(0, 0, 0, 30),
            QColor(0, 0, 0, 15)
        ]
        for i, col in enumerate(shadow_colors, start=1):
            s_rect = sheet_rect.adjusted(-i * 1.5, i * 2, i * 1.5, i * 3)
            painter.setBrush(col)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(s_rect, 6, 6)

        # 3. Paper Sheet (Pure White Canvas)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#cbd5e1"), 1))
        painter.drawRoundedRect(sheet_rect, 2, 2)

        # 4. Render Page Content / Imposition Layout
        scaled_pixmap_dim = None
        if self.pixmap_p1 is not None and not self.pixmap_p1.isNull():
            if self.n_up == 1 and not self.booklet:
                # 1-Up Full Page (WYSIWYG layout matching Ghostscript)
                pix = self.pixmap_p1
                doc_is_landscape = pix.width() > pix.height()
                if self.auto_rotate and is_landscape_sheet != doc_is_landscape:
                    # Match Ghostscript auto-rotation to target sheet orientation
                    transform = QTransform().rotate(90)
                    pix = pix.transformed(transform, Qt.TransformationMode.SmoothTransformation)

                # Base content size fitting sheet scaled by content_scale
                base_w = sheet_rect.width()
                base_h = sheet_rect.height()
                target_size = QSize(int(base_w * self.content_scale), int(base_h * self.content_scale))

                scaled_pixmap = pix.scaled(
                    target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                scaled_pixmap_dim = scaled_pixmap.size()
                dest_x = sheet_rect.x() + (sheet_rect.width() - scaled_pixmap.width()) / 2.0
                dest_y = sheet_rect.y() + (sheet_rect.height() - scaled_pixmap.height()) / 2.0

                # Gutter shift reflection in preview (+mm moves content away from left spine)
                paper_w_mm = 215.9 if self.paper_code in ("F4", "Folio") else (148.0 if self.paper_code == "A5" else 210.0)
                gutter_px = (self.binding_gutter_mm / paper_w_mm) * sheet_rect.width() if self.binding_gutter_mm > 0 else 0.0
                dest_x += gutter_px

                # Duplex onion-skin overlay ("Terawang Sisi Belakang")
                if self.show_duplex_back and self.pixmap_back_duplex is not None and not self.pixmap_back_duplex.isNull():
                    back_pix = self.pixmap_back_duplex
                    if self.auto_rotate and is_landscape_sheet != (back_pix.width() > back_pix.height()):
                        back_pix = back_pix.transformed(QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation)
                    back_scaled = back_pix.scaled(
                        target_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ).transformed(QTransform().scale(-1.0, 1.0))
                    bx = sheet_rect.x() + (sheet_rect.width() - back_scaled.width()) / 2.0 + gutter_px
                    by = sheet_rect.y() + (sheet_rect.height() - back_scaled.height()) / 2.0
                    painter.save()
                    painter.setClipRect(sheet_rect)
                    painter.setOpacity(0.16)
                    painter.drawPixmap(int(bx), int(by), back_scaled)
                    painter.restore()

                painter.save()
                painter.setClipRect(sheet_rect)
                painter.drawPixmap(int(dest_x), int(dest_y), scaled_pixmap)
                painter.restore()

            elif self.n_up == 2 or self.booklet:
                # 2-Up or Booklet Spread (Side-by-Side on Landscape Sheet)
                gutter = 12 * self.zoom_factor
                half_w = (sheet_w - (gutter * 3)) / 2.0
                content_h = sheet_h - (gutter * 2)

                rect_left = QRectF(sheet_x + gutter, sheet_y + gutter, half_w, content_h)
                rect_right = QRectF(sheet_x + gutter * 2 + half_w, sheet_y + gutter, half_w, content_h)

                target_cell_size = QSize(int(half_w * self.content_scale), int(content_h * self.content_scale))

                # Draw Left Page
                scaled_p1 = self.pixmap_p1.scaled(
                    target_cell_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                dest_p1_x = rect_left.x() + (rect_left.width() - scaled_p1.width()) / 2.0
                dest_p1_y = rect_left.y() + (rect_left.height() - scaled_p1.height()) / 2.0
                
                painter.save()
                painter.setClipRect(rect_left)
                painter.drawPixmap(int(dest_p1_x), int(dest_p1_y), scaled_p1)
                painter.restore()

                # Draw Right Page (or placeholder)
                if self.pixmap_p2 is not None and not self.pixmap_p2.isNull():
                    scaled_p2 = self.pixmap_p2.scaled(
                        target_cell_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    dest_p2_x = rect_right.x() + (rect_right.width() - scaled_p2.width()) / 2.0
                    dest_p2_y = rect_right.y() + (rect_right.height() - scaled_p2.height()) / 2.0
                    
                    painter.save()
                    painter.setClipRect(rect_right)
                    painter.drawPixmap(int(dest_p2_x), int(dest_p2_y), scaled_p2)
                    painter.restore()
                else:
                    painter.setPen(QPen(QColor("#e2e8f0"), 1, Qt.PenStyle.DashLine))
                    painter.drawRoundedRect(rect_right, 2, 2)
                    painter.setPen(QColor("#94a3b8"))
                    painter.setFont(QFont("sans-serif", max(8, int(10 * self.zoom_factor))))
                    painter.drawText(rect_right, Qt.AlignmentFlag.AlignCenter, "[ Halaman Selanjutnya ]")

                # Center Fold / Spine Line
                center_x = sheet_x + (sheet_w / 2.0)
                if self.booklet:
                    # Spine fold line with staple markers
                    spine_pen = QPen(QColor("#0284c7"), 1.5, Qt.PenStyle.DashDotLine)
                    painter.setPen(spine_pen)
                    painter.drawLine(QPointF(center_x, sheet_y + 4), QPointF(center_x, sheet_y + sheet_h - 4))

                    # Saddle-Stitch Staples
                    staple_pen = QPen(QColor("#0f172a"), 3)
                    painter.setPen(staple_pen)
                    painter.drawLine(QPointF(center_x, sheet_y + sheet_h * 0.22), QPointF(center_x, sheet_y + sheet_h * 0.28))
                    painter.drawLine(QPointF(center_x, sheet_y + sheet_h * 0.72), QPointF(center_x, sheet_y + sheet_h * 0.78))
                else:
                    # Simple 2-Up dividing border line
                    div_pen = QPen(QColor("#94a3b8"), 1, Qt.PenStyle.SolidLine)
                    painter.setPen(div_pen)
                    painter.drawLine(QPointF(center_x, sheet_y + 8), QPointF(center_x, sheet_y + sheet_h - 8))

            elif self.n_up == 4:
                # 4-Up Grid
                pad = 8 * self.zoom_factor
                cell_w = (sheet_w - (pad * 3)) / 2.0
                cell_h = (sheet_h - (pad * 3)) / 2.0

                r1 = QRectF(sheet_x + pad, sheet_y + pad, cell_w, cell_h)
                r2 = QRectF(sheet_x + pad * 2 + cell_w, sheet_y + pad, cell_w, cell_h)
                r3 = QRectF(sheet_x + pad, sheet_y + pad * 2 + cell_h, cell_w, cell_h)
                r4 = QRectF(sheet_x + pad * 2 + cell_w, sheet_y + pad * 2 + cell_h, cell_w, cell_h)

                target_4up_size = QSize(int(cell_w * self.content_scale), int(cell_h * self.content_scale))
                scaled_p1 = self.pixmap_p1.scaled(
                    target_4up_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                painter.save()
                painter.setClipRect(r1)
                painter.drawPixmap(int(r1.x() + (r1.width() - scaled_p1.width()) / 2.0),
                                   int(r1.y() + (r1.height() - scaled_p1.height()) / 2.0), scaled_p1)
                painter.restore()
                for r, txt in [(r2, "Hlm +1"), (r3, "Hlm +2"), (r4, "Hlm +3")]:
                    painter.setPen(QPen(QColor("#e2e8f0"), 1, Qt.PenStyle.DashLine))
                    painter.drawRect(r)
                    painter.setPen(QColor("#94a3b8"))
                    painter.setFont(QFont("sans-serif", max(7, int(9 * self.zoom_factor))))
                    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)
        else:
            # Placeholder text inside blank paper
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont("sans-serif", 13, QFont.Weight.Medium))
            painter.drawText(sheet_rect, Qt.AlignmentFlag.AlignCenter, "Silakan buka berkas PDF\nuntuk pratinjau lembar cetak")

        # 5. Printable Margins Boundary (PPD ImageableArea exact hardware limits)
        if self.show_margins:
            fl, ft, fr, fb = self._get_ppd_margin_fracs(is_landscape_sheet)
            margin_bound = sheet_rect.adjusted(
                fl * sheet_rect.width(),
                ft * sheet_rect.height(),
                -fr * sheet_rect.width(),
                -fb * sheet_rect.height(),
            )
            is_overflow = False
            if scaled_pixmap_dim and (scaled_pixmap_dim.width() > margin_bound.width() * 1.01 or scaled_pixmap_dim.height() > margin_bound.height() * 1.01):
                is_overflow = True
            margin_col = QColor("#f59e0b") if is_overflow else QColor("#f43f5e")
            margin_pen = QPen(margin_col, 1.2 if is_overflow else 1, Qt.PenStyle.DashLine if is_overflow else Qt.PenStyle.DotLine)
            painter.setPen(margin_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(margin_bound)

        # 5b. Binding Gutter Guide Line
        if self.binding_gutter_mm > 0:
            paper_w_mm = 215.9 if self.paper_code in ("F4", "Folio") else (148.0 if self.paper_code == "A5" else 210.0)
            gx = sheet_rect.x() + (self.binding_gutter_mm / paper_w_mm) * sheet_rect.width()
            painter.save()
            painter.setPen(QPen(QColor("#0ea5e9"), 1.3, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(gx, sheet_rect.top() + 4), QPointF(gx, sheet_rect.bottom() - 4))
            painter.restore()

        # 6. Watermark Overlay (Real-time Canvas Rendering)
        if self.watermark_text:
            painter.save()
            painter.translate(sheet_rect.center())
            painter.rotate(-45)
            wm_font = QFont("sans-serif", int(sheet_w * 0.11), QFont.Weight.Bold)
            painter.setFont(wm_font)
            painter.setPen(QColor(220, 38, 38, 70))  # Semi-transparent red
            text_rect = QRectF(-sheet_w / 2.0, -50, sheet_w, 100)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.watermark_text)
            painter.restore()

        # 7. Paper Tag in Corner
        painter.setFont(QFont("sans-serif", 10, QFont.Weight.Medium))
        tag_text = f"📄 {self.paper_name} • {'Mendatar (Landscape)' if is_landscape_sheet else 'Tegak (Portrait)'} • Skala Konten {int(self.content_scale * 100)}% • 600 DPI"
        painter.setPen(QColor("#64748b"))
        painter.drawText(QRectF(16, h - 22, w - 32, 18), Qt.AlignmentFlag.AlignRight, tag_text)


# ==============================================================================
# SECTION HEADER FACTORY
# ==============================================================================
def make_section_header(title: str, icon: str = "") -> QLabel:
    text = f"{icon} {title}".strip() if icon else title
    lbl = QLabel(text)
    lbl.setStyleSheet("""
        font-size: 11px;
        font-weight: 800;
        color: #38bdf8;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        margin-top: 2px;
        margin-bottom: 2px;
        background: transparent;
        border: none;
    """)
    return lbl


# ==============================================================================
# INTERACTIVE VISUAL CARD SELECTOR
# ==============================================================================
class VisualCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, card_id: str, title: str, subtitle: str, icon_str: str, parent=None, is_compact: bool = False):
        super().__init__(parent)
        self.card_id = card_id
        self.is_selected = False
        self.is_compact = is_compact
        self.setObjectName("VisualCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.NoFrame)

        # Dynamic Drop Shadow for elevation
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(6)
        self.shadow.setColor(QColor(0, 0, 0, 60))
        self.shadow.setOffset(0, 2)
        self.setGraphicsEffect(self.shadow)

        self.anim = QPropertyAnimation(self.shadow, b"blurRadius")
        self.anim.setDuration(120)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        if is_compact:
            # Vertically stacked compact tile (perfect for 3-across rows with ZERO text clipping)
            self.setFixedHeight(68)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setSpacing(2)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)
            self.lbl_icon = QLabel(icon_str)
            self.lbl_icon.setStyleSheet("font-size: 18px; background: transparent; border: none;")
            top_row.addWidget(self.lbl_icon)

            self.lbl_title = QLabel(title)
            self.lbl_title.setStyleSheet("font-weight: 700; font-size: 12px; color: #f8fafc; background: transparent; border: none;")
            self.lbl_title.setWordWrap(True)
            top_row.addWidget(self.lbl_title, stretch=1)

            self.lbl_check = QLabel("○")
            self.lbl_check.setStyleSheet("font-size: 13px; color: #475569; background: transparent; border: none;")
            top_row.addWidget(self.lbl_check)
            layout.addLayout(top_row)

            self.lbl_sub = QLabel(subtitle)
            self.lbl_sub.setWordWrap(True)
            self.lbl_sub.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent; border: none;")
            layout.addWidget(self.lbl_sub)
        else:
            # Full-width horizontal console card
            self.setMinimumHeight(56)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(12)

            self.lbl_icon = QLabel(icon_str)
            self.lbl_icon.setFixedSize(38, 38)
            self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_icon.setStyleSheet("""
                font-size: 20px;
                background-color: #0d1728;
                border: 1px solid #1e293b;
                border-radius: 6px;
            """)
            layout.addWidget(self.lbl_icon)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)
            self.lbl_title = QLabel(title)
            self.lbl_title.setStyleSheet("font-weight: 700; font-size: 13px; color: #f8fafc; background: transparent; border: none;")
            self.lbl_title.setWordWrap(True)

            self.lbl_sub = QLabel(subtitle)
            self.lbl_sub.setWordWrap(True)
            self.lbl_sub.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; border: none;")

            text_layout.addWidget(self.lbl_title)
            text_layout.addWidget(self.lbl_sub)
            layout.addLayout(text_layout, stretch=1)

            self.lbl_check = QLabel("○")
            self.lbl_check.setStyleSheet("font-size: 15px; color: #475569; background: transparent; border: none;")
            layout.addWidget(self.lbl_check)

        self.update_appearance()

    def enterEvent(self, event):
        self.anim.stop()
        self.anim.setStartValue(self.shadow.blurRadius())
        self.anim.setEndValue(14)
        if self.is_selected:
            self.shadow.setColor(QColor(14, 165, 233, 140))
        else:
            self.shadow.setColor(QColor(30, 41, 59, 120))
        self.shadow.setOffset(0, 3)
        self.anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.anim.stop()
        self.anim.setStartValue(self.shadow.blurRadius())
        self.anim.setEndValue(8 if self.is_selected else 6)
        if self.is_selected:
            self.shadow.setColor(QColor(14, 165, 233, 90))
        else:
            self.shadow.setColor(QColor(0, 0, 0, 60))
        self.shadow.setOffset(0, 2)
        self.anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.shadow.setBlurRadius(2)
            self.shadow.setOffset(0, 1)
            self.clicked.emit(self.card_id)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.shadow.setOffset(0, 2)
        self.anim.stop()
        self.anim.setStartValue(2)
        self.anim.setEndValue(14 if self.underMouse() else (8 if self.is_selected else 6))
        self.anim.start()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.lbl_check.setText("✓" if selected else "○")
        self.lbl_check.setStyleSheet("font-size: 14px; font-weight: 800; color: #38bdf8;" if selected else "font-size: 14px; font-weight: 400; color: #475569;")
        if selected:
            self.shadow.setColor(QColor(14, 165, 233, 90))
            self.shadow.setBlurRadius(8)
        else:
            self.shadow.setColor(QColor(0, 0, 0, 60))
            self.shadow.setBlurRadius(6)
        self.update_appearance()

    def update_appearance(self):
        if self.is_selected:
            self.setStyleSheet("""
                QFrame#VisualCard {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0c2340, stop:1 #0f2d52);
                    border: 1.5px solid #0ea5e9;
                    border-radius: 8px;
                }
                QFrame#VisualCard QLabel {
                    background: transparent;
                    border: none;
                }
            """)
            if hasattr(self, "lbl_title"):
                self.lbl_title.setStyleSheet("font-weight: 700; font-size: 12px; color: #ffffff; background: transparent; border: none;")
            if hasattr(self, "lbl_sub"):
                self.lbl_sub.setStyleSheet("font-size: 10px; color: #7dd3fc; background: transparent; border: none;")
        else:
            self.setStyleSheet("""
                QFrame#VisualCard {
                    background-color: #0b1322;
                    border: 1px solid #1e293b;
                    border-radius: 8px;
                }
                QFrame#VisualCard:hover {
                    background-color: #111c30;
                    border-color: #38bdf8;
                }
                QFrame#VisualCard QLabel {
                    background: transparent;
                    border: none;
                }
            """)
            if hasattr(self, "lbl_title"):
                self.lbl_title.setStyleSheet("font-weight: 700; font-size: 12px; color: #f1f5f9; background: transparent; border: none;")
            if hasattr(self, "lbl_sub"):
                self.lbl_sub.setStyleSheet("font-size: 10px; color: #94a3b8; background: transparent; border: none;")


# ==============================================================================
# MAIN WINPRINT STUDIO WINDOW
# ==============================================================================
class WinPrintStudio(QMainWindow):
    def __init__(self, initial_pdf: str = None, job_meta: dict = None):
        super().__init__()
        self.setWindowTitle("WinPrint Studio Enterprise — Brother Workstation")
        self.resize(1260, 840)
        self.setMinimumSize(1040, 720)

        self.cfg = winprint_spooler.get_config()
        self.job_meta = dict(job_meta or {})
        req_model = self.job_meta.get("printer") or self.cfg.get("printer_model", "Brother DCP-B7640DW")
        if req_model not in ("Brother DCP-B7640DW", "Brother DCP-L2540DW"):
            req_model = "Brother DCP-B7640DW"
        self.printer_model = req_model

        known_ips = self.cfg.get("known_printers") if isinstance(self.cfg.get("known_printers"), dict) else {}
        self.printer_ip = (
            known_ips.get(self.printer_model)
            or (self.cfg.get("printer_ip") if self.cfg.get("printer_model", "Brother DCP-B7640DW") == self.printer_model else None)
            or brother_snmp.PRINTER_CATALOG.get(self.printer_model, {}).get("default_ip", "192.168.100.229")
        )
        self.current_pdf = None
        self.original_document_name = None
        self._owned_temp_files = set()
        self._retired_threads = []
        self.detected_doc_media = None
        self.detected_tray_media = None
        self.total_pages = 1
        self.current_page = 1
        self.zoom_factor = 1.0
        self.current_content_scale = 100
        self.auto_rotate_content = True
        self.selected_orientation = "auto"
        self.detected_doc_landscape = False
        self.sp_copies_quick = None
        self.btn_copy_presets = []

        # Enable Drag-and-Drop of any document/image onto window
        self.setAcceptDrops(True)

        # Apply global stylesheet
        self.setStyleSheet(ENTERPRISE_STYLE)

        self.init_ui()
        self.init_shortcuts()
        self._sync_printer_ui_labels()
        self.refresh_calibration_spinboxes()

        # Telemetry Probe
        self.refresh_telemetry()

        # Load initial document if provided (PDF, Word, Excel, Image, Text, HTML)
        if initial_pdf and os.path.exists(initial_pdf):
            self.load_document(
                initial_pdf,
                display_name=self.job_meta.get("job_name"),
                cleanup_source=bool(self.job_meta.get("cleanup_temp", False)),
            )
            if self.job_meta.get("copies"):
                self.set_copies_count(int(self.job_meta["copies"]))
            if self.job_meta.get("duplex") in ("none", "long", "short"):
                self.select_duplex_mode(self.job_meta["duplex"])
            if not self.detected_doc_media and self.job_meta.get("paper"):
                self._select_paper_by_code(self.job_meta["paper"])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path):
                self.load_document(file_path)
                break

    def init_ui(self):
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # 1. COMMAND DECK & TELEMETRY HEADER
        main_layout.addWidget(self.create_command_header())

        # 2. EXECUTIVE PRESETS RIBBON
        main_layout.addWidget(self.create_presets_ribbon())

        # 3. SPLIT WORKSTATION: DRAFTING CANVAS (LEFT) + SETTINGS DECK (RIGHT)
        workstation_splitter = QSplitter(Qt.Orientation.Horizontal)
        workstation_splitter.setHandleWidth(8)
        workstation_splitter.setStyleSheet("QSplitter::handle { background: #1e293b; border-radius: 4px; }")

        workstation_splitter.addWidget(self.create_canvas_panel())
        workstation_splitter.addWidget(self.create_settings_deck())
        workstation_splitter.setStretchFactor(0, 5)
        workstation_splitter.setStretchFactor(1, 5)
        workstation_splitter.setSizes([680, 560])

        main_layout.addWidget(workstation_splitter, stretch=1)

        # 4. MASTER EXECUTION & SUMMARY DECK
        main_layout.addWidget(self.create_execution_deck())

    # ==========================================================================
    # 1. COMMAND DECK & HARDWARE TELEMETRY HEADER
    # ==========================================================================
    def create_command_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("CommandHeader")
        frame.setStyleSheet("""
            QFrame#CommandHeader {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:1 #020617);
                border: 1px solid #1e293b;
                border-radius: 10px;
            }
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        # Device Identity & Printer Selector Card
        id_box = QFrame()
        id_box.setMinimumHeight(76)
        id_box.setStyleSheet("background: transparent; border: none;")
        id_layout = QVBoxLayout(id_box)
        id_layout.setContentsMargins(4, 2, 4, 2)
        id_layout.setSpacing(3)

        lbl_brand = QLabel("BROTHER ENTERPRISE PRINTING SUBSYSTEM")
        lbl_brand.setStyleSheet("font-size: 9px; font-weight: 700; color: #0284c7; letter-spacing: 0.5px;")

        self.cb_printer_select = QComboBox()
        self.cb_printer_select.setMinimumWidth(245)
        self.cb_printer_select.setFixedHeight(28)
        self.cb_printer_select.setStyleSheet(
            "QComboBox { padding: 3px 10px; font-size: 12px; font-weight: 700; }"
        )
        self.cb_printer_select.addItem("Brother DCP-B7640DW (PCL / F4 Calibrated)", "Brother DCP-B7640DW")
        self.cb_printer_select.addItem("Brother DCP-L2540DW (PCL Laser)", "Brother DCP-L2540DW")
        sel_idx = self.cb_printer_select.findData(self.printer_model)
        if sel_idx >= 0:
            self.cb_printer_select.setCurrentIndex(sel_idx)
        self.cb_printer_select.currentIndexChanged.connect(self.on_printer_selected)

        self.lbl_conn_status = QLabel(f"ONLINE • {self.printer_ip}:9100 RAW")
        self.lbl_conn_status.setStyleSheet("font-size: 11px; font-weight: 500; color: #10b981;")

        id_layout.addWidget(lbl_brand)
        id_layout.addWidget(self.cb_printer_select)
        id_layout.addWidget(self.lbl_conn_status)
        layout.addWidget(id_box)

        # Authentic Backlit OLED Mirror Display
        oled_box = QFrame()
        oled_box.setFixedSize(170, 72)
        oled_box.setStyleSheet("""
            QFrame {
                background-color: #041014;
                border: 1.5px solid #083344;
                border-radius: 6px;
            }
        """)
        oled_layout = QVBoxLayout(oled_box)
        oled_layout.setContentsMargins(8, 6, 8, 6)
        oled_layout.setSpacing(2)

        lbl_lcd_header = QLabel("PANEL LCD MIRROR")
        lbl_lcd_header.setStyleSheet("font-size: 9px; color: #0891b2; font-weight: bold; letter-spacing: 0.5px;")
        self.lbl_oled_display = QLabel('[ "Menghubungkan..." ]')
        self.lbl_oled_display.setStyleSheet("""
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 13px;
            font-weight: bold;
            color: #22d3ee;
        """)
        oled_layout.addWidget(lbl_lcd_header)
        oled_layout.addWidget(self.lbl_oled_display)
        oled_layout.addStretch()
        layout.addWidget(oled_box)

        # Toner TN-B028 Telemetry Card
        toner_box = QFrame()
        toner_box.setStyleSheet("background-color: #0b1424; border: 1px solid #1e293b; border-radius: 6px;")
        toner_box.setFixedSize(165, 72)
        t_layout = QVBoxLayout(toner_box)
        t_layout.setContentsMargins(10, 6, 10, 6)
        t_layout.setSpacing(2)

        t_top = QHBoxLayout()
        t_top.setContentsMargins(0, 0, 0, 0)
        self.lbl_t_name = QLabel("TONER TN-B028")
        self.lbl_t_name.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        t_top.addWidget(self.lbl_t_name)
        t_top.addStretch()

        self.lbl_t_badge = QLabel("OPTIMAL")
        self.lbl_t_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #34d399; background: #064e3b; border-radius: 3px; padding: 1px 4px;")
        t_top.addWidget(self.lbl_t_badge)
        t_layout.addLayout(t_top)

        t_mid = QHBoxLayout()
        t_mid.setContentsMargins(0, 0, 0, 0)
        self.lbl_t_val = QLabel("100%")
        self.lbl_t_val.setStyleSheet("font-size: 17px; font-weight: 800; color: #38bdf8;")
        t_mid.addWidget(self.lbl_t_val)
        lbl_t_sub = QLabel("Tersisa")
        lbl_t_sub.setStyleSheet("font-size: 10px; color: #64748b; margin-top: 4px;")
        t_mid.addWidget(lbl_t_sub)
        t_mid.addStretch()
        t_layout.addLayout(t_mid)

        self.toner_bar = QProgressBar()
        self.toner_bar.setFixedHeight(5)
        self.toner_bar.setRange(0, 100)
        self.toner_bar.setValue(100)
        self.toner_bar.setTextVisible(False)
        self.toner_bar.setStyleSheet("""
            QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8); border-radius: 2px; }
        """)
        t_layout.addWidget(self.toner_bar)
        layout.addWidget(toner_box)

        # Drum DR-B028 Telemetry Card
        drum_box = QFrame()
        drum_box.setStyleSheet("background-color: #0b1424; border: 1px solid #1e293b; border-radius: 6px;")
        drum_box.setFixedSize(165, 72)
        d_layout = QVBoxLayout(drum_box)
        d_layout.setContentsMargins(10, 6, 10, 6)
        d_layout.setSpacing(2)

        d_top = QHBoxLayout()
        d_top.setContentsMargins(0, 0, 0, 0)
        self.lbl_d_name = QLabel("DRUM DR-B028")
        self.lbl_d_name.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        d_top.addWidget(self.lbl_d_name)
        d_top.addStretch()

        self.lbl_d_badge = QLabel("NORMAL")
        self.lbl_d_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #fbbf24; background: #78350f; border-radius: 3px; padding: 1px 4px;")
        d_top.addWidget(self.lbl_d_badge)
        d_layout.addLayout(d_top)

        d_mid = QHBoxLayout()
        d_mid.setContentsMargins(0, 0, 0, 0)
        self.lbl_d_val = QLabel("57%")
        self.lbl_d_val.setStyleSheet("font-size: 17px; font-weight: 800; color: #f59e0b;")
        d_mid.addWidget(self.lbl_d_val)
        lbl_d_sub = QLabel("Masa Pakai")
        lbl_d_sub.setStyleSheet("font-size: 10px; color: #64748b; margin-top: 4px;")
        d_mid.addWidget(lbl_d_sub)
        d_mid.addStretch()
        d_layout.addLayout(d_mid)

        self.drum_bar = QProgressBar()
        self.drum_bar.setFixedHeight(5)
        self.drum_bar.setRange(0, 100)
        self.drum_bar.setValue(57)
        self.drum_bar.setTextVisible(False)
        self.drum_bar.setStyleSheet("""
            QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
            QProgressBar::chunk { background: #f59e0b; border-radius: 2px; }
        """)
        d_layout.addWidget(self.drum_bar)
        layout.addWidget(drum_box)

        layout.addStretch()

        # Telemetry Refresh Action
        btn_refresh = AnimatedButton("🔄 Segarkan", accent_color="#38bdf8")
        btn_refresh.setFixedHeight(36)
        btn_refresh.clicked.connect(self.refresh_telemetry)
        layout.addWidget(btn_refresh)

        # Open Web EWS Console
        btn_ews = AnimatedButton("🌐 Web Admin", accent_color="#0ea5e9")
        btn_ews.setFixedHeight(36)
        btn_ews.setToolTip("Buka Brother Web-Based Management (Port 80)")
        btn_ews.clicked.connect(self.open_ews_browser)
        layout.addWidget(btn_ews)

        return frame

    # ==========================================================================
    # 2. EXECUTIVE PRESETS RIBBON (ONE-CLICK PROFILES)
    # ==========================================================================
    def create_presets_ribbon(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl = QLabel("Profil Tugas Cepat:")
        lbl.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 12px;")
        layout.addWidget(lbl)

        presets = [
            ("📋 Ujian / Soal F4 Duplex", self.apply_preset_ujian, "#0284c7"),
            ("📚 Modul Belajar (2-Up)", self.apply_preset_modul, "#0f766e"),
            ("📖 Buku Lipat (Buklet F4)", self.apply_preset_booklet, "#6366f1"),
            ("📜 Dokumen Resmi A4", self.apply_preset_surat, "#334155"),
            ("⚡ Draft Hemat Toner", self.apply_preset_draft, "#047857")
        ]

        for title, handler, border_color in presets:
            btn = AnimatedButton(title, accent_color=border_color)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #0d1524;
                    border: 1px solid #1e293b;
                    border-left: 3.5px solid {border_color};
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-size: 12px;
                    font-weight: 600;
                    color: #f1f5f9;
                }}
                QPushButton:hover {{
                    background-color: #162238;
                    color: #ffffff;
                    border-color: {border_color};
                }}
            """)
            btn.clicked.connect(handler)
            layout.addWidget(btn)

        layout.addStretch()
        return widget

    # ==========================================================================
    # 3. DRAFTING CANVAS PANEL (LEFT)
    # ==========================================================================
    def create_canvas_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # File Select & Title Bar
        top_bar = QHBoxLayout()
        self.lbl_doc_title = QLabel("Belum ada dokumen terbuka")
        self.lbl_doc_title.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
        top_bar.addWidget(self.lbl_doc_title, stretch=1)

        btn_browse = AnimatedButton("📂 Buka Dokumen...", accent_color="#0284c7", is_primary=True)
        btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: white;
                font-weight: 700;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #0ea5e9;
            }
        """)
        btn_browse.clicked.connect(self.select_document_dialog)
        top_bar.addWidget(btn_browse)

        layout.addLayout(top_bar)

        # Canvas Scroll Area
        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas_scroll.setStyleSheet("QScrollArea { border: 1px solid #1e293b; border-radius: 8px; background: #070b13; }")

        self.paper_canvas = RealisticPaperCanvas()
        self.canvas_scroll.setWidget(self.paper_canvas)
        self.canvas_scroll.setWidgetResizable(True)
        layout.addWidget(self.canvas_scroll, stretch=1)

        # Canvas Control Toolbar
        bar = QHBoxLayout()
        self.btn_prev = AnimatedButton("◀ Sebelumnya", accent_color="#38bdf8")
        self.btn_prev.clicked.connect(self.prev_page)
        bar.addWidget(self.btn_prev)

        self.lbl_page_counter = QLabel("Halaman 0 / 0")
        self.lbl_page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_counter.setStyleSheet("font-weight: 700; color: #38bdf8; min-width: 110px;")
        bar.addWidget(self.lbl_page_counter)

        self.btn_next = AnimatedButton("Selanjutnya ▶", accent_color="#38bdf8")
        self.btn_next.clicked.connect(self.next_page)
        bar.addWidget(self.btn_next)

        bar.addSpacing(16)
        btn_zoom_out = AnimatedButton("−", accent_color="#38bdf8")
        btn_zoom_out.setToolTip("Perkecil Tampilan (Ctrl + Scroll Down)")
        btn_zoom_out.setFixedSize(32, 32)
        btn_zoom_out.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_zoom_out.clicked.connect(self.zoom_out)
        bar.addWidget(btn_zoom_out)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_zoom.setStyleSheet("font-size: 11px; color: #38bdf8; font-weight: 700; min-width: 44px;")
        bar.addWidget(self.lbl_zoom)

        btn_zoom_in = AnimatedButton("+", accent_color="#38bdf8")
        btn_zoom_in.setToolTip("Perbesar Tampilan (Ctrl + Scroll Up)")
        btn_zoom_in.setFixedSize(32, 32)
        btn_zoom_in.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_zoom_in.clicked.connect(self.zoom_in)
        bar.addWidget(btn_zoom_in)

        btn_zoom_reset = AnimatedButton("Fit 100%", accent_color="#38bdf8")
        btn_zoom_reset.setToolTip("Reset Zoom ke Ukuran Standar")
        btn_zoom_reset.setFixedHeight(32)
        btn_zoom_reset.clicked.connect(self.zoom_reset)
        bar.addWidget(btn_zoom_reset)

        bar.addSpacing(12)
        self.chk_show_margin = QCheckBox("Batas Margin 4mm")
        self.chk_show_margin.setChecked(True)
        self.chk_show_margin.toggled.connect(self.toggle_margins)
        bar.addWidget(self.chk_show_margin)

        bar.addSpacing(8)
        self.chk_duplex_xray = QCheckBox("Terawang Sisi Belakang")
        self.chk_duplex_xray.setToolTip("Tampilkan bayangan transparan halaman pasangan bolak-balik pada kertas")
        self.chk_duplex_xray.setChecked(False)
        self.chk_duplex_xray.toggled.connect(self.toggle_duplex_xray)
        bar.addWidget(self.chk_duplex_xray)

        bar.addStretch()
        layout.addLayout(bar)

        return panel

    # ==========================================================================
    # 4. SETTINGS DECK (ERGONOMIC 5-TAB WORKSTATION)
    # ==========================================================================
    def create_settings_deck(self) -> QWidget:
        deck = QWidget()
        layout = QVBoxLayout(deck)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.tab_paper_orientation(), "📄 Kertas & Format")
        self.tabs.addTab(self.tab_layout_imposition(), "📑 Tata Letak")
        self.tabs.addTab(self.tab_duplex_finishing(), "🔄 Bolak-Balik")
        self.tabs.addTab(self.tab_quality_toner(), "🌿 Kualitas & Tinta")
        self.tabs.addTab(self.tab_range_collate(), "🔢 Halaman & Cap")

        layout.addWidget(self.tabs)
        return deck

    # Tab 1: Paper & Orientation & Scaling
    def tab_paper_orientation(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(7)
        layout.setContentsMargins(12, 8, 12, 8)

        # 1. Hardware Paper Size
        layout.addWidget(make_section_header("Ukuran Kertas Fisik (Hardware Tray):", "📄"))
        self.cb_paper = QComboBox()
        self.cb_paper.addItems([
            "F4 / Folio (Standar Indonesia: 215 x 330 mm)",
            "A4 (Standar Internasional: 210 x 297 mm)",
            "Legal (Standar USA: 216 x 356 mm)",
            "Letter (8.5 x 11 inci: 216 x 279 mm)",
            "A5 (Buku Saku: 148 x 210 mm)"
        ])
        self.cb_paper.currentIndexChanged.connect(self.on_paper_changed)
        layout.addWidget(self.cb_paper)

        # Tray & Media Type (2 columns)
        media_box = QHBoxLayout()
        media_box.setSpacing(8)

        v1 = QVBoxLayout()
        v1.setSpacing(4)
        v1.addWidget(QLabel("<span style='font-size: 11px; font-weight: 600; color: #94a3b8;'>Baki Kertas:</span>"))
        self.cb_tray = QComboBox()
        self.cb_tray.addItems(["Otomatis (Auto Select)", "Baki Utama 1 (Tray 1 - 250 lbr)", "Slot Manual (Bypass Depan)"])
        v1.addWidget(self.cb_tray)
        media_box.addLayout(v1)

        v2 = QVBoxLayout()
        v2.setSpacing(4)
        v2.addWidget(QLabel("<span style='font-size: 11px; font-weight: 600; color: #94a3b8;'>Tipe Media:</span>"))
        self.cb_media = QComboBox()
        self.cb_media.addItems(["Kertas Biasa (Plain 60-105 g/m²)", "Kertas Tebal (Thick 105-163 g/m²)", "Kertas Daur Ulang", "Stiker Label / Amplop"])
        v2.addWidget(self.cb_media)
        media_box.addLayout(v2)
        layout.addLayout(media_box)

        layout.addSpacing(4)

        # 2. Page Orientation Cards
        layout.addWidget(make_section_header("Orientasi Dokumen & Kertas:", "🧭"))
        self.cards_orientation = {}
        orient_layout = QHBoxLayout()
        orient_layout.setSpacing(8)

        c_auto = VisualCard("auto", "Otomatis", "Ikuti format PDF", "🔄", is_compact=True)
        c_port = VisualCard("portrait", "Tegak", "Portrait vertikal", "📄", is_compact=True)
        c_land = VisualCard("landscape", "Mendatar", "Landscape horizontal", "📃", is_compact=True)

        for card in [c_auto, c_port, c_land]:
            self.cards_orientation[card.card_id] = card
            card.clicked.connect(self.select_orientation_mode)
            orient_layout.addWidget(card)

        c_auto.set_selected(True)
        self.selected_orientation = "auto"
        layout.addLayout(orient_layout)

        self.chk_auto_rotate = QCheckBox("Putar isi dokumen 90° jika orientasi kertas berbeda")
        self.chk_auto_rotate.setChecked(True)
        self.chk_auto_rotate.toggled.connect(self.on_auto_rotate_toggled)
        layout.addWidget(self.chk_auto_rotate)

        layout.addSpacing(4)

        # 3. Content Scaling Group
        layout.addWidget(make_section_header("Skala Konten (Smart Scaling Fit):", "🔍"))
        self.grp_scaling = QFrame()
        self.grp_scaling.setStyleSheet("background: #0b1424; border: 1px solid #1e293b; border-radius: 8px;")
        scale_box = QVBoxLayout(self.grp_scaling)
        scale_box.setSpacing(8)
        scale_box.setContentsMargins(10, 10, 10, 10)

        # Preset buttons grid
        preset_layout = QGridLayout()
        preset_layout.setSpacing(6)

        self.btn_scale_100 = AnimatedButton("100% (Normal)", accent_color="#38bdf8")
        self.btn_scale_100.setFixedHeight(34)
        self.btn_scale_100.clicked.connect(lambda: self.set_scale_value(100))
        preset_layout.addWidget(self.btn_scale_100, 0, 0)

        self.btn_scale_fit = AnimatedButton("Pas Kertas (Fit)", accent_color="#38bdf8")
        self.btn_scale_fit.setFixedHeight(34)
        self.btn_scale_fit.clicked.connect(lambda: self.set_scale_value(100))
        preset_layout.addWidget(self.btn_scale_fit, 0, 1)

        self.btn_scale_f4 = AnimatedButton("🎯 Optimalkan ke F4 (+12%)", accent_color="#0ea5e9", is_primary=True)
        self.btn_scale_f4.setFixedHeight(34)
        self.btn_scale_f4.clicked.connect(lambda: self.set_scale_value(112))
        preset_layout.addWidget(self.btn_scale_f4, 1, 0)

        self.btn_scale_120 = AnimatedButton("Perbesar 120% (Penuh)", accent_color="#38bdf8")
        self.btn_scale_120.setFixedHeight(34)
        self.btn_scale_120.clicked.connect(lambda: self.set_scale_value(120))
        preset_layout.addWidget(self.btn_scale_120, 1, 1)

        scale_box.addLayout(preset_layout)

        # Precision stepper row
        slider_row = QHBoxLayout()
        slider_row.setSpacing(6)
        slider_row.addWidget(QLabel("<span style='font-size: 11px; font-weight: 600; color: #94a3b8;'>Skala:</span>"))

        btn_sc_minus = AnimatedButton("−", accent_color="#38bdf8")
        btn_sc_minus.setFixedSize(32, 32)
        btn_sc_minus.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_sc_minus.clicked.connect(lambda: self.adjust_scale_by(-5))
        slider_row.addWidget(btn_sc_minus)

        self.sp_content_scale = QSpinBox()
        self.sp_content_scale.setRange(50, 160)
        self.sp_content_scale.setValue(100)
        self.sp_content_scale.setSuffix(" %")
        self.sp_content_scale.setFixedSize(76, 32)
        self.sp_content_scale.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sp_content_scale.valueChanged.connect(self.on_scale_spinbox_changed)
        slider_row.addWidget(self.sp_content_scale)

        btn_sc_plus = AnimatedButton("+", accent_color="#38bdf8")
        btn_sc_plus.setFixedSize(32, 32)
        btn_sc_plus.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_sc_plus.clicked.connect(lambda: self.adjust_scale_by(5))
        slider_row.addWidget(btn_sc_plus)

        self.lbl_scale_info = QLabel("(Ukuran Standar 1:1)")
        self.lbl_scale_info.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600;")
        slider_row.addWidget(self.lbl_scale_info, stretch=1)
        scale_box.addLayout(slider_row)

        self.lbl_f4_hint = QLabel("💡 Tip: Dokumen A4 memiliki ruang sisa di lembar F4. Gunakan skala 112% agar teks & tabel memenuhi lembar F4 secara proporsional.")
        self.lbl_f4_hint.setWordWrap(True)
        self.lbl_f4_hint.setStyleSheet("font-size: 11px; color: #94a3b8; background: #070d18; padding: 6px 8px; border-radius: 6px; border: 1px solid #1e293b;")
        scale_box.addWidget(self.lbl_f4_hint)

        layout.addWidget(self.grp_scaling)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(w)
        return scroll

    # Tab 2: Layout & Imposition
    def tab_layout_imposition(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Imposition Selector (Cards)
        layout.addWidget(make_section_header("Format Imposisi Lembar (N-Up / Buklet):", "📑"))
        self.cards_imposition = {}
        imp_layout = QVBoxLayout()
        imp_layout.setSpacing(8)

        c1 = VisualCard("1up", "1 Halaman per Lembar (1-Up)", "Cetak ukuran penuh standar 1:1", "📄")
        c2 = VisualCard("2up", "2 Halaman per Lembar (2-Up)", "Modul hemat kertas berdampingan", "📑")
        c3 = VisualCard("4up", "4 Halaman per Lembar (4-Up)", "Handout presentasi / ringkasan kompak", "🗂️")
        c4 = VisualCard("booklet", "Pencetakan Buku Lipat (Saddle-Stitch Booklet)", "Imposisi otomatis lipat tengah siap jilid", "📖")

        for card in [c1, c2, c3, c4]:
            self.cards_imposition[card.card_id] = card
            card.clicked.connect(self.select_imposition_mode)
            imp_layout.addWidget(card)

        c1.set_selected(True)
        self.selected_imposition = "1up"
        layout.addLayout(imp_layout)

        layout.addSpacing(6)

        # Booklet Options Box
        self.grp_booklet_opts = QGroupBox("Pengaturan Tambahan Buku Lipat (Booklet)")
        b_layout = QVBoxLayout(self.grp_booklet_opts)
        b_layout.setSpacing(8)

        b_sub = QHBoxLayout()
        b_sub.addWidget(QLabel("Arah Penjilidan:"))
        self.cb_binding_dir = QComboBox()
        self.cb_binding_dir.addItems([
            "Jilid Kiri (Standar Buku Latin / Indonesia)",
            "Jilid Kanan (Standar Kitab / Al-Qur'an / Arab)"
        ])
        b_sub.addWidget(self.cb_binding_dir, stretch=1)
        b_layout.addLayout(b_sub)
        self.grp_booklet_opts.setVisible(False)
        layout.addWidget(self.grp_booklet_opts)

        # Border separator checkbox
        self.chk_border = QCheckBox("Garis Batas Pembagi Antar Halaman (Border Dividing Line)")
        layout.addWidget(self.chk_border)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(w)
        return scroll

    # Tab 3: Duplex & Finishing
    def tab_duplex_finishing(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(make_section_header("Mode Cetak Bolak-Balik Otomatis (Auto Duplex):", "🔄"))
        self.cards_duplex = {}
        dup_layout = QVBoxLayout()
        dup_layout.setSpacing(8)

        d1 = VisualCard("none", "Satu Sisi Saja (Simplex)", "Hanya mencetak pada sisi depan kertas", "📄")
        d2 = VisualCard("long", "Bolak-Balik Sisi Panjang (Long-Edge)", "Standar buku tegak / dokumen vertikal resmi", "🔄")
        d3 = VisualCard("short", "Bolak-Balik Sisi Pendek (Short-Edge)", "Standar kalender lipat / dokumen horizontal / buklet", "🔃")

        for card in [d1, d2, d3]:
            self.cards_duplex[card.card_id] = card
            card.clicked.connect(self.select_duplex_mode)
            dup_layout.addWidget(card)

        d2.set_selected(True)
        self.selected_duplex = "long"
        layout.addLayout(dup_layout)

        layout.addSpacing(8)
        layout.addWidget(make_section_header("Kompensasi Margin Jilid (Binding Shift / Gutter):", "📏"))
        self.cb_shift = QComboBox()
        self.cb_shift.addItems([
            "0 mm (Presisi Standar / Tanpa Pergeseran)",
            "5 mm (Jilid Ring Plastik / Spiral)",
            "10 mm (Jilid Lakban / Staples Tengah)",
            "15 mm (Jilid Hardcover Tebal)"
        ])
        self.cb_shift.currentIndexChanged.connect(self.on_shift_changed)
        layout.addWidget(self.cb_shift)

        lbl_hint = QLabel("💡 Memberikan ruang kosong ekstra di sisi jilid agar teks tidak tertutup saat dokumen dijilid atau dibundel.")
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("font-size: 11px; color: #94a3b8; background: #070d18; padding: 6px 8px; border-radius: 6px; border: 1px solid #1e293b; margin-top: 4px;")
        layout.addWidget(lbl_hint)

        layout.addSpacing(8)
        layout.addWidget(make_section_header("Kalibrasi Penjajaran Duplex Belakang (X / Y mm):", "⚖️"))

        calib_row = QHBoxLayout()
        calib_row.setSpacing(8)

        calib_row.addWidget(QLabel("<span style='font-size: 11px; font-weight: 600; color: #94a3b8;'>Geser X:</span>"))
        self.sp_calib_x_mm = QDoubleSpinBox()
        self.sp_calib_x_mm.setRange(-15.0, 15.0)
        self.sp_calib_x_mm.setSingleStep(0.1)
        self.sp_calib_x_mm.setDecimals(1)
        self.sp_calib_x_mm.setSuffix(" mm")
        self.sp_calib_x_mm.setFixedHeight(32)
        calib_row.addWidget(self.sp_calib_x_mm, stretch=1)

        calib_row.addWidget(QLabel("<span style='font-size: 11px; font-weight: 600; color: #94a3b8;'>Geser Y:</span>"))
        self.sp_calib_y_mm = QDoubleSpinBox()
        self.sp_calib_y_mm.setRange(-15.0, 15.0)
        self.sp_calib_y_mm.setSingleStep(0.1)
        self.sp_calib_y_mm.setDecimals(1)
        self.sp_calib_y_mm.setSuffix(" mm")
        self.sp_calib_y_mm.setFixedHeight(32)
        calib_row.addWidget(self.sp_calib_y_mm, stretch=1)

        layout.addLayout(calib_row)

        calib_btn_row = QHBoxLayout()
        calib_btn_row.setSpacing(8)

        self.btn_save_calib = AnimatedButton("Simpan Profil", accent_color="#0ea5e9", is_primary=True)
        self.btn_save_calib.setFixedHeight(32)
        self.btn_save_calib.clicked.connect(self.save_current_calibration_profile)
        calib_btn_row.addWidget(self.btn_save_calib, stretch=1)

        self.btn_reset_calib = AnimatedButton("Netral (0.0 mm)", accent_color="#64748b")
        self.btn_reset_calib.setFixedHeight(32)
        self.btn_reset_calib.clicked.connect(self.reset_calibration_spinboxes)
        calib_btn_row.addWidget(self.btn_reset_calib)

        layout.addLayout(calib_btn_row)

        self.btn_calib_3x2 = AnimatedButton("Cetak Lembar Kalibrasi 3x2", accent_color="#38bdf8")
        self.btn_calib_3x2.setFixedHeight(32)
        self.btn_calib_3x2.clicked.connect(self.load_calibration_3x2_sheet)
        layout.addWidget(self.btn_calib_3x2)

        self.lbl_calib_hint = QLabel("Nilai X/Y dimuat otomatis dari profil printer, ukuran kertas, dan mode duplex aktif.")
        self.lbl_calib_hint.setWordWrap(True)
        self.lbl_calib_hint.setStyleSheet("font-size: 11px; color: #38bdf8; background: #070d18; padding: 6px 8px; border-radius: 6px; border: 1px solid #1e293b; margin-top: 4px;")
        layout.addWidget(self.lbl_calib_hint)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(w)
        return scroll

    # Tab 4: Quality & Toner
    def tab_quality_toner(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(make_section_header("Resolusi Cetak Laser Brother:", "🖨️"))
        self.cb_res = QComboBox()
        self.cb_res.addItems([
            "600 dpi (Standar Rekomendasi - Tajam & Efisien)",
            "300 dpi (Draft Cepat - Sangat Ringan)",
            "1200 dpi (Presisi Tinggi - Teks Mikro & Grafik Halus)"
        ])
        layout.addWidget(self.cb_res)

        layout.addSpacing(6)
        layout.addWidget(make_section_header("Efisiensi Toner & Mode Operasi:", "🌿"))
        self.chk_tonersave = QCheckBox("Mode Hemat Toner (Economode / Perpanjang Umur TN-B028)")
        self.chk_tonersave.setStyleSheet("font-weight: 600; color: #10b981;")
        layout.addWidget(self.chk_tonersave)

        self.chk_quiet = QCheckBox("Mode Operasi Hening (Quiet Mode / Redam Suara Motor ke 20 ppm)")
        layout.addWidget(self.chk_quiet)

        layout.addSpacing(6)
        layout.addWidget(make_section_header("Kepekatan Tinta (Print Density Offset):", "🎚️"))
        self.slider_density = QSlider(Qt.Orientation.Horizontal)
        self.slider_density.setRange(-2, 2)
        self.slider_density.setValue(0)
        self.slider_density.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_density.setTickInterval(1)
        layout.addWidget(self.slider_density)

        lbl_den = QLabel("Lebih Hemat (-2)  ◄───  Standar Pabrik (0)  ───►  Lebih Pekat (+2)")
        lbl_den.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 500;")
        layout.addWidget(lbl_den)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(w)
        return scroll

    # Tab 5: Range & Copies & Watermark
    def tab_range_collate(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # 1. Jangkauan Halaman
        layout.addWidget(make_section_header("Filter Jangkauan Halaman Dokumen:", "🔢"))
        self.txt_range = QLineEdit("all")
        self.txt_range.setPlaceholderText("all, 1-10, 15, odd, even")
        self.txt_range.textChanged.connect(self.update_job_summary)
        layout.addWidget(self.txt_range)

        # Quick Range Pills
        chip_layout = QHBoxLayout()
        chip_layout.setSpacing(6)

        btn_r_all = AnimatedButton("Semua (all)", accent_color="#38bdf8")
        btn_r_all.setFixedHeight(28)
        btn_r_all.clicked.connect(lambda: self.txt_range.setText("all"))
        chip_layout.addWidget(btn_r_all)

        btn_r_odd = AnimatedButton("Halaman Ganjil (odd)", accent_color="#38bdf8")
        btn_r_odd.setFixedHeight(28)
        btn_r_odd.clicked.connect(lambda: self.txt_range.setText("odd"))
        chip_layout.addWidget(btn_r_odd)

        btn_r_even = AnimatedButton("Halaman Genap (even)", accent_color="#38bdf8")
        btn_r_even.setFixedHeight(28)
        btn_r_even.clicked.connect(lambda: self.txt_range.setText("even"))
        chip_layout.addWidget(btn_r_even)
        layout.addLayout(chip_layout)

        layout.addSpacing(4)
        self.chk_reverse = QCheckBox("Cetak Urutan Terbalik (Reverse Order: Akhir ke Awal)")
        layout.addWidget(self.chk_reverse)

        self.chk_collate = QCheckBox("Urutkan per Bundel Dokumen (Collate: 1-2-3, 1-2-3)")
        self.chk_collate.setChecked(True)
        layout.addWidget(self.chk_collate)

        layout.addSpacing(6)

        # 2. Rangkap (Copies) row - synchronized with bottom pod
        layout.addWidget(make_section_header("Pengaturan Rangkap (Copies):", "📋"))
        c_layout = QHBoxLayout()
        c_layout.setSpacing(8)
        c_layout.addWidget(QLabel("<span style='font-size: 12px; font-weight: 600; color: #f8fafc;'>Jumlah Rangkap:</span>"))

        self.sp_copies = QSpinBox()
        self.sp_copies.setRange(1, 999)
        self.sp_copies.setValue(1)
        self.sp_copies.setFixedSize(72, 32)
        self.sp_copies.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sp_copies.valueChanged.connect(self.set_copies_count)
        c_layout.addWidget(self.sp_copies)
        c_layout.addStretch()
        layout.addLayout(c_layout)

        layout.addSpacing(6)

        # 3. Watermark
        layout.addWidget(make_section_header("Tanda Air Dokumen (Watermark Stamp):", "🏷️"))
        self.cb_watermark = QComboBox()
        self.cb_watermark.addItems([
            "Tidak Ada",
            "DRAFT",
            "CONFIDENTIAL",
            "RAHASIA",
            "SALINAN RESMI",
            "CONTOH SOAL UJIAN",
            "ARSIP SEKOLAH",
            "Kustom Teks..."
        ])
        self.cb_watermark.currentTextChanged.connect(self.on_watermark_changed)
        layout.addWidget(self.cb_watermark)

        self.txt_custom_watermark = QLineEdit()
        self.txt_custom_watermark.setPlaceholderText("Ketik teks tanda air kustom di sini...")
        self.txt_custom_watermark.setEnabled(False)
        self.txt_custom_watermark.textChanged.connect(self.on_custom_watermark_changed)
        layout.addWidget(self.txt_custom_watermark)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(w)
        return scroll

    def tab_watermark_brand(self) -> QWidget:
        # Backward compatibility alias
        return self.tab_range_collate()

    # ==========================================================================
    # 5. MASTER EXECUTION & SUMMARY DECK (BOTTOM)
    # ==========================================================================
    def create_execution_deck(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ExecutionDeck")
        frame.setStyleSheet("""
            QFrame#ExecutionDeck {
                background-color: #070d18;
                border: 1px solid #1e293b;
                border-top: 2px solid #0284c7;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(6)

        # 1. Real-time Progress bar
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(5)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setStyleSheet("""
            QProgressBar { background: #070c16; border-radius: 2px; border: none; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:0.6 #0ea5e9, stop:1 #10b981);
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.pbar)

        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        # A. Job summary capsule
        summary_card = QFrame()
        summary_card.setStyleSheet("""
            QFrame {
                background-color: #0b1424;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)
        s_layout = QVBoxLayout(summary_card)
        s_layout.setContentsMargins(12, 6, 12, 6)
        s_layout.setSpacing(2)

        self.lbl_job_summary = QLabel()
        self.lbl_job_summary.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_job_summary.setStyleSheet("background: transparent; border: none;")
        s_layout.addWidget(self.lbl_job_summary)
        bottom_bar.addWidget(summary_card, stretch=1)

        # B. Prominent Copies Control Pod (Always Visible)
        copies_pod = QFrame()
        copies_pod.setStyleSheet("""
            QFrame {
                background-color: #0b1424;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)
        pod_layout = QHBoxLayout(copies_pod)
        pod_layout.setContentsMargins(10, 6, 10, 6)
        pod_layout.setSpacing(6)

        lbl_cp = QLabel("<b>RANGKAP:</b>")
        lbl_cp.setStyleSheet("font-size: 11px; font-weight: 800; color: #94a3b8; letter-spacing: 0.5px; border: none; background: transparent;")
        pod_layout.addWidget(lbl_cp)

        btn_c_minus = AnimatedButton("−", accent_color="#38bdf8")
        btn_c_minus.setToolTip("Kurangi 1 Rangkap")
        btn_c_minus.setFixedSize(30, 30)
        btn_c_minus.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_c_minus.clicked.connect(lambda: self.adjust_copies_by(-1))
        pod_layout.addWidget(btn_c_minus)

        self.sp_copies_quick = QSpinBox()
        self.sp_copies_quick.setRange(1, 999)
        self.sp_copies_quick.setValue(1)
        self.sp_copies_quick.setFixedSize(54, 30)
        self.sp_copies_quick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sp_copies_quick.setStyleSheet("""
            QSpinBox {
                background: #070d18;
                border: 1.5px solid #0284c7;
                border-radius: 5px;
                color: #38bdf8;
                font-size: 14px;
                font-weight: 800;
                padding: 1px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }
        """)
        self.sp_copies_quick.valueChanged.connect(self.set_copies_count)
        pod_layout.addWidget(self.sp_copies_quick)

        btn_c_plus = AnimatedButton("+", accent_color="#38bdf8")
        btn_c_plus.setToolTip("Tambah 1 Rangkap")
        btn_c_plus.setFixedSize(30, 30)
        btn_c_plus.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0;")
        btn_c_plus.clicked.connect(lambda: self.adjust_copies_by(1))
        pod_layout.addWidget(btn_c_plus)

        # Quick preset buttons (1x, 2x, 5x, 10x, 25x)
        self.btn_copy_presets = []
        for c_val in [1, 2, 5, 10, 25]:
            p_btn = AnimatedButton(f"{c_val}x", accent_color="#0ea5e9")
            p_btn.setToolTip(f"Set {c_val} Rangkap")
            p_btn.setFixedSize(34, 30)
            p_btn.clicked.connect(lambda checked=False, val=c_val: self.set_copies_count(val))
            pod_layout.addWidget(p_btn)
            self.btn_copy_presets.append((c_val, p_btn))

        bottom_bar.addWidget(copies_pod)

        # C. Master Action Buttons
        btn_export = AnimatedButton("💾 Ekspor PDF", accent_color="#64748b")
        btn_export.setFixedHeight(38)
        btn_export.setToolTip("Simpan berkas hasil imposisi ke PDF tanpa mencetak")
        btn_export.clicked.connect(self.export_imposed_pdf)
        bottom_bar.addWidget(btn_export)

        btn_test = AnimatedButton("📑 Uji", accent_color="#64748b")
        btn_test.setFixedHeight(38)
        btn_test.setToolTip("Cetak halaman pengujian kalibrasi Brother")
        btn_test.clicked.connect(self.print_test_page)
        bottom_bar.addWidget(btn_test)

        self.btn_print_master = AnimatedButton("🖨️ CETAK SEKARANG KE BROTHER", accent_color="#38bdf8", is_primary=True)
        self.btn_print_master.setFixedHeight(42)
        self.btn_print_master.setMinimumWidth(260)
        self.btn_print_master.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0ea5e9);
                color: #ffffff;
                font-weight: 800;
                font-size: 13px;
                letter-spacing: 0.5px;
                padding: 8px 20px;
                border-radius: 8px;
                border: 1px solid #38bdf8;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0284c7);
                border-color: #7dd3fc;
            }
            QPushButton:pressed {
                background-color: #0c4a6e;
                padding-top: 10px;
                padding-bottom: 6px;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                border-color: #334155;
                color: #64748b;
            }
        """)
        self.btn_print_master.clicked.connect(self.execute_print)
        bottom_bar.addWidget(self.btn_print_master)

        self.btn_cancel_print = AnimatedButton("Batal Kirim", accent_color="#f43f5e")
        self.btn_cancel_print.setFixedHeight(42)
        self.btn_cancel_print.setVisible(False)
        self.btn_cancel_print.clicked.connect(self.cancel_print_job)
        bottom_bar.addWidget(self.btn_cancel_print)

        layout.addLayout(bottom_bar)
        return frame

    def set_copies_count(self, count: int):
        count = max(1, min(999, int(count)))
        if hasattr(self, "sp_copies") and self.sp_copies.value() != count:
            self.sp_copies.blockSignals(True)
            self.sp_copies.setValue(count)
            self.sp_copies.blockSignals(False)
        if hasattr(self, "sp_copies_quick") and self.sp_copies_quick is not None and self.sp_copies_quick.value() != count:
            self.sp_copies_quick.blockSignals(True)
            self.sp_copies_quick.setValue(count)
            self.sp_copies_quick.blockSignals(False)
        
        # Highlight matching preset button
        if hasattr(self, "btn_copy_presets"):
            for val, btn in self.btn_copy_presets:
                if val == count:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #0284c7;
                            border: 1.5px solid #38bdf8;
                            border-radius: 4px;
                            color: #ffffff;
                            font-size: 11px;
                            font-weight: 800;
                            padding: 0;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #111a2e;
                            border: 1px solid #1e293b;
                            border-radius: 4px;
                            color: #cbd5e1;
                            font-size: 11px;
                            font-weight: 600;
                            padding: 0;
                        }
                        QPushButton:hover {
                            background-color: #1e293b;
                            color: #ffffff;
                            border-color: #0284c7;
                        }
                    """)

        self.update_job_summary()

    def adjust_copies_by(self, delta: int):
        curr_val = 1
        if hasattr(self, "sp_copies_quick") and self.sp_copies_quick is not None:
            curr_val = self.sp_copies_quick.value()
        elif hasattr(self, "sp_copies"):
            curr_val = self.sp_copies.value()
        self.set_copies_count(curr_val + delta)

    # ==========================================================================
    # LOGIC, SLOTS & EVENT HANDLERS
    # ==========================================================================
    def _current_paper_code(self) -> str:
        if not hasattr(self, "cb_paper"):
            return "F4"
        raw = self.cb_paper.currentText()
        if "F4" in raw or "Folio" in raw:
            return "F4"
        if "Legal" in raw:
            return "Legal"
        if "Letter" in raw:
            return "Letter"
        if "A5" in raw:
            return "A5"
        return "A4"

    def _select_paper_by_code(self, code: str):
        if not hasattr(self, "cb_paper"):
            return
        idx_map = {"F4": 0, "Folio": 0, "A4": 1, "Legal": 2, "Letter": 3, "A5": 4}
        idx = idx_map.get(code)
        if idx is not None and self.cb_paper.currentIndex() != idx:
            self.cb_paper.setCurrentIndex(idx)

    def _sync_printer_ui_labels(self):
        is_l2540 = (self.printer_model == "Brother DCP-L2540DW")
        self.setWindowTitle(f"WinPrint Studio Enterprise — {self.printer_model}")
        if hasattr(self, "lbl_t_name"):
            self.lbl_t_name.setText("TONER TN-2356" if is_l2540 else "TONER TN-B028")
        if hasattr(self, "lbl_d_name"):
            self.lbl_d_name.setText("DRUM DR-2306" if is_l2540 else "DRUM DR-B028")

    def on_printer_selected(self, idx: int = 0):
        if not hasattr(self, "cb_printer_select"):
            return
        selected = self.cb_printer_select.itemData(self.cb_printer_select.currentIndex())
        if not selected or selected == self.printer_model:
            return
        self.printer_model = selected
        self.detected_tray_media = None
        cfg = winprint_spooler.get_config()
        known = cfg.get("known_printers") if isinstance(cfg.get("known_printers"), dict) else {}
        spec = brother_snmp.PRINTER_CATALOG.get(selected, brother_snmp.PRINTER_CATALOG["Brother DCP-B7640DW"])
        self.printer_ip = known.get(selected) or spec["default_ip"]
        brother_snmp.sync_printer_config(self.printer_ip, printer_model=selected, set_active=True)
        self._sync_printer_ui_labels()
        self.refresh_calibration_spinboxes()
        self.refresh_telemetry()
        self.update_media_hint()

    def refresh_calibration_spinboxes(self):
        if not hasattr(self, "sp_calib_x_mm") or not hasattr(self, "sp_calib_y_mm"):
            return
        paper = self._current_paper_code()
        duplex_mode = winprint_engine_v2.normalize_duplex_mode(getattr(self, "selected_duplex", "long"))
        is_dup = duplex_mode in ("LONG_EDGE", "SHORT_EDGE")
        off_x, off_y = winprint_engine_v2.get_calibration_mm(
            media=paper,
            duplex_mode=duplex_mode,
            printer_model=self.printer_model,
        )
        self.sp_calib_x_mm.setValue(off_x)
        self.sp_calib_y_mm.setValue(off_y)
        self.sp_calib_x_mm.setEnabled(is_dup)
        self.sp_calib_y_mm.setEnabled(is_dup)
        if hasattr(self, "btn_save_calib"):
            self.btn_save_calib.setEnabled(is_dup)
        if hasattr(self, "lbl_calib_hint"):
            if is_dup:
                self.lbl_calib_hint.setText(
                    f"Profil aktif: {self.printer_model} • {paper} • {duplex_mode} "
                    f"(X={off_x:+.1f} mm, Y={off_y:+.1f} mm)."
                )
            else:
                self.lbl_calib_hint.setText("Mode 1-Sisi (Simplex) aktif — kalibrasi sisi belakang tidak diterapkan.")

    def save_current_calibration_profile(self):
        paper = self._current_paper_code()
        duplex_mode = winprint_engine_v2.normalize_duplex_mode(getattr(self, "selected_duplex", "long"))
        if duplex_mode == "SIMPLEX":
            return
        x_mm = round(self.sp_calib_x_mm.value(), 1)
        y_mm = round(self.sp_calib_y_mm.value(), 1)
        winprint_engine_v2.save_calibration_mm(
            media=paper,
            duplex_mode=duplex_mode,
            offset_x_mm=x_mm,
            offset_y_mm=y_mm,
            printer_model=self.printer_model,
            notes="Saved from WinPrint Studio UI",
        )
        self.refresh_calibration_spinboxes()
        self.statusBar().showMessage(
            f"Profil kalibrasi disimpan: {self.printer_model} ({paper} {duplex_mode}) X={x_mm:+.1f} mm, Y={y_mm:+.1f} mm",
            5000,
        )

    def reset_calibration_spinboxes(self):
        if hasattr(self, "sp_calib_x_mm") and hasattr(self, "sp_calib_y_mm"):
            self.sp_calib_x_mm.setValue(0.0)
            self.sp_calib_y_mm.setValue(0.0)
            self.statusBar().showMessage("Nilai kalibrasi UI direset ke 0.0 mm (belum disimpan ke profil).", 4000)

    def update_media_hint(self):
        if not hasattr(self, "lbl_f4_hint"):
            return
        paper = self._current_paper_code()
        doc_media = getattr(self, "detected_doc_media", None)
        tray_media = (getattr(self, "detected_tray_media", None) or "").upper()
        show_hint = (paper == "F4" or tray_media == "FOLIO")
        self.lbl_f4_hint.setVisible(show_hint)
        if hasattr(self, "btn_scale_f4"):
            self.btn_scale_f4.setEnabled(show_hint)

        if doc_media == "F4" and paper == "F4":
            self.lbl_f4_hint.setText(
                "Dokumen berformat asli F4/Folio (215 x 330 mm). Gunakan skala 100% untuk cetak presisi 1:1."
            )
        elif doc_media == "A4" and (paper == "F4" or tray_media == "FOLIO"):
            self.lbl_f4_hint.setText(
                "Terdeteksi dokumen A4 pada kertas/baki F4 (Folio). Gunakan skala 112% untuk memenuhi lembar F4, atau 100% untuk ukuran asli A4."
            )
        else:
            self.lbl_f4_hint.setText(
                "Tip: Dokumen A4 memiliki ruang sisa di lembar F4. Gunakan skala 112% agar teks & tabel memenuhi lembar F4 secara proporsional."
            )

    def _retire_worker(self, attr_name: str):
        old = getattr(self, attr_name, None)
        if old is not None and old.isRunning():
            self._retired_threads.append(old)
            old.finished.connect(
                lambda _t=old: self._retired_threads.remove(_t) if _t in self._retired_threads else None
            )

    def refresh_telemetry(self):
        self.lbl_oled_display.setText('[ "Membaca..." ]')
        self._retire_worker("t_worker")
        self.t_worker = TelemetryWorker(self.printer_ip, self.printer_model)
        self.t_worker.telemetry_ready.connect(self.on_telemetry_ready)
        self.t_worker.start()

    def on_telemetry_ready(self, t: dict):
        if t.get("printer_model") and t.get("printer_model") != self.printer_model:
            return
        online = t.get("online", False)
        model = t.get("model") or self.printer_model
        ip = t.get("ip") or self.printer_ip
        self.printer_ip = ip
        pjl_state = t.get("pjl_state") or ("READY" if online else "UNKNOWN")
        tray2 = t.get("pjl_tray2")
        self.detected_tray_media = tray2
        lcd = t.get("pjl_display") or t.get("lcd_text") or ("Ready" if online else "Offline")

        tray_suffix = f" • Baki: {tray2}" if tray2 else ""
        color_map = {
            "READY": "#10b981",
            "BUSY": "#f59e0b",
            "ERROR": "#f43f5e",
            "UNKNOWN": "#94a3b8",
        }
        status_col = color_map.get(pjl_state, "#94a3b8")

        if hasattr(self, "cb_printer_select"):
            self.cb_printer_select.setToolTip(f"Model terdeteksi: {model} ({ip})")
        if pjl_state in ("READY", "BUSY") or online:
            self.lbl_conn_status.setText(f"{pjl_state} • {ip}:9100{tray_suffix}")
            self.lbl_conn_status.setStyleSheet(f"font-size: 11px; font-weight: 500; color: {status_col};")
            self.lbl_oled_display.setText(f'[ "{lcd}" ]')
        elif pjl_state == "ERROR":
            self.lbl_conn_status.setText(f"ERROR • {ip}:9100{tray_suffix}")
            self.lbl_conn_status.setStyleSheet("font-size: 11px; font-weight: 500; color: #f43f5e;")
            self.lbl_oled_display.setText(f'[ "{lcd}" ]')
        else:
            self.lbl_conn_status.setText(f"UNKNOWN • {ip}{tray_suffix}")
            self.lbl_conn_status.setStyleSheet("font-size: 11px; font-weight: 500; color: #94a3b8;")
            self.lbl_oled_display.setText(f'[ "{lcd}" ]')
        self.update_media_hint()

        toner = t.get("toner_pct")
        drum = t.get("drum_pct")

        if toner is not None:
            self.toner_bar.setValue(int(toner))
            self.lbl_t_val.setText(f"{int(toner)}%")
            if toner > 30:
                self.lbl_t_badge.setText("OPTIMAL")
                self.lbl_t_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #34d399; background: #064e3b; border-radius: 3px; padding: 1px 4px;")
            elif toner > 15:
                self.lbl_t_badge.setText("RENDAH")
                self.lbl_t_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #fbbf24; background: #78350f; border-radius: 3px; padding: 1px 4px;")
            else:
                self.lbl_t_badge.setText("KRITIS")
                self.lbl_t_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #f87171; background: #7f1d1d; border-radius: 3px; padding: 1px 4px;")
        else:
            self.lbl_t_val.setText("N/A")
            self.lbl_t_badge.setText("UNKNOWN")
            self.lbl_t_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; background: #1e293b; border-radius: 3px; padding: 1px 4px;")

        if drum is not None:
            self.drum_bar.setValue(int(drum))
            self.lbl_d_val.setText(f"{int(drum)}%")
            if drum > 10:
                self.lbl_d_badge.setText("NORMAL")
                self.lbl_d_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #fbbf24; background: #78350f; border-radius: 3px; padding: 1px 4px;")
                self.drum_bar.setStyleSheet("""
                    QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
                    QProgressBar::chunk { background: #f59e0b; border-radius: 2px; }
                """)
            else:
                self.lbl_d_badge.setText("KRITIS")
                self.lbl_d_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #f87171; background: #7f1d1d; border-radius: 3px; padding: 1px 4px;")
                self.drum_bar.setStyleSheet("""
                    QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
                    QProgressBar::chunk { background: #dc2626; border-radius: 2px; }
                """)
        else:
            self.lbl_d_val.setText("N/A")
            self.lbl_d_badge.setText("UNKNOWN")
            self.lbl_d_badge.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; background: #1e293b; border-radius: 3px; padding: 1px 4px;")

    def open_ews_browser(self):
        import webbrowser
        self.printer_ip = brother_snmp.resolve_printer_ip(self.printer_model, self.printer_ip, set_active=True)
        webbrowser.open(f"http://{self.printer_ip}")

    # Imposition selection
    def select_imposition_mode(self, mode: str):
        self.selected_imposition = mode
        for card_id, card in self.cards_imposition.items():
            card.set_selected(card_id == mode)

        is_booklet = (mode == "booklet")
        self.grp_booklet_opts.setVisible(is_booklet)

        n_up = 1
        if mode == "2up" or is_booklet:
            n_up = 2
            self.select_orientation_mode("landscape", update_canvas=False)
        elif mode == "4up":
            n_up = 4
        elif mode == "1up":
            self.select_orientation_mode("portrait", update_canvas=False)

        if is_booklet:
            self.select_duplex_mode("short")
            self.cb_paper.setCurrentIndex(0)  # F4

        self.paper_canvas.set_layout_mode(n_up, is_booklet)
        self.paper_canvas.set_orientation(self.selected_orientation)
        self.update_job_summary()
        self.render_current_page()

    # Orientation selection
    def select_orientation_mode(self, mode: str, update_canvas: bool = True):
        self.selected_orientation = mode
        if hasattr(self, "cards_orientation"):
            for card_id, card in self.cards_orientation.items():
                card.set_selected(card_id == mode)
        if hasattr(self, "paper_canvas"):
            self.paper_canvas.set_orientation(mode)
        self.update_job_summary()
        if update_canvas:
            self.render_current_page()

    def on_auto_rotate_toggled(self, checked: bool):
        self.auto_rotate_content = checked
        if hasattr(self, "paper_canvas"):
            self.paper_canvas.set_auto_rotate(checked)

    # Content Scaling methods
    def set_scale_value(self, val: int):
        if hasattr(self, "sp_content_scale"):
            self.sp_content_scale.setValue(val)

    def adjust_scale_by(self, delta: int):
        if hasattr(self, "sp_content_scale"):
            new_val = max(50, min(160, self.sp_content_scale.value() + delta))
            self.sp_content_scale.setValue(new_val)

    def on_scale_spinbox_changed(self, val: int):
        self.current_content_scale = val
        factor = val / 100.0
        if hasattr(self, "lbl_scale_info"):
            if val == 100:
                self.lbl_scale_info.setText("(Ukuran Standar 1:1)")
            elif val == 112:
                self.lbl_scale_info.setText("(Optimal Lembar F4)")
            elif val > 100:
                self.lbl_scale_info.setText(f"(Diperbesar +{val - 100}%)")
            else:
                self.lbl_scale_info.setText(f"(Diperkecil -{100 - val}%)")
            
        if hasattr(self, "paper_canvas"):
            self.paper_canvas.set_content_scale(factor)

    # Duplex selection
    def select_duplex_mode(self, mode: str):
        self.selected_duplex = mode
        for card_id, card in self.cards_duplex.items():
            card.set_selected(card_id == mode)
        self.refresh_calibration_spinboxes()
        self.update_job_summary()

    # Paper selection
    def on_paper_changed(self, idx: int):
        code = self._current_paper_code()
        self.paper_canvas.set_paper_size(code)
        self.update_media_hint()
        self.refresh_calibration_spinboxes()

    def toggle_margins(self, checked: bool):
        self.paper_canvas.show_margins = checked
        self.paper_canvas.update()

    def toggle_duplex_xray(self, checked: bool):
        self.paper_canvas.set_show_duplex_back(checked)
        self.render_current_page()

    def on_shift_changed(self, idx: int):
        gutter_map = {0: 0.0, 1: 5.0, 2: 10.0, 3: 15.0}
        self.paper_canvas.set_binding_gutter_mm(gutter_map.get(idx, 0.0))

    def init_shortcuts(self):
        bindings = [
            ("Ctrl+P", self.execute_print),
            ("Ctrl+O", self.select_document_dialog),
            ("PgUp", self.prev_page),
            ("PgDown", self.next_page),
            ("Ctrl+=", self.zoom_in),
            ("Ctrl++", self.zoom_in),
            ("Ctrl+-", self.zoom_out),
            ("Ctrl+0", self.zoom_reset),
        ]
        self._shortcuts = []
        for seq, handler in bindings:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(handler)
            self._shortcuts.append(sc)

    def on_watermark_changed(self, text: str):
        is_custom = ("Kustom" in text)
        self.txt_custom_watermark.setEnabled(is_custom)
        if not is_custom:
            self.paper_canvas.set_watermark(text)

    def on_custom_watermark_changed(self, text: str):
        self.paper_canvas.set_watermark(text.strip())

    # Presets
    def apply_preset_ujian(self):
        self.cb_paper.setCurrentIndex(0)  # F4
        self.select_imposition_mode("1up")
        self.select_orientation_mode("portrait")
        self.select_duplex_mode("long")
        self.chk_tonersave.setChecked(True)
        self.cb_res.setCurrentIndex(0)    # 600dpi
        QMessageBox.information(self, "Profil Aktif", "Profil 'Ujian / Soal F4 Duplex' diterapkan:\n• Kertas F4/Folio (215x330mm)\n• Orientasi Tegak (Portrait)\n• Bolak-balik Sisi Panjang\n• Mode Hemat Toner Aktif")

    def apply_preset_modul(self):
        self.cb_paper.setCurrentIndex(0)  # F4
        self.select_imposition_mode("2up")
        self.select_orientation_mode("landscape")
        self.chk_border.setChecked(True)
        self.select_duplex_mode("long")
        self.chk_tonersave.setChecked(False)
        QMessageBox.information(self, "Profil Aktif", "Profil 'Modul Belajar (2-Up F4)' diterapkan:\n• Kertas F4/Folio\n• Orientasi Mendatar (Landscape)\n• 2 Halaman per Lembar dengan Garis Pemisah\n• Bolak-balik Sisi Panjang")

    def apply_preset_booklet(self):
        self.cb_paper.setCurrentIndex(0)  # F4
        self.select_imposition_mode("booklet")
        self.select_orientation_mode("landscape")
        self.select_duplex_mode("short")
        QMessageBox.information(self, "Profil Aktif", "Profil 'Buku Lipat (Buklet F4)' diterapkan:\n• Imposisi lipat tengah Saddle-Stitch\n• Orientasi Mendatar (Landscape)\n• Bolak-balik Sisi Pendek (Tumble)\n• Kertas F4 (215x330mm)")

    def apply_preset_surat(self):
        self.cb_paper.setCurrentIndex(1)  # A4
        self.select_imposition_mode("1up")
        self.select_orientation_mode("portrait")
        self.select_duplex_mode("none")
        self.chk_tonersave.setChecked(False)
        self.cb_res.setCurrentIndex(0)
        QMessageBox.information(self, "Profil Aktif", "Profil 'Dokumen Resmi A4' diterapkan:\n• Kertas A4 (210x297mm)\n• Orientasi Tegak (Portrait)\n• 1-Sisi (Simplex)\n• Presisi 600 DPI")

    def apply_preset_draft(self):
        self.select_imposition_mode("2up")
        self.select_orientation_mode("landscape")
        self.chk_tonersave.setChecked(True)
        self.cb_res.setCurrentIndex(1)    # 300dpi
        QMessageBox.information(self, "Profil Aktif", "Profil 'Draft Cepat Hemat Toner' diterapkan:\n• Mode 2-Up\n• Orientasi Mendatar (Landscape)\n• Mode Hemat Toner ON\n• Resolusi 300 DPI")

    # Document Loading & Universal Conversion
    def select_document_dialog(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Buka Dokumen untuk Dicetak",
            "",
            "Semua Berkas yang Didukung (*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.webp *.docx *.odt *.xlsx *.pptx *.txt *.md *.html);;"
            "Dokumen PDF (*.pdf);;"
            "Berkas Gambar (*.png *.jpg *.jpeg *.bmp *.tiff *.webp);;"
            "Dokumen Office (*.docx *.odt *.xlsx *.pptx);;"
            "Berkas Teks & Kode (*.txt *.md *.csv *.py *.sh);;"
            "Semua Berkas (*)"
        )
        if f:
            self.load_document(f)

    def load_document(self, file_path: str, display_name: str = None, cleanup_source: bool = False):
        if not file_path or not os.path.exists(file_path):
            return
        orig_name = display_name or os.path.basename(file_path)
        self.lbl_doc_title.setText(f"Memproses {orig_name}...")
        QApplication.processEvents()

        try:
            chosen_paper = self._current_paper_code()
            source_is_pdf = winprint_converter.is_pdf(file_path)
            pdf_path = winprint_converter.ensure_pdf(file_path, paper=chosen_paper)
            if cleanup_source and file_path.startswith("/tmp/"):
                self._owned_temp_files.add(file_path)
            if pdf_path != file_path and pdf_path.startswith("/tmp/"):
                self._owned_temp_files.add(pdf_path)

            self.current_pdf = pdf_path
            self.original_document_name = orig_name
            converted_tag = " (Dikonversi ke PDF)" if (not source_is_pdf and pdf_path != file_path) else ""
            self.lbl_doc_title.setText(f"{orig_name}{converted_tag}")
            self.total_pages = winprint_imposition.get_pdf_page_count(pdf_path)
            self.current_page = 1

            # Auto-detect native PDF orientation and paper size from page dimensions
            self.detected_doc_landscape = False
            self.detected_doc_media = None
            try:
                if shutil.which("pdfinfo"):
                    info_out = subprocess.check_output(["pdfinfo", pdf_path], stderr=subprocess.DEVNULL).decode("utf-8")
                    for line in info_out.splitlines():
                        if line.startswith("Page size:"):
                            parts = line.split(":")[1].strip().split()
                            pw = float(parts[0])
                            ph = float(parts[2])
                            if pw > ph:
                                self.detected_doc_landscape = True
                            self.detected_doc_media = winprint_layout.detect_pdf_media(pw, ph)
                            break
            except Exception:
                pass

            if self.detected_doc_media:
                self._select_paper_by_code(self.detected_doc_media)

            if hasattr(self, "paper_canvas"):
                self.paper_canvas.detected_doc_landscape = self.detected_doc_landscape
                if self.selected_orientation == "auto":
                    self.paper_canvas.set_orientation("auto")
                else:
                    self.paper_canvas.set_orientation(self.selected_orientation)

            self.update_media_hint()
            self.refresh_calibration_spinboxes()
            self.update_job_summary()
            self.render_current_page()
        except Exception as e:
            QMessageBox.critical(self, "Gagal Membuka Berkas", f"Gagal memproses dokumen '{orig_name}':\n{e}")
            self.lbl_doc_title.setText("Gagal memuat dokumen")

    # Aliases for backward compatibility
    load_pdf = load_document
    select_pdf_dialog = select_document_dialog

    def update_job_summary(self):
        if not self.current_pdf:
            if hasattr(self, "lbl_job_summary"):
                self.lbl_job_summary.setText(
                    "<span style='color: #64748b; font-size: 11px; font-weight: 600;'>"
                    "📊 Menunggu dokumen... Buka berkas untuk kalkulasi lembar & rangkap."
                    "</span>"
                )
            if hasattr(self, "btn_print_master"):
                self.btn_print_master.setText("🖨️ CETAK SEKARANG KE BROTHER")
            return

        pages = self.total_pages
        # Filter range
        rng = self.txt_range.text().strip()
        if rng and rng != "all":
            if rng == "odd":
                pages = (pages + 1) // 2
            elif rng == "even":
                pages = pages // 2
            elif "-" in rng or "," in rng:
                try:
                    pages = len(winprint_imposition.parse_page_range(rng, pages))
                except Exception:
                    pass

        # N-Up
        sheets = pages
        if self.selected_imposition == "2up" or self.selected_imposition == "booklet":
            sheets = (pages + 1) // 2
        elif self.selected_imposition == "4up":
            sheets = (pages + 3) // 4

        # Duplex
        if self.selected_duplex in ("long", "short"):
            physical_sheets = (sheets + 1) // 2
        else:
            physical_sheets = sheets

        copies = 1
        if hasattr(self, "sp_copies_quick") and self.sp_copies_quick is not None:
            copies = self.sp_copies_quick.value()
        elif hasattr(self, "sp_copies"):
            copies = self.sp_copies.value()

        total_physical = physical_sheets * copies
        duplex_label = "Bolak-Balik" if self.selected_duplex != 'none' else "1-Sisi"

        # Highlight matching preset button in copies pod
        if hasattr(self, "btn_copy_presets"):
            for val, btn in self.btn_copy_presets:
                if val == copies:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #0284c7;
                            border: 1.5px solid #38bdf8;
                            border-radius: 4px;
                            color: #ffffff;
                            font-size: 11px;
                            font-weight: 800;
                            padding: 0;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #111a2e;
                            border: 1px solid #1e293b;
                            border-radius: 4px;
                            color: #94a3b8;
                            font-size: 11px;
                            font-weight: 600;
                            padding: 0;
                        }
                        QPushButton:hover {
                            background-color: #1e293b;
                            color: #ffffff;
                            border-color: #0284c7;
                        }
                    """)

        doc_name = self.original_document_name or os.path.basename(self.current_pdf)
        if len(doc_name) > 36:
            doc_name = doc_name[:33] + "..."

        if hasattr(self, "lbl_job_summary"):
            self.lbl_job_summary.setText(
                f"<div style='line-height: 135%;'>"
                f"<span style='color: #94a3b8; font-size: 11px; font-weight: 700;'>📄 {doc_name}</span>"
                f"<span style='color: #475569;'> • </span>"
                f"<b style='color: #f8fafc; font-size: 12px;'>{pages} Halaman</b>"
                f"<span style='color: #475569;'> • </span>"
                f"<b style='color: #38bdf8; font-size: 12px;'>{physical_sheets} Lembar ({duplex_label})</b><br>"
                f"<span style='color: #cbd5e1; font-size: 11px;'>Pencetakan: </span>"
                f"<span style='background: #0369a1; color: #ffffff; padding: 1px 6px; border-radius: 3px; font-weight: 800; font-size: 11px;'>✖ {copies} Rangkap</span>"
                f"<span style='color: #475569;'> = </span>"
                f"<b style='color: #10b981; font-size: 13px;'>Total {total_physical} Lembar Fisik</b>"
                f"</div>"
            )

        if hasattr(self, "btn_print_master"):
            if copies > 1:
                self.btn_print_master.setText(f"🖨️ CETAK {copies} RANGKAP ({total_physical} LEMBAR)")
            else:
                self.btn_print_master.setText(f"🖨️ CETAK SEKARANG ({total_physical} LEMBAR)")

    def render_current_page(self):
        if not self.current_pdf:
            return
        self.lbl_page_counter.setText(f"Halaman {self.current_page} / {self.total_pages}")
        dpi = int(120 * self.zoom_factor)

        # Worker for current page
        self._retire_worker("w1")
        self.w1 = PageRenderWorker(self.current_pdf, self.current_page, dpi=dpi)
        self.w1.rendered.connect(self.on_p1_rendered)
        self.w1.start()

        # If 2-up or booklet, render next page for realistic spread
        if (self.selected_imposition == "2up" or self.selected_imposition == "booklet") and self.current_page < self.total_pages:
            self._retire_worker("w2")
            self.w2 = PageRenderWorker(self.current_pdf, self.current_page + 1, dpi=dpi)
            self.w2.rendered.connect(self.on_p2_rendered)
            self.w2.start()
        else:
            self.paper_canvas.set_pages(self.paper_canvas.pixmap_p1, None)

        # Duplex onion-skin paired page preview
        if getattr(self, "chk_duplex_xray", None) and self.chk_duplex_xray.isChecked() and self.selected_imposition == "1up":
            paired_page = (self.current_page + 1) if (self.current_page % 2 == 1) else (self.current_page - 1)
            if 1 <= paired_page <= self.total_pages:
                self._expected_xray_page = paired_page
                self._retire_worker("w_back")
                self.w_back = PageRenderWorker(self.current_pdf, paired_page, dpi=dpi)
                self.w_back.rendered.connect(self.on_back_duplex_rendered)
                self.w_back.start()
            else:
                self._expected_xray_page = None
                self.paper_canvas.set_duplex_back_preview(None)
        else:
            self._expected_xray_page = None
            self.paper_canvas.set_duplex_back_preview(None)

    def on_p1_rendered(self, p_num: int, path: str):
        if p_num == self.current_page and path:
            self.paper_canvas.set_pages(path, None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def on_p2_rendered(self, p_num: int, path: str):
        if p_num == self.current_page + 1 and path:
            self.paper_canvas.set_pages(self.paper_canvas.pixmap_p1, path)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def on_back_duplex_rendered(self, p_num: int, path: str):
        if p_num == getattr(self, "_expected_xray_page", None) and path:
            self.paper_canvas.set_duplex_back_preview(path)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def prev_page(self):
        step = 2 if (self.selected_imposition == "2up" or self.selected_imposition == "booklet") else 1
        if self.current_page > 1:
            self.current_page = max(1, self.current_page - step)
            self.render_current_page()

    def next_page(self):
        step = 2 if (self.selected_imposition == "2up" or self.selected_imposition == "booklet") else 1
        if self.current_page < self.total_pages:
            self.current_page = min(self.total_pages, self.current_page + step)
            self.render_current_page()

    def zoom_in(self):
        self.zoom_factor = min(2.5, round(self.zoom_factor + 0.15, 2))
        self.lbl_zoom.setText(f"{int(self.zoom_factor * 100)}%")
        self.paper_canvas.set_zoom(self.zoom_factor)
        self.render_current_page()

    def zoom_out(self):
        self.zoom_factor = max(0.5, round(self.zoom_factor - 0.15, 2))
        self.lbl_zoom.setText(f"{int(self.zoom_factor * 100)}%")
        self.paper_canvas.set_zoom(self.zoom_factor)
        self.render_current_page()

    def zoom_reset(self):
        self.zoom_factor = 1.0
        self.lbl_zoom.setText("100%")
        self.paper_canvas.set_zoom(1.0)
        self.render_current_page()

    # Settings payload builder
    def collect_settings(self) -> dict:
        raw_p = self.cb_paper.currentText()
        paper = "A4"
        if "F4" in raw_p or "Folio" in raw_p:
            paper = "F4"
        elif "Legal" in raw_p:
            paper = "Legal"
        elif "Letter" in raw_p:
            paper = "Letter"

        n_up = 1
        if self.selected_imposition == "2up" or self.selected_imposition == "booklet":
            n_up = 2
        elif self.selected_imposition == "4up":
            n_up = 4

        res = 600
        if "300" in self.cb_res.currentText():
            res = 300
        elif "1200" in self.cb_res.currentText():
            res = 1200

        wm = None
        raw_wm = self.cb_watermark.currentText()
        if raw_wm != "Tidak Ada":
            wm = self.txt_custom_watermark.text().strip() if "Kustom" in raw_wm else raw_wm

        binding_dir = "left" if "Kiri" in self.cb_binding_dir.currentText() else "right"

        eff_orientation = getattr(self, "selected_orientation", "auto")
        if eff_orientation == "auto":
            eff_orientation = "landscape" if getattr(self, "detected_doc_landscape", False) else "portrait"
        if self.selected_imposition in ("2up", "booklet"):
            eff_orientation = "landscape"

        scale_pct = getattr(self, "current_content_scale", 100)
        content_scale = float(scale_pct) / 100.0
        auto_rotate = getattr(self, "auto_rotate_content", True)

        copies = 1
        if hasattr(self, "sp_copies_quick") and self.sp_copies_quick is not None:
            copies = self.sp_copies_quick.value()
        elif hasattr(self, "sp_copies"):
            copies = self.sp_copies.value()

        duplex_offset_x = 0.0
        duplex_offset_y = 0.0
        if self.selected_duplex in ("long", "short") and hasattr(self, "sp_calib_x_mm") and hasattr(self, "sp_calib_y_mm"):
            duplex_offset_x = self.sp_calib_x_mm.value() * winprint_layout.PT_PER_MM
            duplex_offset_y = self.sp_calib_y_mm.value() * winprint_layout.PT_PER_MM

        tray_map = {0: "auto", 1: "tray1", 2: "manual"}
        media_map = {0: "plain", 1: "thick", 2: "recycled", 3: "envelope"}
        gutter_map = {0: 0.0, 1: 5.0, 2: 10.0, 3: 15.0}

        paper_source = tray_map.get(self.cb_tray.currentIndex(), "auto") if hasattr(self, "cb_tray") else "auto"
        media_type = media_map.get(self.cb_media.currentIndex(), "plain") if hasattr(self, "cb_media") else "plain"
        binding_gutter_mm = gutter_map.get(self.cb_shift.currentIndex(), 0.0) if hasattr(self, "cb_shift") else 0.0
        density = int(self.slider_density.value()) if hasattr(self, "slider_density") else 0
        collate = self.chk_collate.isChecked() if hasattr(self, "chk_collate") else True

        return {
            "printer_model": self.printer_model,
            "paper": paper,
            "paper_source": paper_source,
            "media_type": media_type,
            "binding_gutter_mm": binding_gutter_mm,
            "orientation": eff_orientation,
            "duplex": self.selected_duplex,
            "duplex_offset_x": duplex_offset_x,
            "duplex_offset_y": duplex_offset_y,
            "n_up": n_up,
            "add_border": self.chk_border.isChecked(),
            "booklet": (self.selected_imposition == "booklet"),
            "booklet_binding": binding_dir,
            "toner_save": self.chk_tonersave.isChecked(),
            "quiet_mode": self.chk_quiet.isChecked(),
            "density": density,
            "resolution": res,
            "page_range": self.txt_range.text().strip() or "all",
            "reverse_order": self.chk_reverse.isChecked(),
            "copies": copies,
            "collate": collate,
            "watermark": wm,
            "content_scale": content_scale,
            "auto_rotate": auto_rotate
        }

    # Print execution
    def execute_print(self):
        if not self.current_pdf:
            QMessageBox.warning(self, "Peringatan", "Silakan pilih dokumen PDF terlebih dahulu.")
            return
        if getattr(self, "print_worker", None) and self.print_worker.isRunning():
            return

        settings = self.collect_settings()
        self.btn_print_master.setEnabled(False)
        if hasattr(self, "btn_cancel_print"):
            self.btn_cancel_print.setVisible(True)
            self.btn_cancel_print.setEnabled(True)
        self.pbar.setValue(10)

        self.print_worker = PrintExecutionWorker(self.printer_ip, self.current_pdf, settings)
        self.print_worker.progress.connect(self.on_print_progress)
        self.print_worker.finished_result.connect(self.on_print_finished)
        self.print_worker.start()

    def cancel_print_job(self):
        w = getattr(self, "print_worker", None)
        if w and w.isRunning():
            w.cancel()
            if hasattr(self, "btn_cancel_print"):
                self.btn_cancel_print.setEnabled(False)
            self.statusBar().showMessage("Membatalkan pengiriman data cetak...", 4000)

    def on_print_progress(self, val: int, msg: str):
        self.pbar.setValue(val)
        self.statusBar().showMessage(msg, 5000)

    def on_print_finished(self, success: bool, msg: str):
        self.btn_print_master.setEnabled(True)
        if hasattr(self, "btn_cancel_print"):
            self.btn_cancel_print.setVisible(False)
            self.btn_cancel_print.setEnabled(True)
        self.pbar.setValue(100 if success else 0)
        if success:
            QMessageBox.information(self, "Cetak Berhasil", msg)
        else:
            QMessageBox.critical(self, "Cetak Gagal", msg)

    def export_imposed_pdf(self):
        if not self.current_pdf:
            QMessageBox.warning(self, "Peringatan", "Pilih dokumen PDF terlebih dahulu.")
            return

        out_path, _ = QFileDialog.getSaveFileName(self, "Simpan Berkas Hasil Imposisi", os.path.expanduser("~/Documents/Hasil_Tata_Letak.pdf"), "Dokumen PDF (*.pdf)")
        if not out_path:
            return

        settings = self.collect_settings()
        self.pbar.setValue(50)
        ok = winprint_imposition.build_imposed_pdf(
            input_pdf=self.current_pdf,
            output_pdf=out_path,
            page_range_str=settings["page_range"],
            n_up=settings["n_up"],
            booklet=settings["booklet"],
            booklet_binding=settings["booklet_binding"],
            reverse_order=settings["reverse_order"],
            add_border=settings["add_border"],
            watermark_text=settings["watermark"]
        )
        self.pbar.setValue(100)
        if ok and os.path.exists(out_path):
            QMessageBox.information(self, "Berhasil", f"Berkas hasil imposisi berhasil disimpan ke:\n{out_path}")
        else:
            QMessageBox.critical(self, "Gagal", "Gagal memproses imposisi PDF.")

    def print_test_page(self):
        # Generate clean calibration test PDF
        test_pdf = "/tmp/winprint_calibration_test.pdf"
        cmd = [
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            "-sOutputFile=" + test_pdf,
            "-c",
            "/Helvetica-Bold findfont 22 scalefont setfont 50 780 moveto (BROTHER DCP-B7640DW / DCP-L2540DW) show "
            "/Helvetica findfont 14 scalefont setfont 50 755 moveto (Enterprise Direct PCL-XL Test Page - WinPrint Subsystem) show "
            f"/Helvetica findfont 10 scalefont setfont 50 735 moveto (Target: {self.printer_ip}:9100 RAW | 600 DPI Calibrated) show "
            "50 720 moveto 545 720 lineto 2 setlinewidth stroke "
            "50 100 moveto 545 100 lineto stroke "
            "/Helvetica findfont 9 scalefont setfont 50 80 moveto (TonerBox TN-B028 | Drum Unit DR-B028 | Standard F4/A4 Alignment OK) show "
            "showpage"
        ]
        try:
            subprocess.run(cmd, check=True)
            if os.path.exists(test_pdf):
                self.load_pdf(test_pdf)
                QMessageBox.information(self, "Halaman Uji Siap", "Halaman kalibrasi Brother telah dibuat di pratinjau. Klik 'CETAK SEKARANG' untuk mengirim ke pencetak.")
        except Exception as e:
            QMessageBox.critical(self, "Gagal", f"Gagal membuat halaman uji: {e}")

    def load_calibration_3x2_sheet(self):
        """Generates a 2-page 3x2 calibration sheet for the active paper size and prepares 1 duplex test print."""
        try:
            paper = self.collect_settings().get("paper", "F4")
            geom = winprint_layout.get_media_geometry(winprint_engine.resolve_ppd_path(), paper, "portrait")
            calib_pdf = "/tmp/winprint_calibration_3x2.pdf"
            winprint_layout.generate_calibration_pdf(calib_pdf, geom)
            self.load_pdf(calib_pdf)
            self.select_duplex_mode("long")
            self.set_scale_value(100)
            QMessageBox.information(
                self,
                "Lembar Kalibrasi 3x2 Siap",
                f"Lembar kalibrasi 3x2 ({paper}) sudah dimuat di pratinjau dengan mode bolak-balik Long-Edge 100%.\n\n"
                "Klik 'CETAK SEKARANG' untuk mencetak 1 lembar dan melihat akurasi depan-belakang."
            )
        except Exception as e:
            QMessageBox.critical(self, "Gagal", f"Gagal membuat lembar kalibrasi 3x2: {e}")

    def closeEvent(self, event):
        for worker_name in ("w1", "w2", "w_back", "t_worker", "print_worker"):
            w = getattr(self, worker_name, None)
            if w and w.isRunning():
                w.quit()
                w.wait(2000)
        for w in list(getattr(self, "_retired_threads", ())):
            if w and w.isRunning():
                w.quit()
                w.wait(2000)
        self._retired_threads.clear()
        for path in list(getattr(self, "_owned_temp_files", ())):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        pid_prefix = f"winprint_prev_{os.getpid()}_"
        try:
            for entry in os.scandir("/tmp"):
                if entry.name.startswith(pid_prefix) and entry.is_file(follow_symlinks=False):
                    try:
                        os.unlink(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="WinPrint Studio Enterprise GUI")
    parser.add_argument("file", nargs="?", help="Optional PDF/document file to open")
    parser.add_argument("--job-name", help="Original document name from print job")
    parser.add_argument("--copies", type=int, help="Initial copy count")
    parser.add_argument("--duplex", choices=["none", "long", "short"], help="Initial duplex mode")
    parser.add_argument("--paper", help="Fallback paper size when PDF dimensions are non-standard")
    parser.add_argument("--printer", help="Initial printer model")
    parser.add_argument("--cleanup-temp", action="store_true", help="Delete initial /tmp file when closed")
    args, qt_args = parser.parse_known_args()

    app = QApplication.instance() or QApplication([sys.argv[0]] + qt_args)
    job_meta = {
        "job_name": args.job_name,
        "copies": args.copies,
        "duplex": args.duplex,
        "paper": args.paper,
        "printer": args.printer,
        "cleanup_temp": args.cleanup_temp,
    }
    window = WinPrintStudio(args.file, job_meta=job_meta)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
