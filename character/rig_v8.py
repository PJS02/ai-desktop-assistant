"""Original rig calculation in a bounded, local, long-lived V8 subprocess."""
from __future__ import annotations

import atexit
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading
from app_logging import log_event, new_trace_id

DEFAULT_RIG_ROOT = Path(__file__).resolve().parents[1] / "assets_cloudy_rig_v4" / "directional_v5"


def find_node() -> str:
    configured = os.environ.get("CLOUDY_NODE")
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        raise FileNotFoundError("CLOUDY_NODE does not point to a Node.js executable")
    found = shutil.which("node")
    if found:
        return found
    bundled = (Path.home() / ".cache/codex-runtimes/codex-primary-runtime"
               / "dependencies/node/bin/node.exe")
    if bundled.is_file():
        return str(bundled)
    raise FileNotFoundError("Node.js is needed for Cloudy rig math; use CLOUDY_RENDERER=sprite for PNG playback")


class NodeRigPlanner:
    """Same planning interface as RigPlanner, with binary Float32 transport.

    Availability metadata stays in the worker; native texture eviction cannot
    alter material selection. The worker reads only this rig and its adapter.
    """
    def __init__(self, rig_root: str | Path | None = None, parent=None):
        del parent
        self.rig_root = (Path(rig_root) if rig_root is not None else DEFAULT_RIG_ROOT).resolve()
        self._responses = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self.log_trace_id = new_trace_id('rig')
        self._stderr_lines = deque(maxlen=200)
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            self.process = subprocess.Popen(
                [find_node(), "--max-old-space-size=64", "--max-semi-space-size=4",
                 str(Path(__file__).with_name("rig_worker.cjs")),
                 str(self.rig_root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0, **kwargs)
        except Exception as exc:
            log_event('renderer.worker.start_failed', 'Node 렌더 계산 프로세스를 시작하지 못했습니다.',
                      category='오류', level='ERROR', trace_id=self.log_trace_id,
                      rig_root=str(self.rig_root), error=str(exc))
            raise
        log_event('renderer.worker.started', 'Node 렌더 계산 프로세스를 시작했습니다.',
                  trace_id=self.log_trace_id, pid=self.process.pid, rig_root=str(self.rig_root))
        self._stderr_reader = threading.Thread(target=self._read_stderr, name="cloudy-rig-stderr", daemon=True)
        self._stderr_reader.start()
        self._reader = threading.Thread(target=self._read_responses, name="cloudy-rig-reader", daemon=True)
        self._reader.start()
        try:
            init = self._request({"op": "init"}, timeout=10)
            self.parts, self.source_hashes = init["parts"], init["hashes"]
            self._recipes, self._effects = init["recipes"], init["effects"]
            log_event('renderer.worker.ready', 'Node 렌더 데이터 준비가 끝났습니다.',
                      trace_id=self.log_trace_id, parts=len(self.parts), source_hashes=self.source_hashes)
        except Exception as exc:
            log_event('renderer.worker.init_failed', 'Node 렌더 데이터 초기화에 실패했습니다.',
                      category='오류', level='ERROR', trace_id=self.log_trace_id, error=str(exc))
            self.close()
            raise
        atexit.register(self.close)

    def _read_stderr(self):
        """Drain diagnostics independently of the binary mesh protocol."""
        try:
            for raw in self.process.stderr:
                line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                self._stderr_lines.append(line)
                log_event('renderer.worker.stderr', 'Node 렌더 계산 프로세스 진단 출력입니다.',
                          category='오류', level='WARNING', trace_id=self.log_trace_id, output=line)
        except (OSError, ValueError) as exc:
            if not self._closed:
                log_event('renderer.worker.stderr_failed', 'Node 진단 출력을 읽지 못했습니다.',
                          category='오류', level='ERROR', trace_id=self.log_trace_id, error=str(exc))

    def _read_exact(self, length):
        chunks = bytearray()
        while len(chunks) < length:
            data = self.process.stdout.read(length - len(chunks))
            if not data:
                raise EOFError("Cloudy math worker exited")
            chunks.extend(data)
        return bytes(chunks)

    def _read_responses(self):
        try:
            while not self._closed:
                length = struct.unpack("<I", self._read_exact(4))[0]
                if length > 16 * 1024 * 1024:
                    raise RuntimeError("Oversized rig metadata response")
                header = json.loads(self._read_exact(length))
                binary_length = header.get("binaryLength", 0)
                if not 0 <= binary_length <= 16 * 1024 * 1024:
                    raise RuntimeError("Oversized rig mesh response")
                binary = self._read_exact(binary_length)
                result = header["result"]
                if isinstance(result, dict) and "commands" in result:
                    mesh = memoryview(binary)
                    for command in result["commands"]:
                        offset = command.pop("vertexOffset")
                        size = command.pop("vertexByteLength")
                        if offset < 0 or offset + size > len(mesh):
                            raise RuntimeError("Invalid rig mesh range")
                        command["vertexBytes"] = mesh[offset:offset + size]
                self._responses.put(result)
        except Exception as exc:
            if not self._closed:
                log_event('renderer.worker.read_failed', 'Node 렌더 응답을 읽지 못했습니다.',
                          category='오류', level='ERROR', trace_id=self.log_trace_id,
                          error=str(exc), exit_code=self.process.poll(), stderr='\n'.join(list(self._stderr_lines)))
            self._responses.put(exc)

    def _request(self, request, *, timeout=5):
        if self._closed:
            raise RuntimeError("Cloudy math worker is closed")
        with self._lock:
            encoded = (json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n").encode("utf8")
            try:
                self.process.stdin.write(encoded)
                self.process.stdin.flush()
                result = self._responses.get(timeout=timeout)
            except (OSError, queue.Empty) as exc:
                log_event('renderer.worker.request_failed', 'Node 렌더 요청이 실패하거나 응답 시간이 지났습니다.',
                          category='오류', level='ERROR', trace_id=self.log_trace_id,
                          operation=request.get('op'), state=request.get('state'), timeout_seconds=timeout,
                          error=str(exc))
                # A late reply has no request ID. Retire the worker before
                # releasing the lock so a later call cannot consume that reply.
                self.close()
                raise RuntimeError("Cloudy math worker did not respond") from exc
            if isinstance(result, Exception):
                self.close()
                raise RuntimeError(str(result)) from result
            if isinstance(result, dict) and result.get("workerError"):
                log_event('renderer.worker.operation_failed', 'Node 렌더 계산 중 오류가 발생했습니다.',
                          category='오류', level='ERROR', trace_id=self.log_trace_id,
                          operation=request.get('op'), state=request.get('state'), error=result['workerError'])
                raise RuntimeError(result["workerError"])
            return result

    def plan(self, state=None):
        return self._request({"op": "plan", "state": state or {}})

    def sample(self, state=None):
        return self._request({"op": "sample", "state": state or {}})

    def effect_recipes(self):
        return self._recipes

    def effect_metadata(self):
        return self._effects

    def texture_metadata(self, name):
        return self.parts.get(name) or self._effects.get(name)

    def stats(self):
        return self._request({"op": "stats"})

    def close(self):
        if self._closed:
            return
        self._closed = True
        stop_method = 'stdin_closed'
        log_event('renderer.worker.stopping', 'Node 렌더 계산 프로세스를 종료합니다.', trace_id=self.log_trace_id)
        try:
            self.process.stdin.close()
            self.process.wait(timeout=1)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            stop_method = 'terminate'
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                stop_method = 'kill'
                self.process.kill()
                self.process.wait(timeout=1)
        finally:
            self.process.stdout.close()
            self._reader.join(timeout=1)
            self._stderr_reader.join(timeout=1)
            self.process.stderr.close()
            log_event('renderer.worker.stopped', 'Node 렌더 계산 프로세스가 종료되었습니다.',
                      trace_id=self.log_trace_id, method=stop_method,
                      exit_code=self.process.poll(), stderr='\n'.join(list(self._stderr_lines)),
                      retained_stderr_lines=len(self._stderr_lines))
            atexit.unregister(self.close)
