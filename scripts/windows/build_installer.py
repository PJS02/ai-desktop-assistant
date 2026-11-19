"""Build a Windows installer from this checkout and its working Python environment."""
import argparse
import hashlib
from importlib.metadata import distributions
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from threading import Event
from urllib.request import urlopen
from zipfile import ZipFile

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
SOURCE_FILES = (
    'main.py', 'app_logging.py', 'app_paths.py', 'inference_device.py', 'log_classification.py', 'native_log_capture.py',
    'setup_tts_runtime.cmd', 'scripts/setup_tts_runtime.py', 'docs/tts-installation.md',
    'docs/bundled-models.md',
)
SOURCE_DIRECTORIES = (
    'ai', 'assets', 'assets_cloudy_rig_v4', 'character', 'context', 'emotion', 'hand_overlay',
    'medeapipe_capstone', 'memory', 'perception', 'tts_runtime',
)
LOCAL_PATHS = (
    'ai/config/', 'context/config/', 'context/cache/', 'context/gemini_config.json',
    'medeapipe_capstone/config/', 'medeapipe_capstone/media/',
    'tts_runtime/vendor/GPT_SoVITS/pretrained_models/',
)
BUILD_PACKAGES = {'pip', 'pytest', 'iniconfig', 'pluggy'}
INSTALLER_NAME = 'Cloudy-Setup-x64.exe'
ARCHIVE_NAME = 'Cloudy-Setup-x64-full.zip'
MODEL_DOWNLOAD_CACHE = ROOT / 'build' / 'windows' / 'model-downloads'
POSE_MODEL = Path('mediapipe/modules/pose_landmark/pose_landmark_heavy.tflite')
POSE_MODEL_SHA256 = '59e42d71bcd44cbdbabc419f0ff76686595fd265419566bd4009ef703ea8e1fe'


def copy_hub_model(destination, repo_id, revision, files, local_cache=None):
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    target_dir = destination / repo_id.split('/')[-1]
    print(f'Staging {repo_id}...', flush=True)
    for name in files:
        source = None
        if local_cache is not None:
            # PaddleX and Supertonic use standalone Hub downloads alongside their files.
            local_file = local_cache / name
            metadata = local_cache / '.cache/huggingface/download' / f'{name}.metadata'
            if local_file.is_file() and metadata.is_file():
                with metadata.open(encoding='utf-8') as stream:
                    if stream.readline().strip() == revision:
                        source = local_file
        if source is None:
            cached = try_to_load_from_cache(repo_id, name, revision=revision)
            source = Path(cached) if isinstance(cached, str) else Path(hf_hub_download(
                repo_id, name, revision=revision, cache_dir=MODEL_DOWNLOAD_CACHE,
                endpoint='https://huggingface.co', token=False))
        if source.stat().st_size == 0:
            raise ValueError(f'Empty model file: {source}')
        target = target_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def copy_models(destination):
    from supertonic.config import get_model_cache_dir

    copy_hub_model(
        destination, 'Supertone/supertonic-3', '724fb5abbf5502583fb520898d45929e62f02c0b',
        ('LICENSE', 'README.md', 'config.json', 'onnx/duration_predictor.onnx',
         'onnx/text_encoder.onnx', 'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
         'onnx/tts.json', 'onnx/unicode_indexer.json',
         *(f'voice_styles/{voice}{index}.json' for voice in ('F', 'M') for index in range(1, 6))),
        local_cache=get_model_cache_dir('supertonic-3'),
    )
    copy_hub_model(
        destination, 'intfloat/multilingual-e5-small', '614241f622f53c4eeff9890bdc4f31cfecc418b3',
        ('README.md', 'config.json', 'model.safetensors', 'modules.json', '1_Pooling/config.json',
         'sentence_bert_config.json', 'sentencepiece.bpe.model', 'special_tokens_map.json',
         'tokenizer.json', 'tokenizer_config.json'),
    )
    copy_hub_model(
        destination, 'Leo97/KoELECTRA-small-v3-modu-ner', 'bb9d562674e260712d9779f140ff5564a9e44d36',
        ('config.json', 'model.safetensors', 'special_tokens_map.json', 'tokenizer.json',
         'tokenizer_config.json', 'vocab.txt'),
    )
    paddle_cache = Path(os.environ.get('PADDLE_PDX_CACHE_HOME', Path.home() / '.paddlex')) / 'official_models'
    for name, revision in (
        ('PP-OCRv5_server_det', 'ca867c897ecbca8873081573a802ad70d499cb94'),
        ('korean_PP-OCRv5_mobile_rec', 'c02ecaf1f22bfd1c618cce154fd19185b47e663a'),
    ):
        copy_hub_model(
            destination, f'PaddlePaddle/{name}', revision,
            ('README.md', 'config.json', 'inference.json', 'inference.pdiparams', 'inference.yml'),
            local_cache=paddle_cache / name,
        )


