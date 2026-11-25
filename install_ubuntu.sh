#!/usr/bin/env bash
set -euo pipefail

# WinPrint Studio v2.1.2 - Installer Lengkap Ubuntu / Debian / Linux Mint
# Otomatis:
# 1. Memasang paket APT Ubuntu (Ghostscript, Poppler, QPDF, PyQt6, Cairo, CUPS)
# 2. Memasang WinPrint Studio + driver biner rawtobr3 (x86_64) + profil kalibrasi F4 Duplex
# 3. Mendaftarkan Brother_B7640DW_WinPrint ke CUPS DAN menyetelnya sebagai Printer Default Ctrl+P

if [ "$(id -u)" -eq 0 ]; then
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        echo "Mendeteksi dijalankan via sudo; silakan jalankan sebagai user biasa: ./install_ubuntu.sh $*" >&2
        exit 1
    fi
fi

WITH_CUPS=1
FORCE_PROFILES=1

for arg in "$@"; do
    case "$arg" in
        --with-cups) WITH_CUPS=1 ;;
        --no-cups) WITH_CUPS=0 ;;
        --keep-profiles) FORCE_PROFILES=0 ;;
        --force-profiles) FORCE_PROFILES=1 ;;
        -h|--help)
            echo "Penggunaan: $0 [--no-cups] [--keep-profiles]"
            echo "  (default)        Pasang paket APT, WinPrint Studio, rawtobr3 F4, & set Brother_B7640DW_WinPrint sebagai Printer Default"
            echo "  --no-cups        Lewati pendaftaran printer virtual Ctrl+P ke CUPS"
            echo "  --keep-profiles  Pertahankan calibration_profiles.json lama bila sudah ada"
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
    cups
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

echo "  Memerlukan hak sudo untuk memasang paket APT Ubuntu..."
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"

echo "[2/4] Menjalankan installer user-space (termasuk rawtobr3 F4 & profil kalibrasi)..."
INSTALL_ARGS=()
if [ "${FORCE_PROFILES}" -eq 1 ]; then
    INSTALL_ARGS+=(--force-profiles)
fi
bash "${SRC_DIR}/install_winprint.sh" "${INSTALL_ARGS[@]}"

echo "[3/4] Memverifikasi driver PCL F4 Duplex (Brother rawtobr3 x86_64)..."
if [ -x "${HOME}/.local/share/winprint/drivers/b7640dw/rawtobr3" ] || [ -x "/opt/brother/Printers/DCPB7640DW/lpd/x86_64/rawtobr3" ]; then
    echo "  [OK] Mesin PCL Brother rawtobr3 (kode kertas Folio 1038) aktif dan siap dipakai!"
else
    echo "  [PERINGATAN] rawtobr3 tidak ditemukan — cetak F4 Duplex akan turun ke mode PCL-XL." >&2
fi

echo "[4/4] Mendaftarkan printer virtual Ctrl+P & menyetelnya sebagai Default CUPS..."
PPD_FILE="${HOME}/.local/share/winprint/Brother_B7640DW_WinPrint.ppd"
if [ "${WITH_CUPS}" -eq 1 ]; then
    if command -v lpadmin >/dev/null 2>&1 && [ -f "${PPD_FILE}" ]; then
        sudo systemctl enable --now cups >/dev/null 2>&1 || true
        sudo lpadmin -p Brother_B7640DW_WinPrint -E -v ipp://127.0.0.1:9631/printers/Brother_B7640DW -P "${PPD_FILE}"
        sudo lpadmin -d Brother_B7640DW_WinPrint
        lpoptions -d Brother_B7640DW_WinPrint >/dev/null 2>&1 || true
        echo "  [OK] Printer virtual 'Brother_B7640DW_WinPrint' terdaftar & disetel sebagai DEFAULT CUPS."
    else
        echo "  [PERINGATAN] lpadmin atau PPD tidak ditemukan; lewati pendaftaran CUPS." >&2
    fi
else
    echo "  Lewati pendaftaran CUPS (--no-cups)."
fi

echo ""
echo "Instalasi Ubuntu selesai! Setiap Ctrl+P kini langsung membuka WinPrint Studio dengan setelan terkalibrasi."
echo "Jalankan 'winprint-tray &' atau relogin agar ikon Tray memantau status printer di panel atas."
