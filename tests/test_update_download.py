import hashlib
from pathlib import Path

import pytest

from detectorist.update.download import DownloadCancelled, download
from detectorist.update.feed import USER_AGENT, Update, UpdateError
from tests.update_helpers import Route, never, no_progress

BLOB = bytes(range(256)) * 20_000  # 5 MB, several download chunks


def served_update(server, version: str = "0.9.0", sha256: str | None = None) -> Update:
    server.routes["/a.bin"] = Route(BLOB)
    digest = hashlib.sha256(BLOB).hexdigest() if sha256 is None else sha256
    return Update(version, "", "", "a.bin", server.url("/a.bin"), len(BLOB), digest)


def test_download_writes_verified_file(tmp_path: Path, local_http_server) -> None:
    dest = tmp_path / "0.9.0" / "a.bin"
    download(served_update(local_http_server), dest, no_progress, never)
    assert dest.read_bytes() == BLOB
    assert not (tmp_path / "0.9.0" / "a.bin.part").exists()
    assert local_http_server.requests[0]["User-Agent"] == USER_AGENT


def test_progress_reports_done_and_total(tmp_path: Path, local_http_server) -> None:
    calls = []
    download(served_update(local_http_server), tmp_path / "a.bin", lambda d, t: calls.append((d, t)), never)
    assert len(calls) > 1
    assert calls[-1] == (len(BLOB), len(BLOB))


def test_interrupted_download_resumes_with_range(tmp_path: Path, local_http_server) -> None:
    update = served_update(local_http_server)
    dest = tmp_path / "a.bin"
    local_http_server.cut_after = 1_500_000
    with pytest.raises(UpdateError):
        download(update, dest, no_progress, never)
    part = tmp_path / "a.bin.part"
    assert part.stat().st_size == 1_500_000
    download(update, dest, no_progress, never)
    assert local_http_server.requests[-1]["Range"] == "bytes=1500000-"
    assert dest.read_bytes() == BLOB


def test_server_ignoring_range_restarts_from_zero(tmp_path: Path, local_http_server) -> None:
    update = served_update(local_http_server)
    (tmp_path / "a.bin.part").write_bytes(b"x" * 1000)
    local_http_server.honor_range = False
    download(update, tmp_path / "a.bin", no_progress, never)
    assert (tmp_path / "a.bin").read_bytes() == BLOB


def test_digest_mismatch_deletes_part_and_raises(tmp_path: Path, local_http_server) -> None:
    update = served_update(local_http_server, sha256="0" * 64)
    with pytest.raises(UpdateError):
        download(update, tmp_path / "a.bin", no_progress, never)
    assert not (tmp_path / "a.bin.part").exists()
    assert not (tmp_path / "a.bin").exists()


def test_cancel_keeps_part_and_raises(tmp_path: Path, local_http_server) -> None:
    with pytest.raises(DownloadCancelled):
        download(served_update(local_http_server), tmp_path / "a.bin", no_progress, lambda: True)
    assert (tmp_path / "a.bin.part").exists()


def test_a_complete_part_file_is_verified_without_a_request(tmp_path: Path, local_http_server) -> None:
    update = served_update(local_http_server)
    (tmp_path / "a.bin.part").write_bytes(BLOB)
    download(update, tmp_path / "a.bin", no_progress, never)
    assert (tmp_path / "a.bin").read_bytes() == BLOB
    assert local_http_server.requests == []


def test_a_complete_but_wrong_part_file_starts_over(tmp_path: Path, local_http_server) -> None:
    update = served_update(local_http_server)
    (tmp_path / "a.bin.part").write_bytes(b"x" * len(BLOB))
    with pytest.raises(UpdateError):
        download(update, tmp_path / "a.bin", no_progress, never)
    assert not (tmp_path / "a.bin.part").exists()
    download(update, tmp_path / "a.bin", no_progress, never)
    assert (tmp_path / "a.bin").read_bytes() == BLOB
