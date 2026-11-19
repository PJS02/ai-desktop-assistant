"""Keep Paddle's CPU inference GIL in a reusable local child process."""

import atexit
import multiprocessing
import os
from time import monotonic

from app_logging import log_event
from app_paths import BUNDLED_MODELS_DIR, IS_INSTALLED

OCR_TIMEOUT_SECONDS = 120
_RESULT_FIELDS = ("rec_texts", "rec_scores", "rec_polys", "dt_polys",
                  "text_word", "text_word_region")


def _load_engine():
    model_options = dict(lang="korean", ocr_version="PP-OCRv5")
    if IS_INSTALLED:
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        detection = "PP-OCRv5_server_det"
        recognition = "korean_PP-OCRv5_mobile_rec"
        model_options = dict(
            text_detection_model_name=detection,
            text_detection_model_dir=str(BUNDLED_MODELS_DIR / detection),
            text_recognition_model_name=recognition,
            text_recognition_model_dir=str(BUNDLED_MODELS_DIR / recognition),
        )
    from paddleocr import PaddleOCR

    return PaddleOCR(
        device="cpu", cpu_threads=2,
        enable_mkldnn=False,  # Windows oneDNN/PIR inference is unsupported on some Paddle versions.
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, text_rec_score_thresh=0.0,
        **model_options,
    )


def _serve(connection):
    # Limit native CPU pools without changing the GUI or other model runtimes.
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "2"
    engine = None
    try:
        while True:
            try:
                image, return_word_box = connection.recv()
            except EOFError:
                return
            if engine is None:
                try:
                    engine = _load_engine()
                except Exception:
                    connection.send(("initialization_failed", None))
                    return
                connection.send(("inference_started", None))
            try:
                results = [{key: page[key] for key in _RESULT_FIELDS if key in page}
                           for page in engine.predict(image, return_word_box=return_word_box)]
            except Exception:
                # OCR exceptions can contain private input; send no exception text.
                connection.send(("inference_failed", None))
                return
            connection.send(("result", results))
    except (OSError, KeyboardInterrupt):
        # Windows console interrupts also reach this child while it waits for work.
        return
    finally:
        connection.close()


class OCRWorker:
    """Serialized by the screenshot lock; models and images stay in memory."""

    def __init__(self):
        self._process = None
        self._connection = None
        atexit.register(self.close)

    @property
    def running(self):
        return self._process is not None and self._process.is_alive()

    def predict(self, image, *, return_word_box, timeout=OCR_TIMEOUT_SECONDS):
        started = monotonic()
        deadline = started + timeout
        stage = "inference"
        try:
            if self._process is None:
                stage = "worker_start"
                context = multiprocessing.get_context("spawn")
                self._connection, child = context.Pipe()
                self._process = context.Process(target=_serve, args=(child,),
                                                name="screen-ocr", daemon=True)
                try:
                    self._process.start()
                finally:
                    child.close()
                stage = "model_initialization"
            self._connection.send((image, return_word_box))
            while self._connection.poll(max(0, deadline - monotonic())):
                outcome, results = self._connection.recv()
                if outcome == "result":
                    return results
                if outcome in ("initialization_failed", "inference_failed"):
                    reason = outcome
                    break
                if outcome != "inference_started":
                    raise ValueError("Invalid OCR worker response")
                stage = "inference"
            else:
                reason = "response_timeout" if self.running else "worker_exited"
        except (EOFError, OSError):
            reason = "worker_start_failed" if stage == "worker_start" else "worker_exited"
        except Exception:
            reason = "worker_start_failed" if stage == "worker_start" else "worker_protocol_failed"

        elapsed = round(monotonic() - started, 3)
        # Discard the connection so a late reply cannot serve the next screenshot.
        exit_code = self.close(grace=0.2 if reason != "response_timeout" else 0)
        log_event("screen.ocr.failed", "화면 글자 인식 실패", category="오류", level="ERROR",
                  reason=reason, stage=stage, elapsed_seconds=elapsed, timeout_seconds=timeout,
                  exit_code=exit_code)
        raise RuntimeError("OCR worker failed; screenshot transmission must be blocked") from None

    def close(self, *, grace=0):
        process, self._process = self._process, None
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        if process is not None:
            exit_code = None
            if process.pid is not None:
                process.join(timeout=grace)
                exit_code = process.exitcode
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            if not process.is_alive():
                process.close()
            return exit_code
