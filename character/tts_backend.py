"""Persistent, cancellable local inference subprocess; Qt audio stays in tts_service."""
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import wave
from app_logging import log_event

from .tts_models import ModelStore

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG = Path(os.environ.get('CAPSTONE_TTS_RUNTIME_CONFIG', str(ROOT / '.tts-runtime' / 'runtime.json')))


def runtime_python():
    try:
        config = json.loads(RUNTIME_CONFIG.read_text(encoding='utf8'))
        python = Path(config['python'])
        if not python.is_file():
            raise ValueError('missing interpreter')
        return python
    except (OSError, ValueError, KeyError):
        raise ValueError('TTS 실행 환경이 준비되지 않았습니다. 프로젝트의 setup_tts_runtime.cmd를 먼저 실행해 주세요.') from None


class SynthesisCancelled(Exception):
    pass


class LocalVoiceBackend:
    def __init__(self, store=None):
        self.store = store or ModelStore()
        self.process = None
        self.voice = None
        self.lines = queue.Queue()
        self.errors = deque(maxlen=20)
        self.lock = threading.RLock()
        self.closed = False

    def _line(self, cancelled, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.closed or cancelled():
                self.stop()
                raise SynthesisCancelled()
            try:
                line = self.lines.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError('TTS 실행기가 종료되었습니다. ' + ' '.join(self.errors)[-2000:])
            if line.startswith('CAPSTONE_TTS:'):
                result = json.loads(line[len('CAPSTONE_TTS:'):])
                if result.get('error'):
                    raise RuntimeError(result['error'])
                if result.get('status') == 'loading':
                    done, total = result.get('completed'), result.get('total')
                    if type(done) is int and type(total) is int and 0 <= done < total:
                        log_event('tts.model_progress', '음성 모델 준비 단계 완료', category='대화·AI',
                                  model=self.voice, completed=done, total=total,
                                  detail=str(result.get('detail', '음성 모델을 준비하는 중'))[:160])
                    continue
                return result
        self.stop()
        raise TimeoutError('TTS 응답 시간이 초과되었습니다. 다시 시도해 주세요.')

    def _start(self, voice, cancelled):
        with self.lock:
            if self.closed:
                raise SynthesisCancelled()
            if self.process is not None and self.process.poll() is None and self.voice == voice:
                return
            self.stop()
            log_event('tts.model_loading', '음성 모델 불러오기 시작', category='대화·AI', model=voice)
            python = runtime_python()
            self.store.verify_engine(voice)
            work = self.store.root / voice
            work.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                       TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1',
                       TRANSFORMERS_OFFLINE='1', HF_HOME=str(self.store.root / '.cache'),
                       NLTK_DATA=str(ROOT / '.tts-runtime' / 'nltk_data'))
            settings = json.loads(RUNTIME_CONFIG.read_text(encoding='utf8'))
            env['CAPSTONE_TTS_EXTRA_SITE'] = json.dumps(settings.get('site_packages', []))
            self.lines, self.errors = queue.Queue(), deque(maxlen=20)
            process = subprocess.Popen([str(python), '-B', '-X', 'utf8', '-u',
                str(ROOT / 'tts_runtime' / 'worker.py'), voice, str(self.store.root)],
                cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, encoding='utf8', text=True, bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.process, self.voice = process, voice
            lines, errors = self.lines, self.errors
            def output():
                try:
                    for line in process.stdout:
                        if line.startswith('CAPSTONE_TTS:'):
                            lines.put(line)
                except (OSError, ValueError):
                    pass
                finally:
                    lines.put(None)
            def stderr():
                try:
                    for line in process.stderr:
                        errors.append(line.strip()[-500:])
                except (OSError, ValueError):
                    pass
            threading.Thread(target=output, daemon=True, name='tts-output').start()
            threading.Thread(target=stderr, daemon=True, name='tts-errors').start()
        if self._line(cancelled, 180).get('status') != 'ready':
            raise RuntimeError('TTS 모델 준비 응답이 올바르지 않습니다.')
        log_event('tts.model_ready', '음성 모델 준비 완료', category='대화·AI', model=voice)

    def synthesize(self, text, voice, cancelled):
        try:
            self._start(voice, cancelled)
        except SynthesisCancelled:
            raise
        except Exception as exc:
            self.stop()
            log_event('tts.model_failed', '음성 모델 준비 실패', category='대화·AI',
                      level='ERROR', model=voice, error=str(exc))
            raise
        if cancelled():
            raise SynthesisCancelled()
        fd, name = tempfile.mkstemp(suffix='.wav', prefix='capstone-tts-')
        os.close(fd)
        path = Path(name)
        try:
            self.process.stdin.write(json.dumps({'text': text, 'output': name}, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            if self._line(cancelled, 120).get('status') != 'done':
                raise RuntimeError('TTS 합성 응답이 올바르지 않습니다.')
            with wave.open(name, 'rb') as audio:
                if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                    raise ValueError('TTS 출력은 16비트 모노 WAV여야 합니다.')
                return audio.readframes(audio.getnframes()), audio.getframerate()
        except Exception:
            self.stop()
            raise
        finally:
            path.unlink(missing_ok=True)

    def stop(self):
        with self.lock:
            process, self.process = self.process, None
            voice = self.voice
            self.voice = None
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                log_event('tts.model_unloaded', '음성 모델 실행기 종료', category='대화·AI', model=voice)

    def close(self):
        self.closed = True
        self.stop()
