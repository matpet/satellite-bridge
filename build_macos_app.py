#!/usr/bin/env python3
"""Build the self-contained Intel macOS app; never installs or tunes a radio."""

import subprocess
import os
import struct
import sys
import tkinter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    if sys.version_info < (3, 12) or tkinter.TkVersion < 9:
        raise SystemExit("Build with Python 3.12 or later and Tk 9; the old Tk 8.6.8 runtime renders blank windows on this Mac.")
    BUILD.mkdir(exist_ok=True)
    run("/usr/bin/xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa", PACKAGING / "draw_icon.m", "-o", BUILD / "draw-icon")
    run(BUILD / "draw-icon", BUILD / "icon.png")
    iconset = BUILD / "SatelliteBridge.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = "@2x" if scale == 2 else ""
            run("/usr/bin/sips", "-z", size * scale, size * scale, BUILD / "icon.png", "--out", iconset / f"icon_{size}x{size}{suffix}.png")
    # ICNS stores the PNG representations directly. This also works when
    # iconutil's ImageIO service is unavailable in a restricted build session.
    chunks = []
    for code, filename in ((b"icp4", "16x16"), (b"icp5", "32x32"), (b"icp6", "32x32@2x"),
                           (b"ic07", "128x128"), (b"ic08", "256x256"), (b"ic09", "512x512"),
                           (b"ic10", "512x512@2x"), (b"ic11", "16x16@2x"),
                           (b"ic12", "32x32@2x"), (b"ic13", "128x128@2x"), (b"ic14", "256x256@2x")):
        png = (iconset / f"icon_{filename}.png").read_bytes()
        chunks.append(code + struct.pack(">I", len(png) + 8) + png)
    payload = b"".join(chunks)
    (PACKAGING / "SatelliteBridge.icns").write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(BUILD / "pyinstaller-cache")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", ROOT / "dist", "--workpath", BUILD / "pyinstaller", PACKAGING / "Satellite Bridge.spec")
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", ROOT / "dist" / "Satellite Bridge.app")
    print(f"Ready: {ROOT / 'dist' / 'Satellite Bridge.app'}")


if __name__ == "__main__":
    main()
