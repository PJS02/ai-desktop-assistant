"""Versioned model-only downloads; no inference or package installation on the UI thread."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
import urllib.request

from PyQt6.QtCore import QCoreApplication, QObject, QStandardPaths, pyqtSignal
from PyQt6 import sip

CATALOG_PATH = Path(__file__).with_name('tts_models.json')
ENGINE_NAMES = {'gpt_sovits': 'GPT-SoVITS', 'openvoice_v2': 'OpenVoice V2'}


def model_directory():
    override = os.environ.get('CAPSTONE_TTS_MODEL_DIR')
    if override:
        return Path(override).resolve()
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / 'PJS02' / 'AIDesktopAssistant' / 'tts-models'


def load_catalog(path=CATALOG_PATH):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    seen = set()
    for asset in catalog['assets']:
        relative = PurePosixPath(asset['path'])
        if (relative.is_absolute() or '..' in relative.parts or ':' in asset['path']
                or '\\' in asset['path'] or asset['path'] in seen):
            raise ValueError('잘못된 음성 모델 경로입니다.')
        if (asset['size'] <= 0 or len(asset['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in asset['sha256'])):
            raise ValueError('음성 모델 검증 정보가 올바르지 않습니다.')
        if not asset['url'].startswith('https://'):
            raise ValueError('음성 모델은 HTTPS 주소가 필요합니다.')
        seen.add(asset['path'])
    return catalog


def fingerprint(catalog, engine):
    selected = [{key: a[key] for key in ('path', 'size', 'sha256')}
                for a in catalog['assets'] if engine in a['engines']]
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


class DownloadCancelled(Exception):
    pass


class ModelStore:
    def __init__(self, root=None, catalog=None, opener=None):
        self.root = Path(root) if root is not None else model_directory()
        self.catalog = catalog if catalog is not None else load_catalog()
        self.opener = opener or urllib.request.urlopen

    def assets(self, engine):
        if engine not in ENGINE_NAMES:
            raise ValueError('알 수 없는 음성 엔진입니다.')
        return [a for a in self.catalog['assets'] if engine in a['engines']]

    def target(self, asset):
        path = self.root / asset['path']
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('음성 모델 저장 경로를 벗어났습니다.')
        return path

    def marker(self, engine):
        return self.root / (engine + '.installed.json')

    def installed(self, engine):
        try:
            receipt = json.loads(self.marker(engine).read_text(encoding='utf8'))
            return (receipt['fingerprint'] == fingerprint(self.catalog, engine)
                    and all(self.target(a).stat().st_size == a['size']
                            and self.target(a).stat().st_mtime_ns == receipt['files'][a['path']]
                            for a in self.assets(engine)))
        except (OSError, KeyError, ValueError):
            return False

    def published(self, engine):
        return all(a.get('published', True) for a in self.assets(engine))

    def verified(self, asset, cancel=None):
        path = self.target(asset)
        if not path.is_file() or path.stat().st_size != asset['size']:
            return False
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                digest.update(block)
        return digest.hexdigest() == asset['sha256']

    def verify_engine(self, engine):
        if not self.installed(engine) or not all(self.verified(a) for a in self.assets(engine)):
            raise ValueError('음성 모델이 없거나 손상되었습니다. 설정 → 음성에서 다시 다운로드해 주세요.')

    def install(self, engine, cancel, progress):
        assets = self.assets(engine)
        if not self.published(engine):
            raise ValueError('학습한 목소리의 배포 파일을 준비하고 있습니다.')
        self.root.mkdir(parents=True, exist_ok=True)
        total = sum(a['size'] for a in assets)
        # Previously verified files do not need to be downloaded again, but are
        # hashed in the worker before reusing them across engines/retries.
        missing = sum(a['size'] for a in assets if not self.target(a).is_file()
                      or self.target(a).stat().st_size != a['size'])
        if shutil.disk_usage(self.root).free < missing + 32 * 1024 * 1024:
            raise OSError('음성 모델을 저장할 디스크 공간이 부족합니다.')
        completed = 0
        for asset in assets:
            if cancel.is_set():
                raise DownloadCancelled()
            progress(completed, total, '검증 중: ' + Path(asset['path']).name)
            if not self.verified(asset, cancel):
                destination = self.target(asset)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + '.download')
                try:
                    digest, received = hashlib.sha256(), 0
                    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'Capstone-TTS/1'})
                    with self.opener(request, timeout=20) as response, temporary.open('wb') as stream:
                        for block in iter(lambda: response.read(512 * 1024), b''):
                            if cancel.is_set():
                                raise DownloadCancelled()
                            received += len(block)
                            if received > asset['size']:
                                raise ValueError('다운로드한 모델의 크기가 일치하지 않습니다.')
                            stream.write(block)
                            digest.update(block)
                            progress(completed + received, total, '다운로드 중: ' + destination.name)
                    if received != asset['size'] or digest.hexdigest() != asset['sha256']:
                        raise ValueError('음성 모델 검증에 실패했습니다. 다시 다운로드해 주세요.')
                    if cancel.is_set():
                        raise DownloadCancelled()
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            completed += asset['size']
            progress(completed, total, '검증 완료')
        if cancel.is_set():
            raise DownloadCancelled()
        receipt = {'version': self.catalog['version'], 'fingerprint': fingerprint(self.catalog, engine),
                   'files': {a['path']: self.target(a).stat().st_mtime_ns for a in assets}}
        temporary = self.marker(engine).with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt), encoding='utf8')
        temporary.replace(self.marker(engine))


class ModelDownloadManager(QObject):
    changed = pyqtSignal()
    progress_changed = pyqtSignal(str, int, str)
    finished = pyqtSignal(str, bool, str)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or ModelStore()
        self.active_engine = None
        self._cancel = threading.Event()
        self._thread = None
        self.last_result = {}
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cancel)

    def start(self, engine):
        if self.active_engine is not None:
            return False
        self.store.assets(engine)
        self.active_engine = engine
        self._cancel.clear()
        self.last_result.pop(engine, None)
        self.changed.emit()
        self._thread = threading.Thread(target=self._download, args=(engine,), daemon=True, name='tts-model-download')
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def _download(self, engine):
        def progress(done, total, text):
            self.progress_changed.emit(engine, min(100, int(done * 100 / max(1, total))), text)
        try:
            self.store.install(engine, self._cancel, progress)
            ok, message = True, '설치 완료 — 목소리를 선택하고 적용해 주세요.'
        except DownloadCancelled:
            ok, message = False, '다운로드를 취소했습니다. 완료된 파일은 재사용합니다.'
        except Exception as exc:
            ok, message = False, '설치 실패: ' + str(exc)
        self.last_result[engine] = (ok, message)
        self.active_engine = None
        try:
            self.finished.emit(engine, ok, message)
            self.changed.emit()
        except RuntimeError:
            pass  # Qt has already shut down; a cancelled daemon must not crash.


_manager = None


def download_manager():
    global _manager
    if _manager is None or sip.isdeleted(_manager):
        _manager = ModelDownloadManager()
    return _manager
