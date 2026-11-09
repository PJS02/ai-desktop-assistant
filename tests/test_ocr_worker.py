"""Exercise Windows-compatible process isolation without downloading models."""

import multiprocessing
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from context import ocr_worker


def echo_ocr(connection):
    try:
        while True:
            image, word_boxes = connection.recv()
            connection.send([{"pid": os.getpid(), "pixels": image.tolist(), "word_boxes": word_boxes}])
    except EOFError:
        pass
    finally:
        connection.close()


def blocked_ocr(connection):
    connection.recv()
    time.sleep(60)


def crashed_ocr(connection):
    connection.recv()
    os._exit(7)


def failed_ocr(connection):
    connection.recv()
    connection.send(None)
    connection.close()


def test_predictions_run_in_one_reused_child_process(monkeypatch):
    monkeypatch.setattr(ocr_worker, "_serve", echo_ocr)
    worker = ocr_worker.OCRWorker()
    image = np.full((2, 3, 3), 42, dtype=np.uint8)
    try:
        first = worker.predict(image, return_word_box=True)[0]
        second = worker.predict(image + 1, return_word_box=False)[0]
        assert first["pid"] != os.getpid()
        assert first["pid"] == second["pid"]
        assert first["pixels"] == image.tolist()
        assert second["pixels"] == (image + 1).tolist()
        assert first["word_boxes"] is True
        assert second["word_boxes"] is False
        process_id = first["pid"]
    finally:
        worker.close()
    assert process_id not in {child.pid for child in multiprocessing.active_children()}


@pytest.mark.parametrize("target", [blocked_ocr, crashed_ocr, failed_ocr])
def test_failure_retires_worker_and_next_request_restarts(monkeypatch, target):
    monkeypatch.setattr(ocr_worker, "_serve", target)
    monkeypatch.setattr(ocr_worker, "OCR_TIMEOUT_SECONDS", 0.1 if target is blocked_ocr else 10)
    worker = ocr_worker.OCRWorker()
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    try:
        with pytest.raises(RuntimeError, match="screenshot transmission must be blocked"):
            worker.predict(image, return_word_box=True)
        assert worker._process is None
        assert worker._connection is None
        assert not any(child.name == "screen-ocr" for child in multiprocessing.active_children())
        monkeypatch.setattr(ocr_worker, "_serve", echo_ocr)
        monkeypatch.setattr(ocr_worker, "OCR_TIMEOUT_SECONDS", 10)
        assert worker.predict(image, return_word_box=True)[0]["pixels"] == image.tolist()
    finally:
        worker.close()


def test_worker_reuses_model_and_returns_only_masking_fields(monkeypatch):
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    page = dict(rec_texts=["private"], rec_scores=[0.99], rec_polys=[], dt_polys=[],
                text_word=[["private"]], text_word_region=[[]], input_img=image)
    factory = Mock()
    factory.return_value.predict.return_value = [page]
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=factory))
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.setenv("MKL_NUM_THREADS", "8")
    connection = Mock()
    connection.recv.side_effect = [(image, True), (image, True), EOFError]
    ocr_worker._serve(connection)
    factory.assert_called_once()
    assert factory.call_args.kwargs["cpu_threads"] == 2
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["MKL_NUM_THREADS"] == "2"
    assert factory.return_value.predict.call_count == 2
    assert connection.send.call_count == 2
    returned = connection.send.call_args.args[0][0]
    assert returned == {key: value for key, value in page.items() if key != "input_img"}
    connection.close.assert_called_once()


def test_worker_hides_private_exception_text(monkeypatch):
    factory = Mock(side_effect=RuntimeError("private OCR input"))
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=factory))
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.setenv("MKL_NUM_THREADS", "8")
    connection = Mock()
    connection.recv.return_value = (np.zeros((2, 3, 3), dtype=np.uint8), True)
    ocr_worker._serve(connection)
    connection.send.assert_called_once_with(None)
    connection.close.assert_called_once()


@pytest.mark.skipif(os.environ.get("RUN_PADDLE_OCR_TEST") != "1", reason="requires local OCR models")
def test_real_paddleocr_keeps_main_thread_responsive():
    worker = ocr_worker.OCRWorker()
    image = np.full((480, 640, 3), 255, dtype=np.uint8)
    gaps = []
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(worker.predict, image, return_word_box=True)
            previous = time.monotonic()
            while not result.done():
                time.sleep(0.02)
                current = time.monotonic()
                gaps.append(current - previous)
                previous = current
            assert len(result.result()) == 1
        print(f"Main-thread heartbeat: max gap {max(gaps):.3f}s")
        assert max(gaps) < 0.5
    finally:
        worker.close()
