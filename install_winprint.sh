#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    echo "Kesalahan: Jangan jalankan $0 dengan sudo. Jalankan sebagai user biasa: ./install_winprint.sh" >&2
    exit 1
fi

AUTHORITATIVE=1
FORCE_PROFILES=1
for arg in "$@"; do
    case "$arg" in
        --authoritative|--force-profiles)
            AUTHORITATIVE=1
            FORCE_PROFILES=1
            ;;
        --keep-local|--keep-profiles)
            AUTHORITATIVE=0
            FORCE_PROFILES=0
            ;;
        -h|--help)
            echo "Penggunaan: $0 [--authoritative | --keep-local]"
            echo "  (default / --authoritative) Timpa config & kalibrasi dengan standar kantor terkalibrasi"
            echo "  --keep-local                Pertahankan config.json & calibration_profiles.json lokal"
            exit 0
            ;;
        *)
            echo "Argumen tidak dikenal: $arg" >&2
            exit 1
            ;;
    esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/.local/share/winprint"
BIN_DIR="${HOME}/.local/bin"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
AUTOSTART_DIR="${HOME}/.config/autostart"
APPS_DIR="${HOME}/.local/share/applications"

echo "[1/5] Memeriksa dependensi sistem & Python..."
missing_req=0
for cmd in python3 gs pdfinfo pdftoppm; do
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "  [OK] $cmd ($(command -v "$cmd"))"
    else
        echo "  [KURANG] $cmd tidak ditemukan di PATH"
        missing_req=1
    fi
done

if ! python3 -c "import PyQt6, cairo" 2>/dev/null; then
    echo "  [KURANG] Paket Python PyQt6 dan/atau cairo (pycairo) belum terpasang"
    missing_req=1
else
    echo "  [OK] Modul Python PyQt6 & cairo tersedia"
fi

if [ "$missing_req" -ne 0 ]; then
    echo "Peringatan: Ada dependensi wajib yang belum lengkap. Lengkapi paket di atas agar GUI & rasterisasi berjalan penuh." >&2
    exit 1
fi

for br_bin in \
    "${SRC_DIR}/drivers/b7640dw/rawtobr3" \
    "/opt/brother/Printers/DCPB7640DW/lpd/x86_64/rawtobr3" \
    "/opt/brother/Printers/DCPL2540DW/lpd/rawtobr3"; do
    if [ -f "$br_bin" ]; then
        echo "  [OK] Brother PCL filter: $br_bin"
    else
        echo "  [INFO] Driver opsional tidak ditemukan: $br_bin (engine akan otomatis memakai fallback Pure PCL-XL)"
    fi
done

echo "[2/5] Menyinkronkan berkas ke ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}" "${TARGET_DIR}/modules" "${TARGET_DIR}/tests" "${TARGET_DIR}/scripts" "${TARGET_DIR}/drivers"

if [ "${SRC_DIR}" != "${TARGET_DIR}" ]; then
    cp -a "${SRC_DIR}/modules/." "${TARGET_DIR}/modules/"
    if [ -d "${SRC_DIR}/drivers" ]; then
        cp -a "${SRC_DIR}/drivers/." "${TARGET_DIR}/drivers/"
    fi
    if [ -d "${SRC_DIR}/tests" ]; then
        cp -a "${SRC_DIR}/tests/." "${TARGET_DIR}/tests/"
    fi
    if [ -d "${SRC_DIR}/scripts" ]; then
        cp -a "${SRC_DIR}/scripts/." "${TARGET_DIR}/scripts/"
    fi
    for ppd in BRPPB7640DW.PPD Brother_B7640DW_WinPrint.ppd office_manifest.json; do
        if [ -f "${SRC_DIR}/${ppd}" ]; then
            cp -f "${SRC_DIR}/${ppd}" "${TARGET_DIR}/${ppd}"
        fi
    done
    if [ -f "${SRC_DIR}/calibration_profiles.json" ]; then
        if [ ! -f "${TARGET_DIR}/calibration_profiles.json" ] || [ "${FORCE_PROFILES}" -eq 1 ]; then
            cp -f "${SRC_DIR}/calibration_profiles.json" "${TARGET_DIR}/calibration_profiles.json"
            echo "  [OK] calibration_profiles.json otoritatif diterapkan (+2.5 mm X, -3.8 mm Y)"
        else
            echo "  [KEEP] calibration_profiles.json lama dipertahankan (--keep-local)"
        fi
    fi
    cp -f "${SRC_DIR}/install_winprint.sh" "${TARGET_DIR}/install_winprint.sh"
    if [ -f "${SRC_DIR}/install_ubuntu.sh" ]; then
        cp -f "${SRC_DIR}/install_ubuntu.sh" "${TARGET_DIR}/install_ubuntu.sh"
        chmod +x "${TARGET_DIR}/install_ubuntu.sh"
    fi
