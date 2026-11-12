"""Tests for the job types the Pipeline hands to its lanes."""

from detectorist.jobs import CancelToken, DecodeJob


def test_jobs_compare_by_identity():
    token = CancelToken()

    assert DecodeJob("a.png", token) != DecodeJob("a.png", token)
