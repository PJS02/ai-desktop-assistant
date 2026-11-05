"""Keep Paddle's CPU inference GIL in a reusable local child process."""

import atexit
import multiprocessing
import os


OCR_TIMEOUT_SECONDS = 120
_RESULT_FIELDS = ("rec_texts", "rec_scores", "rec_polys", "dt_polys",
                  "text_word", "text_word_region")


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
            try:
                if engine is None:
                    from paddleocr import PaddleOCR

                    engine = PaddleOCR(
                        lang="korean", ocr_version="PP-OCRv5", device="cpu", cpu_threads=2,
                        enable_mkldnn=False,  # Windows oneDNN/PIR inference is unsupported on some Paddle versions.
                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False, text_rec_score_thresh=0.0,
                    )
                results = [{key: page[key] for key in _RESULT_FIELDS if key in page}
                           for page in engine.predict(image, return_word_box=return_word_box)]
            except Exception:
                # OCR exceptions can contain private input; send no exception text.
                connection.send(None)
                return
            connection.send(results)
    finally:
        connection.close()


class OCRWorker:
    """Serialized by the screenshot lock; models and images stay in memory."""

    def __init__(self):
        self._process = None
        self._connection = None
        atexit.register(self.close)

    def predict(self, image, *, return_word_box):
        try:
            if self._process is None:
                context = multiprocessing.get_context("spawn")
                self._connection, child = context.Pipe()
                self._process = context.Process(target=_serve, args=(child,),
                                                name="screen-ocr", daemon=True)
                try:
                    self._process.start()
                finally:
                    child.close()
            self._connection.send((image, return_word_box))
            if not self._connection.poll(OCR_TIMEOUT_SECONDS):
                raise TimeoutError
            results = self._connection.recv()
            if results is None:
                raise RuntimeError
            return results
        except Exception:
            # A late reply must never be used for a subsequent screenshot.
            self.close()
            raise RuntimeError("OCR worker failed; screenshot transmission must be blocked") from None

    def close(self):
        process, self._process = self._process, None
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
            if not process.is_alive():
                process.close()
