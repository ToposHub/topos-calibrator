from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.prepare_argyll_bundle import prepare_bundle


def _fake_argyll(tmp_path: Path) -> Path:
    argyll_dir = tmp_path / "ArgyllCMS"
    bin_dir = argyll_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "spotread").write_text("fake binary", encoding="utf-8")
    (bin_dir / "spotread.exe").write_bytes(b"fake windows binary")
    (argyll_dir / "License.txt").write_text("AGPL license", encoding="utf-8")
    (argyll_dir / "License2.txt").write_text("GPL license", encoding="utf-8")
    return argyll_dir


def test_prepare_bundle_records_licenses_and_source(tmp_path: Path):
    argyll_dir = _fake_argyll(tmp_path)
    source_archive = tmp_path / "Argyll_V3.5.0_source.zip"
    source_archive.write_bytes(b"source archive")

    summary = prepare_bundle(
        argyll_dir,
        "macos",
        source_archive=source_archive,
        require_source=True,
    )

    assert summary["license_count"] == 2
    assert (argyll_dir / "THIRD_PARTY_NOTICES.md").is_file()
    assert (argyll_dir / "BUILD_METADATA.txt").is_file()
    assert (argyll_dir / "licenses" / "ARGYLLCMS_LICENSE_MANIFEST.txt").is_file()
    assert (argyll_dir / "source" / source_archive.name).read_bytes() == b"source archive"
    assert "SHA256=" in (
        argyll_dir / "licenses" / "ARGYLLCMS_LICENSE_MANIFEST.txt"
    ).read_text(encoding="utf-8")


def test_prepare_bundle_requires_source_for_distribution(tmp_path: Path):
    argyll_dir = _fake_argyll(tmp_path)

    with pytest.raises(SystemExit, match="requires the matching ArgyllCMS source archive"):
        prepare_bundle(argyll_dir, "windows", require_source=True)


def test_prepare_bundle_copies_license_from_source_archive(tmp_path: Path):
    argyll_dir = _fake_argyll(tmp_path)
    (argyll_dir / "License.txt").unlink()
    (argyll_dir / "License2.txt").unlink()
    source_archive = tmp_path / "Argyll_source.zip"
    with ZipFile(source_archive, "w") as archive:
        archive.writestr("Argyll_V3.5.0/License.txt", "AGPL license from source")

    summary = prepare_bundle(
        argyll_dir,
        "macos",
        source_archive=source_archive,
        require_source=True,
    )

    assert summary["license_count"] == 1
    manifest = (argyll_dir / "licenses" / "ARGYLLCMS_LICENSE_MANIFEST.txt").read_text(
        encoding="utf-8"
    )
    assert "source-archive/Argyll_V3.5.0/License.txt" in manifest
