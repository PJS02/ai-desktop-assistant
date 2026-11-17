"""Build a Windows installer from this checkout and its working Python environment."""
import argparse
from importlib.metadata import distributions
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent
SOURCE_FILES = (
    'main.py', 'app_logging.py', 'app_paths.py', 'log_classification.py', 'native_log_capture.py',
    'setup_tts_runtime.cmd', 'scripts/setup_tts_runtime.py', 'docs/tts-installation.md',
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


def copy_python(destination, redist):
    base = Path(sys.base_prefix)
    destination.mkdir(parents=True)
    for name in ('python.exe', 'python3.dll', 'python310.dll', 'LICENSE.txt'):
        shutil.copyfile(base / name, destination / name)
    for dll in sorted(redist.glob('*.dll')):
        shutil.copyfile(dll, destination / dll.name)
    for folder in ('Lib', 'DLLs', 'tcl'):
        shutil.copytree(base / folder, destination / folder, ignore=shutil.ignore_patterns(
            'site-packages', '__pycache__', 'test', 'idlelib', 'turtledemo', 'ensurepip'))

    site_packages = Path(sysconfig.get_path('purelib'))
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
        source = site_packages / file
        if not source.resolve().is_relative_to(site_packages):
            raise ValueError(f'Wheel file is outside site-packages: {file}')
        target = target_site / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    (destination / 'python310._pth').write_text(
        '.\nDLLs\nLib\nLib\\site-packages\n..\\..\\app\nimport site\n', encoding='ascii')


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

    compiled = payload.parent / 'setup'
    compiled.mkdir(exist_ok=True)
    print(f'Compiling {INSTALLER_NAME}...', flush=True)
    subprocess.run([str(iscc.resolve()), '/Qp', f'/DPayload={payload}', f'/DOutput={compiled}',
                    str(SCRIPTS / 'Cloudy.iss')], cwd=ROOT, check=True)
    installer = output / INSTALLER_NAME
    (compiled / INSTALLER_NAME).replace(installer)
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

    payload = ROOT / 'build' / 'windows' / 'payload'
    output = ROOT / 'dist'
    if payload.resolve() != payload or output.resolve() != output:
        raise ValueError('Build and output paths must be inside this checkout.')
    if payload.exists():
        shutil.rmtree(payload)
    output.mkdir(exist_ok=True)

    print('Staging app and private runtimes...', flush=True)
    copy_application(payload / 'app')
    copy_python(payload / 'runtime' / 'python', args.vc_redist)
    node = payload / 'runtime' / 'node'
    node.mkdir()
    for name in ('node.exe', 'LICENSE'):
        shutil.copyfile(args.node_dir / name, node / name)
    build_launcher(payload)

    compile_setup(payload, output, args.iscc)


if __name__ == '__main__':
    main()
