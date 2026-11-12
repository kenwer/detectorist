import json
import re
import socket
from pathlib import Path

import pytest

from detectorist.update.feed import (
    USER_AGENT,
    UpdateError,
    fetch_latest_release,
    find_update,
    release_asset_name,
)
from tests.update_helpers import FakeServer, Route

ASSET = "Detectorist-macos-arm64.dmg"
HEX = "ab" * 32


def release(tag: str = "v0.9.0", digest: str | None = f"sha256:{HEX}", asset: str = ASSET) -> dict:
    entry = {"name": asset, "browser_download_url": f"https://example.org/{asset}", "size": 1234}
    if digest is not None:
        entry["digest"] = digest
    return {
        "tag_name": tag,
        "body": "## Changes\n- Something",
        "html_url": f"https://github.com/kenwer/detectorist/releases/tag/{tag}",
        "assets": [entry],
    }


def test_newer_release_is_an_update() -> None:
    update = find_update(release("v0.9.0"), "0.8.0", ASSET)
    assert update is not None
    assert update.version == "0.9.0"
    assert update.sha256 == HEX
    assert update.notes == "## Changes\n- Something"
    assert update.page_url == "https://github.com/kenwer/detectorist/releases/tag/v0.9.0"
    assert update.asset_name == ASSET
    assert update.asset_url == f"https://example.org/{ASSET}"
    assert update.size == 1234


def test_same_version_is_no_update() -> None:
    assert find_update(release("v0.8.0"), "0.8.0", ASSET) is None


def test_unparsable_versions_are_no_update() -> None:
    assert find_update(release("v0.9.0"), "unknown", ASSET) is None
    assert find_update(release("nightly"), "0.8.0", ASSET) is None


def test_missing_asset_is_no_update() -> None:
    assert find_update(release(asset="other.zip"), "0.8.0", ASSET) is None
    assert find_update(release(), "0.8.0", None) is None


@pytest.mark.parametrize("digest", [None, f"md5:{HEX}", "sha256:nothex"])
def test_a_release_without_a_sha256_digest_is_no_update(digest: str | None) -> None:
    """Without a digest the download could not be verified, so it is never offered."""
    assert find_update(release(digest=digest), "0.8.0", ASSET) is None


def test_asset_names_match_the_build_matrix() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"^\s+asset: (\S+)$", workflow, re.MULTILINE)) == {
        release_asset_name("darwin", "arm64"),
        release_asset_name("win32", "AMD64"),
        release_asset_name("linux", "x86_64"),
        release_asset_name("linux", "aarch64"),
    }


def test_unknown_platform_has_no_asset() -> None:
    assert release_asset_name("freebsd", "x86_64") is None
    assert release_asset_name("linux", "riscv64") is None


def test_fetch_returns_the_release_and_names_the_client(local_http_server: FakeServer) -> None:
    local_http_server.routes["/latest"] = Route(json.dumps(release()).encode(), content_type="application/json")
    assert fetch_latest_release(local_http_server.url("/latest"))["tag_name"] == "v0.9.0"
    # GitHub's API refuses requests without a User-Agent
    assert local_http_server.requests[0]["User-Agent"] == USER_AGENT


def test_fetch_raises_update_error_on_rate_limit(local_http_server: FakeServer) -> None:
    local_http_server.routes["/latest"] = Route(b'{"message": "API rate limit exceeded"}', status=403)
    with pytest.raises(UpdateError):
        fetch_latest_release(local_http_server.url("/latest"))


def test_fetch_raises_update_error_on_bad_json(local_http_server: FakeServer) -> None:
    local_http_server.routes["/latest"] = Route(b"not json")
    with pytest.raises(UpdateError):
        fetch_latest_release(local_http_server.url("/latest"))


def test_fetch_raises_update_error_when_offline() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(UpdateError):
        fetch_latest_release(f"http://127.0.0.1:{port}/latest", timeout=2)


@pytest.mark.parametrize(
    "bad",
    [
        [],  # a list instead of an object
        {"tag_name": "v0.9.0", "assets": ["not-a-dict"]},
        {"tag_name": "v0.9.0", "assets": [{"name": ASSET, "digest": f"sha256:{HEX}", "size": 1}]},  # no URL
        {
            "tag_name": "v0.9.0",
            "assets": [{"name": ASSET, "digest": f"sha256:{HEX}", "browser_download_url": "u", "size": "big"}],
        },
    ],
)
def test_malformed_release_raises_update_error(bad) -> None:
    with pytest.raises(UpdateError):
        find_update(bad, "0.8.0", ASSET)


def test_fetch_raises_update_error_on_a_truncated_body(local_http_server: FakeServer) -> None:
    local_http_server.routes["/latest"] = Route(json.dumps(release()).encode())
    local_http_server.cut_after = 10
    with pytest.raises(UpdateError):
        fetch_latest_release(local_http_server.url("/latest"))
