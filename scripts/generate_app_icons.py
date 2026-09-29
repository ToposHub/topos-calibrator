#!/usr/bin/env python3
"""Generate the platform application icons from the canonical 1024px PNG.

The source image lives in ``resources/app-icons/topos-calibrator.png``.  The
generated files are intentionally kept in the packaging directories so that
PyInstaller and NSIS can consume them without any extra build-time steps.

Run from the repository root (or from any directory)::

    python scripts/generate_app_icons.py

``iconutil`` is only available on macOS.  When run elsewhere, the script still
generates the Windows ICO and Linux PNG and reports that the ICNS was skipped.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "resources" / "app-icons" / "topos-calibrator.png"
MAC_ICONSET = PROJECT_ROOT / "packaging" / "macos" / "ToposCalibrator.iconset"
MAC_ICNS = PROJECT_ROOT / "packaging" / "macos" / "ToposCalibrator.icns"
WINDOWS_ICO = PROJECT_ROOT / "packaging" / "windows" / "ToposCalibrator.ico"
LINUX_PNG = PROJECT_ROOT / "packaging" / "linux" / "ToposCalibrator.png"


MAC_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)
WINDOWS_SIZES = (16, 24, 32, 48, 64, 96, 128, 256)


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def generate_mac_icon(source: Image.Image) -> None:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        print("Skipping ICNS: iconutil is only available on macOS")
        return

    if MAC_ICONSET.exists():
        shutil.rmtree(MAC_ICONSET)
    MAC_ICONSET.mkdir(parents=True)

    for filename, size in MAC_SIZES:
        resized(source, size).save(MAC_ICONSET / filename, format="PNG", optimize=True)

    subprocess.run(
        [iconutil, "-c", "icns", "-o", str(MAC_ICNS), str(MAC_ICONSET)],
        check=True,
    )
    shutil.rmtree(MAC_ICONSET)
    print(f"Generated {MAC_ICNS}")


def generate_windows_icon(source: Image.Image) -> None:
    WINDOWS_ICO.parent.mkdir(parents=True, exist_ok=True)
    # Pillow stores every requested size in the ICO container.  Keeping a
    # 256px entry is important for Windows Explorer's high-DPI rendering.
    source.save(WINDOWS_ICO, format="ICO", sizes=[(size, size) for size in WINDOWS_SIZES])
    print(f"Generated {WINDOWS_ICO}")


def generate_linux_icon() -> None:
    LINUX_PNG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, LINUX_PNG)
    print(f"Copied {LINUX_PNG}")


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Icon source not found: {SOURCE}")

    with Image.open(SOURCE) as image:
        if "A" not in image.mode:
            raise SystemExit(
                "Icon source must include an alpha channel (RGBA/LA) for transparent packaging"
            )
        source = image.convert("RGBA")
        if source.width != 1024 or source.height != 1024:
            raise SystemExit(
                f"Icon source must be 1024x1024 for the Retina master; got "
                f"{source.width}x{source.height}"
            )

        generate_mac_icon(source)
        generate_windows_icon(source)
        generate_linux_icon()


if __name__ == "__main__":
    main()
