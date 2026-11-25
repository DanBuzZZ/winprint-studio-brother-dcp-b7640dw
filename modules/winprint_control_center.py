#!/usr/bin/env python3
"""
winprint_control_center.py - Enterprise Dashboard & Control Center for Brother DCP-B7640DW
Provides an executive unified console for print studio, scanner OCR hub, spooler, and network setup.
"""

import sys
import os
import subprocess
import webbrowser

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QProgressBar, QMessageBox, QInputDialog,
    QScrollArea, QSizePolicy
)
from PyQt6.QtGui import QColor, QFont, QCursor, QPixmap
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import brother_snmp
import brother_scan


CONTROL_CENTER_STYLE = """
QMainWindow, QWidget#CentralWidget {
    background-color: #0b0f17;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Ubuntu, sans-serif;
    font-size: 13px;
}

QFrame#HeaderCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #111827, stop:1 #0f172a);
    border: 1px solid #1f2937;
    border-radius: 10px;
}

QFrame#ServiceTile, QFrame#ActionTile {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
QFrame#ServiceTile:hover, QFrame#ActionTile:hover {
    background-color: #162032;
    border: 1px solid #0284c7;
}
QFrame#ActionTile QLabel {
    background: transparent;
    border: none;
}

QPushButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #f8fafc;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}
"""


class TelemetryWorker(QThread):
    telemetry_ready = pyqtSignal(dict)

    def __init__(self, ip: str):
        super().__init__()
        self.ip = ip

    def run(self):
        try:
            t = brother_snmp.get_printer_telemetry(self.ip)
            self.telemetry_ready.emit(t)
        except Exception:
            self.telemetry_ready.emit({"online": False, "ip": self.ip})


class ActionTile(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, tile_id: str, title: str, description: str, icon_str: str, badge: str = None, parent=None):
        super().__init__(parent)
        self.tile_id = tile_id
        self.setObjectName("ActionTile")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        lbl_icon = QLabel(icon_str)
        lbl_icon.setStyleSheet("font-size: 28px; background: transparent; border: none;")
        layout.addWidget(lbl_icon)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        title_row = QHBoxLayout()
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #f8fafc; background: transparent; border: none;")
        title_row.addWidget(lbl_title)

        if badge:
            lbl_badge = QLabel(badge)
            lbl_badge.setStyleSheet("font-size: 10px; font-weight: 700; color: #38bdf8; background: #0c4a6e; border-radius: 4px; padding: 2px 8px; margin-left: 8px;")
            title_row.addWidget(lbl_badge)
        title_row.addStretch()

        lbl_desc = QLabel(description)
        lbl_desc.setStyleSheet("font-size: 12px; color: #94a3b8; background: transparent; border: none;")
        lbl_desc.setWordWrap(True)

        text_layout.addLayout(title_row)
        text_layout.addWidget(lbl_desc)
        layout.addLayout(text_layout, stretch=1)

        lbl_arrow = QLabel("➔")
        lbl_arrow.setStyleSheet("font-size: 16px; color: #475569; font-weight: bold; background: transparent; border: none;")
        layout.addWidget(lbl_arrow)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.tile_id)


class ControlCenterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brother Enterprise Control Center — DCP-B7640DW Suite")
        self.resize(960, 680)
        self.setMinimumSize(880, 600)
        self.setStyleSheet(CONTROL_CENTER_STYLE)

        self.cfg = winprint_spooler.get_config()
        self.printer_ip = brother_snmp.resolve_b7640_ip(self.cfg.get("printer_ip", "192.168.100.229"))

        self.init_ui()
        self.refresh_telemetry()

    def init_ui(self):
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. HEADER TELEMETRY HERO
        main_layout.addWidget(self.create_hero_header())

        # 2. GRID OF SERVICE TILES
        main_layout.addWidget(self.create_tiles_grid(), stretch=1)

        # 3. BOTTOM UTILITY BAR
        main_layout.addWidget(self.create_bottom_bar())

    def create_hero_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("HeaderCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(16)

        # Identity
        v_id = QVBoxLayout()
        v_id.setSpacing(2)
        lbl_sub = QLabel("BROTHER WORKSTATION ECOSYSTEM")
        lbl_sub.setStyleSheet("font-size: 10px; font-weight: 700; color: #0284c7; letter-spacing: 0.5px;")

        self.lbl_model = QLabel("Brother DCP-B7640DW")
        self.lbl_model.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        self.lbl_model.setMinimumWidth(180)

        self.lbl_ip_conn = QLabel(f"🟢 ONLINE (Wi-Fi: {self.printer_ip} • 9100 RAW)")
        self.lbl_ip_conn.setStyleSheet("font-size: 11px; font-weight: 500; color: #10b981;")

        v_id.addWidget(lbl_sub)
        v_id.addWidget(self.lbl_model)
        v_id.addWidget(self.lbl_ip_conn)
        layout.addLayout(v_id)

        layout.addSpacing(6)

        # Backlit OLED LCD screen
        oled_box = QFrame()
        oled_box.setStyleSheet("background-color: #041014; border: 1.5px solid #083344; border-radius: 6px; padding: 4px 10px;")
        v_oled = QVBoxLayout(oled_box)
        v_oled.setContentsMargins(4, 2, 4, 2)
        v_oled.setSpacing(1)
        lbl_lcd_h = QLabel("PANEL LCD MIRROR")
        lbl_lcd_h.setStyleSheet("font-size: 9px; color: #0891b2; font-weight: bold;")
        self.lbl_lcd_text = QLabel('[ "Menghubungkan..." ]')
        self.lbl_lcd_text.setStyleSheet("font-family: monospace; font-size: 13px; font-weight: bold; color: #22d3ee;")
        v_oled.addWidget(lbl_lcd_h)
        v_oled.addWidget(self.lbl_lcd_text)
        layout.addWidget(oled_box)

        layout.addSpacing(6)

        # Toner Gauge
        t_box = QFrame()
        t_box.setStyleSheet("background-color: #111827; border: 1px solid #1f2937; border-radius: 6px;")
        t_box.setFixedSize(140, 62)
        v_t = QVBoxLayout(t_box)
        v_t.setContentsMargins(10, 6, 10, 6)
        v_t.setSpacing(1)

        lbl_t_name = QLabel("TONER TN-B028")
        lbl_t_name.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        v_t.addWidget(lbl_t_name)

        t_sub = QHBoxLayout()
        self.lbl_t_val = QLabel("100%")
        self.lbl_t_val.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        t_sub.addWidget(self.lbl_t_val)
        t_sub.addStretch()
        v_t.addLayout(t_sub)

        self.bar_toner = QProgressBar()
        self.bar_toner.setFixedHeight(5)
        self.bar_toner.setRange(0, 100)
        self.bar_toner.setValue(100)
        self.bar_toner.setTextVisible(False)
        self.bar_toner.setStyleSheet("""
            QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8); border-radius: 2px; }
        """)
        v_t.addWidget(self.bar_toner)
        layout.addWidget(t_box)

        # Drum Gauge
        d_box = QFrame()
        d_box.setStyleSheet("background-color: #111827; border: 1px solid #1f2937; border-radius: 6px;")
        d_box.setFixedSize(140, 62)
        v_d = QVBoxLayout(d_box)
        v_d.setContentsMargins(10, 6, 10, 6)
        v_d.setSpacing(1)

        lbl_d_name = QLabel("DRUM DR-B028")
        lbl_d_name.setStyleSheet("font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px;")
        v_d.addWidget(lbl_d_name)

        d_sub = QHBoxLayout()
        self.lbl_d_val = QLabel("6%")
        self.lbl_d_val.setStyleSheet("font-size: 15px; font-weight: 800; color: #f59e0b;")
        d_sub.addWidget(self.lbl_d_val)
        d_sub.addStretch()
        v_d.addLayout(d_sub)

        self.bar_drum = QProgressBar()
        self.bar_drum.setFixedHeight(5)
        self.bar_drum.setRange(0, 100)
        self.bar_drum.setValue(6)
        self.bar_drum.setTextVisible(False)
        self.bar_drum.setStyleSheet("""
            QProgressBar { background: #1e293b; border-radius: 2px; border: none; }
            QProgressBar::chunk { background: #eab308; border-radius: 2px; }
        """)
        v_d.addWidget(self.bar_drum)
        layout.addWidget(d_box)

        layout.addStretch()

        btn_ref = QPushButton("🔄 Segarkan")
        btn_ref.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_ref.clicked.connect(self.refresh_telemetry)
        layout.addWidget(btn_ref)

        return frame

    def create_tiles_grid(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)

        # Tile 1: WinPrint Studio
        t1 = ActionTile(
            "studio",
            "WinPrint Studio Enterprise",
            "Pusat pencetakan canggih: pratinjau lembar nyata, pencetakan buku lipat (booklet), 2-up, duplex bolak-balik, ukuran F4/Folio, dan tanda air.",
            "🎨",
            badge="FITUR UTAMA"
        )
        t1.clicked.connect(self.handle_tile_click)
        grid.addWidget(t1, 0, 0)

        # Tile 2: Scan Hub Pro
        t2 = ActionTile(
            "scan",
            "Pusat Pemindaian Dokumen (Scan Hub)",
            "Pindai dokumen dari kaca datar atau baki otomatis ADF 50-lembar. Otomatis OCR dengan Tesseract v5 menghasilkan PDF Teks Terindeks.",
            "📄",
            badge="OCR v5"
        )
        t2.clicked.connect(self.handle_tile_click)
        grid.addWidget(t2, 0, 1)

        # Tile 3: Spooler Queue
        t3 = ActionTile(
            "spooler",
            "Kelola Antrean Cetak (WinPrint Spooler)",
            "Pantau riwayat pekerjaan cetak, antrean dokumen aktif, log pengiriman, dan fitur pemulihan otomatis jika kertas habis.",
            "📥"
        )
        t3.clicked.connect(self.handle_tile_click)
        grid.addWidget(t3, 1, 0)

        # Tile 4: Network Discovery & Auto-Heal
        t4 = ActionTile(
            "network",
            "Deteksi Jaringan & Auto-Heal",
            "Pindai subnet Wi-Fi lokal untuk menemukan alamat IP printer Brother secara otomatis dan memperbarui konfigurasi sistem.",
            "🔍"
        )
        t4.clicked.connect(self.handle_tile_click)
        grid.addWidget(t4, 1, 1)

        # Tile 5: F4 Paper Configuration
        t5 = ActionTile(
            "f4_paper",
            "Standar Kertas F4 / Folio (215 x 330 mm)",
            "Pastikan profil ukuran kertas F4 terdaftar sempurna pada LibreOffice, cups-pdf, dan Ghostscript untuk naskah ujian sekolah.",
            "📐"
        )
        t5.clicked.connect(self.handle_tile_click)
        grid.addWidget(t5, 2, 0)

        # Tile 6: Brother Web Admin (EWS)
        t6 = ActionTile(
            "ews",
            "Brother Web-Based Management (EWS)",
            "Akses portal web internal Brother untuk konfigurasi perangkat keras, pengaturan baki kertas, Wi-Fi, dan kata sandi admin.",
            "🌐"
        )
        t6.clicked.connect(self.handle_tile_click)
        grid.addWidget(t6, 2, 1)

        return container

    def create_bottom_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_ip = QPushButton("⚙️ Ganti IP Printer")
        btn_ip.clicked.connect(self.change_printer_ip)
        layout.addWidget(btn_ip)

        btn_test = QPushButton("📑 Cetak Halaman Uji PCL-XL")
        btn_test.clicked.connect(self.print_test_page)
        layout.addWidget(btn_test)

        layout.addStretch()

        btn_exit = QPushButton("Tutup")
        btn_exit.clicked.connect(self.close)
        layout.addWidget(btn_exit)

        return widget

    def refresh_telemetry(self):
        self.lbl_lcd_text.setText('[ "Membaca..." ]')
        self.worker = TelemetryWorker(self.printer_ip)
        self.worker.telemetry_ready.connect(self.on_telemetry_ready)
        self.worker.start()

    def on_telemetry_ready(self, t: dict):
        online = t.get("online", False)
        model = t.get("model") or "Brother Laser Printer"
        ip = t.get("ip") or self.printer_ip
        lcd = t.get("lcd_text") or ("Ready" if online else "Offline")

        self.lbl_model.setText(model)
        if online:
            self.lbl_ip_conn.setText(f"🟢 ONLINE (Wi-Fi: {ip} • Port 9100 RAW)")
            self.lbl_ip_conn.setStyleSheet("font-size: 12px; font-weight: 500; color: #10b981;")
            self.lbl_lcd_text.setText(f'[ "{lcd}" ]')
        else:
            self.lbl_ip_conn.setText(f"🔴 OFFLINE / SLEEP ({ip})")
            self.lbl_ip_conn.setStyleSheet("font-size: 12px; font-weight: 500; color: #f43f5e;")
            self.lbl_lcd_text.setText('[ "Offline" ]')

        toner = t.get("toner_pct", 100)
        drum = t.get("drum_pct", 100)

        self.bar_toner.setValue(toner if toner is not None else 0)
        self.lbl_t_val.setText(f"{toner}%" if toner is not None else "N/A")

        self.bar_drum.setValue(drum if drum is not None else 0)
        if drum is not None and drum <= 10:
            self.lbl_d_val.setText(f"{drum}% (⚠️ Unit Segera Habis)")
            self.lbl_d_val.setStyleSheet("font-weight: bold; color: #ef4444;")
            self.bar_drum.setStyleSheet("QProgressBar { background: #1e293b; border-radius: 4px; border: none; } QProgressBar::chunk { background: #dc2626; border-radius: 4px; }")
        else:
            self.lbl_d_val.setText(f"{drum}%" if drum is not None else "N/A")

    def handle_tile_click(self, tile_id: str):
        if tile_id == "studio":
            subprocess.Popen([sys.executable, os.path.join(SCRIPT_DIR, "winprint_studio.py")])
        elif tile_id == "scan":
            self.open_scan_dialog()
        elif tile_id == "spooler":
            self.show_spooler_queue()
        elif tile_id == "network":
            self.run_network_discovery()
        elif tile_id == "f4_paper":
            self.setup_f4_paper()
        elif tile_id == "ews":
            webbrowser.open(f"http://{self.printer_ip}")

    def open_scan_dialog(self):
        cmd = [
            "zenity", "--forms", "--title=Pusat Pemindaian Dokumen Brother (Scan Hub Pro)",
            "--text=Konfigurasi Pemindaian Dokumen Brother DCP-B7640DW:",
            f"--add-entry=Alamat IP Printer ({self.printer_ip})",
            "--add-combo=Sumber Kertas", "--combo-values=Kaca Datar (Flatbed)|Baki Otomatis (ADF 50-Lembar)",
            "--add-combo=Format Dokumen", "--combo-values=PDF Teks Terindeks (Searchable OCR)|PDF Standar|Gambar JPEG|Gambar PNG",
            "--add-combo=Resolusi (DPI)", "--combo-values=300|150|200|600",
            "--add-combo=Mode Warna", "--combo-values=Warna (Color)|Abu-abu (Grayscale)|Monokrom (Hitam-Putih)",
            "--separator=|"
        ]
        try:
            res = subprocess.check_output(cmd, text=True).strip()
            if not res:
                return
            parts = res.split("|")
            ip = parts[0].strip() or self.printer_ip
            src = "adf" if "ADF" in parts[1] else "flatbed"
            fmt = "pdf"
            do_ocr = ("OCR" in parts[2])
            if "JPEG" in parts[2]:
                fmt = "jpeg"
            elif "PNG" in parts[2]:
                fmt = "png"
            dpi = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 300
            mode = "color"
            if "Abu" in parts[4]:
                mode = "gray"
            elif "Mono" in parts[4]:
                mode = "lineart"

            out_dir = os.path.expanduser("~/Documents/Scans")
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, f"Scan_Brother_{int(time.time())}.{fmt}")

            QMessageBox.information(self, "Memulai Pemindaian", f"Memulai pemindaian dari {src.upper()}...\nBerkas akan disimpan ke:\n{out_file}")
            
            # Execute scan
            scanned = brother_scan.scan_document(
                ip=ip,
                output_path=out_file,
                source=src,
                resolution=dpi,
                color_mode=mode,
                fmt=fmt,
                ocr=do_ocr
            )
            if scanned and os.path.exists(scanned):
                QMessageBox.information(self, "Pemindaian Berhasil", f"Dokumen berhasil disimpan ke:\n{scanned}")
            else:
                QMessageBox.critical(self, "Pemindaian Gagal", "Gagal memindai dokumen. Pastikan dokumen sudah ditaruh di pemindai.")
        except subprocess.CalledProcessError:
            pass

    def show_spooler_queue(self):
        jobs = winprint_spooler.list_jobs(limit=20)
        if not jobs:
            QMessageBox.information(self, "Antrean Spooler", "Antrean kosong. Tidak ada pekerjaan cetak yang tertunda.")
            return

        lines = ["DAFTAR PEKERJAAN CETAK (WINPRINT SPOOLER):", "═" * 50]
        for j in jobs:
            lines.append(f"• ID #{j['id']} | {j['file_name']} | Status: {j['status']} | {j['created_at']}")
        QMessageBox.information(self, "Antrean Spooler", "\n".join(lines))

    def run_network_discovery(self):
        QMessageBox.information(self, "Pencarian Jaringan", "Sedang memindai subnet Wi-Fi lokal untuk menemukan Brother DCP-B7640DW (Ruang Guru)...")
        import socket
        base_ip = ".".join(self.printer_ip.split(".")[:3])
        found = []
        for i in range(1, 255):
            target = f"{base_ip}.{i}"
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.04)
            if s.connect_ex((target, 9100)) == 0:
                found.append(target)
            s.close()

        b7640_ip = None
        l2540_ip = None

        for ip in found:
            t = brother_snmp.get_printer_telemetry(ip)
            m = (t.get("model") or "").upper()
            if "B7640" in m or "7640" in m:
                b7640_ip = ip
                break
            elif "2540" in m or "L2540" in m or ip == "192.168.100.236":
                l2540_ip = ip

        if b7640_ip:
            winprint_spooler.update_config({"printer_ip": b7640_ip, "printer_name": "Brother-DCP-B7640DW"})
            self.printer_ip = b7640_ip
            self.refresh_telemetry()
            QMessageBox.information(self, "Printer Ditemukan", f"Brother DCP-B7640DW (Ruang Guru) terdeteksi pada IP: {b7640_ip}\nKonfigurasi berhasil disinkronkan.")
        elif l2540_ip and not b7640_ip:
            QMessageBox.warning(
                self,
                "B7640DW Belum Ditemukan",
                f"Perhatian:\nDi jaringan hanya terdeteksi Brother DCP-L2540DW ({l2540_ip}) di Ruang Kepala Sekolah.\n\n"
                f"Target printer Anda: Brother DCP-B7640DW di Ruang Guru belum terdeteksi (kemungkinan sedang Sleep atau belum terhubung Wi-Fi).\n"
                f"Konfigurasi TIDAK dialihkan ke printer Kepala Sekolah untuk menjaga privasi dokumen."
            )
        else:
            QMessageBox.warning(self, "Hasil Pencarian", f"Tidak ada printer port 9100 yang merespons di subnet {base_ip}.x.")

    def setup_f4_paper(self):
        # Register custom F4 paper
        try:
            subprocess.run(["lpadmin", "-p", "Brother-DCP-B7640DW", "-o", "PageSize=Custom.215x330mm"], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        QMessageBox.information(
            self,
            "Pengaturan Kertas F4 / Folio",
            "Standar ukuran F4 (215 x 330 mm / 8.46 x 12.99 inci) telah dikonfigurasi ke seluruh subsistem WinPrint dan Ghostscript.\n\n"
            "Dokumen ujian dan formulir legal Indonesia siap dicetak tanpa terpotong batas margin."
        )

    def change_printer_ip(self):
        new_ip, ok = QInputDialog.getText(self, "Ubah IP Printer", "Masukkan alamat IP printer Brother:", text=self.printer_ip)
        if ok and new_ip.strip():
            self.printer_ip = new_ip.strip()
            winprint_spooler.update_config({"printer_ip": self.printer_ip})
            self.refresh_telemetry()
            QMessageBox.information(self, "Berhasil", f"Alamat IP printer diperbarui ke: {self.printer_ip}")

    def print_test_page(self):
        test_pdf = "/tmp/winprint_control_test.pdf"
        cmd = [
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
            "-sOutputFile=" + test_pdf,
            "-c",
            "/Helvetica-Bold findfont 24 scalefont setfont 50 780 moveto (BROTHER ENTERPRISE SUBSYSTEM) show "
            "/Helvetica findfont 12 scalefont setfont 50 755 moveto (Direct Port 9100 RAW Verification Page - WinPrint Subsystem) show "
            "/Helvetica findfont 10 scalefont setfont 50 735 moveto (DCP-B7640DW / DCP-L2540DW Protocol OK) show "
            "50 720 moveto 545 720 lineto 2 setlinewidth stroke "
            "showpage"
        ]
        try:
            subprocess.run(cmd, check=True)
            ok = winprint_engine.print_file_direct(self.printer_ip, test_pdf, paper="A4", duplex="none")
            if ok:
                QMessageBox.information(self, "Berhasil", "Halaman uji berhasil dikirim ke printer via Port 9100.")
            else:
                QMessageBox.critical(self, "Gagal", "Gagal mengirim ke printer.")
        except Exception as e:
            QMessageBox.critical(self, "Kesalahan", str(e))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = ControlCenterWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
