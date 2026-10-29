"""Tests for the ImageWorker, the decode lane, on a real thread."""

import numpy as np
import pytest
from PySide6.QtCore import QObject, QThread, Signal

from detectorist.image_object import ImageObject
from detectorist.image_worker import ImageWorker
from detectorist.jobs import CancelToken, DecodeJob, DisplayJob
from tests.fakes import make_images


class Sender(QObject):
    """Sends jobs across threads the way the Pipeline does, through a queued signal."""
    submit = Signal(object)


@pytest.fixture
def worker(qtbot):
    thread = QThread()
    worker = ImageWorker()
    worker.moveToThread(thread)
    sender = Sender()
    sender.submit.connect(worker.run)
    thread.start()
    yield worker, sender.submit.emit
    thread.quit()
    thread.wait()


def test_worker_decodes_an_image(qtbot, worker, tmp_path):
    lane, submit = worker
    (path,) = make_images(tmp_path, ["a.png"], (64, 48))
    job = DecodeJob(path, CancelToken())

    with qtbot.waitSignal(lane.decoded) as blocker:
        submit(job)

    returned_job, image, decode_time_ms = blocker.args
    assert returned_job is job
    assert (image.width, image.height) == (64, 48)
    assert decode_time_ms > 0


def test_worker_reports_an_unreadable_file(qtbot, worker, tmp_path):
    lane, submit = worker
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    job = DecodeJob(str(path), CancelToken())

    with qtbot.waitSignal(lane.failed) as blocker:
        submit(job)

    assert blocker.args[0] is job


def test_worker_skips_a_cancelled_job(qtbot, worker, tmp_path):
    lane, submit = worker
    (path,) = make_images(tmp_path, ["a.png"])
    job = DecodeJob(path, CancelToken())
    job.token.cancel()

    with qtbot.waitSignal(lane.cancelled) as blocker:
        submit(job)

    assert blocker.args == [job]


@pytest.mark.parametrize("exposure_correction", [False, True])
def test_worker_builds_the_display_of_a_decoded_image(qtbot, worker, tmp_path, exposure_correction):
    lane, submit = worker
    (path,) = make_images(tmp_path, ["a.png"])
    image = ImageObject.create(path)
    job = DisplayJob(image, exposure_correction, CancelToken())

    with qtbot.waitSignal(lane.displayed) as blocker:
        submit(job)

    returned_job, display, display_time_ms = blocker.args
    assert returned_job is job
    np.testing.assert_array_equal(display, image.display_rgb_8bit(exposure_correction))
    assert display_time_ms > 0
