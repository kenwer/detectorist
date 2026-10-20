"""Checks on models/models.json and models/classifiers/models.json, the manifests the released app downloads.

The app fetches these files from the main branch, so a typo here reaches every
user without a release. These checks need only the JSON files, not the model
files, and run in the fast tier.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from detectorist.model_downloader import model_filename_from_url

MODELS_DIR = Path(__file__).parent.parent / "models"
DETECTORS = json.loads((MODELS_DIR / "models.json").read_text())
CLASSIFIERS = json.loads((MODELS_DIR / "classifiers" / "models.json").read_text())
URL_PREFIX = "https://github.com/kenwer/detectorist/raw/main/models/"

both_manifests = pytest.mark.parametrize(("manifest", "url_prefix"), [
    (DETECTORS, URL_PREFIX),
    (CLASSIFIERS, URL_PREFIX + "classifiers/"),
], ids=["detectors", "classifiers"])


@both_manifests
def test_manifest_is_a_non_empty_list(manifest, url_prefix):
    assert isinstance(manifest, list)
    assert manifest


@both_manifests
def test_entries_have_the_fields_the_dialog_shows(manifest, url_prefix):
    for entry in manifest:
        assert {"name", "url", "description", "size_mb", "release_date"} <= set(entry), entry.get("name")
        assert entry["name"].strip()
        assert entry["description"].strip()
        assert entry["size_mb"] > 0
        date.fromisoformat(entry["release_date"])


@both_manifests
def test_urls_point_at_model_files_in_the_manifest_folder(manifest, url_prefix):
    for entry in manifest:
        assert entry["url"].startswith(url_prefix), entry["url"]
        assert "/" not in entry["url"].removeprefix(url_prefix), entry["url"]
        assert entry["url"].endswith((".onnx", ".onnx.gz")), entry["url"]


def test_names_and_filenames_are_unique_across_both_manifests():
    # filename_to_name and successor_of look files up across both
    names = [entry["name"] for entry in DETECTORS + CLASSIFIERS]
    filenames = [model_filename_from_url(entry["url"]) for entry in DETECTORS + CLASSIFIERS]

    assert len(set(names)) == len(names)
    assert len(set(filenames)) == len(filenames)


@both_manifests
def test_no_entry_supersedes_a_current_model(manifest, url_prefix):
    current = {model_filename_from_url(entry["url"]) for entry in manifest}
    superseded = {filename for entry in manifest for filename in entry.get("supersedes", [])}

    # A download deletes the files it supersedes, so this would delete a live model
    assert not current & superseded


@both_manifests
def test_no_entry_names_a_kind(manifest, url_prefix):
    # The folder decides the kind. Releases before classifier support read
    # every top-level entry as a detection model, whatever its kind says.
    for entry in manifest:
        assert "kind" not in entry, entry["name"]


def test_only_classifiers_say_which_detection_classes_they_name():
    # Spelled out even for "*", so that applying to everything is a decision and not an omission
    for entry in CLASSIFIERS:
        patterns = entry.get("classifies")
        assert isinstance(patterns, list) and patterns, entry["name"]
        assert all(isinstance(pattern, str) and pattern.strip() for pattern in patterns), entry["name"]
    for entry in DETECTORS:
        assert "classifies" not in entry, entry["name"]
