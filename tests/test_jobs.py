"""Tests for the job types the Pipeline hands to its lanes."""

from detectorist.jobs import CancelToken, DecodeJob


def test_cancel_token_starts_uncancelled_and_stays_cancelled():
    token = CancelToken()
    assert not token.cancelled

    token.cancel()
    token.cancel()

    assert token.cancelled


def test_jobs_compare_by_identity():
    token = CancelToken()

    assert DecodeJob("a.png", token) != DecodeJob("a.png", token)
