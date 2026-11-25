#!/usr/bin/env bash
set -euo pipefail

# WinPrint Studio v2.1 - Installer Khusus Ubuntu / Debian / Linux Mint
# Memasang seluruh paket sistem (Ghostscript, Poppler, QPDF, PyQt6, Cairo),
# memasang WinPrint Studio + daemon ke user-space, dan (opsional) mendaftarkan
# antrean Ctrl+P loopback CUPS via --with-cups.

WITH_CUPS=0
FORCE_PROFILES=0

for arg in "$@"; do
    case "$arg" in
        --with-cups) WITH_CUPS=1 ;;
        --force-profiles) FORCE_PROFILES=1 ;;
        -h|--help)
            echo "Penggunaan: $0 [--with-cups] [--force-profiles]"
            echo "  --with-cups       Daftarkan printer virtual Ctrl+P (Brother_B7640DW_WinPrint) ke CUPS"
            echo "  --force-profiles  Timpa calibration_profiles.json lokal dengan profil bawaan repo"
            exit 0
            ;;
        *)
            echo "Argumen tidak dikenal: $arg" >&2
            exit 1
            ;;
    esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Kesalahan: apt-get tidak ditemukan. Gunakan ./install_winprint.sh untuk distro non-Ubuntu/Debian." >&2
    exit 1
fi

echo "[1/4] Memasang dependensi sistem & Python untuk Ubuntu via APT..."
APT_PACKAGES=(
    python3
    ghostscript
    poppler-utils
    qpdf
    cups-client
    libnotify-bin
    libxcb-cursor0
    python3-pyqt6
    python3-cairo
    python3-gi
    python3-gi-cairo
    gir1.2-poppler-0.18
    python3-pil
)

if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
else
    echo "  Memerlukan hak sudo untuk memasang paket APT Ubuntu..."
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
fi

echo "[2/4] Menjalankan installer user-space WinPrint Studio..."
INSTALL_ARGS=()
if [ "${FORCE_PROFILES}" -eq 1 ]; then
    INSTALL_ARGS+=(--force-profiles)
fi
bash "${SRC_DIR}/install_winprint.sh" "${INSTALL_ARGS[@]}"

echo "[3/4] Memeriksa driver PCL resmi Brother Linux (opsional untuk F4 Duplex native)..."
if [ ! -f "/opt/brother/Printers/DCPB7640DW/lpd/x86_64/rawtobr3" ] && [ ! -f "/opt/brother/Printers/DCPL2540DW/lpd/rawtobr3" ]; then
    echo "  [INFO] Driver LPR Brother belum terpasang di /opt/brother/Printers/."
    echo "         WinPrint tetap berjalan lewat backend Pure PCL-XL, atau pasang driver Linux resmi Brother"
    echo "         (DCP-B7640DW / DCP-L2540DW) bila membutuhkan mode raster PCL 1038 untuk F4 Duplex."
fi

echo "[4/4] Pengaturan antrean CUPS virtual Ctrl+P..."
PPD_FILE="${HOME}/.local/share/winprint/Brother_B7640DW_WinPrint.ppd"
if [ "${WITH_CUPS}" -eq 1 ]; then
    if command -v lpadmin >/dev/null 2>&1 && [ -f "${PPD_FILE}" ]; then
        if [ "$(id -u)" -eq 0 ]; then
            lpadmin -p Brother_B7640DW_WinPrint -E -v ipp://127.0.0.1:9631/printers/Brother_B7640DW -P "${PPD_FILE}"
        else
            sudo lpadmin -p Brother_B7640DW_WinPrint -E -v ipp://127.0.0.1:9631/printers/Brother_B7640DW -P "${PPD_FILE}"
        fi
        echo "  [OK] Printer virtual Brother_B7640DW_WinPrint terdaftar untuk Ctrl+P."
    else
        echo "  [PERINGATAN] lpadmin atau PPD tidak ditemukan; lewati pendaftaran CUPS." >&2
    fi
else
    echo "  Lewati pendaftaran CUPS (jalankan ulang dengan --with-cups bila ingin intersepsi Ctrl+P otomatis)."
fi

echo ""
echo "Instalasi Ubuntu selesai! Jalankan 'winprint-studio' dari terminal atau cari 'WinPrint Studio' di menu aplikasi."