fi

if [ "${AUTHORITATIVE}" -eq 1 ] || [ ! -f "${TARGET_DIR}/config.json" ]; then
    PYTHONPATH="${TARGET_DIR}/modules" python3 -c "import winprint_spooler; winprint_spooler.apply_authoritative_manifest()"
    echo "  [OK] config.json disinkronkan dengan office_manifest.json (F4 + Long-Edge + Safe Margin)"
fi

chmod +x "${TARGET_DIR}/install_winprint.sh"
if [ -f "${TARGET_DIR}/drivers/b7640dw/rawtobr3" ]; then
    chmod +x "${TARGET_DIR}/drivers/b7640dw/rawtobr3"
fi
for py_entry in winprint_cli.py winprint_studio.py winprint_tray.py winprint_control_center.py winprint_daemon.py winprint_ipp_server.py winprint_spooler.py winprint_engine.py; do
    if [ -f "${TARGET_DIR}/modules/${py_entry}" ]; then
        chmod +x "${TARGET_DIR}/modules/${py_entry}"
    fi
done

echo "[3/5] Membuat tautan perintah di ${BIN_DIR}..."
mkdir -p "${BIN_DIR}"
ln -sf "${TARGET_DIR}/modules/winprint_cli.py" "${BIN_DIR}/winprint"
ln -sf "${TARGET_DIR}/modules/winprint_studio.py" "${BIN_DIR}/winprint-studio"
ln -sf "${TARGET_DIR}/modules/winprint_tray.py" "${BIN_DIR}/winprint-tray"
ln -sf "${TARGET_DIR}/modules/winprint_control_center.py" "${BIN_DIR}/winprint-control-center"

echo "[4/5] Memasang layanan systemd --user, menu aplikasi & autostart tray..."
mkdir -p "${SYSTEMD_DIR}" "${AUTOSTART_DIR}" "${APPS_DIR}"

cat > "${APPS_DIR}/winprint-studio.desktop" <<EOF
[Desktop Entry]
Name=WinPrint Studio (Brother DCP-B7640DW / DCP-L2540DW)
Comment=Cetak Presisi F4/A4, Auto-Duplex & Imposisi Vektor untuk Printer Brother
Exec=${BIN_DIR}/winprint-studio %f
Icon=printer
Terminal=false
Type=Application
Categories=Office;Utility;Printing;
MimeType=application/pdf;
StartupNotify=true
EOF

cat > "${SYSTEMD_DIR}/winprint.service" <<'EOF'
[Unit]
Description=WinPrint-Linux Master Spooler & IPP Bridge Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/share/winprint/modules/winprint_daemon.py
Restart=always
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

cat > "${AUTOSTART_DIR}/winprint-tray.desktop" <<EOF
[Desktop Entry]
Name=Brother Status Monitor & WinPrint Tray
Comment=Real-time supply monitor and quick actions for Brother Printers
Exec=${BIN_DIR}/winprint-tray
Icon=printer
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;Utility;
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

echo "[5/5] Mengaktifkan winprint.service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
    systemctl --user enable --now winprint.service || true
    if systemctl --user is-active --quiet winprint.service; then
        systemctl --user restart winprint.service || true
    fi
    echo "  Status winprint.service: $(systemctl --user is-active winprint.service 2>/dev/null || echo 'inactive')"
fi

echo ""
echo "Instalasi user-space selesai."
echo "Opsional (bila mendaftarkan antrean CUPS loopback di PC baru untuk intersepsi Ctrl+P):"
echo "  lpadmin -p Brother_B7640DW_WinPrint -E -v ipp://127.0.0.1:9631/printers/Brother_B7640DW -P \"${TARGET_DIR}/Brother_B7640DW_WinPrint.ppd\""
