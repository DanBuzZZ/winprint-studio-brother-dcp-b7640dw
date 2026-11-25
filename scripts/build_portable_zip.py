#!/usr/bin/env python3
"""
build_portable_zip.py - Clean Portable Distribution Packager for WinPrint Studio v2
Excludes runtime state (spool.db, spool_files/, config.json, test_logs/, __pycache__/)
and emits releases/WinPrint_Studio_v2_Portable.zip + SHA-256 checksum file.
"""

import hashlib
import os
import stat
import sys
import zipfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASE_DIR = os.path.join(ROOT_DIR, "releases")
ARCHIVE_NAME = "WinPrint_Studio_v2_Portable.zip"
ARCHIVE_PREFIX = "WinPrint_Studio_v2"

STATIC_FILES = (
    "README.md",
    "LICENSE",
    "requirements.txt",
    "install_winprint.sh",
    "install_ubuntu.sh",
    "Brother_B7640DW_WinPrint.ppd",
    "calibration_profiles.json",
    "scripts/build_portable_zip.py",
)


def collect_release_files(root_dir: str):
    """Collects (abs_path, rel_path) pairs belonging to the clean portable release."""
    entries = []
    for rel in STATIC_FILES:
        abs_p = os.path.join(root_dir, rel)
        if os.path.isfile(abs_p):
            entries.append((abs_p, rel))

    for sub in ("modules", "tests", "drivers"):
        sub_dir = os.path.join(root_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for cur_root, _, filenames in os.walk(sub_dir):
            if "__pycache__" in cur_root:
                continue
            for fname in sorted(filenames):
                if fname.endswith(".pyc"):
                    continue
                if sub in ("modules", "tests") and not fname.endswith(".py"):
                    continue
                abs_p = os.path.join(cur_root, fname)
                if os.path.isfile(abs_p):
                    rel_p = os.path.relpath(abs_p, root_dir)
                    entries.append((abs_p, rel_p))
    return entries


def build_archive(root_dir: str = ROOT_DIR, output_dir: str = RELEASE_DIR) -> tuple:
    os.makedirs(output_dir, exist_ok=True)
    zip_path = os.path.join(output_dir, ARCHIVE_NAME)
    sha_path = zip_path + ".sha256"

    files = collect_release_files(root_dir)
    if not files:
        raise RuntimeError(f"No release files found under {root_dir}")

    tmp_zip = zip_path + ".tmp"
    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for abs_p, rel_p in files:
            arcname = f"{ARCHIVE_PREFIX}/{rel_p}"
            info = zipfile.ZipInfo.from_file(abs_p, arcname=arcname)
            mode = os.stat(abs_p).st_mode
            if rel_p.endswith(".sh") or rel_p.endswith("rawtobr3"):
                mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            info.external_attr = (stat.S_IFMT(mode) | stat.S_IMODE(mode)) << 16
            with open(abs_p, "rb") as src:
                zf.writestr(info, src.read(), compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp_zip, zip_path)

    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with open(sha_path, "w", encoding="utf-8") as f:
        f.write(f"{digest}  {ARCHIVE_NAME}\n")

    return zip_path, sha_path, digest, len(files)


def main():
    zip_path, sha_path, digest, count = build_archive()
    print(f"[✓] Packaged {count} files -> {zip_path}")
    print(f"[✓] SHA-256 ({sha_path}): {digest}")


if __name__ == "__main__":
    main()
