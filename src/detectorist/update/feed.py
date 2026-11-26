"""The GitHub release feed: is there a newer version, and which file is it."""

import http.client
import json
import logging
import platform
import re
import ssl
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any

import truststore
from packaging.version import InvalidVersion, Version

from detectorist import __version__

_log = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://api.github.com/repos/kenwer/detectorist/releases?per_page=100"
USER_AGENT = f"Detectorist/{__version__}"
TLS_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # Verifies certs with the OS trust store

_SHA256 = re.compile(r"sha256:([0-9a-f]{64})")


class UpdateError(Exception):
    """The feed or a download failed: network, HTTP status, bad data or a digest mismatch."""


@dataclass(frozen=True)
class Update:
    version: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    size: int
    sha256: str


def release_asset_name(system: str = sys.platform, machine: str = platform.machine()) -> str | None:
    """The installer asset for this platform, named as the build-* poe tasks name it."""
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine.lower())
    if arch is None:
        return None
    if system == "darwin":
        return f"Detectorist-macos-{arch}.dmg"
    if system == "win32":
        return f"Detectorist-windows-{arch}-setup.exe"
    if system.startswith("linux"):
        # The Linux build names the architecture as uname -m does
        return f"Detectorist-linux-{'aarch64' if arch == 'arm64' else arch}.AppImage"
    return None


def fetch_releases(url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """The release list JSON at url, newest first. Every failure becomes UpdateError."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=TLS_CONTEXT) as response:
            return json.loads(response.read())
    except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpdateError(f"Could not read the release feed: {exc}") from exc


def find_update(releases: list[dict[str, Any]], current_version: str, asset_name: str | None) -> Update | None:
    """The update the newest full release offers over current_version, or None.

    Drafts and pre-releases are never offered, as on GitHub's latest release.
    The notes join those of every release newer than current_version, newest
    first, pre-releases included since their changes ship in the offered one.
    No update when current_version does not parse, no full release is newer,
    or the newest lacks the platform's asset or that asset's sha256 digest.
    Releases whose tag does not parse are skipped. A feed of an unexpected
    shape raises UpdateError.
    """
    try:
        return _find_update(releases, current_version, asset_name)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise UpdateError(f"The release feed has an unexpected format: {exc!r}") from exc


def _version(release: dict[str, Any]) -> Version | None:
    try:
        return Version(str(release.get("tag_name", "")).removeprefix("v"))
    except InvalidVersion:
        return None


def _find_update(releases: list[dict[str, Any]], current_version: str, asset_name: str | None) -> Update | None:
    try:
        current = Version(current_version)
    except InvalidVersion:
        return None
    newer = sorted(
        (
            (version, r)
            for r in releases
            if not r.get("draft") and (version := _version(r)) is not None and version > current
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    offered, release = next(((v, r) for v, r in newer if not r.get("prerelease")), (None, None))
    if offered is None or release is None or asset_name is None:
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if asset is None:
        return None
    match = _SHA256.fullmatch(str(asset.get("digest", "")))
    if match is None:
        _log.warning("release %s has no sha256 digest for %s, so it is not offered", offered, asset_name)
        return None
    notes = [str(r.get("body") or "").strip() for v, r in newer if v <= offered]
    return Update(
        version=str(offered),
        notes="\n\n".join(n for n in notes if n),
        page_url=release.get("html_url", ""),
        asset_name=asset_name,
        asset_url=asset["browser_download_url"],
        size=int(asset.get("size", 0)),
        sha256=match.group(1),
    )
