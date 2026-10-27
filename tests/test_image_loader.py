"""Tests for the ImageLoader, the decode lane, on a real thread."""

import numpy as np
import pytest
from PySide6.QtCore import QObject, QThread, Signal

from detectorist.image_loader import ImageLoader
from detectorist.image_object import ImageObject
from detectorist.jobs import CancelToken, DecodeJob, FileStamp
from tests.fakes import make_images


class Sender(QObject):
    """Sends jobs across threads the way the Pipeline does, through a queued signal."""
    submit = Signal(object)


@pytest.fixture
def loader(qtbot):
    thread = QThread()
    loader = ImageLoader()
    loader.moveToThread(thread)
    sender = Sender()
    sender.submit.connect(loader.run)
    thread.start()
    yield loader, sender.submit.emit
    thread.quit()
    thread.wait()


def test_loader_decodes_and_builds_the_display(qtbot, loader, tmp_path):
    lane, submit = loader
    (path,) = make_images(tmp_path, ["a.png"], (64, 48))
    job = DecodeJob(path, False, CancelToken())

    with qtbot.waitSignal(lane.loaded) as blocker:
        submit(job)

    returned_job, image, display, stamp = blocker.args
    assert returned_job is job
    assert (image.width, image.height) == (64, 48)
    np.testing.assert_array_equal(display, image.image_data_rgb_8bit)
    assert stamp == FileStamp.of(path)


def test_loader_reports_an_unreadable_file(qtbot, loader, tmp_path):
    lane, submit = loader
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    job = DecodeJob(str(path), False, CancelToken())

    with qtbot.waitSignal(lane.failed) as blocker:
        submit(job)

    assert blocker.args[0] is job


def test_loader_skips_a_cancelled_job(qtbot, loader, tmp_path):
    lane, submit = loader
    (path,) = make_images(tmp_path, ["a.png"])
    job = DecodeJob(path, False, CancelToken())
    job.token.cancel()

    with qtbot.waitSignal(lane.cancelled) as blocker:
        submit(job)

    assert blocker.args == [job]


def test_loader_only_rebuilds_the_display_for_a_given_image(qtbot, loader, tmp_path):
    lane, submit = loader
    (path,) = make_images(tmp_path, ["a.png"])
    image = ImageObject.create(path)
    job = DecodeJob(path, True, CancelToken(), image=image)

    with qtbot.waitSignal(lane.loaded) as blocker:
        submit(job)

    _, returned_image, display, stamp = blocker.args
    assert returned_image is image
    np.testing.assert_array_equal(display, image.display_rgb_8bit(True))
    assert stamp is None


def test_batch_image_carries_the_exposure_flag_for_export(qtbot, loader, tmp_path):
    lane, submit = loader
    (path,) = make_images(tmp_path, ["a.png"])

    with qtbot.waitSignal(lane.loaded) as blocker:
        submit(DecodeJob(path, True, CancelToken(), for_batch=True))

    assert blocker.args[1].exposure_correction