def copy_pose_model(site_packages, target_site):
    source = site_packages / POSE_MODEL
    # MediaPipe downloads the Heavy graph's weights on demand outside its wheel.
    data = source.read_bytes() if source.is_file() else b''
    if hashlib.sha256(data).hexdigest() != POSE_MODEL_SHA256:
        with urlopen(f'https://storage.googleapis.com/mediapipe-assets/{POSE_MODEL.name}', timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != POSE_MODEL_SHA256:
            raise ValueError(f'Unexpected checksum for {POSE_MODEL.name}')
    (target_site / POSE_MODEL).write_bytes(data)


def copy_application(destination):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', *SOURCE_DIRECTORIES], cwd=ROOT)
    for file in (*SOURCE_FILES, *tracked.decode('utf-8').split('\0')):
        if not file or Path(file).name == '.gitignore' or file.startswith(LOCAL_PATHS):
            continue
        source = ROOT / file
        if not source.resolve().is_relative_to(ROOT) or not source.is_file():
            raise ValueError(f'Missing or invalid application file: {file}')
        target = destination / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (destination / '.cloudy-installed').touch()


def copy_python(destination, redist, *, tts_site_packages=None):
    base = Path(sys.base_prefix)
    destination.mkdir(parents=True)
    for name in ('python.exe', 'python3.dll', 'python310.dll', 'LICENSE.txt'):
        shutil.copyfile(base / name, destination / name)
    for dll in sorted(redist.glob('*.dll')):
        shutil.copyfile(dll, destination / dll.name)
    for folder in ('Lib', 'DLLs', 'tcl'):
        shutil.copytree(base / folder, destination / folder, ignore=shutil.ignore_patterns(
            'site-packages', '__pycache__', 'test', 'idlelib', 'turtledemo', 'ensurepip'))

    site_packages = tts_site_packages or Path(sysconfig.get_path('purelib'))
    target_site = destination / 'Lib' / 'site-packages'
    wheel_files = set()
    for package in distributions(path=[str(site_packages)]):
        if package.metadata['Name'].lower() in BUILD_PACKAGES:
            continue
        if not package.files:
            raise ValueError(f'No installed file list for {package.metadata["Name"]}')
        wheel_files.update(package.files)
    for file in sorted(wheel_files):
        if '..' in file.parts or '__pycache__' in file.parts or file.suffix in {'.pyc', '.pyi'}:
            continue
        if tts_site_packages and (file.suffix == '.lib' or file.parts[:2] == ('torch', 'include')):
            continue
        source = site_packages / file
        target = target_site / file
        if tts_site_packages and file.as_posix() == '_MeCab.cp310-win_amd64.pyd':
            # Eunjeon moves this extension into its data directory on first import.
            relocated = Path('eunjeon/data') / file
            if not source.is_file():
                source = site_packages / relocated
            target = target_site / relocated
        if not source.resolve().is_relative_to(site_packages):
            raise ValueError(f'Wheel file is outside site-packages: {file}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    if tts_site_packages is None:
        copy_pose_model(site_packages, target_site)
    (destination / 'python310._pth').write_text(
        '.\nDLLs\nLib\nLib\\site-packages\n..\\..\\app\nimport site\n', encoding='ascii')


def copy_custom_voices(payload, redist):
    from character.tts_models import ENGINE_NAMES, ModelStore

    source = ModelStore(ROOT / '.tts-models')
    cancel = Event()
    for engine in ENGINE_NAMES:
        print(f'Verifying {engine} model files...', flush=True)
        try:
            source.verify_engine(engine)
        except ValueError:
            source.install(engine, cancel, lambda *_: None)
    target = ModelStore(payload / 'app' / 'models' / 'tts', catalog=source.catalog)
    for asset in source.catalog['assets']:
        file = target.target(asset)
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.target(asset), file)

    tts_home = ROOT / '.tts-runtime'
    if not (tts_home / 'runtime.json').is_file():
        subprocess.run([sys.executable, str(ROOT / 'scripts' / 'setup_tts_runtime.py')], cwd=ROOT, check=True)
    runtime = payload / 'runtime' / 'tts-python'
    print('Staging the voice runtime...', flush=True)
    copy_python(runtime, redist, tts_site_packages=tts_home / 'env' / 'Lib' / 'site-packages')
    for folder in ('corpora/cmudict', 'taggers/averaged_perceptron_tagger'):
        shutil.copytree(tts_home / 'nltk_data' / folder, runtime / 'nltk_data' / folder)


def build_launcher(payload):
    portrait = (payload / 'app' / 'assets_cloudy_rig_v4' / 'directional_v5'
                / 'exports' / 'previews-v35' / 'front-neutral.webp')
    icon_path = payload / 'Cloudy.ico'
    with Image.open(portrait) as source:
        character = source.convert('RGBA')
        character.thumbnail((240, 240), Image.Resampling.LANCZOS)
        icon = Image.new('RGBA', (256, 256))
        icon.paste(character, ((256 - character.width) // 2, (256 - character.height) // 2))
        icon.save(icon_path, sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001',
                    '/reference:System.Windows.Forms.dll', f'/win32icon:{icon_path}',
                    f'/out:{payload / "Cloudy.exe"}', str(SCRIPTS / 'CloudyLauncher.cs')], check=True)


def compile_setup(payload, output, iscc):
    python = payload / 'runtime' / 'python' / 'python.exe'
    system = Path(os.environ['SystemRoot'])
    env = dict(os.environ, PATH=os.pathsep.join((str(system / 'System32'), str(system))))
    subprocess.run(
        [str(python), '-B', '-X', 'utf8', '-c',
         'import main, win32gui, tkinter, torch; from app_paths import IS_INSTALLED; '
         'assert IS_INSTALLED; tkinter.Tcl(); assert torch.ones(1).item() == 1'],
        cwd=payload, env=env, check=True, timeout=60)
    tts_runtime = payload / 'runtime' / 'tts-python'
    subprocess.run(
        [str(tts_runtime / 'python.exe'), '-B', '-X', 'utf8', '-c',
         'import sys, torch, torchaudio, soundfile, nltk; '
         'assert sys.flags.isolated and torch.version.cuda == "11.8"; '
         'assert torch.ones(1, device="cpu").item() == 1; '
         'nltk.data.find("corpora/cmudict"); nltk.data.find("taggers/averaged_perceptron_tagger")'],
        cwd=payload, env=dict(env, CUDA_VISIBLE_DEVICES='-1', NLTK_DATA=str(tts_runtime / 'nltk_data')),
        check=True, timeout=120)

    compiled = payload.parent / 'setup'
    compiled.mkdir(exist_ok=True)
    for previous_slice in compiled.glob('Cloudy-Setup-x64-*.bin'):
        previous_slice.unlink()
    print(f'Compiling {INSTALLER_NAME}...', flush=True)
    subprocess.run([str(iscc.resolve()), '/Qp', f'/DPayload={payload}', f'/DOutput={compiled}',
                    str(SCRIPTS / 'Cloudy.iss')], cwd=ROOT, check=True)
    slices = sorted(compiled.glob('Cloudy-Setup-x64-*.bin'))
    if not slices:
        raise ValueError('Installer data files were not created.')
    installer = output / ARCHIVE_NAME
    temporary = installer.with_suffix('.zip.tmp')
    print(f'Packing {ARCHIVE_NAME}...', flush=True)
    try:
        with ZipFile(temporary, 'w') as archive:
            for file in (compiled / INSTALLER_NAME, *slices):
                archive.write(file, arcname=file.name)
        temporary.replace(installer)
    finally:
        temporary.unlink(missing_ok=True)
    print(installer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', required=True, type=Path, help='Inno Setup ISCC.exe')
    parser.add_argument('--node-dir', required=True, type=Path, help='Extracted Node.js Windows x64 ZIP')
    parser.add_argument('--vc-redist', required=True, type=Path, help='Current Visual C++ x64 app-local CRT directory')
    args = parser.parse_args()
    if sysconfig.get_platform() != 'win-amd64' or sys.version_info[:2] != (3, 10):
        parser.error('Run with the app’s 64-bit Windows Python 3.10 environment.')
    if sys.prefix == sys.base_prefix:
        parser.error('Run with an app virtual environment that contains the app dependencies.')
    if not (args.vc_redist / 'msvcp140.dll').is_file() or not (args.vc_redist / 'vcruntime140_1.dll').is_file():
        parser.error('Use the Microsoft.VC143.CRT x64 redistributable DLL directory.')

    payload = ROOT / 'build' / 'windows' / 'full-voices' / 'payload'
    output = ROOT / 'dist'
    if payload.resolve() != payload or output.resolve() != output:
        raise ValueError('Build and output paths must be inside this checkout.')
    if payload.exists():
        shutil.rmtree(payload)
    output.mkdir(exist_ok=True)

    print('Staging app and default models...', flush=True)
    copy_application(payload / 'app')
    copy_models(payload / 'app' / 'models')
    copy_custom_voices(payload, args.vc_redist)
    print('Staging private runtimes...', flush=True)
    copy_python(payload / 'runtime' / 'python', args.vc_redist)
    node = payload / 'runtime' / 'node'
    node.mkdir()
    for name in ('node.exe', 'LICENSE'):
        shutil.copyfile(args.node_dir / name, node / name)
    build_launcher(payload)

    compile_setup(payload, output, args.iscc)


if __name__ == '__main__':
    main()
