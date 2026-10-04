"""Original rig calculation in a bounded, local, long-lived V8 subprocess."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading

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
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.process = subprocess.Popen(
            [find_node(), "--max-old-space-size=64", "--max-semi-space-size=4",
             str(Path(__file__).with_name("rig_worker.cjs")),
             str(self.rig_root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0, **kwargs)
        self._reader = threading.Thread(target=self._read_responses, name="cloudy-rig-reader", daemon=True)
        self._reader.start()
        try:
            init = self._request({"op": "init"}, timeout=10)
            self.parts, self.source_hashes = init["parts"], init["hashes"]
            self._recipes, self._effects = init["recipes"], init["effects"]
        except Exception:
            self.close()
            raise
        atexit.register(self.close)

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
                # A late reply has no request ID. Retire the worker before
                # releasing the lock so a later call cannot consume that reply.
                self.close()
                raise RuntimeError("Cloudy math worker did not respond") from exc
            if isinstance(result, Exception):
                self.close()
                raise RuntimeError(str(result)) from result
            if isinstance(result, dict) and result.get("workerError"):
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
        try:
            self.process.stdin.close()
            self.process.wait(timeout=1)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        finally:
            self.process.stdout.close()
            self._reader.join(timeout=1)
            atexit.unregister(self.close)
