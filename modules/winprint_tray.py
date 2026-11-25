#!/usr/bin/env python3
"""
winprint_tray.py - System Tray Applet for Brother Status Monitor & WinPrint
Provides real-time tray icon with dynamic supply status badge (Toner & Drum),
desktop notifications on paper jam / low toner, and one-click quick actions.
Parity equivalent of Brother Status Monitor 3 on Windows.
"""

import sys
import os
import time
import subprocess
import webbrowser

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QFileDialog, QMessageBox
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen, QAction
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import winprint_spooler
import brother_snmp
import winprint_engine
import brother_scan
import winprint_layout


class TelemetryWorker(QThread):
    telemetry_ready = pyqtSignal(dict)

    def __init__(self, ip: str, printer_model: str = "Brother DCP-B7640DW"):
        super().__init__()
        self.ip = ip
        self.printer_model = printer_model

    def run(self):
        try:
            data = brother_snmp.get_printer_telemetry(self.ip)
            if not data.get("online"):
                resolved = brother_snmp.resolve_printer_ip(self.printer_model, self.ip, set_active=True)
                if resolved and resolved != self.ip:
                    self.ip = resolved
                    data = brother_snmp.get_printer_telemetry(resolved)
            self.telemetry_ready.emit(data)
        except Exception:
            self.telemetry_ready.emit({"online": False, "ip": self.ip, "status": "Error"})


