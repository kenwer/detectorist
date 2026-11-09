"""Resumable download of a release asset, verified against its sha256."""

import hashlib
import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .feed import TLS_CONTEXT, USER_AGENT, Update, UpdateError

_CHUNK = 1 << 20


class DownloadCancelled(Exception):
    """The user cancelled. The partial file stays, so the next download resumes."""


def sha256_of(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download(
    update: Update,
    dest: Path,
    progress: Callable[[int, int], None],
    cancelled: Callable[[], bool],
) -> None:
    """Download update to dest, resuming a partial file, and verify its sha256.

    Raises UpdateError on a network failure or a mismatch, and
    DownloadCancelled when cancelled() turns true.
    """
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if update.size and have >= update.size:
        # Complete already, say killed between the last write and the rename.
        # A Range request past the end would only get a 416.
        _finish(part, dest, sha256_of(part), update.sha256)
        return
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        request = urllib.request.Request(update.asset_url, headers=headers)
        with urllib.request.urlopen(request, timeout=30, context=TLS_CONTEXT) as response:
            if response.status == 206:
                with part.open("rb") as existing:
                    digest = hashlib.file_digest(existing, "sha256")
                mode = "ab"
            else:
                digest = hashlib.sha256()
                have, mode = 0, "wb"
            expected_end = have + int(response.headers.get("Content-Length", 0))
            total = update.size or expected_end
            with part.open(mode) as out:
                while block := response.read(_CHUNK):
                    out.write(block)
                    digest.update(block)
                    have += len(block)
                    progress(have, total)
                    if cancelled():
                        raise DownloadCancelled
            # read(n) returns b"" on a dropped connection instead of raising
            if have < expected_end:
                raise UpdateError("The download was interrupted. It resumes on the next try.")
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # the .part does not fit the file on the server
            part.unlink(missing_ok=True)
        raise UpdateError(f"The download failed: {exc}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise UpdateError(f"The download failed: {exc}") from exc
    _finish(part, dest, digest.hexdigest(), update.sha256)


def _finish(part: Path, dest: Path, actual: str, expected: str) -> None:
    if actual != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("The download does not match the release checksum.")
    part.replace(dest)
