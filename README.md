# WinPrint Studio v2 — Brother DCP-B7640DW & DCP-L2540DW Edition

Subsistem cetak langsung (*direct-to-printer TCP Port 9100*) dan antarmuka pratinjau PyQt6 untuk printer laser jaringan **Brother DCP-B7640DW** dan **Brother DCP-L2540DW** di Linux.

Dirancang khusus untuk mengatasi kendala umum CUPS/PCL-XL pada ukuran kertas **F4 / Folio (215 x 330 mm / 8.5 x 13 in)**, termasuk pergeseran halaman belakang (*back-side origin fallback* 50,8 mm) saat cetak bolak-balik (*Auto Duplex*), serta menghadirkan kendali penuh ala driver Windows langsung dari desktop Linux.

---

## Perangkat yang Didukung

| Model Printer | Status Dukungan | Backend Utama | Kalibrasi Folio Duplex Bawaan |
| :--- | :--- | :--- | :--- |
| **Brother DCP-B7640DW** | Terkalibrasi Penuh | Brother PCL (`rawtobr3`, kode Folio `1038`) / Fallback `pxlmono` | `+2.5 mm X`, `-3.8 mm Y` (Long-Edge) |
| **Brother DCP-L2540DW** | Didukung (Multi-Printer) | Brother PCL (`rawtobr3`, `4096a3a`) / Fallback `pxlmono` | Default `0.0 mm` (dapat dikalibrasi via UI 3x2) |

---

## Fitur Utama

- **Presisi F4 / Folio & Auto Duplex**: Menggunakan rasterisasi PCL resmi Brother (`rawtobr3` kode media Folio) dengan kompensasi offset sub-milimeter (`±0.1 mm`) per model dan per ukuran kertas di [calibration_profiles.json](calibration_profiles.json).
- **Lembar Kalibrasi 3x2 Terawang**: Pembuat PDF kalibrasi 2 halaman dengan target crosshair dan mistar milimeter `±15 mm` untuk memverifikasi ketepatan depan-belakang hanya dengan 1 lembar kertas.
- **Imposisi Vektor Murni**: Seleksi halaman lossless via `qpdf` serta komposisi **2-Up**, **4-Up**, **Booklet Jilid Kiri/Kanan (Kitab/Arab)**, garis pemisah, dan *watermark* vektor via `Poppler + Cairo` agar ketajaman 600/1200 DPI terjaga.
- **Kontrol Hardware Penuh**: Pemilihan *Paper Source* (`Auto`, `Tray 1`, `Bypass/Manual`), *Media Type* (`Plain`, `Thick`, `Recycled`, `Envelopes`), *Economode / Toner Save*, *Quiet Mode* (`PAPERFEEDSPEED=HALF`), *Print Density* (`-2` s.d. `+2`), serta kompensasi *Binding Gutter* (`0–15 mm`).
- **Akselerasi Multi-Rangkap & Kolasi**: Penggandaan hardware (`\x1b&lNX`) untuk pekerjaan 1-halaman berkecepatan penuh, serta bundel `@PJL JOB` / `@PJL EOJ` lewat soket TCP tunggal dengan tombol **Batal Kirim**.
- **Bridge IPP Loopback (`Ctrl+P` Intercept)**: Mendengarkan port lokal `9631` (`WinPrintThreadingIPPServer`) untuk menangkap tugas cetak dari aplikasi desktop (OnlyOffice, LibreOffice, Browser) beserta nama dokumen asli, rangkap, dan ukuran halaman PDF otomatis.
- **Telemetri Dua Arah SNMP + PJL**: Menampilkan status panel LCD langsung, level Toner & Drum, ukuran kertas terpasang di baki (`INTRAY2SIZE`), serta *auto-discovery* perubahan IP DHCP.

---

## Persyaratan Sistem

- Python `3.10+`
- Utilitas sistem: `ghostscript` (`gs`), `poppler-utils` (`pdfinfo`, `pdftoppm`), `qpdf`
- Library Python (`requirements.txt`): `PyQt6`, `pycairo`, `PyGObject` (`gi` + `gir1.2-poppler-0.18`), `Pillow`
- **Opsional (Sangat Direkomendasikan untuk F4 Duplex Brother)**: Driver LPR resmi Brother Linux (`DCPB7640DW` / `DCPL2540DW`) agar `rawtobr3` tersedia; jika belum terpasang, engine otomatis memakai jalur `gs -sDEVICE=pxlmono`.

---

## Instalasi Cepat

### Ubuntu / Debian / Linux Mint (Otomatis Pasang Paket APT)

```bash
git clone https://github.com/DanBuzZZ/winprint-studio-brother-dcp-b7640dw.git
cd winprint-studio-brother-dcp-b7640dw
chmod +x install_ubuntu.sh install_winprint.sh
./install_ubuntu.sh --with-cups
```

Opsi `--with-cups` otomatis mendaftarkan antrean virtual `Brother_B7640DW_WinPrint` ke CUPS agar `Ctrl+P` dari OnlyOffice, LibreOffice, dan browser langsung membuka WinPrint Studio.

### Distro Linux Lain (Arch / Fedora — User-Space Tanpa Root)

```bash
git clone https://github.com/DanBuzZZ/winprint-studio-brother-dcp-b7640dw.git
cd winprint-studio-brother-dcp-b7640dw
./install_winprint.sh
```

Skrip [install_winprint.sh](install_winprint.sh) akan memeriksa dependensi, menyalin modul ke `~/.local/share/winprint/`, menautkan perintah (`winprint-studio`, `winprint`, `winprint-tray`, `winprint-control-center`) ke `~/.local/bin/`, membuat entri menu desktop, serta mengaktifkan layanan latar belakang `winprint.service` (`systemd --user`).

### Opsional: Mendaftarkan Intersepsi `Ctrl+P` CUPS Secara Manual

```bash
lpadmin -p Brother_B7640DW_WinPrint -E \
  -v ipp://127.0.0.1:9631/printers/Brother_B7640DW \
  -P ~/.local/share/winprint/Brother_B7640DW_WinPrint.ppd
```

---

## Pengujian Otomatis (Offline, Tanpa Membuang Kertas)

```bash
python3 -m py_compile modules/*.py scripts/build_portable_zip.py
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Untuk membuat arsip portabel bersih siap bagikan:

```bash
python3 scripts/build_portable_zip.py
```

---

## Lisensi

Dirilis di bawah lisensi [MIT](LICENSE).
