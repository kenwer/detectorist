"""Tests for list_supported_images and filter_out_appledouble_files.

macOS writes AppleDouble sidecar files (e.g. "._IMG_1234.HIF") next to real
files when copying to filesystems without resource-fork support. These
sidecars share the original's extension, so a naive extension filter picks
them up as if they were real images.
"""

from detectorist.image_object import (
    APPLEDOUBLE_MAGIC,
    filter_out_appledouble_files,
    list_supported_images,
)


def test_sidecar_excluded_when_sibling_present(tmp_path):
    (tmp_path / "IMG_0001.jpg").write_bytes(b"fake jpeg data")
    (tmp_path / "._IMG_0001.jpg").write_bytes(APPLEDOUBLE_MAGIC + b"\x00" * 20)

    assert list_supported_images(str(tmp_path)) == ["IMG_0001.jpg"]


def test_sidecar_excluded_via_magic_number_without_sibling(tmp_path):
    (tmp_path / "._IMG_0002.jpg").write_bytes(APPLEDOUBLE_MAGIC + b"\x00" * 20)

    assert list_supported_images(str(tmp_path)) == []


def test_dot_underscore_file_kept_without_sibling_or_magic_number(tmp_path):
    (tmp_path / "._IMG_0003.jpg").write_bytes(b"not an appledouble file")

    assert list_supported_images(str(tmp_path)) == ["._IMG_0003.jpg"]


def test_unrelated_dotfile_excluded_by_extension_filter(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    (tmp_path / "IMG_0004.jpg").write_bytes(b"fake jpeg data")

    assert list_supported_images(str(tmp_path)) == ["IMG_0004.jpg"]


def test_mixed_case_extensions_still_matched(tmp_path):
    (tmp_path / "IMG_0005.HIF").write_bytes(b"fake heif data")
    (tmp_path / "IMG_0006.Jpg").write_bytes(b"fake jpeg data")

    assert list_supported_images(str(tmp_path)) == ["IMG_0005.HIF", "IMG_0006.Jpg"]


def test_filter_out_appledouble_files_drops_sidecar_with_sibling(tmp_path):
    original = tmp_path / "IMG_0007.jpg"
    sidecar = tmp_path / "._IMG_0007.jpg"
    original.write_bytes(b"fake jpeg data")
    sidecar.write_bytes(APPLEDOUBLE_MAGIC + b"\x00" * 20)

    kept = filter_out_appledouble_files([str(original), str(sidecar)])

    assert kept == [str(original)]


def test_filter_out_appledouble_files_checks_magic_number_without_sibling(tmp_path):
    sidecar = tmp_path / "._IMG_0008.jpg"
    sidecar.write_bytes(APPLEDOUBLE_MAGIC + b"\x00" * 20)

    assert filter_out_appledouble_files([str(sidecar)]) == []


def test_filter_out_appledouble_files_does_not_match_across_directories(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    unrelated_original = dir_a / "IMG_0009.jpg"
    lookalike_sidecar = dir_b / "._IMG_0009.jpg"
    unrelated_original.write_bytes(b"fake jpeg data")
    # Not a real AppleDouble file, and its "sibling" lives in a different directory.
    lookalike_sidecar.write_bytes(b"a genuine file that happens to start with ._")

    kept = filter_out_appledouble_files([str(unrelated_original), str(lookalike_sidecar)])

    assert set(kept) == {str(unrelated_original), str(lookalike_sidecar)}
