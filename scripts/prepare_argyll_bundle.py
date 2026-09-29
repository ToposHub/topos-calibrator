#!/usr/bin/env python3
"""Prepare an ArgyllCMS bundle for a distributable Topos Calibrator build.

The project does not commit third-party binaries. A packager downloads the
official ArgyllCMS binary archive, extracts it to ``ArgyllCMS/``, and supplies
the matching official source archive to this script. The script only adds
compliance metadata and copies license/source archives; it never modifies an
ArgyllCMS executable.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARGYLL_DIR = PROJECT_ROOT / "ArgyllCMS"
ARGYLL_WEBSITE = "https://www.argyllcms.com/"
ARGYLL_SOURCE_URL = "https://www.argyllcms.com/downloadsrc.html"

LICENSE_BASENAMES = {
    "license",
    "license.txt",
    "license2.txt",
    "license3.txt",
    "license4.txt",
    "copying",
    "copying.txt",
    "copying_lgpl.txt",
    "copying-lgpl.txt",
    "copyright",
}
REQUIRED_TOOLS = ("spotread", "dispcal", "targen", "colprof", "collink", "dispwin")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_name(value: str | None) -> str:
    if value:
        return value.lower()
    current = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(current, current)


def _binary_suffix(target_platform: str) -> str:
    return ".exe" if target_platform == "windows" else ""


def find_bin_dir(argyll_dir: Path, target_platform: str) -> Path:
    """Return the directory containing the ArgyllCMS command-line tools."""

    suffix = _binary_suffix(target_platform)
    candidates = [argyll_dir / "bin", argyll_dir]
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        existing = [candidate / f"{name}{suffix}" for name in REQUIRED_TOOLS]
        if (candidate / f"spotread{suffix}").is_file():
            return candidate
        # A partial official package is still useful for diagnostics, but the
        # release must contain at least spotread to be bundled.
        if any(path.is_file() for path in existing):
            return candidate
    expected = f"spotread{suffix}"
    raise SystemExit(
        f"ArgyllCMS bundle is missing {expected}. Expected {argyll_dir / 'bin' / expected}."
    )


def infer_version(bin_dir: Path, target_platform: str) -> str:
    """Read the version from a non-device Argyll tool when possible."""

    suffix = _binary_suffix(target_platform)
    for tool in ("dispwin", "targen", "colprof", "spotread"):
        executable = bin_dir / f"{tool}{suffix}"
        if not executable.is_file():
            continue
        try:
            result = subprocess.run(
                [str(executable), "-?"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Version\s+([0-9]+(?:\.[0-9]+)+)", output, re.IGNORECASE)
        if match:
            return match.group(1)
    return "unknown"


def _license_files(argyll_dir: Path) -> list[Path]:
    generated = argyll_dir / "licenses"
    matches: list[Path] = []
    for path in argyll_dir.rglob("*"):
        if not path.is_file() or generated in path.parents:
            continue
        if path.name.lower() in LICENSE_BASENAMES:
            matches.append(path)
    return sorted(matches)


def _copy_source_archive(source_archive: Path | None, argyll_dir: Path) -> tuple[str, str]:
    if source_archive is None:
        return "", ""
    source_archive = source_archive.expanduser().resolve()
    if not source_archive.is_file():
        raise SystemExit(f"ArgyllCMS source archive not found: {source_archive}")
    destination_dir = argyll_dir / "source"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_archive.name
    if source_archive != destination.resolve():
        shutil.copy2(source_archive, destination)
    return destination.name, _sha256(destination)


def _archive_license_files(source_archive: Path | None) -> list[tuple[str, bytes]]:
    """Read official license files from a matching ZIP/TGZ without extracting code."""
    if source_archive is None:
        return []

    records: list[tuple[str, bytes]] = []
    if zipfile.is_zipfile(source_archive):
        with zipfile.ZipFile(source_archive) as archive:
            for member in archive.infolist():
                if member.is_dir() or Path(member.filename).name.lower() not in LICENSE_BASENAMES:
                    continue
                records.append((f"source-archive/{member.filename}", archive.read(member)))
        return records

    if tarfile.is_tarfile(source_archive):
        with tarfile.open(source_archive, mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or Path(member.name).name.lower() not in LICENSE_BASENAMES:
                    continue
                extracted = archive.extractfile(member)
                if extracted is not None:
                    records.append((f"source-archive/{member.name}", extracted.read()))
    return records


def prepare_bundle(
    argyll_dir: Path,
    target_platform: str,
    source_archive: Path | None = None,
    require_source: bool = False,
) -> dict[str, str | int]:
    if not argyll_dir.is_dir():
        raise SystemExit(f"ArgyllCMS directory does not exist: {argyll_dir}")

    bin_dir = find_bin_dir(argyll_dir, target_platform)
    version = infer_version(bin_dir, target_platform)
    official_files = _license_files(argyll_dir)
    source_name, source_hash = _copy_source_archive(source_archive, argyll_dir)
    license_records = [
        (path.relative_to(argyll_dir).as_posix(), path.read_bytes())
        for path in official_files
    ]
    license_records.extend(_archive_license_files(source_archive))

    if not license_records:
        raise SystemExit(
            "No official ArgyllCMS license files were found in the binary or source "
            "archive. The distributable cannot be prepared without the official "
            "license texts."
        )
    if require_source and source_archive is None:
        raise SystemExit(
            "A distributable build requires the matching ArgyllCMS source archive. "
            "Pass --source-archive /path/to/Argyll_Vx.y.z_source.zip."
        )

    licenses_dir = argyll_dir / "licenses"
    official_dir = licenses_dir / "official"
    official_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines = [
        "ArgyllCMS official license files included in this build",
        f"ArgyllCMS version: {version}",
        f"Binary source directory: {argyll_dir}",
        "",
    ]
    for source_name_in_archive, content in license_records:
        safe_name = "official-" + source_name_in_archive.replace("/", "__")
        destination = official_dir / safe_name
        destination.write_bytes(content)
        manifest_lines.append(
            f"{source_name_in_archive} -> licenses/official/{destination.name}  "
            f"SHA256={_sha256(destination)}"
        )
    (licenses_dir / "ARGYLLCMS_LICENSE_MANIFEST.txt").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8"
    )

    notice_template = PROJECT_ROOT / "packaging" / "argyll" / "THIRD_PARTY_NOTICES.md"
    shutil.copy2(notice_template, argyll_dir / "THIRD_PARTY_NOTICES.md")

    source_lines = [
        "ArgyllCMS corresponding-source record",
        f"Version detected at build time: {version}",
        f"Official source page: {ARGYLL_SOURCE_URL}",
        f"Official project page: {ARGYLL_WEBSITE}",
    ]
    if source_name:
        source_lines.extend(
            [
                f"Bundled source archive: source/{source_name}",
                f"Bundled source archive SHA-256: {source_hash}",
            ]
        )
    else:
        source_lines.extend(
            [
                "Bundled source archive: NOT INCLUDED",
                "The packager must publish the exact corresponding source archive "
                "alongside the application or provide a valid written source offer.",
            ]
        )
    (licenses_dir / "ARGYLLCMS_SOURCE_CODE.txt").write_text(
        "\n".join(source_lines) + "\n", encoding="utf-8"
    )

    build_info = [
        "Topos Calibrator ArgyllCMS bundle metadata",
        f"ArgyllCMS version: {version}",
        f"Target platform: {target_platform}",
        f"Binary directory: {bin_dir.relative_to(argyll_dir).as_posix()}",
        f"Official license files copied: {len(license_records)}",
        f"Corresponding source archive: {source_name or 'NOT INCLUDED'}",
    ]
    (argyll_dir / "BUILD_METADATA.txt").write_text(
        "\n".join(build_info) + "\n", encoding="utf-8"
    )
    return {
        "version": version,
        "license_count": len(license_records),
        "source_archive": source_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add license, source, and third-party metadata to an ArgyllCMS bundle."
    )
    parser.add_argument(
        "--argyll-dir",
        type=Path,
        default=DEFAULT_ARGYLL_DIR,
        help="Extracted official ArgyllCMS directory (default: ./ArgyllCMS)",
    )
    parser.add_argument(
        "--platform",
        choices=("macos", "windows", "linux"),
        default=None,
        help="Target platform; inferred from the current host when omitted",
    )
    parser.add_argument(
        "--source-archive",
        type=Path,
        help="Matching official ArgyllCMS source ZIP/TGZ to ship as corresponding source",
    )
    parser.add_argument(
        "--require-source",
        action="store_true",
        help="Fail unless a matching source archive is copied into the bundle",
    )
    args = parser.parse_args()

    target_platform = _platform_name(args.platform)
    summary = prepare_bundle(
        args.argyll_dir.expanduser().resolve(),
        target_platform,
        args.source_archive,
        args.require_source,
    )
    print(
        f"Prepared ArgyllCMS {summary['version']} for {target_platform}: "
        f"{summary['license_count']} official license files; "
        f"source archive={summary['source_archive'] or 'not included'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
