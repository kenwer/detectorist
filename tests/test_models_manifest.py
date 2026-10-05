"""Checks on models/models.json, the manifest the released app downloads.

The app fetches this file from the main branch, so a typo here reaches every
user without a release. These checks need only the JSON file, not the model
files, and run in the fast tier.
"""

import json
from datetime import date
from pathlib import Path

from detectorist.model_downloader import model_filename_from_url

MANIFEST_PATH = Path(__file__).parent.parent / "models" / "models.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
URL_PREFIX = "https://github.com/kenwer/detectorist/raw/main/models/"


def test_manifest_is_a_non_empty_list():
    assert isinstance(MANIFEST, list)
    assert MANIFEST


def test_entries_have_the_fields_the_dialog_shows():
    for entry in MANIFEST:
        assert {"name", "url", "description", "size_mb", "release_date"} <= set(entry), entry.get("name")
        assert entry["name"].strip()
        assert entry["description"].strip()
        assert entry["size_mb"] > 0
        date.fromisoformat(entry["release_date"])


def test_urls_point_at_model_files_in_this_repository():
    for entry in MANIFEST:
        assert entry["url"].startswith(URL_PREFIX), entry["url"]
        assert entry["url"].endswith((".onnx", ".onnx.gz")), entry["url"]


def test_names_and_filenames_are_unique():
    names = [entry["name"] for entry in MANIFEST]
    filenames = [model_filename_from_url(entry["url"]) for entry in MANIFEST]

    assert len(set(names)) == len(names)
    assert len(set(filenames)) == len(filenames)


def test_no_entry_supersedes_a_current_model():
    current = {model_filename_from_url(entry["url"]) for entry in MANIFEST}
    superseded = {filename for entry in MANIFEST for filename in entry.get("supersedes", [])}

    # A download deletes the files it supersedes, so this would delete a live model
    assert not current & superseded
