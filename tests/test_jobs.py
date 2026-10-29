"""Tests for the job and identity types the Pipeline hands to its lanes."""

from detectorist.jobs import CancelToken, DecodeJob, FileStamp, ModelId


def test_cancel_token_starts_uncancelled_and_stays_cancelled():
    token = CancelToken()
    assert not token.cancelled

    token.cancel()
    token.cancel()

    assert token.cancelled


def test_file_stamp_changes_when_the_file_is_rewritten(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"one")
    before = FileStamp.from_path(str(path))

    path.write_bytes(b"other content")

    assert FileStamp.from_path(str(path)) != before
    assert FileStamp.from_path(str(path)) == FileStamp.from_path(str(path))


def test_model_id_is_filename_and_mtime(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"model")

    model_id = ModelId.from_path(str(path))

    assert model_id.filename == "model.onnx"
    assert model_id.mtime_ns == path.stat().st_mtime_ns


def test_jobs_compare_by_identity():
    token = CancelToken()

    assert DecodeJob("a.png", False, token) != DecodeJob("a.png", False, token)