class StatusDialog(QWidget):
    """Detailed visual status window for TonerBox & Drum health."""
    def __init__(self, telemetry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Brother DCP-B7640DW - Status Monitor")
        self.setFixedSize(450, 320)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.init_ui(telemetry)

    def init_ui(self, t: dict):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        model = t.get("model") or "Brother Laser Printer"
        ip = t.get("ip") or "-"
        online = t.get("online", False)
        
        status_color = "#28a745" if online else "#dc3545"
        status_text = "Online / Siap" if online else "Offline / Tidak Terhubung"

        header_lbl = QLabel(f"<b>{model}</b>")
        header_lbl.setStyleSheet("font-size: 16px;")
        layout.addWidget(header_lbl)

        sub_lbl = QLabel(f"IP: {ip} | Status: <span style='color:{status_color}; font-weight:bold;'>{status_text}</span>")
        layout.addWidget(sub_lbl)

        lcd = t.get("lcd_text") or ("Ready" if online else "Offline")
        lcd_lbl = QLabel(f"Layar LCD: <i>\"{lcd}\"</i>")
        lcd_lbl.setStyleSheet("background-color: #2b2b2b; color: #a3e635; padding: 6px; border-radius: 4px; font-family: monospace;")
        layout.addWidget(lcd_lbl)

        # TonerBox Progress
        toner_pct = t.get("toner_pct")
        layout.addWidget(QLabel("<b>TonerBox TN-B028:</b>"))
        toner_bar = QProgressBar()
        toner_bar.setRange(0, 100)
        toner_bar.setValue(toner_pct if toner_pct is not None else 0)
        toner_bar.setTextVisible(True)
        toner_bar.setFormat(f"{toner_pct}%" if toner_pct is not None else "Tidak Terdeteksi")
        
        # Color coding toner bar
        if toner_pct is not None and toner_pct <= 10:
            toner_bar.setStyleSheet("QProgressBar::chunk { background-color: #dc3545; }")
        else:
            toner_bar.setStyleSheet("QProgressBar::chunk { background-color: #0284c7; }")
        layout.addWidget(toner_bar)

        # Drum Progress
        drum_pct = t.get("drum_pct")
        layout.addWidget(QLabel("<b>Unit Drum DR-B028:</b>"))
        drum_bar = QProgressBar()
        drum_bar.setRange(0, 100)
        drum_bar.setValue(drum_pct if drum_pct is not None else 0)
        drum_bar.setTextVisible(True)
        drum_bar.setFormat(f"{drum_pct}%" if drum_pct is not None else "Tidak Terdeteksi")
        if drum_pct is not None and drum_pct <= 10:
            drum_bar.setStyleSheet("QProgressBar::chunk { background-color: #dc3545; }")
        else:
            drum_bar.setStyleSheet("QProgressBar::chunk { background-color: #10b981; }")
        layout.addWidget(drum_bar)

        pages = t.get("page_count")
        pages_str = f"{pages:,} lembar" if pages is not None else "-"
        pages_lbl = QLabel(f"Total Halaman Dicetak: <b>{pages_str}</b>")
        layout.addWidget(pages_lbl)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_close = QPushButton("Tutup")
        btn_close.clicked.connect(self.close)
        btn_web = QPushButton("Buka Web Admin")
        btn_web.clicked.connect(lambda: webbrowser.open(f"http://{ip}"))
        btn_layout.addWidget(btn_web)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        self.setLayout(layout)


class WinPrintTrayApp:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.cfg = winprint_spooler.get_config()
        self.printer_model = self.cfg.get("printer_model", "Brother DCP-B7640DW")
        self.printer_ip = self.cfg.get("printer_ip", "192.168.100.229")
        self.last_telemetry = {}
        self.status_window = None

        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(self.render_tray_icon(100, online=False))
        self.tray_icon.setToolTip(f"Brother DCP-B7640DW ({self.printer_ip})\nMenghubungkan...")

        self.build_menu()
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

        # Polling Timer
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.refresh_telemetry)
        self.poll_timer.start(30000)  # every 30s

        # Initial probe
        self.refresh_telemetry()

    def render_tray_icon(self, toner_pct: int = 100, online: bool = True) -> QIcon:
        """Draws a crisp dynamic printer icon with a supply status dot."""
        pm = QPixmap(64, 64)
        pm.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Base printer body (Dark Gray)
        painter.setBrush(QColor(55, 65, 81))
        painter.setPen(QPen(QColor(31, 41, 55), 2))
        painter.drawRoundedRect(8, 22, 48, 30, 4, 4)

        # Paper tray top slot
        painter.setBrush(QColor(243, 244, 246))
        painter.setPen(QPen(QColor(156, 163, 175), 1))
        painter.drawRect(18, 10, 28, 14)

        # Output paper tray
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRect(16, 42, 32, 12)

        # Status Badge Indicator
        if not online:
            badge_color = QColor(220, 38, 38)     # Red
        elif toner_pct is not None and toner_pct <= 10:
            badge_color = QColor(234, 179, 8)     # Yellow
        else:
            badge_color = QColor(34, 197, 94)     # Green

        painter.setBrush(badge_color)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawEllipse(42, 4, 18, 18)

        painter.end()
        return QIcon(pm)

    def build_menu(self):
        menu = QMenu()

        act_status = QAction("📊 Status Monitor & Level Toner", menu)
        act_status.triggered.connect(self.show_status_dialog)
        menu.addAction(act_status)

        act_studio = QAction("🎨 Buka WinPrint Studio (Full Print Modes)", menu)
        act_studio.triggered.connect(self.launch_studio)
        menu.addAction(act_studio)

        act_print = QAction("⚡ Cetak Dokumen Cepat (PDF)", menu)
        act_print.triggered.connect(self.quick_print)
        menu.addAction(act_print)

        act_scan = QAction("📄 Pusat Pemindaian & OCR", menu)
        act_scan.triggered.connect(self.quick_scan)
        menu.addAction(act_scan)

        act_queue = QAction("📥 Kelola Antrean Cetak", menu)
        act_queue.triggered.connect(self.show_queue)
        menu.addAction(act_queue)

        menu.addSeparator()

        act_web = QAction("🌐 Buka Web Admin Printer", menu)
        act_web.triggered.connect(lambda: webbrowser.open(f"http://{self.printer_ip}"))
        menu.addAction(act_web)

        act_refresh = QAction("🔄 Segarkan Status Sekarang", menu)
        act_refresh.triggered.connect(self.refresh_telemetry)
        menu.addAction(act_refresh)

        menu.addSeparator()

        act_wizard = QAction("🛠️ Buka Printer Setup Wizard", menu)
        act_wizard.triggered.connect(self.launch_wizard_gui)
        menu.addAction(act_wizard)

        act_exit = QAction("❌ Keluar", menu)
        act_exit.triggered.connect(self.app.quit)
        menu.addAction(act_exit)

        self.tray_icon.setContextMenu(menu)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Single click
            self.show_status_dialog()

    def refresh_telemetry(self):
        self.cfg = winprint_spooler.get_config()
        self.printer_model = self.cfg.get("printer_model", "Brother DCP-B7640DW")
        self.printer_ip = self.cfg.get("printer_ip", self.printer_ip)
        self.worker = TelemetryWorker(self.printer_ip, self.printer_model)
        self.worker.telemetry_ready.connect(self.on_telemetry_received)
        self.worker.start()

    def on_telemetry_received(self, data: dict):
        self.last_telemetry = data
        if data.get("ip"):
            self.printer_ip = data["ip"]
        online = data.get("online", False)
        toner = data.get("toner_pct")
        drum = data.get("drum_pct")
        lcd = data.get("lcd_text", "Ready")
        model = data.get("model") or "Brother DCP-B7640DW"

        # Update Tray Icon
        self.tray_icon.setIcon(self.render_tray_icon(toner if toner is not None else 100, online=online))

        # Tooltip
        if online:
            tip = f"{model} ({self.printer_ip})\nStatus: {lcd}\nTonerBox: {toner}%\nDrum: {drum}%"
        else:
            tip = f"{model} ({self.printer_ip})\nStatus: OFFLINE"
        self.tray_icon.setToolTip(tip)

        # Notify on critical toner
        if online and toner is not None and toner <= 10:
            self.tray_icon.showMessage(
                "TonerBox Hampir Habis",
                f"Sisa toner Brother TN-B028 tinggal {toner}%. Harap siapkan cartridge baru.",
                QSystemTrayIcon.MessageIcon.Warning,
                6000
            )

    def show_status_dialog(self):
        if self.status_window is not None:
            self.status_window.close()
        self.status_window = StatusDialog(self.last_telemetry)
        self.status_window.show()

    def quick_print(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None, "Pilih Dokumen PDF untuk Dicetak", "", "Dokumen PDF (*.pdf);;Semua Berkas (*)"
        )
        if file_path:
            detected_paper = "A4"
            try:
                pw, ph = winprint_layout.get_pdf_page_size(file_path)
                detected_paper = winprint_layout.detect_pdf_media(pw, ph) or "A4"
            except Exception:
                pass
            job_id = winprint_spooler.submit_job(
                file_path=file_path,
                paper=detected_paper,
                duplex="none",
                printer_model=self.printer_model,
            )
            self.tray_icon.showMessage(
                "Cetak Dokumen",
                f"Dokumen '{os.path.basename(file_path)}' ({detected_paper}) dikirim ke {self.printer_model} (ID #{job_id}).",
                QSystemTrayIcon.MessageIcon.Information,
                4000
            )

    def quick_scan(self):
        save_path, _ = QFileDialog.getSaveFileName(
            None, "Simpan Hasil Pindaian", os.path.expanduser("~/Documents/Scan.pdf"), "PDF (*.pdf);;JPEG (*.jpg)"
        )
        if save_path:
            base_url = brother_scan.get_escl_base_url(self.printer_ip)
            ok = False
            if base_url:
                ok = brother_scan.scan_escl(base_url, "flatbed", 300, "color", save_path, do_ocr=True)
            if ok:
                self.tray_icon.showMessage("Pemindaian Selesai", f"Tersimpan di: {save_path}", QSystemTrayIcon.MessageIcon.Information, 4000)
                webbrowser.open(f"file://{save_path}")
            else:
                self.tray_icon.showMessage("Pemindaian Gagal", "Pastikan scanner terhubung dan aktif.", QSystemTrayIcon.MessageIcon.Critical, 4000)

    def show_queue(self):
        jobs = winprint_spooler.list_jobs(limit=10)
        txt = "Antrean Cetak WinPrint Saat Ini:\n\n"
        if not jobs:
            txt += "(Tidak ada antrean cetak aktif)"
        else:
            for j in jobs:
                txt += f"#{j['id']} | {j['status']} | {j['paper']} | {j['job_name'][:25]}\n"
        QMessageBox.information(None, "WinPrint Queue", txt)

    def launch_studio(self):
        cmd = os.path.join(os.path.expanduser("~/.local/bin"), "winprint-studio")
        if not os.path.exists(cmd):
            cmd = os.path.join(SCRIPT_DIR, "winprint_studio.py")
        subprocess.Popen([cmd])

    def launch_wizard_gui(self):
        cmd = os.path.join(os.path.expanduser("~/.local/bin"), "printer-wizard-gui")
        if not os.path.exists(cmd):
            cmd = os.path.join(SCRIPT_DIR, "../Arch/printer-wizard-gui")
        subprocess.Popen([cmd])

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    app = WinPrintTrayApp()
    app.run()
